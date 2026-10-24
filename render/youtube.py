"""Connecting YouTube channels through the official API (OAuth, web app).

The OAuth client file and one refresh token per channel are kept in SECRETS,
a folder outside the videos, so the upload browser (which sees the videos)
never sees them. Only the standard library is used.
"""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS = Path(os.environ.get("YOUTUBE_SECRETS", Path(__file__).parent.parent / "secrets"))
CLIENT = SECRETS / "client.json"
CHANNELS = SECRETS / "channels"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube"

_states: dict[str, float] = {}  # OAuth state -> when it was issued


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def save_client(raw: bytes) -> str:
    """Checks and stores the client file downloaded from Google Cloud.
    Returns its client id."""
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("Это не JSON-файл. Скачайте ключ кнопкой «Скачать JSON» в Google Cloud.")
    if "installed" in data:
        raise ValueError("Это ключ типа «Приложение для компьютера». Нужен тип «Веб-приложение».")
    web = data.get("web") or {}
    if not web.get("client_id") or not web.get("client_secret"):
        raise ValueError("В файле нет client_id и client_secret. Нужен JSON идентификатора клиента OAuth (веб-приложение).")
    _write(CLIENT, {"web": web})
    return web["client_id"]


def client() -> dict | None:
    try:
        return json.loads(CLIENT.read_text(encoding="utf-8"))["web"]
    except (OSError, ValueError, KeyError):
        return None


def redirect_uri(fallback_host: str) -> str:
    host = os.environ.get("RELAX_HOST") or fallback_host
    return f"https://{host}/youtube/callback"


def auth_url(redirect: str) -> str:
    c = client()
    if not c:
        raise ValueError("Сначала загрузите ключ (JSON) из Google Cloud.")
    now = time.time()
    for s, t in list(_states.items()):
        if now - t > 1800:
            del _states[s]
    state = secrets.token_urlsafe(24)
    _states[state] = now
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
    })


