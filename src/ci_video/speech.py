import asyncio
import json
import math
import os
import subprocess
from datetime import timedelta
from pathlib import Path

import edge_tts
import srt
from dotenv import load_dotenv

from .llm import ROOT
from .models import Storyboard
from .storage import read, save, digest, local_file
from .pipeline import normalize
from .media_api import settings, speech_request


def duration(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return float(json.loads(p.stdout)["format"]["duration"])


def align(lines, events, audio_seconds, offset):
    """Map user caption chunks to TTS word boundaries; label proportional fallback."""
    words = [e for e in events if e.get("type") in {"WordBoundary", "SentenceBoundary"}]
    target = normalize(''.join(lines))
    spoken = normalize(''.join(e["text"] for e in words))
    spans = []
    cursor = 0
    for e in words:
        size = len(normalize(e["text"]))
        if size:
            spans.append((cursor, cursor + size, e["offset"] / 1e7, (e["offset"] + e["duration"]) / 1e7))
            cursor += size
    exact = bool(spans) and target == spoken
    cues = []
    cursor = 0
    for text in lines:
        endpos = cursor + len(normalize(text))
        if exact:
            matches = [s for s in spans if s[0] < endpos and s[1] > cursor]
            first, last = matches[0], matches[-1]
            start = first[2] + (first[3]-first[2]) * max(0, cursor-first[0]) / (first[1]-first[0])
            end = last[2] + (last[3]-last[2]) * min(last[1]-last[0], endpos-last[0]) / (last[1]-last[0])
        else:
            start = audio_seconds * cursor / len(target)
            end = audio_seconds * endpos / len(target)
        cues.append({"start": offset + start, "end": offset + min(end, audio_seconds), "text": text})
        cursor = endpos
    # Hold through punctuation pauses; avoid blinking off between clauses.
    for i in range(len(cues)-1):
        cues[i]["end"] = cues[i+1]["start"]
    return cues, "tts_boundaries" if exact else "estimated"


async def synthesize(project, fit=False, provider=None, voice=None):
    load_dotenv(ROOT / ".env.local")
    board = read(project / "storyboard.json", Storyboard).model_dump()
    from .pipeline import validate_recital
    validate_recital(Storyboard.model_validate(board))
    provider = provider or os.getenv("TTS_PROVIDER", "external")
    base, _, api_model = settings("TTS")
    defaults = {"external": "coral", "edge": "zh-CN-XiaoxiaoNeural", "macos": "Tingting"}
    if provider not in defaults:
        raise ValueError("Unknown TTS provider")
    voice = voice or os.getenv(f"{provider.upper()}_TTS_VOICE", defaults[provider])
    model = api_model if provider == "external" else provider
    rate = os.getenv("TTS_SPEED", "0.8") if provider == "external" else os.getenv("EDGE_TTS_RATE", "-30%") if provider == "edge" else os.getenv("MACOS_TTS_RATE", "130")
    instructions = os.getenv("TTS_INSTRUCTIONS", "以温柔、自然、平静的中文女声朗诵宋词。吐字清楚，四三节奏，含蓄、略带怀旧，句尾留白。不模仿播音腔，不唱歌，不添加任何输入以外的文字。") if provider == "external" else ""
    for scene in board["scenes"]:
        key = digest(json.dumps([scene["narration"], provider, base if provider == "external" else "", model, voice, rate, instructions], ensure_ascii=False))[:24]
        ext = "mp3" if provider in {"edge", "external"} else "wav"
        relative = f"audio/{key}.{ext}"
        path = local_file(project, relative)
        sidecar = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        valid_cache = path.exists() and sidecar.exists() and read(sidecar).get("sha256") == digest(path.read_bytes())
        if not valid_cache:
            tmp = path.with_name(f"{key}.tmp.{ext}")
            events = []
            try:
                if provider == "edge":
                    communicate = edge_tts.Communicate(scene["narration"], voice, rate=rate, boundary="SentenceBoundary")
                    with tmp.open("wb") as f:
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                f.write(chunk["data"])
                            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                                events.append(chunk)
                elif provider == "external":
                    data, run, record = await asyncio.to_thread(speech_request, project, scene["narration"], voice, model, float(rate), instructions)
                    tmp.write_bytes(data)
                    duration(tmp)  # Do not mark malformed/empty audio as successful.
                    record.update(status="complete", output=relative, sha256=digest(data))
                    save(run, record, history=False)
                else:
                    # Force ordinary WAV PCM; Remotion's bundled ffprobe cannot decode Apple's AIFF-C.
                    subprocess.run(["say", "-v", voice, "-r", rate, "--file-format=WAVE", "--data-format=LEI16@22050", "-o", str(tmp), scene["narration"]], check=True)
                seconds = duration(tmp)
                tmp.replace(path)
                save(sidecar, {"sha256": digest(path.read_bytes()), "duration": seconds, "events": events}, history=False)
            finally:
                tmp.unlink(missing_ok=True)
        cache = read(sidecar)
        seconds = cache["duration"]
        offset = scene["voice_offset"]
        if fit:
            scene["duration"] = max(scene["duration"], math.ceil((seconds + offset + 0.8) * board["fps"]) / board["fps"])
        elif offset + seconds > scene["duration"]:
            raise ValueError(f"{scene['id']}: {seconds:.2f}s speech exceeds scene; use --fit or increase duration")
        cues, method = align([s["text"] for s in scene["subtitle"]], cache["events"], seconds, offset)
        scene["subtitle"] = cues
        scene["audio"] = {"path": relative, "text_sha256": digest(scene["narration"]),
            "file_sha256": cache["sha256"], "duration": seconds, "offset": offset,
            "provider": provider, "voice": voice, "rate": rate, "timing_method": method,
            "model": model, "request_hash": key}
        print(f"{scene['id']}: {seconds:.2f}s speech / {scene['duration']:.2f}s scene ({method})", flush=True)
    validated = Storyboard.model_validate(board)
    save(project / "storyboard.json", validated)
    captions = []
    start = 0
    for scene in validated.scenes:
        for c in scene.subtitle:
            captions.append(srt.Subtitle(len(captions)+1, timedelta(seconds=start+c.start), timedelta(seconds=start+c.end), c.text))
        start += scene.duration
    (project / "subtitles.srt").write_text(srt.compose(captions))
    print(f"Total: {start:.2f}s", flush=True)
