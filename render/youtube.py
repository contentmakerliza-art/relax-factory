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
