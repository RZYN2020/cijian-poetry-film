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
from .prompts import resolve
from . import traces


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


@traces.traced('tts', 'stage')
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
    instruction, prompt = resolve(project, 'tts')
    params = prompt['parameters']
    voice = voice or params.get('edge_voice' if provider == 'edge' else 'voice') or os.getenv(f"{provider.upper()}_TTS_VOICE", defaults[provider])
    model = params.get('model', api_model) if provider == "external" else provider
    rate = os.getenv("TTS_SPEED", "0.8") if provider == "external" else os.getenv("EDGE_TTS_RATE", "-30%") if provider == "edge" else os.getenv("MACOS_TTS_RATE", "130")
    rate = str(params.get('speed' if provider == 'external' else 'edge_rate',rate)) if provider != 'macos' else rate
    instructions = instruction if provider == "external" else ""
    traces.update(prompt=prompt, provider=provider, model=model, note='Edge/macOS do not accept prose instructions; voice/rate only' if provider != 'external' else None)
    for scene in board["scenes"]:
        key = digest(json.dumps([scene["narration"], provider, base if provider == "external" else "", model, voice, rate, instructions], ensure_ascii=False))[:24]
        ext = "mp3" if provider in {"edge", "external"} else "wav"
        relative = f"audio/{key}.{ext}"
        path = local_file(project, relative)
        sidecar = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        cache = await obtain_audio(project, scene['id'], scene['narration'], provider, model, voice, rate, instructions, path, prompt)
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


@traces.traced('speech')
async def obtain_audio(project, scene_id, text, provider, model, voice, rate, instructions, path, prompt):
    traces.update(scene_id=scene_id, provider=provider, model=model, prompt=prompt,
                  request={'input':text,'voice':voice,'rate':rate,'instructions':instructions})
    sidecar = path.with_suffix('.json')
    if path.exists() and sidecar.exists() and read(sidecar).get('sha256') == digest(path.read_bytes()):
        cache = read(sidecar)
        traces.update(result_status='cached', artifacts=[{'path':str(path.relative_to(project)), 'sha256':cache['sha256']}], response=cache)
        return cache
    tmp = path.with_name(path.stem + '.tmp' + path.suffix)
    events = []
    try:
        if provider == 'edge':
            communicate = edge_tts.Communicate(text, voice, rate=rate, boundary='SentenceBoundary')
            with tmp.open('wb') as f:
                async for chunk in communicate.stream():
                    if chunk['type'] == 'audio':
                        f.write(chunk['data'])
                    elif chunk['type'] in ('WordBoundary','SentenceBoundary'):
                        events.append(chunk)
        elif provider == 'external':
            data, run, record = await asyncio.to_thread(speech_request, project, text, voice, model, float(rate), instructions)
            tmp.write_bytes(data)
            duration(tmp)
            record.update(status='complete',output=str(path.relative_to(project)),sha256=digest(data))
            save(run,record,history=False)
        else:
            subprocess.run(['say','-v',voice,'-r',rate,'--file-format=WAVE','--data-format=LEI16@22050','-o',str(tmp),text],check=True)
        seconds = duration(tmp)
        tmp.replace(path)
        cache = {'sha256':digest(path.read_bytes()),'duration':seconds,'events':events}
        save(sidecar,cache,history=False)
        traces.update(response=cache,artifacts=[{'path':str(path.relative_to(project)),'sha256':cache['sha256']}])
        return cache
    finally:
        tmp.unlink(missing_ok=True)