def _post(url: str, fields: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise ValueError(f"Google ответил {e.code}: {e.read().decode(errors='replace')[:300]}")


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ValueError(f"YouTube ответил {e.code}: {e.read().decode(errors='replace')[:300]}")


def finish(code: str, state: str, redirect: str) -> dict:
    """Swaps the code from Google for tokens and remembers the channel."""
    if _states.pop(state, None) is None:
        raise ValueError("Ссылка устарела. Нажмите «Подключить YouTube» ещё раз.")
    c = client()
    if not c:
        raise ValueError("Ключ из Google Cloud не загружен.")
    tok = _post(TOKEN_URL, {"code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
                            "redirect_uri": redirect, "grant_type": "authorization_code"})
    refresh = tok.get("refresh_token")
    if not refresh:
        raise ValueError("Google не выдал постоянный доступ. Отзовите доступ в настройках аккаунта и подключите снова.")
    items = _get(f"{API}/channels?part=snippet&mine=true", tok["access_token"]).get("items") or []
    if not items:
        raise ValueError("У этого аккаунта нет канала YouTube. При входе выберите аккаунт канала.")
    ch = items[0]
    info = {"id": ch["id"], "title": ch["snippet"]["title"], "refresh_token": refresh, "connected": int(time.time())}
    _write(CHANNELS / f"{ch['id']}.json", info)
    return info


def channels() -> list[dict]:
    out = []
    for f in sorted(CHANNELS.glob("*.json")) if CHANNELS.exists() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": d["id"], "title": d["title"], "connected": d.get("connected")})
        except (OSError, ValueError, KeyError):
            continue
    return out


def access_token(channel_id: str) -> str:
    """A fresh short-lived token for API calls on this channel."""
    c = client()
    f = CHANNELS / f"{channel_id}.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    try:
        tok = _post(TOKEN_URL, {"refresh_token": d["refresh_token"], "client_id": c["client_id"],
                                "client_secret": c["client_secret"], "grant_type": "refresh_token"})
    except ValueError as e:
        if "invalid_grant" in str(e):  # access revoked on Google's side: forget the channel
            f.unlink(missing_ok=True)
            raise ValueError(f"Доступ к каналу «{d['title']}» отозван. Подключите его снова.")
        raise
    return tok["access_token"]


def disconnect(channel_id: str) -> None:
    f = CHANNELS / f"{channel_id}.json"
    if not f.exists():
        return
    try:
        _post(REVOKE_URL, {"token": json.loads(f.read_text(encoding="utf-8"))["refresh_token"]})
    except (ValueError, KeyError):
        pass  # already revoked on Google's side
    f.unlink()


UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
THUMB_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CHUNK = 64 * 1024 * 1024  # a multiple of 256 KB, as resumable uploads require
TOKEN_LIFE = 45 * 60  # Google tokens last an hour: take a fresh one well before


class ApiError(ValueError):
    def __init__(self, code: int, text: str):
        super().__init__(f"YouTube ответил {code}: {text}")
        self.code = code


class _Token:
    """Keeps a fresh access token for a long upload."""

    def __init__(self, channel_id: str):
        self.channel_id, self.value, self.at = channel_id, "", 0.0

    def __str__(self) -> str:
        if time.time() - self.at > TOKEN_LIFE:
            self.value, self.at = access_token(self.channel_id), time.time()
        return self.value


def _call(method: str, url: str, token, body: bytes | None = None, headers: dict | None = None,
          ok=(200, 201)) -> tuple[int, dict, bytes]:
    h = {"Authorization": f"Bearer {token}", **(headers or {})}
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        data = e.read()
        if e.code in ok:
            return e.code, dict(e.headers), data
        raise ApiError(e.code, data.decode(errors="replace")[:400])


def _json(token, method: str, url: str, data: dict) -> dict:
    _, _, raw = _call(method, url, token, json.dumps(data).encode(),
                      {"Content-Type": "application/json; charset=utf-8"})
    return json.loads(raw or b"{}")


def playlists(channel_id: str) -> list[dict]:
    t = access_token(channel_id)
    items = _get(f"{API}/playlists?part=snippet&mine=true&maxResults=50", t).get("items") or []
    return [{"id": p["id"], "title": p["snippet"]["title"]} for p in items]


def upload(channel_id: str, video: Path, meta: dict, thumbnail: Path | None, playlist: str,
           progress) -> tuple[str, str]:
    """Uploads the video in pieces (resumable: a dropped connection continues
    where it stopped), then sets the thumbnail and adds it to the playlist.
    Returns the video id and what did not work after the video was in."""
    token = _Token(channel_id)
    size = video.stat().st_size
    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": bool(meta.get("synthetic"))}
    if meta.get("publish_at"):
        status["publishAt"] = meta["publish_at"]
    body = {"snippet": {"title": meta["title"], "description": meta.get("description", ""),
                        "tags": meta.get("tags", []), "categoryId": meta.get("category", "22"),
                        "defaultLanguage": meta.get("language", "en"),
                        "defaultAudioLanguage": meta.get("language", "en")},
            "status": status}
    _, headers, _ = _call("POST", UPLOAD_URL, token, json.dumps(body).encode(), {
        "Content-Type": "application/json; charset=utf-8",
        "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    session = {k.lower(): v for k, v in headers.items()}["location"]

    sent, fails, result = 0, 0, None
    with video.open("rb") as f:
        while result is None:
            f.seek(sent)
            piece = f.read(CHUNK)
            end = sent + len(piece) - 1
            try:
                code, h, raw = _call("PUT", session, token, piece,
                                     {"Content-Range": f"bytes {sent}-{end}/{size}"}, ok=(200, 201, 308))
                fails = 0
            except (ValueError, OSError) as e:
                fails += 1
                if fails > 8 or (isinstance(e, ApiError) and e.code < 500):
                    raise  # a refused request will not get better by retrying
                time.sleep(min(60, 5 * fails))
                try:  # ask how much YouTube already has, then continue from there
                    code, h, raw = _call("PUT", session, token, b"",
                                         {"Content-Range": f"bytes */{size}"}, ok=(200, 201, 308))
                except (ValueError, OSError):
                    continue
            if code in (200, 201):
                result = json.loads(raw)
                break
            got = {k.lower(): v for k, v in h.items()}.get("range")
            sent = int(got.split("-")[1]) + 1 if got else 0
            progress(sent / size)
    video_id = result["id"]
    progress(1.0)

    problems = []  # the video is already in: report these, don't fail the upload
    if thumbnail and thumbnail.exists():
        try:
            _call("POST", f"{THUMB_URL}?videoId={video_id}", token, thumbnail.read_bytes(),
                  {"Content-Type": "image/jpeg"})
        except (ValueError, OSError) as e:
            problems.append(f"обложка не поставилась ({e})")
    if playlist:
        try:
            _json(token, "POST", f"{API}/playlistItems?part=snippet", {
                "snippet": {"playlistId": playlist, "resourceId": {"kind": "youtube#video", "videoId": video_id}}})
        except (ValueError, OSError) as e:
            problems.append(f"в плейлист не добавилось ({e})")
    return video_id, "; ".join(problems)[:500]
