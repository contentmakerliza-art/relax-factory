"""A Telegram bot for approving test videos from a phone: Telegram loads well
where Google Drive and the app do not.

The bot token comes from @BotFather and is kept in SECRETS. The first chat
that sends /start becomes the only chat the bot talks to.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from render.youtube import SECRETS, _write

API = os.environ.get("TELEGRAM_API", "https://api.telegram.org")  # another address only in tests
STATE = SECRETS / "telegram.json"


def state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(d: dict) -> None:
    _write(STATE, d)


def _url(method: str, token: str = "") -> str:
    return f"{API}/bot{token or state().get('token', '')}/{method}"


def call(method: str, params: dict | None = None, token: str = "", timeout: int = 60) -> dict:
    req = urllib.request.Request(_url(method, token), data=json.dumps(params or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read())
        except ValueError:
            raise RuntimeError(f"Telegram ответил {e.code}") from None
    if not data.get("ok"):
        raise RuntimeError(f"Telegram: {data.get('description', 'ошибка')}")
    return data["result"]


def set_token(token: str) -> str:
    """Checks the token, drops a webhook (it would block getUpdates); returns
    the bot's @name."""
    me = call("getMe", token=token)
    call("deleteWebhook", token=token)
    save({"token": token, "bot": me.get("username", ""), "chat_id": None, "offset": 0})
    return me.get("username", "")


def send_video(video: Path, caption: str, buttons: list[list[dict]]) -> dict:
    d = state()
    boundary = uuid.uuid4().hex
    fields = {"chat_id": str(d["chat_id"]), "caption": caption[:1000], "supports_streaming": "true",
              "reply_markup": json.dumps({"inline_keyboard": buttons})}
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items())
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="video"; filename="{video.name}"\r\n'
             "Content-Type: video/mp4\r\n\r\n").encode() + video.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(_url("sendVideo"), data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        data = json.loads(e.read() or b"{}")
    if not data.get("ok"):
        raise RuntimeError(f"Telegram: {data.get('description', 'видео не отправилось')}")
    return data["result"]


def send_text(text: str, chat_id=None) -> None:
    call("sendMessage", {"chat_id": chat_id or state()["chat_id"], "text": text})


def download(file_id: str, dst: Path) -> None:
    path = call("getFile", {"file_id": file_id})["file_path"]
    with urllib.request.urlopen(f"{API}/file/bot{state()['token']}/{path}", timeout=120) as r:
        dst.write_bytes(r.read())
