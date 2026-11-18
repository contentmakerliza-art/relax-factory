"""Replace the full ambience source without changing the approved preview."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse


def inspect_audio(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
        'stream=codec_type:format=duration', '-of', 'json', str(path)],
        capture_output=True, text=True, check=True, timeout=30)
    meta = json.loads(result.stdout)
    seconds = float(meta.get('format', {}).get('duration', 0))
    if not math.isfinite(seconds) or not 30 < seconds <= 7200:
        raise ValueError('Нужен полный звук длиннее 30 секунд, до двух часов')
    if not any(s.get('codec_type') == 'audio' for s in meta.get('streams', [])):
        raise ValueError('В файле нет звука')
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path),
        '-map', '0:a:0', '-f', 'null', '-'], check=True, capture_output=True, timeout=180)
    return seconds


def eligible(source, jobs, publications, label):
    info = jobs.get(source)
    if not info or (info.get('approval') or {}).get('status') != 'одобрено':
        raise HTTPException(400, 'Нужна одобренная проба')
    channels = ('Quiet Pines Cabin', 'Mountain View Cafe')
    if not (any(c in label(info) for c in channels) or
            any(p.get('source') == source and p.get('channel') in channels for p in publications)):
        raise HTTPException(400, 'Замена доступна для Quiet Pines Cabin и Mountain View Cafe')
    if info.get('status') != 'готово':
        raise HTTPException(409, 'Дождитесь завершения пробы')
    for item in publications:
        if item.get('source') == source and (item.get('status') != 'ждёт' or item.get('job') or item.get('ready')):
            raise HTTPException(409, 'Длинная сборка уже начата или отправлена; звук не изменён')
    return info


def replace_source(folder, info, path, seconds, loudness, save):
    """Keep rollback files outside renderer input directories; never rewrite MP4."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    destination = folder / 'ambient'
    backup = folder / 'audio-history' / (time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:12])
    backup.mkdir(parents=True, exist_ok=False)
    for name in ('job.json', 'imported-recipe.json', 'background-audio.json'):
        if (folder / name).exists():
            shutil.copy2(folder / name, backup / name)
    staged = folder / ('ambient-new-' + digest[:12])
    staged.mkdir()
    target = staged / ('full-fireplace-' + digest[:12] + path.suffix.lower())
    shutil.copy2(path, target)
    old_ambient = info['job'].ambient
    old_tracks = info['job'].tracks
    old_level = info['job'].settings.ambient_level
    old_loudness = info['job'].settings.loudness
    try:
        if destination.exists():
            destination.rename(backup / 'ambient')
        staged.rename(destination)
        job = info['job']
        job.ambient = [destination / target.name]
        job.tracks = []
        if (folder / 'tracks').exists():
            (folder / 'tracks').rename(backup / 'tracks')
        (folder / 'tracks').mkdir()
        job.settings.ambient_level = 0
        job.settings.loudness = loudness
        record = dict(file=target.name, sha256=digest, seconds=seconds,
            loudness_lufs=loudness, ambient_level_db=0, music=False,
            updated_at=time.time(), backup=str(backup.relative_to(folder)))
        (folder / 'background-audio.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
        save()
        persisted = json.loads((folder / 'job.json').read_text())
        if persisted['settings']['loudness'] != loudness or persisted['settings']['ambient_level'] != 0:
            raise OSError('Не удалось сохранить настройки полного звука')
        return record
    except BaseException:
        info['job'].ambient, info['job'].tracks = old_ambient, old_tracks
        info['job'].settings.ambient_level = old_level
        info['job'].settings.loudness = old_loudness
        shutil.rmtree(destination, ignore_errors=True)
        if (backup / 'ambient').exists():
            (backup / 'ambient').rename(destination)
        if (backup / 'tracks').exists():
            shutil.rmtree(folder / 'tracks', ignore_errors=True)
            (backup / 'tracks').rename(folder / 'tracks')
        for name in ('job.json', 'imported-recipe.json', 'background-audio.json'):
            if (backup / name).exists():
                shutil.copy2(backup / name, folder / name)
            elif name == 'background-audio.json':
                (folder / name).unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def install(app, data, jobs, publications, lock, label, save, measure, auth):
    @app.get('/background-audio', response_class=HTMLResponse, dependencies=[Depends(auth)])
    def page():
        return '''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Полный звук камина</title>
        <body style="max-width:720px;margin:40px auto;font:18px system-ui"><h1>Полный звук камина</h1>
        <p>Для одобренной пробы, длинная сборка которой ещё не началась. Видео, одобрение и дата сохраняются.</p>
        <form id="audio"><p><label>Номер одобренной пробы <input name="source" required></label></p>
        <p><label>Полный аудиофайл <input type="file" name="file" accept="audio/*"></label></p>
        <p>Или номер пробы, к которой уже подключён полный звук: <input name="from_job"></p>
        <button>Подключить полный звук</button></form><pre id="result" style="white-space:pre-wrap"></pre>
        <script>document.querySelector('#audio').onsubmit=async e=>{e.preventDefault();let f=new FormData(e.target);
        let source=f.get('source');f.delete('source');if(!f.get('file').size)f.delete('file');
        let r=await fetch('/jobs/'+encodeURIComponent(source)+'/background-audio',{method:'POST',body:f});
        document.querySelector('#result').textContent=JSON.stringify(await r.json(),null,2);};</script></body></html>'''

    @app.get('/jobs/{source}/background-audio', dependencies=[Depends(auth)])
    def read(source: str):
        if source not in jobs:
            raise HTTPException(404, 'Нет такой пробы')
        p = Path(data) / source / 'background-audio.json'
        return json.loads(p.read_text()) if p.exists() else {'configured': False}

    @app.post('/jobs/{source}/background-audio', dependencies=[Depends(auth)])
    def update(source: str, file: UploadFile = File(None), from_job: str = Form('')):
        with lock:
            eligible(source, jobs, publications, label)
        if bool(file) == bool(from_job):
            raise HTTPException(400, 'Выберите файл или пробу с полным звуком')
        with tempfile.TemporaryDirectory(dir=data) as temporary:
            if file:
                extension = Path(file.filename or '').suffix.lower()
                if extension not in {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac'}:
                    raise HTTPException(400, 'Выберите аудиофайл')
                path = Path(temporary) / ('upload' + extension)
                with path.open('wb') as out:
                    total = 0
                    while chunk := file.file.read(1024 * 1024):
                        total += len(chunk)
                        if total > 250 * 1024 * 1024:
                            raise HTTPException(413, 'Файл больше 250 МБ')
                        out.write(chunk)
            else:
                if from_job not in jobs:
                    raise HTTPException(404, 'Нет пробы с полным звуком')
                parent = Path(data) / from_job
                try:
                    record = json.loads((parent / 'background-audio.json').read_text())
                    path = parent / 'ambient' / Path(record['file']).name
                    if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                        raise ValueError('Контрольная сумма звука не совпала')
                except (OSError, KeyError, ValueError):
                    raise HTTPException(400, 'У этой пробы нет проверенного полного звука')
                copied = Path(temporary) / path.name
                shutil.copy2(path, copied)
                path = copied
            try:
                seconds = inspect_audio(path)
                loudness = measure(path)
                if not math.isfinite(loudness):
                    raise ValueError('Не удалось измерить уровень звука')
            except (ValueError, subprocess.SubprocessError) as error:
                raise HTTPException(400, str(error)[:300])
            with lock:
                info = eligible(source, jobs, publications, label)
                return replace_source(Path(data) / source, info, path, seconds, loudness,
                    lambda: save(source, info))
