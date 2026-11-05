"""Download files from a Google Drive link straight to the server.

The folder (or file) must be shared as "Anyone with the link can view".
"""

from __future__ import annotations

import re
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import gdown

FOLDER = re.compile(r"/folders/([\w-]+)")
FILE = re.compile(r"(?:/d/|[?&]id=)([\w-]{20,})")


# first bytes -> extension, for files that come without a usable name
KNOWN = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".m4a", ".mp3", ".wav", ".ogg", ".flac",
         ".webm", ".mkv", ".aac"}


def sniff(path: Path) -> str:
    with path.open("rb") as f:
        head = f.read(16)
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    if head[4:8] == b"ftyp":
        return ".m4a" if head[8:11] == b"M4A" else ".mov" if head[8:10] == b"qt" else ".mp4"
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return ".mp3"
    if head.startswith(b"OggS"):
        return ".ogg"
    if head.startswith(b"fLaC"):
        return ".flac"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return ".mkv"
    return ""


CACHE: Path | None = None  # set by the app: files by Drive id, shared by all jobs
TIMEOUT = (20, 120)  # seconds to connect, and with no data: a stuck download fails instead of hanging
LIST_TTL = 600  # a folder's file list is asked again after this many seconds
_lists: dict[str, tuple[float, list[tuple[str, str]]]] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _retry(what: str, fn):
    """Drive fails one request now and then, and slows down a link fetched
    too often: wait longer each time, then say so plainly."""
    for attempt in range(1, 5):
        try:
            return fn()
        except Exception as exc:
            if attempt < 4:
                time.sleep(10 * 3 ** (attempt - 1))  # 10, 30, 90 s
                continue
            raise RuntimeError(
                f"Google Диск не отдал {what} после 4 попыток. Проверьте доступ «Все, у кого есть ссылка». "
                "Если ссылку недавно скачивали много раз, Диск мог временно ограничить её: "
                f"подождите час или возьмите файлы из готовой пробы. ({str(exc)[:200]})") from exc


def _listing(folder_id: str) -> list[tuple[str, str]]:
    """(file id, path inside the folder) for every file, remembered for a while."""
    with _lock("list:" + folder_id):
        hit = _lists.get(folder_id)
        if hit and time.time() - hit[0] < LIST_TTL:
            return hit[1]
        with tempfile.TemporaryDirectory() as tmp:
            files = _retry("список файлов папки", lambda: gdown.download_folder(
                id=folder_id, output=tmp, quiet=True, use_cookies=False, skip_download=True,
                timeout=TIMEOUT))
        rows = [(f.id, f.path) for f in files or []]
        _lists[folder_id] = (time.time(), rows)
        return rows


def _cached(file_id: str, name: str, scratch: Path) -> Path:
    """The file, downloaded once and kept under its Drive id: later jobs get
    a hard link instead of asking Drive again."""
    home = (CACHE or scratch) / file_id
    with _lock("file:" + file_id):
        ready = [p for p in home.iterdir() if p.is_file()] if home.is_dir() else []
        if ready:
            return ready[0]
        part = home / ".part"
        part.mkdir(parents=True, exist_ok=True)
        got = Path(_retry(f"файл {name or file_id}", lambda: gdown.download(
            id=file_id, output=str(part) + "/", quiet=True, use_cookies=False, resume=True,
            timeout=TIMEOUT)))
        # Drive sometimes gives a file without its name, so without an
        # extension: tell the type by its first bytes
        final = name or got.name
        if Path(final).suffix.lower() not in KNOWN and (ext := sniff(got)):
            final += ext
        target = home / Path(final).name
        got.replace(target)
        shutil.rmtree(part, ignore_errors=True)
        return target


def _put(src: Path, dst: Path) -> Path:
    target = dst / src.name
    target.unlink(missing_ok=True)
    try:
        os.link(src, target)
    except OSError:
        shutil.copy2(src, target)
    return target


def fetch_folder(url: str, dst: Path, exts: set[str], progress=None) -> list[Path]:
    """Put every file with one of `exts` from the Drive folder or file at `url`
    into `dst`. `progress(done, total)` is told after each file."""
    dst.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dst.parent) as tmp:
        if m := FOLDER.search(url):
            rows = _listing(m.group(1))
            # skip what is surely not wanted; a file without a known extension is
            # fetched and told by its bytes
            rows = [(i, p) for i, p in rows
                    if Path(p).suffix.lower() in exts or Path(p).suffix.lower() not in KNOWN]
            if not rows:
                raise RuntimeError("В папке на Google Диске нет подходящих файлов (или папка закрыта)")
        elif m := FILE.search(url):
            rows = [(m.group(1), "")]
        else:
            raise RuntimeError("Это не похоже на ссылку на файл или папку Google Диска")
        found = []
        for n, (file_id, path) in enumerate(rows, 1):
            f = _cached(file_id, Path(path).name, Path(tmp))
            if f.suffix.lower() in exts:
                found.append(_put(f, dst))
            if progress:
                progress(n, len(rows))
        if not found:
            raise RuntimeError("На Google Диске по этой ссылке нет подходящих файлов")
    return sorted(found)
