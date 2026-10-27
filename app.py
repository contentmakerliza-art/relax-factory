"""Web app: upload a picture or clip plus an album, press Render, download the video.

Run:  APP_PASSWORD=... uvicorn app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import html
import json
import os
import queue
import random
import re
import secrets
import shutil
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from render.drive import fetch_folder
from render.breathing import parse_script
from render.engine import Breath, Job, RenderSettings, kit_dir, make_check_clips, probe_duration, render
from render.scripts import DEFAULT, PRESETS
from render import youtube

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
        save_job(job_id, info)
        started = time.time()
        busy = DATA / "busy"  # auto-update waits while this file exists
        busy.touch()

        def progress(msg: str, frac: float) -> None:
            info["step"], info["progress"] = msg, frac

        try:
            if problem := space_problem(info["job"].settings, _black(info)):
                raise RuntimeError(problem)
            if info.get("drive"):
                _fetch_from_drive(info, progress)
            render(info["job"], progress)
            info["status"] = "готово"
        except Exception as exc:  # shown to the user on the page
            info["status"], info["step"] = "ошибка", str(exc)[-500:]
            info["job"].output.unlink(missing_ok=True)  # a half-written video only takes space
        info["seconds"] = round(time.time() - started)
        save_job(job_id, info)
        if work.empty():
            busy.unlink(missing_ok=True)


VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}
VISUAL_EXTS = VIDEO_EXTS | {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def _fetch_from_drive(info: dict, progress) -> None:
    """Download the clips and tracks from Google Drive links straight to the server."""
    job: Job = info["job"]
    folder = job.output.parent
    visual_url, tracks_url, pick, ambient_url, mask_url, voice_url = info["drive"]
    if visual_url:
        progress("Скачиваю клипы с Google Диска", 0.0)
        found = fetch_folder(visual_url, folder / "visual", VISUAL_EXTS)
        # a folder with clips may also hold the frames they were made from
        clips = [p for p in found if p.suffix.lower() in VIDEO_EXTS]
        job.visuals = clips or found
    if tracks_url:
        progress("Скачиваю треки с Google Диска", 0.0)
        job.tracks = fetch_folder(tracks_url, folder / "tracks", AUDIO_EXTS)
    if pick and len(job.tracks) > pick:
        job.tracks = sorted(random.sample(job.tracks, pick))
    if ambient_url:
        progress("Скачиваю фоновый звук с Google Диска", 0.0)
        job.ambient = fetch_folder(ambient_url, folder / "ambient", AUDIO_EXTS)[:5]
    if voice_url:
        progress("Скачиваю голос с Google Диска", 0.0)
        job.voice = fetch_folder(voice_url, folder / "voice", AUDIO_EXTS)[0]
    if mask_url:
        progress("Скачиваю маску с Google Диска", 0.0)
        job.mask, job.still = split_mask(fetch_folder(mask_url, folder / "mask", IMAGE_EXTS))


def split_mask(files: list[Path]) -> tuple[Path | None, Path | None]:
    """The mask field takes the mask and, optionally, the picture the clips
    were made from: the file named mask/маска is the mask."""
    if not files:
        return None, None
    if len(files) == 1:
        return files[0], None
    named = [f for f in files if re.search(r"mask|маск", f.stem, re.I)]
    if len(named) != 1:
        raise ValueError("В поле «Маска» назовите файл маски словом mask или маска")
    rest = [f for f in files if f != named[0]]
    return named[0], rest[0]


def _label(info: dict) -> str:
    if info.get("label"):
        return info["label"]
    job: Job = info["job"]
    if job.visuals:
        return job.visuals[0].name + (f" + ещё {len(job.visuals) - 1}" if len(job.visuals) > 1 else "")
    if job.voice or (info.get("drive") or [None] * 6)[5]:
        return "дыхание + чёрный экран"
    return "клипы с Google Диска"


def save_job(job_id: str, info: dict) -> None:
    """The list lives in memory; this copy next to the files brings it back
    after the app restarts (every update rebuilds the container)."""
    job: Job = info["job"]
    meta = {"status": info["status"], "step": info["step"], "seconds": info.get("seconds"),
            "created": info.get("created"), "label": _label(info), "tracks": len(job.tracks),
            "output": job.output.name, "previews": [p.name for p in job.previews],
            "timecodes": job.timecodes, "warning": job.warning, "checks": job.checks, "settings": asdict(job.settings),
            "youtube": info.get("yt")}
    try:
        (DATA / job_id / "job.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def load_jobs() -> None:
    """Finished videos come back into the list after a restart. A video made
    before job.json existed is found by its file. A job cut off by the restart
    shows as interrupted."""
    for folder in sorted(p for p in DATA.iterdir() if p.is_dir()):
        meta_file = folder / "job.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        else:
            videos = sorted(folder.glob("*.mp4"))
            if not videos:
                continue
            meta = {"status": "готово", "step": "", "label": videos[0].stem, "tracks": 0,
                    "output": videos[0].name, "previews": [p.name for p in sorted(folder.glob("*_preview_*.jpg"))],
                    "timecodes": "", "settings": {}}
            txt = videos[0].with_suffix(".txt")
            if txt.exists():
                meta["timecodes"] = txt.read_text(encoding="utf-8").strip()
        if meta["status"] in ("в очереди", "работает"):
            meta["status"], meta["step"] = "ошибка", "Прервано: сервер обновлялся. Запустите заново"
        if meta["status"] == "готово" and not (folder / meta["output"]).exists():
            continue
        known = {k: v for k, v in meta.get("settings", {}).items() if k in RenderSettings.__dataclass_fields__}
        job = Job([], [], folder / meta["output"], RenderSettings(**known))
        job.previews = [folder / n for n in meta.get("previews", [])]
        job.timecodes = meta.get("timecodes", "")
        job.warning = meta.get("warning", "")
        job.checks = meta.get("checks", "")
        if "duration" not in known and job.output.exists():
            job.settings.duration = probe_duration(job.output)
        jobs[folder.name] = {"job": job, "status": meta["status"], "step": meta["step"],
                             "progress": 1.0, "seconds": meta.get("seconds"),
                             "created": meta.get("created"), "label": meta["label"],
                             "tracks": meta.get("tracks", 0), "yt": meta.get("youtube")}
        yt = jobs[folder.name]["yt"]
        if yt and yt.get("status") == "загружается":
            yt["status"], yt["error"] = "ошибка", "Прервано: сервер обновлялся. Загрузите заново"


load_jobs()
threading.Thread(target=worker, daemon=True).start()


CHUNK_LIMIT = 64 * 1024 * 1024
KINDS = {"visual", "tracks", "ambient", "mask", "voice"}


MAX_FILE_GB = 20  # the server disk is small and shared
# never let the disk get below this: n8n and the rest of the server need it
RESERVE_GB = float(os.environ.get("RELAX_RESERVE_GB", "5"))


def need_gb(s: RenderSettings, black: bool = False) -> float:
    """Disk a render may take: the video at its bitrate (a black screen takes
    almost nothing), the sound (twice: once more in the kit for assembling on the computer), and
    room for the working files."""
    mbit = 0.5 if black else float(s.video_bitrate.rstrip("M") or 8)
    return (mbit + 0.7) * s.duration / 8000 * 1.1 + 2


def _black(info: dict) -> bool:
    """Breathing intro + black screen: the video is nearly free."""
    return bool(info["job"].voice or (info.get("drive") or [""] * 6)[5])


def free_gb() -> float:
    return shutil.disk_usage(DATA).free / 1e9


def space_problem(s: RenderSettings, black: bool, queued: float = 0.0) -> str:
    """Why this render must not start, or ''."""
    need = need_gb(s, black)
    left = free_gb() - queued - need
    if left >= RESERVE_GB:
        return ""
    return (f"Мало места на сервере: свободно {free_gb():.1f} ГБ, для видео нужно около "
            f"{need + queued:.1f} ГБ, и {RESERVE_GB:g} ГБ должно остаться для остальных программ. "
            "Удалите старые видео в очереди (кнопка «Удалить» или «Удалить старые»).")


def auto_bitrate(resolution: str, hours: float) -> int:
    """Mbit/s: full quality for usual lengths; long videos (mostly still
    scenes) get less so the file stays under MAX_FILE_GB."""
    full = 15 if resolution == "4k" else 8
    fits = int(MAX_FILE_GB * 8000 / (hours * 3600))
    return max(4, min(full, fits))


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
    fps: int = Form(0),  # 0 = same as the clips
    loop_mode: str = Form("crossfade"),
    speed: float = Form(1.0),
    track_crossfade: float = Form(3.0),
    loop_crossfade: float = Form(1.5),
    find_loop_point: bool = Form(False),
    shuffle: bool = Form(False),
    codec: str = Form("h264"),
    bitrate: int = Form(0),  # Мбит/с; 0 = auto
    visual_url: str = Form(""),
    tracks_url: str = Form(""),
    tracks_pick: int = Form(0),
    ambient_url: str = Form(""),
    ambient_level: float = Form(-12.0),
    color_drift: str = Form("none"),
    color_period: float = Form(120.0),
    mask_url: str = Form(""),
    mask_mode: str = Form("still"),
    stabilize: bool = Form(False),
    smooth: bool = Form(False),
    voice_url: str = Form(""),
    breath_start: float = Form(16.0),
    breath_in: float = Form(4.0),
    breath_out: float = Form(6.0),
    breath_cycles: int = Form(9),
    breath_duck: float = Form(-24.0),
    breath_after: float = Form(-2.0),
    breath_hold: float = Form(0.0),
    breath_script: str = Form(""),
):
    if not 0 < hours <= 12:
        raise HTTPException(400, "Длина от 0 до 12 часов")
    if job_id in jobs:
        raise HTTPException(400, "Задание уже запущено")
    folder = _job_dir(job_id)
    visual_url, tracks_url, ambient_url = visual_url.strip(), tracks_url.strip(), ambient_url.strip()
    mask_url, voice_url = mask_url.strip(), voice_url.strip()
    voice_dir = folder / "voice"
    voice = None if voice_url or not voice_dir.is_dir() else next(iter(sorted(voice_dir.iterdir())), None)
    breathing = bool(voice or voice_url)
    if not (0 <= breath_start <= 120 and 1 <= breath_in <= 20 and 1 <= breath_out <= 20
            and 0 <= breath_cycles <= 60 and -60 <= breath_duck <= 0
            and -30 <= breath_after <= 0
            and 0 <= breath_hold <= 30):
        raise HTTPException(400, "Проверьте настройки дыхания")
    breath = Breath(breath_start, breath_in, breath_out, breath_cycles, breath_hold,
                    duck_db=breath_duck, after_db=breath_after)
    if breath_script.strip():
        breath.script = breath_script.strip()
    if breathing:
        try:
            parse_script(breath)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    mask_files = [] if mask_url else sorted((folder / "mask").iterdir()) if (folder / "mask").is_dir() else []
    try:
        mask, still = split_mask(mask_files)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    amb_dir = folder / "ambient"
    ambient = [] if ambient_url or not amb_dir.is_dir() else sorted(amb_dir.iterdir())[:5]
    if breathing and not (ambient or ambient_url):
        raise HTTPException(400, "Для вступления с дыханием нужен фоновый звук (дождь, волны)")
    visuals = [] if visual_url else sorted((folder / "visual").iterdir())
    trk = [] if tracks_url else sorted((folder / "tracks").iterdir())
    if not (visuals or visual_url or breathing) or not (trk or tracks_url or ambient or ambient_url):
        raise HTTPException(400, "Нужны картинка или клипы и треки или фоновый звук (файлы или ссылка на Google Диск)")
    if not tracks_url and tracks_pick and len(trk) > tracks_pick:
        trk = sorted(random.sample(trk, tracks_pick))
    name = "sleep" if breathing else visuals[0].stem if visuals else "video"
    w, h = (3840, 2160) if resolution == "4k" else (1920, 1080)
    if not bitrate:
        bitrate = auto_bitrate(resolution, hours)
    settings = RenderSettings(
        width=w, height=h, fps=fps, duration=hours * 3600, loop_mode=loop_mode,
        speed=speed, loop_crossfade=loop_crossfade, find_loop_point=find_loop_point, track_crossfade=track_crossfade, shuffle_tracks=shuffle,
        codec=codec, video_bitrate=f"{bitrate}M", ambient_level=ambient_level,
        color_drift=color_drift, color_period=color_period, stabilize=stabilize, mask_mode=mask_mode if mask_mode in ("still", "stab") else "still", smooth=smooth,
    )
    queued = sum(need_gb(i["job"].settings, _black(i)) for i in jobs.values()
                 if i["status"] in ("в очереди", "работает"))
    if problem := space_problem(settings, breathing, queued):
        raise HTTPException(400, problem)
    out = folder / f"{name}_{hours:g}h.mp4"
    jobs[job_id] = {"job": Job(visuals, trk, out, settings, ambient=ambient, mask=mask, still=still,
                               voice=voice, breath=breath),
                    "status": "в очереди",
                    "step": "", "progress": 0.0, "created": time.time(),
                    "drive": (visual_url, tracks_url, tracks_pick, ambient_url, mask_url, voice_url)
                    if visual_url or tracks_url or ambient_url or mask_url or voice_url else None}
    save_job(job_id, jobs[job_id])
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
            "visual": _label(info),
            "tracks": info.get("tracks", len(job.tracks)),
            "file": job.output.name if info["status"] == "готово" else None,
            "size_gb": round(job.output.stat().st_size / 1e9, 2) if job.output.exists() and info["status"] == "готово" else None,
            "kit_gb": _kit_gb(job) if info["status"] == "готово" else None,
            "previews": len(job.previews) if info["status"] == "готово" else 0,
            "timecodes": job.timecodes if info["status"] == "готово" else "",
            "warning": job.warning,
            "checks": job.checks if info["status"] == "готово" else "",
            "yt": info.get("yt"),
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


def _kit_gb(job: Job) -> float | None:
    """Download size of the assembly kit, or None when the video has none."""
    kit = kit_dir(job.output)
    if not (kit / "map.json").exists():
        return None
    return round(sum(f.stat().st_size for f in kit.iterdir()) / 1e9, 2)


@app.get("/jobs/{job_id}/kit/{name}", dependencies=[Depends(check)])
def kit_file(job_id: str, name: str):
    """Loop, sound and byte map: the page builds the long video from them
    on the computer (Range requests let it download in resumable pieces)."""
    info = jobs.get(job_id)
    if not info or info["status"] != "готово":
        raise HTTPException(404)
    f = kit_dir(info["job"].output) / Path(name).name
    if not f.is_file():
        raise HTTPException(404, "Нет файлов для сборки (видео сделано до этой функции)")
    return FileResponse(f, media_type="application/json" if f.suffix == ".json" else "application/octet-stream")


SHARES = DATA / "shares.json"
SHARE_HOURS = 24


def _shares() -> dict:
    """Public links: token -> {job, expires}; expired ones dropped."""
    try:
        found = json.loads(SHARES.read_text())
    except (OSError, ValueError):
        return {}
    return {t: v for t, v in found.items() if v["expires"] > time.time()}


@app.post("/jobs/{job_id}/share", dependencies=[Depends(check)])
def share(job_id: str, request: Request):
    """A link to the finished video that opens without the password, for
    24 hours: a service such as Upload-Post downloads the video by it."""
    info = jobs.get(job_id)
    if not info or info["status"] != "готово":
        raise HTTPException(404)
    links = _shares()
    token = secrets.token_urlsafe(24)
    links[token] = {"job": job_id, "expires": time.time() + SHARE_HOURS * 3600}
    SHARES.write_text(json.dumps(links))
    name = info["job"].output.name
    return {"url": f"https://{request.url.netloc}/share/{token}/{name}", "hours": SHARE_HOURS}


@app.delete("/jobs/{job_id}/share", dependencies=[Depends(check)])
def unshare(job_id: str):
    """Close every public link of this video at once."""
    SHARES.write_text(json.dumps({t: v for t, v in _shares().items() if v["job"] != job_id}))
    return {"ok": True}


@app.api_route("/share/{token}/{name}", methods=["GET", "HEAD"])
def shared_video(token: str, name: str):
    """No password: the long random token is the key. Range requests work,
    so a download that breaks can go on where it stopped."""
    link = _shares().get(token)
    info = jobs.get(link["job"]) if link else None
    if not info or info["status"] != "готово" or not info["job"].output.exists():
        raise HTTPException(404)
    out: Path = info["job"].output
    return FileResponse(out, filename=out.name, media_type="video/mp4")


@app.get("/jobs/{job_id}/preview/{n}", dependencies=[Depends(check)])
def preview(job_id: str, n: int, download: bool = False):
    info = jobs.get(job_id)
    if not info or not 1 <= n <= len(info["job"].previews):
        raise HTTPException(404)
    p: Path = info["job"].previews[n - 1]
    return FileResponse(p, filename=p.name, media_type="image/jpeg",
                        content_disposition_type="attachment" if download else "inline")


@app.get("/jobs/{job_id}/check/{part}", dependencies=[Depends(check)])
def check_clip(job_id: str, part: str):
    """The first 3 minutes or the last minute of the video, small enough to open at once."""
    if part not in ("start", "end"):
        raise HTTPException(404)
    f = _job_dir(job_id) / f"check_{part}.mp4"
    info = jobs.get(job_id)
    if not f.exists() and info and info["status"] == "готово" and info["job"].output.exists():
        make_check_clips(info["job"])  # videos made before this existed: a few seconds
        save_job(job_id, info)
    if not f.exists():
        raise HTTPException(404, "Нет кусочка для проверки")
    return FileResponse(f, media_type="video/mp4", content_disposition_type="inline")


@app.get("/jobs/{job_id}/voice-timing", dependencies=[Depends(check)])
def voice_timing(job_id: str):
    """Where each line of the voice was found and placed (breathing intro)."""
    f = _job_dir(job_id) / "voice-timing.txt"
    if not f.exists():
        raise HTTPException(404, "Нет разметки голоса")
    return FileResponse(f, media_type="text/plain; charset=utf-8")


@app.delete("/jobs/{job_id}", dependencies=[Depends(check)])
def delete(job_id: str):
    info = jobs.get(job_id)
    if not info or info["status"] == "работает":
        raise HTTPException(400, "Нельзя удалить")
    shutil.rmtree(DATA / job_id, ignore_errors=True)
    jobs.pop(job_id)
    return {"ok": True}


@app.post("/jobs/cleanup", dependencies=[Depends(check)])
def cleanup(days: float = Form(7.0)):
    """Delete finished or failed videos older than `days`, and uploads that
    were never started (older than a day)."""
    now, freed = time.time(), 0
    for job_id, info in list(jobs.items()):
        created = info.get("created") or (DATA / job_id).stat().st_mtime
        if info["status"] in ("готово", "ошибка") and now - created > days * 86400:
            freed += _size(DATA / job_id)
            shutil.rmtree(DATA / job_id, ignore_errors=True)
            jobs.pop(job_id)
    for folder in DATA.iterdir():
        if folder.is_dir() and folder.name not in jobs and now - folder.stat().st_mtime > 86400:
            freed += _size(folder)
            shutil.rmtree(folder, ignore_errors=True)
    return {"freed_gb": round(freed / 1e9, 1), "free_gb": round(free_gb(), 1)}


def _size(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


@app.get("/disk", dependencies=[Depends(check)])
def disk():
    return {"free_gb": round(free_gb(), 1), "reserve_gb": RESERVE_GB}


@app.get("/scripts", dependencies=[Depends(check)])
def scripts():
    return {"default": DEFAULT, "presets": PRESETS}


@app.get("/version")
def version():
    """Public: which commit is deployed (written by deploy/autoupdate.sh)."""
    f = DATA / "version"
    return {"version": f.read_text().strip() if f.exists() else "unknown"}


def _page(name: str) -> str:
    return (Path(__file__).parent / "static" / name).read_text(encoding="utf-8")


@app.get("/about", response_class=HTMLResponse)
def about():
    """Public: the app's home page for Google (OAuth consent screen, API audit)."""
    return _page("about.html")


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    """Public: privacy policy for Google."""
    return _page("privacy.html")


