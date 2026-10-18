"""Render engine: picture or short clip + album of tracks -> long looped video.

All heavy work is done once on a short loop segment; the long video is built
by repeating that segment with stream copy, so a 3-hour render costs about the
same as rendering the loop itself plus encoding the audio.
"""

from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass
class RenderSettings:
    width: int = 3840
    height: int = 2160
    fps: int = 60
    duration: float = 3 * 3600          # final video length, seconds
    loop_mode: str = "crossfade"        # crossfade | pingpong | none (clips only)
    loop_crossfade: float = 1.5         # seconds of blend at the loop seam
    speed: float = 1.0                  # 0.5 = twice slower (after a 60 fps upscale)
    saturation: float = 1.0
    image_segment: float = 10.0         # length of the still-image segment
    track_crossfade: float = 3.0        # seconds between tracks
    shuffle_tracks: bool = False        # reshuffle each pass over the album
    loudness: float = -14.0             # LUFS target (EBU R128)
    video_bitrate: str = "15M"          # loop segment bitrate; not above the source
    codec: str = "h264"                 # h264 | h265
    audio_bitrate: str = "320k"
    seed: int | None = None


@dataclass
class Job:
    visual: Path
    tracks: list[Path]
    output: Path
    settings: RenderSettings = field(default_factory=RenderSettings)


Progress = Callable[[str, float], None]


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.splitlines()[-20:])
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:6])} ...\n{tail}")
    return proc.stderr


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def _video_codec_args(s: RenderSettings) -> list[str]:
    gop = str(s.fps * 2)
    if s.codec == "h265":
        return ["-c:v", "libx265", "-preset", "medium", "-b:v", s.video_bitrate,
                "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
                "-x265-params", f"keyint={gop}:min-keyint={gop}:open-gop=0:log-level=error"]
    return ["-c:v", "libx264", "-preset", "medium", "-b:v", s.video_bitrate,
            "-maxrate", s.video_bitrate, "-bufsize", s.video_bitrate,
            "-pix_fmt", "yuv420p", "-g", gop, "-keyint_min", gop, "-sc_threshold", "0",
            "-profile:v", "high"]


def _frame_filter(s: RenderSettings) -> str:
    """Scale/crop to the target frame, set speed, colour and frame rate."""
    parts = [
        f"scale={s.width}:{s.height}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={s.width}:{s.height}",
        "setsar=1",
    ]
    if s.speed != 1.0:
        parts.append(f"setpts=PTS/{s.speed}")
    if s.saturation != 1.0:
        parts.append(f"eq=saturation={s.saturation}")
    parts.append(f"fps={s.fps}")
    return ",".join(parts)


# ---------- visual loop segment ----------

def _image_segment(src: Path, dst: Path, s: RenderSettings) -> None:
    _run(["ffmpeg", "-y", "-loop", "1", "-i", str(src), "-t", str(s.image_segment),
          "-vf", _frame_filter(s), "-an", *_video_codec_args(s), str(dst)])


def _normalized_clip(src: Path, dst: Path, s: RenderSettings) -> float:
    _run(["ffmpeg", "-y", "-i", str(src), "-vf", _frame_filter(s), "-an",
          *_video_codec_args(s), str(dst)])
    return probe_duration(dst)


def _crossfade_loop(clip: Path, dst: Path, d: float, s: RenderSettings) -> None:
    """Move the first `x` seconds to the end and blend them in: the last frame
    of the result is followed seamlessly by its first frame."""
    x = min(s.loop_crossfade, d / 3)
    flt = (
        f"[0:v]trim=start={x},setpts=PTS-STARTPTS[main];"
        f"[0:v]trim=end={x},setpts=PTS-STARTPTS[head];"
        f"[main][head]xfade=transition=fade:duration={x}:offset={d - 2 * x:.4f},format=yuv420p[v]"
    )
    _run(["ffmpeg", "-y", "-i", str(clip), "-filter_complex", flt, "-map", "[v]",
          "-an", *_video_codec_args(s), str(dst)])


