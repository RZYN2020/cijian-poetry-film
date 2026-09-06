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


def duration(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return float(json.loads(p.stdout)["format"]["duration"])


def align(lines, events, audio_seconds, offset):
    """Map user caption chunks to TTS word boundaries; label proportional fallback."""
    words = [e for e in events if e.get("type") == "WordBoundary"]
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


async def synthesize(project, fit=False, provider="edge"):
    load_dotenv(ROOT / ".env.local")
    board = read(project / "storyboard.json", Storyboard).model_dump()
    voice = os.getenv("TTS_VOICE", "zh-CN-YunxiNeural") if provider == "edge" else "Tingting"
    rate = os.getenv("TTS_RATE", "-8%") if provider == "edge" else "180"
    for scene in board["scenes"]:
        key = digest(json.dumps([scene["narration"], provider, voice, rate], ensure_ascii=False))[:24]
        ext = "mp3" if provider == "edge" else "aiff"
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
                    communicate = edge_tts.Communicate(scene["narration"], voice, rate=rate, boundary="WordBoundary")
                    with tmp.open("wb") as f:
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                f.write(chunk["data"])
                            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                                events.append(chunk)
                else:
                    subprocess.run(["say", "-v", voice, "-r", rate, "-o", str(tmp), scene["narration"]], check=True)
                seconds = duration(tmp)
                tmp.replace(path)
                save(sidecar, {"sha256": digest(path.read_bytes()), "duration": seconds, "events": events}, history=False)
            finally:
                tmp.unlink(missing_ok=True)
        cache = read(sidecar)
        seconds = cache["duration"]
        offset = 0.35
        if fit:
            scene["duration"] = math.ceil((seconds + offset + 0.65) * board["fps"]) / board["fps"]
        elif offset + seconds > scene["duration"]:
            raise ValueError(f"{scene['id']}: {seconds:.2f}s speech exceeds scene; use --fit or increase duration")
        cues, method = align([s["text"] for s in scene["subtitle"]], cache["events"], seconds, offset)
        scene["subtitle"] = cues
        scene["audio"] = {"path": relative, "text_sha256": digest(scene["narration"]),
            "file_sha256": cache["sha256"], "duration": seconds, "offset": offset,
            "provider": provider, "voice": voice, "rate": rate, "timing_method": method}
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