@app.get("/terms", response_class=HTMLResponse)
def terms():
    """Public: terms of use for Google."""
    return _page("terms.html")


CHANNEL_ID = re.compile(r"^UC[\w-]{22}$")


@app.get("/youtube", dependencies=[Depends(check)])
def youtube_state(request: Request):
    c = youtube.client()
    return {"client": bool(c), "client_id": c["client_id"] if c else "",
            "redirect_uri": youtube.redirect_uri(request.url.netloc), "channels": youtube.channels()}


@app.post("/youtube/client", dependencies=[Depends(check)])
async def youtube_client(file: UploadFile = File(...)):
    raw = await file.read(64 * 1024)
    try:
        return {"client_id": youtube.save_client(raw)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/youtube/connect", dependencies=[Depends(check)])
def youtube_connect(request: Request):
    try:
        return RedirectResponse(youtube.auth_url(youtube.redirect_uri(request.url.netloc)))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/youtube/callback", response_class=HTMLResponse, dependencies=[Depends(check)])
def youtube_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    if error:
        text = f"Доступ не выдан ({error}). Можно попробовать ещё раз."
    else:
        try:
            ch = youtube.finish(code, state, youtube.redirect_uri(request.url.netloc))
            text = f"Канал «{ch['title']}» подключён."
        except ValueError as e:
            text = f"Не получилось: {e}"
    return ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<body style="font:17px/1.5 system-ui,sans-serif;max-width:560px;margin:40px auto;padding:0 16px">'
            f'<p>{html.escape(text)}</p><p><a href="/">Вернуться в приложение</a></p>')


