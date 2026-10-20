"""Download files from a Google Drive link straight to the server.

The folder (or file) must be shared as "Anyone with the link can view".
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import gdown

FOLDER = re.compile(r"/folders/([\w-]+)")


def fetch_folder(url: str, dst: Path, exts: set[str]) -> list[Path]:
    """Put every file with one of `exts` from the Drive folder or file at `url` into `dst`."""
    dst.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dst.parent) as tmp:
        try:
            if m := FOLDER.search(url):
                gdown.download_folder(id=m.group(1), output=tmp, quiet=True, use_cookies=False)
            else:
                gdown.download(url, output=tmp + "/", quiet=True, fuzzy=True, use_cookies=False)
        except Exception as exc:
            raise RuntimeError(
                "Не получилось скачать с Google Диска. Проверьте, что доступ открыт "
                f"«Все, у кого есть ссылка». ({exc})"
            ) from exc
        found = sorted(p for p in Path(tmp).rglob("*") if p.is_file() and p.suffix.lower() in exts)
        if not found:
            raise RuntimeError("В папке на Google Диске нет подходящих файлов")
        out = []
        for p in found:
            target = dst / p.name
            shutil.move(p, target)
            out.append(target)
    return out
