import argparse
import asyncio
import sys
from pathlib import Path

from . import pipeline
from .models import Brief, ContentProject, ResearchPack, Script, Storyboard
from .storage import read, save


def _main():
    p = argparse.ArgumentParser(description="Editable poetry films: independent stages, JSON on disk")
    subs = p.add_subparsers(dest="command", required=True)
    for cmd in ["research", "script", "storyboard", "assets", "validate", "tts", "render", "init", "demo", "replay", "images", "import-image", "bgm", "credits", "edit", "traces"]:
        s = subs.add_parser(cmd)
        s.add_argument("project", type=Path)
        if cmd == 'traces':
            s.add_argument('--export', type=Path)
            s.add_argument('--import-legacy', action='store_true')
        if cmd == "edit":
            s.add_argument("--port", type=int, default=8765)
        if cmd == "init":
            s.add_argument("--brief", type=Path, required=True)
            s.add_argument("--sources", type=Path, required=True)
            s.add_argument("--assets", type=Path, required=True)
        if cmd == "tts":
            s.add_argument("--fit", action="store_true")
            s.add_argument("--provider", choices=["external", "edge", "macos"])
            s.add_argument("--voice")
        if cmd == "images":
            s.add_argument("--scene")
            s.add_argument("--dry-run", action="store_true")
        if cmd == "import-image":
            s.add_argument("--scene", required=True)
            s.add_argument("--file", type=Path, required=True)
            s.add_argument("--prompt", required=True)
            s.add_argument("--provider", required=True)
        if cmd == "bgm":
            s.add_argument("--track", default="moonlight")
            s.add_argument("--catalog", type=Path)
        if cmd == "render":
            s.add_argument("--scale", type=float, default=1.0)
            s.add_argument("--still", type=int)
        if cmd == "replay":
            s.add_argument("--run", type=Path, required=True)
    subs.add_parser("schemas").add_argument("directory", type=Path)
    args = p.parse_args()
    try:
        if args.command == "schemas":
            for model in [Brief, ContentProject, ResearchPack, Script, Storyboard]:
                save(args.directory / f"{model.__name__}.schema.json", model.model_json_schema(), history=False)
            return
        root = args.project.resolve()
        if args.command == 'traces':
            from . import traces
            if args.import_legacy:
                print(f'Imported {traces.import_legacy(root)} records')
            if args.export:
                args.export.write_text(traces.export(root))
            else:
                print(f'{len(traces.records(root))} traces')
        elif args.command == "edit":
            from .editor import serve
            serve(root, args.port)
        elif args.command in {"images", "import-image", "bgm", "credits"}:
            from . import assets
            if args.command == "images":
                assets.images(root, args.scene, args.dry_run)
            elif args.command == "import-image":
                assets.import_image(root, args.scene, args.file, args.prompt, args.provider)
            elif args.command == "bgm":
                assets.bgm(root, args.track, args.catalog)
            else:
                assets.credits(root)
        elif args.command == "init":
            pipeline.init(root, args.brief, args.sources, args.assets)
        elif args.command == "demo":
            example = pipeline.ROOT / "examples/huanxisha"
            pipeline.init(root, example / "brief.json", example / "research.json", example / "assets.json")
            save(root / "script.json", read(example / "script.json", Script))
            pipeline.board(root)
        elif args.command == "replay":
            run = read(args.run)
            cls, file = {"research": (ResearchPack, "research.json"), "script": (Script, "script.json")}[run["stage"]]
            obj = cls.model_validate_json(run["response"]["choices"][0]["message"]["content"])
            if cls is Script:
                pipeline.validate_script(obj, read(root / "research.json", ResearchPack))
            else:
                source = read(root / "sources.json", ResearchPack)
                for attr in ["sources", "evidence", "original_text", "author", "poem_title"]:
                    if getattr(obj, attr) != getattr(source, attr):
                        raise ValueError(f"replay changed locked {attr}")
                obj.review_status = "needs_review"
            save(root / file, obj)
        elif args.command == "tts":
            from .speech import synthesize
            asyncio.run(synthesize(root, fit=args.fit, provider=args.provider, voice=args.voice))
        elif args.command == "render":
            if not 0.25 <= args.scale <= 1:
                raise ValueError("scale must be between 0.25 and 1")
            pipeline.render(root, scale=args.scale, still=args.still)
        elif args.command == "validate":
            b = pipeline.validate_render(root)
            print(f"Valid: {len(b.scenes)} scenes, {sum(s.duration for s in b.scenes):.2f}s; no LLM/Research needed")
        else:
            {"research": pipeline.research, "script": pipeline.script,
             "storyboard": pipeline.board, "assets": pipeline.download_assets}[args.command](root)
    except Exception as e:
        from .traces import update
        update(error={'type':type(e).__name__,'message':str(e)[:2000]})
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    import os
    from .traces import Trace
    if len(sys.argv) >= 3 and not sys.argv[2].startswith('-') and sys.argv[1] in {'research','script','storyboard','assets','tts','render','replay','images','import-image','bgm'}:
        project = Path(sys.argv[2]).resolve()
        with Trace(project, sys.argv[1], 'stage', command=sys.argv[1:]) as trace:
            previous = {k:os.environ.get(k) for k in ('CI_RUN_ID','CI_PARENT_TRACE_ID')}
            os.environ['CI_RUN_ID'] = trace.data['run_id']
            os.environ['CI_PARENT_TRACE_ID'] = trace.data['id']
            try:
                _main()
            finally:
                for key,value in previous.items():
                    if value is None:
                        os.environ.pop(key,None)
                    else:
                        os.environ[key]=value
    else:
        _main()


if __name__ == "__main__":
    main()