@app.get("/youtube/channels/{channel_id}/playlists", dependencies=[Depends(check)])
def youtube_playlists(channel_id: str):
    if not CHANNEL_ID.match(channel_id):
        raise HTTPException(404)
    try:
        return youtube.playlists(channel_id)
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))


MSK = timezone(timedelta(hours=3))


def _publish_at(local: str) -> str:
    """'2026-10-25T18:00' in Moscow time -> RFC 3339 in UTC, as YouTube wants."""
    when = datetime.fromisoformat(local).replace(tzinfo=MSK)
    if when < datetime.now(MSK) + timedelta(minutes=30):
        raise HTTPException(400, "Время публикации должно быть хотя бы через 30 минут")
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _upload_worker(job_id: str, channel: str, meta: dict, thumb: Path | None, playlist: str) -> None:
    info = jobs[job_id]
    yt = info["yt"]
    def progress(x: float) -> None:
        yt["progress"] = round(x, 3)
    try:
        yt["id"], yt["error"] = youtube.upload(channel, info["job"].output, meta, thumb, playlist, progress)
        yt["status"] = "загружено"
    except Exception as e:  # shown under the video; the file stays for another try
        yt["status"], yt["error"] = "ошибка", str(e)[:500]
    save_job(job_id, info)


@app.post("/jobs/{job_id}/youtube", dependencies=[Depends(check)])
async def youtube_upload(
    job_id: str,
    channel: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    publish_at: str = Form(""),
    playlist: str = Form(""),
    thumb: int = Form(0),
    thumb_file: UploadFile | None = File(None),
    synthetic: bool = Form(False),
):
    info = jobs.get(job_id)
    if not info or info["status"] != "готово" or not info["job"].output.exists():
        raise HTTPException(404, "Нет готового видео")
    if (info.get("yt") or {}).get("status") == "загружается":
        raise HTTPException(400, "Это видео уже загружается")
    if not CHANNEL_ID.match(channel) or channel not in {c["id"] for c in youtube.channels()}:
        raise HTTPException(400, "Канал не подключён")
    title = title.strip()
    if not title or len(title) > 100 or "<" in title or ">" in title:
        raise HTTPException(400, "Название: от 1 до 100 символов, без < и >")
    if len(description) > 5000:
        raise HTTPException(400, "Описание длиннее 5000 символов")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    if sum(len(t) + 1 for t in tag_list) > 500:
        raise HTTPException(400, "Теги вместе длиннее 500 символов")
    meta = {"title": title, "description": description.replace("<", "‹").replace(">", "›"),
            "tags": tag_list, "synthetic": synthetic}
    if publish_at:
        meta["publish_at"] = _publish_at(publish_at)
    cover = None
    if thumb_file and thumb_file.filename:
        raw = await thumb_file.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024 or raw[:3] != b"\xff\xd8\xff":
            raise HTTPException(400, "Обложка: JPEG до 2 МБ")
        cover = _job_dir(job_id) / "cover.jpg"
        cover.write_bytes(raw)
    elif 1 <= thumb <= len(info["job"].previews):
        cover = info["job"].previews[thumb - 1]
    info["yt"] = {"status": "загружается", "progress": 0.0, "id": None, "error": "",
                  "channel": next(c["title"] for c in youtube.channels() if c["id"] == channel),
                  "publish_at": publish_at}
    save_job(job_id, info)
    threading.Thread(target=_upload_worker, args=(job_id, channel, meta, cover, playlist), daemon=True).start()
    return {"ok": True}


@app.delete("/youtube/channels/{channel_id}", dependencies=[Depends(check)])
def youtube_disconnect(channel_id: str):
    if not CHANNEL_ID.match(channel_id):
        raise HTTPException(404)
    youtube.disconnect(channel_id)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(check)])
def index():
    return _page("index.html")
