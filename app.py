"""Web app: upload a picture or clip plus an album, press Render, download the video.

Run:  APP_PASSWORD=... uvicorn app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
import queue
import random
import secrets
import shutil
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from render.drive import fetch_folder
from render.engine import Job, RenderSettings, render

DATA = Path(os.environ.get("APP_DATA", Path(__file__).parent / "data"))
PASSWORD = os.environ.get("APP_PASSWORD", "")
DATA.mkdir(parents=True, exist_ok=True)
(DATA / "busy").unlink(missing_ok=True)  # left over from a restart mid-render

app = FastAPI(title="Релакс-фабрика")
security = HTTPBasic()

jobs: dict[str, dict] = {}
work: queue.Queue[str] = queue.Queue()


def check(creds: HTTPBasicCredentials = Depends(security)) -> None:
    if not PASSWORD or not secrets.compare_digest(creds.password, PASSWORD):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


def worker() -> None:
    while True:
        job_id = work.get()
        info = jobs[job_id]
        info["status"] = "работает"
        started = time.time()
        busy = DATA / "busy"  # auto-update waits while this file exists
        busy.touch()

        def progress(msg: str, frac: float) -> None:
            info["step"], info["progress"] = msg, frac

        try:
            if info.get("drive"):
                _fetch_from_drive(info, progress)
            render(info["job"], progress)
            info["status"] = "готово"
        except Exception as exc:  # shown to the user on the page
            info["status"], info["step"] = "ошибка", str(exc)[-500:]
        info["seconds"] = round(time.time() - started)
        if work.empty():
            busy.unlink(missing_ok=True)


VISUAL_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def _fetch_from_drive(info: dict, progress) -> None:
    """Download the clips and tracks from Google Drive links straight to the server."""
    job: Job = info["job"]
    folder = job.output.parent
    visual_url, tracks_url, pick = info["drive"]
    if visual_url:
        progress("Скачиваю клипы с Google Диска", 0.0)
        job.visuals = fetch_folder(visual_url, folder / "visual", VISUAL_EXTS)
    if tracks_url:
        progress("Скачиваю треки с Google Диска", 0.0)
        job.tracks = fetch_folder(tracks_url, folder / "tracks", AUDIO_EXTS)
    if pick and len(job.tracks) > pick:
        job.tracks = sorted(random.sample(job.tracks, pick))


threading.Thread(target=worker, daemon=True).start()


CHUNK_LIMIT = 64 * 1024 * 1024
KINDS = {"visual", "tracks"}


def _job_dir(job_id: str) -> Path:
    folder = (DATA / job_id).resolve()
    if folder.parent != DATA.resolve() or not folder.is_dir():
        raise HTTPException(404, "Нет такого задания")
    return folder


@app.post("/jobs/new", dependencies=[Depends(check)])
def new_job():
    """Files are sent in small pieces (a proxy in front may cut long requests)."""
    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    for kind in KINDS:
        (DATA / job_id / kind).mkdir(parents=True)
    return {"id": job_id}


@app.put("/jobs/{job_id}/files/{kind}/{name}", dependencies=[Depends(check)])
async def upload_chunk(job_id: str, kind: str, name: str, request: Request, offset: int = 0):
    if kind not in KINDS or job_id in jobs:
        raise HTTPException(400, "Нельзя загрузить")
    dst = _job_dir(job_id) / kind / Path(name).name
    size = dst.stat().st_size if dst.exists() else 0
    if offset != size:
        raise HTTPException(409, f"Ожидалось смещение {size}")
    received = 0
    with dst.open("ab") as f:
        try:
            async for piece in request.stream():
                received += len(piece)
                if received > CHUNK_LIMIT:
                    raise HTTPException(413, "Слишком большой кусок")
                f.write(piece)
        except BaseException:
            f.truncate(size)  # drop a half-received piece so the browser can send it again
            raise
    return {"size": size + received}


@app.post("/jobs/{job_id}/start", dependencies=[Depends(check)])
def start_job(
    job_id: str,
    hours: float = Form(3.0),
    resolution: str = Form("4k"),
    fps: int = Form(60),
    loop_mode: str = Form("crossfade"),
    speed: float = Form(1.0),
    track_crossfade: float = Form(3.0),
    loop_crossfade: float = Form(1.5),
    shuffle: bool = Form(False),
    codec: str = Form("h264"),
    bitrate: int = Form(15),
    visual_url: str = Form(""),
    tracks_url: str = Form(""),
    tracks_pick: int = Form(0),
):
    if not 0 < hours <= 12:
        raise HTTPException(400, "Длина от 0 до 12 часов")
    if job_id in jobs:
        raise HTTPException(400, "Задание уже запущено")
    folder = _job_dir(job_id)
    visual_url, tracks_url = visual_url.strip(), tracks_url.strip()
    visuals = [] if visual_url else sorted((folder / "visual").iterdir())
    trk = [] if tracks_url else sorted((folder / "tracks").iterdir())
    if not (visuals or visual_url) or not (trk or tracks_url):
        raise HTTPException(400, "Нужны картинка или клипы и хотя бы один трек (файлы или ссылка на Google Диск)")
    if not tracks_url and tracks_pick and len(trk) > tracks_pick:
        trk = sorted(random.sample(trk, tracks_pick))
    name = visuals[0].stem if visuals else "video"
    w, h = (3840, 2160) if resolution == "4k" else (1920, 1080)
    settings = RenderSettings(
        width=w, height=h, fps=fps, duration=hours * 3600, loop_mode=loop_mode,
        speed=speed, loop_crossfade=loop_crossfade, track_crossfade=track_crossfade, shuffle_tracks=shuffle,
        codec=codec, video_bitrate=f"{bitrate}M",
    )
    out = folder / f"{name}_{hours:g}h.mp4"
    jobs[job_id] = {"job": Job(visuals, trk, out, settings), "status": "в очереди",
                    "step": "", "progress": 0.0, "created": time.time(),
                    "drive": (visual_url, tracks_url, tracks_pick) if visual_url or tracks_url else None}
    work.put(job_id)
    return {"id": job_id}


@app.get("/jobs", dependencies=[Depends(check)])
def list_jobs():
    rows = []
    for job_id, info in sorted(jobs.items(), reverse=True):
        job: Job = info["job"]
        rows.append({
            "id": job_id, "status": info["status"], "step": info["step"],
            "progress": info["progress"], "seconds": info.get("seconds"),
            "visual": (job.visuals[0].name + (f" + ещё {len(job.visuals) - 1}" if len(job.visuals) > 1 else ""))
                      if job.visuals else "клипы с Google Диска",
            "tracks": len(job.tracks),
            "file": job.output.name if info["status"] == "готово" else None,
            "size_gb": round(job.output.stat().st_size / 1e9, 2) if job.output.exists() and info["status"] == "готово" else None,
            "settings": asdict(job.settings),
        })
    return rows


@app.get("/jobs/{job_id}/video", dependencies=[Depends(check)])
def download(job_id: str, watch: bool = False):
    """watch=1 opens the video in the browser instead of downloading it."""
    info = jobs.get(job_id)
    if not info or info["status"] != "готово":
        raise HTTPException(404)
    out: Path = info["job"].output
    return FileResponse(out, filename=out.name, media_type="video/mp4",
                        content_disposition_type="inline" if watch else "attachment")


@app.delete("/jobs/{job_id}", dependencies=[Depends(check)])
def delete(job_id: str):
    info = jobs.get(job_id)
    if not info or info["status"] == "работает":
        raise HTTPException(400, "Нельзя удалить")
    shutil.rmtree(DATA / job_id, ignore_errors=True)
    jobs.pop(job_id)
    return {"ok": True}


@app.get("/version")
def version():
    """Public: which commit is deployed (written by deploy/autoupdate.sh)."""
    f = DATA / "version"
    return {"version": f.read_text().strip() if f.exists() else "unknown"}


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(check)])
def index():
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
