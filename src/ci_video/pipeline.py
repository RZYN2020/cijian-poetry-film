import math
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from .models import ContentProject, ResearchPack, Script, Storyboard, Asset
from .storage import read, save, digest, local_file, now
from .llm import generate, ROOT


def normalize(text):
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text)


def validate_script(script, research):
    if script.mode == "recital" and normalize(''.join(b.narration for b in script.beats)) != normalize(research.original_text):
        raise ValueError("Recital must contain the complete original poem, once, in order, with no commentary")
    ids = {c.id for c in research.claims}
    for b in script.beats:
        if not set(b.claim_ids) <= ids:
            raise ValueError(f"{b.id}: invented claim reference")
        if b.quote and normalize(b.quote) not in normalize(research.original_text):
            raise ValueError(f"{b.id}: quotation differs from the verified poem")
        if normalize(''.join(b.subtitle_lines)) != normalize(b.narration):
            raise ValueError(f"{b.id}: subtitles must cover narration exactly")
    return script


def validate_recital(board):
    if board.mode != "recital":
        return
    if not board.original_text or normalize(''.join(s.narration for s in board.scenes)) != normalize(board.original_text):
        raise ValueError("Recital storyboard must match original_text exactly, in order, without commentary")
    for s in board.scenes:
        if normalize(''.join(c.text for c in s.subtitle)) != normalize(s.narration):
            raise ValueError(f"{s.id}: recital subtitles differ from spoken poem")


def research(project):
    manifest = read(project / "project.json", ContentProject)
    bundle = read(project / "sources.json", ResearchPack)
    pack, _ = generate(project, "research", ResearchPack,
        {"brief": manifest.brief.model_dump(), "verified_source_bundle": bundle.model_dump()})
    for attr in ("sources", "evidence", "original_text", "author", "poem_title"):
        if getattr(pack, attr) != getattr(bundle, attr):
            raise ValueError(f"Research changed locked {attr}; inspect saved model response")
    pack.review_status = "needs_review"
    pack.provenance = "DeepSeek/OpenAI API source-constrained draft; semantic claims require editorial review"
    save(project / "research.json", pack)


def script(project):
    manifest = read(project / "project.json", ContentProject)
    pack = read(project / "research.json", ResearchPack)
    result, run = generate(project, "script", Script,
        {"brief": manifest.brief.model_dump(), "research": pack.model_dump(), "assets": read(project / "assets/manifest.json")})
    validate_script(result, pack)
    result.provenance = f"API draft; request/response: {run.relative_to(project)}"
    save(project / "script.json", result)


def board(project):
    manifest = read(project / "project.json", ContentProject)
    pack = read(project / "research.json", ResearchPack)
    script = validate_script(read(project / "script.json", Script), pack)
    assets = [Asset.model_validate(a) for a in read(project / "assets/manifest.json")]
    visual_ids = [a.id for a in assets if a.kind in {"image", "video"}]
    if not visual_ids:
        raise ValueError("Provide at least one local visual asset in assets/manifest.json")
    weights = [len(normalize(b.narration)) + 4 for b in script.beats]
    frames = round(manifest.brief.target_seconds * 24)
    durations = [round(frames * w / sum(weights)) for w in weights]
    durations[-1] += frames - sum(durations)
    scenes = []
    for i, (beat, nframes) in enumerate(zip(script.beats, durations)):
        duration = nframes / 24
        lines = beat.subtitle_lines
        total = sum(len(normalize(t)) for t in lines)
        t = 0.35
        subtitles = []
        for line in lines:
            end = t + (duration - 0.8) * len(normalize(line)) / total
            subtitles.append({"start": t, "end": end, "text": line})
            t = end
        scenes.append({"id": beat.id, "duration": duration, "narration": beat.narration,
            "subtitle": subtitles, "visual_intent": beat.visual_intent,
            "asset_refs": [beat.asset_hint if beat.asset_hint in visual_ids else visual_ids[i % len(visual_ids)]],
            "claim_ids": beat.claim_ids, "role": beat.role, "quote": beat.quote})
    result = Storyboard(project_id=manifest.id, title=script.title, poem_title=pack.poem_title,
                        author=pack.author, mode=script.mode, original_text=pack.original_text,
                        assets=assets, scenes=scenes, bgm_path=None, bgm_volume=0.12)
    # Keep an independently selected music track when rebuilding picture timing.
    if (project / "storyboard.json").exists():
        old = read(project / "storyboard.json")
        for key in ["bgm_path", "bgm_volume", "bgm_start", "bgm_fade", "bgm_duck"]:
            if key in old:
                setattr(result, key, old[key])
    save(project / "storyboard.json", result)


