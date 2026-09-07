"""Small synchronous adapters for OpenAI-compatible image/speech endpoints.

Each stage saves its request and result separately. Auth never enters a log.
No automatic provider switch, quota retry, or expensive model substitution.
"""
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from .storage import digest, now, save
from . import traces

ROOT = Path(__file__).resolve().parents[2]


class MediaError(ValueError):
    pass


def settings(kind):
    load_dotenv(ROOT / ".env.local")
    base = os.getenv(f"{kind}_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    url = urlsplit(base)
    if url.scheme != "https" or url.username or url.password or url.query or url.fragment:
        raise MediaError(f"{kind}_BASE_URL must be an HTTPS API base URL without credentials/query")
    key = os.getenv(f"{kind}_API_KEY")
    # Reuse OpenAI credentials only on OpenAI's own host, never on a custom gateway.
    if not key and url.hostname == "api.openai.com":
        key = os.getenv("OPENAI_API_KEY")
    model = os.getenv(f"{kind}_MODEL", "gpt-image-2" if kind == "IMAGE" else "gpt-4o-mini-tts")
    return base, key, model


def post(project, kind, endpoint, payload):
    base, key, _ = settings(kind)
    traces.update(provider=base, model=payload.get('model'), request=payload, endpoint=endpoint)
    if not key:
        raise MediaError(f"Set {kind}_API_KEY for {base}; credentials are never inferred across providers")
    request_hash = digest(json.dumps({"base": base, "payload": payload}, sort_keys=True, ensure_ascii=False))
    run = Path(project) / "runs" / f"{kind.lower()}-{request_hash[:12]}-{uuid4().hex[:6]}.json"
    record = {"created_at": now(), "provider": base, "request_hash": request_hash, "request": payload, "status": "started", "trace_id": traces.CURRENT.get().data['id'] if traces.CURRENT.get() else None}
    save(run, record, history=False)
    try:
        r = httpx.post(base + endpoint, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=180)
    except httpx.HTTPError:
        record.update(status="failed", error="transport_error")
        save(run, record, history=False)
        raise MediaError(f"{kind}: transport error (request saved; no automatic retry)") from None
    if r.status_code != 200:
        traces.update(http_status=r.status_code)
        code = "http_error"
        try:
            raw = r.json().get("error", {})
            candidate = raw.get("code") or raw.get("type") if isinstance(raw, dict) else "http_error"
            # Do not echo provider messages: gateways may echo credentials or URLs.
            if candidate in {"insufficient_quota", "credit_balance_exhausted", "invalid_api_key", "model_not_found", "rate_limit_exceeded"}:
                code = candidate
        except (ValueError, AttributeError):
            pass
        record.update(status="failed", http_status=r.status_code, error=code)
        traces.update(response={'http_status':r.status_code,'error':code,'body':r.text.replace(key,'[REDACTED]')})
        save(run, record, history=False)
        raise MediaError(f"{kind}: HTTP {r.status_code} ({code}); stage stopped, existing assets preserved")
    record.update(status="received", http_status=r.status_code, response_sha256=digest(r.content))
    traces.update(http_status=r.status_code, response_sha256=digest(r.content), response_bytes=len(r.content))
    save(run, record, history=False)
    return r, run, record


def fetch(url, destination):
    """Download an explicit asset URL, using a public client with no API auth."""
    if urlsplit(url).scheme != "https":
        raise MediaError("Asset download requires HTTPS")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".download")
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=90, headers={"User-Agent": "CiJian/0.1"}) as r:
            if r.status_code != 200 or "text/html" in r.headers.get("content-type", ""):
                raise MediaError(f"Asset download failed (HTTP {r.status_code}); expected media")
            total = 0
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > 200 * 1024 * 1024:
                        raise MediaError("Asset exceeds MVP 200 MiB download limit")
                    f.write(chunk)
        if not total:
            raise MediaError("Empty asset response")
        tmp.replace(destination)
    except httpx.HTTPError:
        raise MediaError("Asset download transport error; retry explicitly") from None
    finally:
        tmp.unlink(missing_ok=True)


@traces.traced('speech_api')
def speech_request(project, text, voice, model, speed, instructions):
    payload = {"model": model, "input": text, "voice": voice, "response_format": "mp3", "speed": speed}
    if instructions:
        payload["instructions"] = instructions
    response, run, record = post(project, "TTS", "/audio/speech", payload)
    if "json" in response.headers.get("content-type", "") or len(response.content) < 64:
        raise MediaError("TTS returned no audio data")
    return response.content, run, record


@traces.traced('image_api')
def image_request(project, prompt, destination, prompt_snapshot=None):
    _, _, model = settings("IMAGE")
    payload = {"model": model, "prompt": prompt, "n": 1, "size": os.getenv("IMAGE_SIZE", "1024x1536")}
    quality = os.getenv("IMAGE_QUALITY", "medium")
    if prompt_snapshot:
        traces.update(prompt=prompt_snapshot,scene_id=prompt_snapshot.get('scene_id'))
        payload.update({k:v for k,v in prompt_snapshot['parameters'].items() if k in {'model','size'}})
        quality = prompt_snapshot['parameters'].get('quality', quality)
    if quality:
        payload["quality"] = quality
    response, run, record = post(project, "IMAGE", "/images/generations", payload)
    try:
        data = response.json()
        item = data["data"][0]
        traces.update(response={**data, 'data': [{k:v for k,v in item.items() if k != 'b64_json'}]}, usage=data.get('usage'))
        destination.parent.mkdir(parents=True, exist_ok=True)
        if item.get("b64_json"):
            destination.write_bytes(base64.b64decode(item["b64_json"], validate=True))
        elif item.get("url"):
            fetch(item["url"], destination)
        else:
            raise ValueError("missing image")
        from PIL import Image
        with Image.open(destination) as im:
            im.verify()
        record.update(status="complete", output=str(destination.relative_to(project)),
                      sha256=digest(destination.read_bytes()), usage=data.get("usage"),
                      revised_prompt=item.get("revised_prompt"))
        save(run, record, history=False)
        traces.update(artifacts=[{'path':str(destination.relative_to(project)), 'sha256':record['sha256']}])
        return record
    except (ValueError, KeyError, IndexError, OSError):
        destination.unlink(missing_ok=True)
        record.update(status="failed", error="invalid_image_response")
        save(run, record, history=False)
        raise MediaError("Image response is not a decodable image; previous assets preserved") from None
