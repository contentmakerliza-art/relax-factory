"""Upload-Post (upload-post.com): it fetches the finished video by a link and
puts it on YouTube through its own verified Google app, so a 10-hour file never
leaves the server through the slow home connection."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from render.youtube import SECRETS

API = os.environ.get("UPLOAD_POST_API", "https://api.upload-post.com/api")  # another address only in tests
KEY_FILE = SECRETS / "upload-post-key"


def api_key() -> str:
    """From the server settings (UPLOAD_POST_API_KEY in deploy/.env) or the
    key saved on the page; never sent back to the page."""
    key = os.environ.get("UPLOAD_POST_API_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
    return key


def save_key(key: str) -> None:
    SECRETS.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.strip())
    KEY_FILE.chmod(0o600)


def _call(req: urllib.request.Request) -> dict:
    req.add_header("Authorization", f"Apikey {api_key()}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:400]
        if e.code == 404 and "not_found" in body:
            return {"status": "not_found"}
        raise RuntimeError(f"Upload-Post {e.code}: {body}") from None


def send(fields: list[tuple[str, str]]) -> dict:
    """POST /upload as multipart/form-data (the video itself goes as a link)."""
    boundary = uuid.uuid4().hex
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode() + v.encode() + b"\r\n"
        for k, v in fields) + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{API}/upload", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return _call(req)


def status(request_id: str = "", job_id: str = "") -> dict:
    q = urllib.parse.urlencode({"request_id": request_id} if request_id else {"job_id": job_id})
    return _call(urllib.request.Request(f"{API}/uploadposts/status?{q}"))
