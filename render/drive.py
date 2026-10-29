"""Download files from a Google Drive link straight to the server.

The folder (or file) must be shared as "Anyone with the link can view".
"""

from __future__ import annotations

import re
import shutil
import tempfile
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


def fetch_folder(url: str, dst: Path, exts: set[str]) -> list[Path]:
    """Put every file with one of `exts` from the Drive folder or file at `url` into `dst`."""
    dst.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dst.parent) as tmp:
        for attempt in range(1, 5):
            try:
                if m := FOLDER.search(url):
                    # resume: files that came down on an earlier attempt are kept
                    gdown.download_folder(id=m.group(1), output=tmp, quiet=True,
                                          use_cookies=False, resume=True)
                else:
                    m = FILE.search(url)
                    gdown.download(id=m.group(1) if m else None, url=None if m else url,
                                   output=tmp + "/", quiet=True, use_cookies=False, resume=True)
                break
            except Exception as exc:  # Drive often fails one file now and then
                if attempt < 4:
                    time.sleep(5 * attempt)
                    continue
                raise RuntimeError(
                    "Не получилось скачать с Google Диска. Проверьте, что доступ открыт "
                    f"«Все, у кого есть ссылка». ({exc})"
                ) from exc
        for p in list(Path(tmp).rglob("*")):
            # Drive sometimes gives a single file without its name, so without
            # an extension: tell the type by its first bytes
            if p.is_file() and p.suffix.lower() not in KNOWN and (ext := sniff(p)):
                p.rename(p.with_name(p.name + ext))
        found = sorted(p for p in Path(tmp).rglob("*") if p.is_file() and p.suffix.lower() in exts)
        if not found:
            got = [p.name for p in Path(tmp).rglob("*") if p.is_file()]
            raise RuntimeError("На Google Диске по этой ссылке нет подходящих файлов"
                               + (f" (пришло: {', '.join(got[:5])})" if got else " (ничего не скачалось)"))
        out = []
        for p in found:
            target = dst / p.name
            shutil.move(p, target)
            out.append(target)
    return out