def _pingpong_loop(clip: Path, dst: Path, d: float, s: RenderSettings, tmp: Path) -> None:
    """Forward then backward. Reversing is done in 2-second chunks so a 4K clip
    never has to sit in memory as a whole."""
    chunk = 2.0
    n = math.ceil(d / chunk)
    rev_parts = []
    for i in range(n):
        part = tmp / f"rev_{i:04d}.mp4"
        _run(["ffmpeg", "-y", "-ss", str(i * chunk), "-t", str(chunk), "-i", str(clip),
              "-vf", "reverse", "-an", *_video_codec_args(s), str(part)])
        rev_parts.append(part)
    # backward pass: last chunk reversed first; drop the duplicated turn-around frames
    lst = tmp / "pingpong.txt"
    lines = [f"file '{clip}'"] + [f"file '{p}'" for p in reversed(rev_parts)]
    lst.write_text("\n".join(lines) + "\n")
    joined = tmp / "pingpong_joined.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    # re-encode once so the segment is a single clean GOP sequence
    _run(["ffmpeg", "-y", "-i", str(joined), "-an", *_video_codec_args(s), str(dst)])


def build_loop_segment(visual: Path, dst: Path, s: RenderSettings, tmp: Path) -> float:
    if visual.suffix.lower() in IMAGE_EXTS:
        _image_segment(visual, dst, s)
        return probe_duration(dst)
    clip = tmp / "clip_norm.mp4"
    d = _normalized_clip(visual, clip, s)
    if s.loop_mode == "crossfade":
        _crossfade_loop(clip, dst, d, s)
    elif s.loop_mode == "pingpong":
        _pingpong_loop(clip, dst, d, s, tmp)
    else:
        shutil.copy(clip, dst)
    return probe_duration(dst)


# ---------- audio ----------

