"""Image generation/import and licensed-music download, with a single manifest."""
import json
from pathlib import Path
import shutil

from .models import Asset, Storyboard
from .storage import digest, local_file, now, read, save
from .media_api import fetch, image_request, settings, ROOT

STYLE = ("Vertical 9:16 full-bleed Song dynasty garden, refined hand-painted Chinese animation background. "
         "Same old pavilion, willow and apricot tree across shots. Restrained ink wash and mineral pigments, "
         "jade-grey, ivory, ink-blue, small amber dusk accents. Quiet wistful late spring. Layered depth, "
         "delicate brushwork, credible architecture. Lower middle quiet for later subtitles. "
         "No modern objects, no text, calligraphy, seals, logos, borders or watermark. ")


def register(project, asset, scene_id=None):
    asset = Asset.model_validate(asset)
    b = read(project / "storyboard.json", Storyboard)
    if scene_id and scene_id not in {s.id for s in b.scenes}:
        raise ValueError(f"Unknown scene {scene_id}")
    # Start from storyboard to recover legacy manifest/board divergence.
    items = {a.id: a for a in b.assets}
    items[asset.id] = asset
    b.assets = list(items.values())
    if scene_id:
        next(s for s in b.scenes if s.id == scene_id).asset_refs = [asset.id]
    b = Storyboard.model_validate(b.model_dump())
    save(project / "storyboard.json", b)
    save(project / "assets/manifest.json", [a.model_dump() for a in b.assets])


def images(project, scene_id=None, dry_run=False):
    b = read(project / "storyboard.json", Storyboard)
    base, _, model = settings("IMAGE")
    scenes = [s for s in b.scenes if scene_id is None or s.id == scene_id]
    if not scenes:
        raise ValueError("Unknown scene")
    import os
    jobs = []
    for s in scenes:
        prompt = STYLE + "Shot: " + s.visual_intent
        config = {"provider": base, "model": model, "prompt": prompt,
                  "size": os.getenv("IMAGE_SIZE", "1024x1536"), "quality": os.getenv("IMAGE_QUALITY", "medium")}
        key = digest(json.dumps(config, sort_keys=True, ensure_ascii=False))[:24]
        jobs.append({"scene_id": s.id, "key": key, **config})
    save(project / "image-prompts.json", jobs)
    if dry_run:
        print(f"Saved {len(jobs)} requests to image-prompts.json; no network calls")
        return
    for job in jobs:
        path = f"assets/generated/{job['key']}.png"
        dest = local_file(project, path)
        meta = dest.with_suffix(".json")
        if dest.exists() and meta.exists() and read(meta).get("sha256") == digest(dest.read_bytes()):
            generation = read(meta)
        else:
            generation = image_request(project, job["prompt"], dest)
            generation = {**job, "created_at": now(), "sha256": generation["sha256"]}
            save(meta, generation, history=False)
        register(project, Asset(id=f"generated-{job['scene_id']}", kind="image", path=path,
            source=base, creator=f"AI generated / {model}", license="Generated output; provider terms apply",
            description=job["prompt"], sha256=digest(dest.read_bytes()), acquired_at=now(), generation=generation), job["scene_id"])
        print(f"image ready: {job['scene_id']}", flush=True)


def import_image(project, scene_id, source_path, prompt, provider):
    from PIL import Image
    source_path = Path(source_path)
    with Image.open(source_path) as im:
        im.verify()
    sha = digest(source_path.read_bytes())
    relative = f"assets/generated/{sha[:24]}{source_path.suffix.lower()}"
    destination = local_file(project, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, destination)
    generation = {"provider": provider, "prompt": prompt, "created_at": now(), "sha256": sha}
    register(project, Asset(id=f"generated-{scene_id}", kind="image", path=relative, source=provider,
        creator=f"AI generated / {provider}", license="Generated output; provider terms apply",
        description=prompt, sha256=sha, acquired_at=now(), generation=generation), scene_id)


def bgm(project, track="moonlight", catalog=None):
    tracks = read(catalog or ROOT / "examples/music/catalog.json")
    selected = next((t for t in tracks if t["id"] == track), None)
    if not selected:
        raise ValueError(f"Unknown music track: {track}")
    a = Asset.model_validate(selected)
    if a.kind != "audio" or not a.license_url or not a.attribution:
        raise ValueError("Music entry must specify audio, license URL and attribution")
    destination = local_file(project, a.path)
    if not destination.exists():
        fetch(a.download_url, destination)
    from .speech import duration
    duration(destination)  # Reject HTML/error payloads before adding music to project.
    sha = digest(destination.read_bytes())
    if a.sha256 and a.sha256 != sha:
        raise ValueError("Music checksum mismatch")
    a.sha256, a.acquired_at = sha, now()
    register(project, a)
    b = read(project / "storyboard.json", Storyboard)
    # Retire the old synthetic placeholder from the active manifest, preserve file/history.
    b.assets = [item for item in b.assets if item.kind != "audio" or item.id == a.id]
    b.bgm_path = a.path
    b.bgm_volume = 0.16
    save(project / "storyboard.json", b)
    save(project / "assets/manifest.json", [item.model_dump() for item in b.assets])
    credits(project)
    print(f"BGM downloaded: {a.id} ({a.license})", flush=True)


def credits(project):
    b = read(project / "storyboard.json", Storyboard)
    used = {ref for s in b.scenes for ref in s.asset_refs}
    lines = [f"# {b.poem_title} · {b.author}", "", "本片仅朗诵原词。声音为 AI 合成。", ""]
    for a in b.assets:
        if a.id not in used and a.path != b.bgm_path and a.kind != "font":
            continue
        lines += [f"## {a.id}", "", a.attribution or f"{a.creator} — {a.license}",
                  f"来源：{a.source}", f"许可：{a.license_url or a.license}",
                  "改动：画面裁剪与缓慢推移；音乐截取、淡入淡出、降低音量。", ""]
    lines += ["发布时将所用素材的署名与许可链接放入视频说明。Moonlight 的作者要求 YouTube 说明栏署名。", ""]
    (project / "credits.md").write_text("\n".join(lines))