def download_assets(project):
    assets = [Asset.model_validate(a) for a in read(project / "assets/manifest.json")]
    with httpx.Client(follow_redirects=True, timeout=60, headers={"User-Agent": "CiVideoResearch/0.1"}) as client:
        for a in assets:
            path = local_file(project, a.path)
            if not path.exists():
                if not a.download_url.startswith("https://"):
                    raise ValueError(f"Prepare local file {path} or provide HTTPS download_url")
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".download")
                try:
                    with client.stream("GET", a.download_url) as r:
                        r.raise_for_status()
                        with tmp.open("wb") as out:
                            for chunk in r.iter_bytes():
                                out.write(chunk)
                    if not tmp.stat().st_size:
                        raise ValueError(f"empty asset {a.id}")
                    tmp.replace(path)
                finally:
                    tmp.unlink(missing_ok=True)
            sha = digest(path.read_bytes())
            if a.sha256 and sha != a.sha256:
                raise ValueError(f"{a.id}: checksum mismatch; review replacement and update manifest")
            a.sha256 = sha
            print(f"asset ready: {a.id}", flush=True)
    save(project / "assets/manifest.json", [a.model_dump() for a in assets])
    if (project / "storyboard.json").exists():
        result = read(project / "storyboard.json", Storyboard)
        result.assets = assets
        save(project / "storyboard.json", result)


def validate_render(project):
    board = read(project / "storyboard.json", Storyboard)
    validate_recital(board)
    used = {ref for s in board.scenes for ref in s.asset_refs}
    if board.bgm_path and not any(a.path == board.bgm_path and a.kind == "audio" for a in board.assets):
        raise ValueError("BGM must be registered as an audio Asset with source/license/checksum")
    for a in board.assets:
        if a.id not in used and a.kind != "font" and a.path != board.bgm_path:
            continue
        p = local_file(project, a.path)
        if not p.is_file():
            raise ValueError(f"Missing asset {p}")
        if not a.sha256 or digest(p.read_bytes()) != a.sha256:
            raise ValueError(f"{a.id}: missing/mismatched SHA-256; run assets after reviewing file")
    for s in board.scenes:
        if not s.audio:
            raise ValueError(f"{s.id}: missing narration audio; run tts")
        if s.audio.text_sha256 != digest(s.narration):
            raise ValueError(f"{s.id}: narration changed; run tts again (Research is unaffected)")
        p = local_file(project, s.audio.path)
        if not p.is_file() or digest(p.read_bytes()) != s.audio.file_sha256:
            raise ValueError(f"{s.id}: audio missing/changed; run tts")
        from .speech import duration
        if abs(duration(p) - s.audio.duration) > 0.05:
            raise ValueError(f"{s.id}: recorded audio duration differs from actual file")
    if board.bgm_path:
        from .speech import duration
        if duration(local_file(project, board.bgm_path)) < board.bgm_start + sum(s.duration for s in board.scenes):
            raise ValueError("Music segment too short; choose an earlier bgm_start or a longer track")
    return board


def render(project, scale=1.0, still=None):
    board = validate_render(project)
    args = ["node", str(ROOT / "renderer/render.mjs"), str(project), "--scale", str(scale)]
    if still is not None:
        args += ["--still", str(still)]
    subprocess.run(args, cwd=ROOT, check=True)
    if still is None:
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(project / "output.mp4")], capture_output=True, text=True, check=True)
        import json
        metadata = json.loads(probe.stdout)
        expected = sum(s.duration for s in board.scenes)
        duration = float(metadata["format"]["duration"])
        if abs(duration - expected) > 0.2 or not any(s["codec_type"] == "audio" for s in metadata["streams"]):
            raise ValueError("render verification failed: duration/audio")
        print(f"Verified MP4: {duration:.2f}s; report written by renderer")


def init(project, brief, source_pack, assets):
    if (project / "project.json").exists():
        raise ValueError("Project exists; edit its JSON or choose another directory")
    from .models import Brief
    b = read(brief, Brief)
    pack = read(source_pack, ResearchPack)
    if normalize(b.poem_text) != normalize(pack.original_text) or b.author != pack.author:
        raise ValueError("Brief poem/author does not match source pack")
    project.mkdir(parents=True, exist_ok=True)
    save(project / "project.json", ContentProject(id=project.name, brief=b, created_at=now()))
    save(project / "sources.json", pack)
    save(project / "research.json", pack)
    manifest = [Asset.model_validate(a).model_dump() for a in read(assets)]
    save(project / "assets/manifest.json", manifest)