def measure_loudness(path: Path) -> float:
    """Integrated loudness of a file, LUFS (EBU R128)."""
    err = _run(["ffmpeg", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"])
    tail = err[err.rfind("Summary:"):]
    for line in tail.splitlines():
        line = line.strip()
        if line.startswith("I:"):
            return float(line.split()[1])
    raise RuntimeError(f"Не удалось измерить громкость: {path.name}")


def build_audio(tracks: list[Path], dst: Path, s: RenderSettings, tmp: Path) -> None:
    """The album is normalised and crossfaded once into a seamless cycle (its
    end blends into its beginning); the cycle is then repeated as raw PCM and
    encoded once, so hours of audio cost about as much as one album."""
    order = list(range(len(tracks)))
    if s.shuffle_tracks:
        random.Random(s.seed).shuffle(order)
    wavs = []
    for i in order:
        gain = s.loudness - measure_loudness(tracks[i])
        w = tmp / f"track_{len(wavs):03d}.wav"
        _run(["ffmpeg", "-y", "-i", str(tracks[i]), "-af",
              f"volume={gain:.2f}dB,alimiter=limit=0.89:level=disabled",
              "-ac", "2", "-ar", "48000", str(w)])
        wavs.append(w)

    x = s.track_crossfade
    inputs: list[str] = []
    for w in wavs:
        inputs += ["-i", str(w)]
    steps, prev = [], "[0:a]"
    for k in range(1, len(wavs)):
        steps.append(f"{prev}[{k}:a]acrossfade=d={x}:c1=tri:c2=tri[a{k}]")
        prev = f"[a{k}]"
    album = tmp / "album.wav"
    script = tmp / "album_filter.txt"
    if steps:
        script.write_text(";".join(steps))
    cmd = ["ffmpeg", "-y", *inputs]
    if steps:
        cmd += ["-filter_complex_script", str(script), "-map", prev]
    cmd += ["-c:a", "pcm_s16le", str(album)]
    _run(cmd)

    # Make the cycle a whole number of AAC frames so it can be repeated as
    # encoded packets: x seconds from the start blend into the end.
    sr, frame = 48000, 1024
    total = _samples(album)
    xs = round(x * sr)
    cycle_len = (total - xs) // frame * frame
    if cycle_len <= frame * 4:
        raise ValueError("Альбом слишком короткий")
    cycle = tmp / "album_cycle.wav"
    if xs > 0:
        _run(["ffmpeg", "-y", "-i", str(album), "-i", str(album), "-filter_complex",
              f"[0:a]atrim=start_sample={xs}:end_sample={xs + cycle_len},asetpts=PTS-STARTPTS[body];"
              f"[1:a]atrim=end_sample={xs},asetpts=PTS-STARTPTS[head];"
              f"[body][head]acrossfade=ns={xs}:c1=tri:c2=tri[cycle]",
              "-map", "[cycle]", "-c:a", "pcm_s16le", str(cycle)])
    else:
        _run(["ffmpeg", "-y", "-i", str(album), "-af", f"atrim=end_sample={cycle_len}",
              "-c:a", "pcm_s16le", str(cycle)])
    encode_seamless_aac(cycle, dst, s.duration, s.audio_bitrate, tmp)


def _samples(wav: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-count_packets",
         "-show_entries", "stream=duration_ts", "-of", "csv=p=0", str(wav)],
        capture_output=True, text=True, check=True).stdout.strip()
    return int(out)


def _adts_frames(data: bytes) -> list[tuple[int, int]]:
    frames, pos = [], 0
    while pos + 7 <= len(data):
        if data[pos] != 0xFF or data[pos + 1] & 0xF0 != 0xF0:
            raise RuntimeError("Повреждённый AAC-поток")
        length = ((data[pos + 3] & 3) << 11) | (data[pos + 4] << 3) | (data[pos + 5] >> 5)
        frames.append((pos, length))
        pos += length
    return frames


def encode_seamless_aac(cycle: Path, dst: Path, duration: float, bitrate: str, tmp: Path) -> None:
    """Encode one cycle (a whole number of 1024-sample frames) so that its
    packets can be repeated back to back without a gap or click.

    The cycle is encoded with a piece of its own end in front and of its own
    start behind, then exactly the packets that cover the cycle are cut out:
    each boundary packet was encoded with the real neighbouring audio, so
    repeating them sounds the same as encoding the whole long track."""
    frame, pad = 1024, 4096          # pad: whole frames of context on each side
    n = _samples(cycle)
    padded = tmp / "cycle_padded.aac"
    _run(["ffmpeg", "-y", "-i", str(cycle), "-i", str(cycle), "-i", str(cycle), "-filter_complex",
          f"[0:a]atrim=start_sample={n - pad},asetpts=PTS-STARTPTS[t];"
          f"[2:a]atrim=end_sample={pad},asetpts=PTS-STARTPTS[h];"
          f"[t][1:a][h]concat=n=3:v=0:a=1[a]",
          "-map", "[a]", "-c:a", "aac", "-b:a", bitrate, "-f", "adts", str(padded)])
    data = padded.read_bytes()
    frames = _adts_frames(data)
    # the encoder adds one frame of delay in front of everything
    first = (pad + frame) // frame
    count = n // frame
    if first + count > len(frames):
        raise RuntimeError("AAC: не хватило кадров")
    start = frames[first][0]
    end = frames[first + count - 1][0] + frames[first + count - 1][1]
    chunk = data[start:end]

    repeats = math.ceil(duration * 48000 / n) + 1
    raw = tmp / "audio_full.aac"
    with raw.open("wb") as f:
        for _ in range(repeats):
            f.write(chunk)
    _run(["ffmpeg", "-y", "-i", str(raw), "-c", "copy", "-t", str(duration), str(dst)])


# ---------- assembly ----------

def render(job: Job, progress: Progress | None = None) -> Path:
    s = job.settings
    say = progress or (lambda msg, frac: None)
    if not job.tracks:
        raise ValueError("Нужен хотя бы один трек")
    job.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render_") as td:
        tmp = Path(td)
        say("Готовлю петлю видео", 0.05)
        seg = tmp / "loop.mp4"
        seg_len = build_loop_segment(job.visual, seg, s, tmp)

        say("Собираю и выравниваю музыку", 0.35)
        audio = tmp / "audio.m4a"
        build_audio(job.tracks, audio, s, tmp)

        say("Склеиваю видео до нужной длины", 0.8)
        repeats = math.ceil(s.duration / seg_len) + 1
        lst = tmp / "repeat.txt"
        lst.write_text(f"file '{seg}'\n" * repeats)
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio),
              "-map", "0:v", "-map", "1:a", "-c", "copy", "-t", str(s.duration),
              str(job.output)])
    say("Готово", 1.0)
    return job.output
