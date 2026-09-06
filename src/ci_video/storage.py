import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data: str | bytes):
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def read(path, model=None):
    data = json.loads(Path(path).read_text())
    return model.model_validate(data) if model else data


def save(path, value, history=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and history:
        old = path.read_bytes()
        if old == payload.encode():
            return
        archive = path.parent / "history" / f"{path.stem}-{digest(old)[:16]}.json"
        archive.parent.mkdir(exist_ok=True)
        archive.write_bytes(old)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def local_file(root, relative):
    root = Path(root).resolve()
    p = (root / relative).resolve()
    if not p.is_relative_to(root):
        raise ValueError("file escapes project directory")
    return p
