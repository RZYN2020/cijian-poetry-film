"""Single-project localhost editor. No generation service is required to edit/render."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
from urllib.parse import unquote, urlsplit

from .models import Asset, Storyboard
from .pipeline import ROOT, validate_recital
from .storage import digest, local_file, now, read, save

WEB = Path(__file__).parent / "web"


class Conflict(ValueError):
    pass


class Editor:
    def __init__(self, project):
        self.project = Path(project).resolve()
        read(self.project / "storyboard.json", Storyboard)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.job = {"status": "idle", "log": ""}

    def snapshot(self):
        data = (self.project / "storyboard.json").read_bytes()
        board = Storyboard.model_validate_json(data)
        report = read(self.project / "render-report.json") if (self.project / "render-report.json").exists() else {}
        return {"board": board.model_dump(), "revision": digest(data), "job": dict(self.job),
                "output_exists": (self.project / "output.mp4").exists(),
                "output_current": report.get("storyboard_sha256") == digest(data),
                "output_version": report.get("output_sha256", ""),
                "catalog": read(ROOT / "examples/music/catalog.json")}

    def writable(self, revision):
        if self.job["status"] == "running":
            raise Conflict("后台任务进行中，请完成后再编辑。")
        if revision != digest((self.project / "storyboard.json").read_bytes()):
            raise Conflict("项目已在其他窗口或命令行修改，请重新载入。")

    def update(self, payload):
        with self.lock:
            self.writable(payload.get("revision"))
            board = read(self.project / "storyboard.json")
            edits = payload["scenes"]
            if len(edits) != len(board["scenes"]) or [s["id"] for s in edits] != [s["id"] for s in board["scenes"]]:
                raise ValueError("镜头列表不匹配。")
            for scene, edit in zip(board["scenes"], edits):
                scene["duration"] = round(float(edit["duration"]) * board["fps"]) / board["fps"]
                offset = float(edit["offset"])
                previous = scene["audio"]["offset"] if scene.get("audio") else scene.get("voice_offset", 1)
                scene["voice_offset"] = offset
                if scene.get("audio"):
                    scene["audio"]["offset"] = offset
                for cue in scene["subtitle"]:
                    cue["start"] += offset - previous
                    cue["end"] += offset - previous
                scene["asset_refs"] = [edit["asset_id"]]
                scene["visual_intent"] = edit["visual_intent"]
            for key in ["bgm_path", "bgm_start", "bgm_volume", "bgm_fade", "bgm_duck"]:
                board[key] = payload["music"][key]
            valid = Storyboard.model_validate(board)
            validate_recital(valid)
            if valid.bgm_path and not any(a.kind == "audio" and a.path == valid.bgm_path for a in valid.assets):
                raise ValueError("音乐必须来自素材清单。")
            save(self.project / "storyboard.json", valid)
            return self.snapshot()

    def upload(self, payload):
        with self.lock:
            self.writable(payload.get("revision"))
            board = read(self.project / "storyboard.json", Storyboard)
            kind = payload["kind"]
            if kind not in {"image", "audio"}:
                raise ValueError("只支持图片或音乐。")
            scene = next((s for s in board.scenes if s.id == payload.get("scene_id")), None)
            if kind == "image" and scene is None:
                raise ValueError("未知镜头。")
            content = base64.b64decode(payload["data"], validate=True)
            if not content or len(content) > 30 * 1024 * 1024:
                raise ValueError("文件需要在 30 MB 以内。")
            suffix = Path(payload["name"]).suffix.lower()
            allowed = {"image": {".png", ".jpg", ".jpeg", ".webp"}, "audio": {".mp3", ".wav", ".m4a"}}
            if suffix not in allowed[kind]:
                raise ValueError("不支持此文件格式。")
            sha = digest(content)
            asset = Asset(id=f"local-{sha[:20]}", kind=kind, path=f"assets/imported/{sha[:24]}{suffix}",
                          source=payload["source"].strip(), creator=payload["creator"].strip(),
                          license=payload["license"].strip(), attribution=payload.get("attribution", ""),
                          description=payload["name"], sha256=sha, acquired_at=now())
            dest = local_file(self.project, asset.path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(suffix + ".upload")
            try:
                tmp.write_bytes(content)
                if kind == "image":
                    from PIL import Image
                    with Image.open(tmp) as image:
                        image.verify()
                else:
                    from .speech import duration
                    duration(tmp)
                tmp.replace(dest)
            finally:
                tmp.unlink(missing_ok=True)
            board.assets = [a for a in board.assets if a.id != asset.id] + [asset]
            if scene:
                scene.asset_refs = [asset.id]
            if kind == "audio":
                board.bgm_path = asset.path
            save(self.project / "storyboard.json", board)
            save(self.project / "assets/manifest.json", [a.model_dump() for a in board.assets])
            return self.snapshot()

    def start(self, payload):
        with self.lock:
            self.writable(payload.get("revision"))
            action = payload["action"]
            args = [sys.executable, "-m", "ci_video.cli"]
            if action == "render":
                args += ["render", str(self.project)]
            elif action == "tts":
                provider = payload.get("provider", "edge")
                if provider not in {"edge", "external"}:
                    raise ValueError("未知语音服务。")
                args += ["tts", str(self.project), "--fit", "--provider", provider]
            elif action == "bgm":
                track = payload["track"]
                if track not in {t["id"] for t in read(ROOT / "examples/music/catalog.json")}:
                    raise ValueError("未知音乐。")
                args += ["bgm", str(self.project), "--track", track]
            else:
                raise ValueError("未知任务。")
            self.job = {"status": "running", "action": action, "log": "", "started_at": now()}
            threading.Thread(target=self.run, args=(args,), daemon=True).start()
            return self.snapshot()

    def run(self, args):
        try:
            process = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                with self.lock:
                    self.job["log"] = (self.job["log"] + line)[-12000:]
            code = process.wait()
            with self.lock:
                self.job.update(status="complete" if code == 0 else "failed", exit_code=code)
        except Exception:
            with self.lock:
                self.job.update(status="failed", log="无法启动任务。请查看本机终端。")


def make_server(project, port=8765):
    editor = Editor(project)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, data, mime="application/json; charset=utf-8"):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def trusted(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.trusted():
                return self.send(403, {"error": "Local access only"})
            route = unquote(urlsplit(self.path).path)
            try:
                if route == "/":
                    html = (WEB / "index.html").read_text().replace("__TOKEN__", editor.token)
                    return self.send(200, html.encode(), "text/html; charset=utf-8")
                if route in {"/editor.js", "/style.css"}:
                    return self.send(200, (WEB / route[1:]).read_bytes(), "text/javascript" if route.endswith("js") else "text/css")
                if route == "/api/state":
                    with editor.lock:
                        return self.send(200, editor.snapshot())
                if route.startswith("/media/"):
                    relative = route[len("/media/"):]
                    b = read(editor.project / "storyboard.json", Storyboard)
                    allowed = {a.path for a in b.assets} | {s.audio.path for s in b.scenes if s.audio} | {"output.mp4"}
                    if relative not in allowed:
                        return self.send(404, {"error": "Unknown media"})
                    return self.media(local_file(editor.project, relative))
                self.send(404, {"error": "Not found"})
            except (ValueError, OSError):
                self.send(404, {"error": "文件不存在或无法读取。"})

        def media(self, path):
            size = path.stat().st_size
            start, end, code = 0, size - 1, 200
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                if not match or not any(match.groups()):
                    return self.send(416, {"error": "Invalid range"})
                first, last = match.groups()
                if first:
                    start, end = int(first), min(int(last), size - 1) if last else size - 1
                else:
                    start = max(0, size - int(last))
                if start > end or start >= size:
                    return self.send(416, {"error": "Invalid range"})
                code = 206
            self.send_response(code)
            self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with path.open("rb") as f:
                    f.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = f.read(min(remaining, 256 * 1024))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            expected_origin = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            if not self.trusted() or self.headers.get("X-Editor-Token") != editor.token or self.headers.get("Origin") not in expected_origin | {None}:
                return self.send(403, {"error": "Invalid local session"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 42 * 1024 * 1024:
                    return self.send(413, {"error": "请求过大，文件上限 30 MB。"})
                payload = json.loads(self.rfile.read(length))
                action = {"/api/save": editor.update, "/api/upload": editor.upload, "/api/job": editor.start}.get(self.path)
                if action is None:
                    return self.send(404, {"error": "Not found"})
                self.send(200, action(payload))
            except Conflict as e:
                self.send(409, {"error": str(e)})
            except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as e:
                self.send(400, {"error": str(e)[:1500]})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.editor = editor
    return server


def serve(project, port=8765):
    server = make_server(project, port)
    print(f"词间编辑器：http://127.0.0.1:{server.server_port}（Ctrl+C 退出）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
