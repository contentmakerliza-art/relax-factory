"""Putting a finished test video on Google Drive, to watch it on a phone.

Uses the same Google Cloud client as YouTube, with the narrow drive.file
scope: the app sees only the folder and files it made itself. The token is
kept in SECRETS next to the YouTube ones.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path

from render import youtube
from render.youtube import ApiError, SECRETS, _call, _json, _write

SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN = SECRETS / "drive.json"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,webViewLink"
FOLDER_NAME = "Relax Factory — пробы"


def state() -> dict | None:
    try:
        d = json.loads(TOKEN.read_text(encoding="utf-8"))
        return {"email": d.get("email", ""), "folder": d.get("folder", "")}
    except (OSError, ValueError):
        return None


def finish(code: str, st: str, redirect: str) -> str:
    """Stores the Drive token; returns the account's address."""
    tok = youtube.swap_code(code, st, redirect)
    if not tok.get("refresh_token"):
        raise ValueError("Google не выдал постоянный доступ. Отключите доступ в настройках аккаунта и подключите снова.")
    _, _, raw = _call("GET", f"{API}/about?fields=user", tok["access_token"])
    email = json.loads(raw)["user"].get("emailAddress", "")
    _write(TOKEN, {"refresh_token": tok["refresh_token"], "email": email, "connected": int(time.time())})
    return email


def disconnect() -> None:
    try:
        youtube._post(youtube.REVOKE_URL, {"token": json.loads(TOKEN.read_text())["refresh_token"]})
    except (OSError, ValueError, KeyError):
        pass
    TOKEN.unlink(missing_ok=True)


class _Token:
    def __init__(self, refresh_token: str):
        self.refresh_token, self.value, self.at = refresh_token, "", 0.0

    def __str__(self) -> str:
        if time.time() - self.at > youtube.TOKEN_LIFE:
            try:
                self.value, self.at = youtube.refresh(self.refresh_token), time.time()
            except ValueError as e:
                if "invalid_grant" in str(e):
                    TOKEN.unlink(missing_ok=True)
                    raise ValueError("Доступ к Google Диску отозван. Подключите Диск снова.")
                raise
        return self.value


def _folder(token, d: dict) -> str:
    """The app's own folder (made once, opened 'anyone with the link')."""
    if d.get("folder"):
        try:
            _, _, raw = _call("GET", f"{API}/files/{d['folder']}?fields=id,trashed", token)
            if not json.loads(raw).get("trashed"):
                return d["folder"]
        except ApiError:
            pass
    folder = _json(token, "POST", f"{API}/files",
                   {"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"})["id"]
    _json(token, "POST", f"{API}/files/{folder}/permissions", {"role": "reader", "type": "anyone"})
    d["folder"] = folder
    _write(TOKEN, d)
    return folder


def upload(video: Path, name: str, progress) -> str:
    """Uploads in pieces (resumable) and returns a link that opens for anyone."""
    d = json.loads(TOKEN.read_text(encoding="utf-8"))
    token = _Token(d["refresh_token"])
    folder = _folder(token, d)
    size = video.stat().st_size
    _, headers, _ = _call("POST", UPLOAD, token, json.dumps({"name": name, "parents": [folder]}).encode(), {
        "Content-Type": "application/json; charset=utf-8",
        "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    session = {k.lower(): v for k, v in headers.items()}["location"]
    sent, fails, result = 0, 0, None
    with video.open("rb") as f:
        while result is None:
            f.seek(sent)
            piece = f.read(youtube.CHUNK)
            try:
                code, h, raw = _call("PUT", session, token, piece,
                                     {"Content-Range": f"bytes {sent}-{sent + len(piece) - 1}/{size}"},
                                     ok=(200, 201, 308))
                fails = 0
            except (ValueError, OSError) as e:
                fails += 1
                if fails > 8 or (isinstance(e, ApiError) and e.code < 500):
                    raise
                time.sleep(min(60, 5 * fails))
                try:
                    code, h, raw = _call("PUT", session, token, b"", {"Content-Range": f"bytes */{size}"},
                                         ok=(200, 201, 308))
                except (ValueError, OSError):
                    continue
            if code in (200, 201):
                result = json.loads(raw)
                break
            got = {k.lower(): v for k, v in h.items()}.get("range")
            sent = int(got.split("-")[1]) + 1 if got else 0
            progress(sent / size)
    progress(1.0)
    # the folder is open by link; the file too, in case it is moved out of it
    _json(token, "POST", f"{API}/files/{result['id']}/permissions", {"role": "reader", "type": "anyone"})
    return result.get("webViewLink") or f"https://drive.google.com/file/d/{result['id']}/view"


def folder_link() -> str:
    s = state()
    return f"https://drive.google.com/drive/folders/{urllib.parse.quote(s['folder'])}" if s and s["folder"] else ""
