"""Render engine: picture or short clip + album of tracks -> long looped video.

All heavy work is done once on a short loop segment; the long video is built
by repeating that segment with stream copy, so a 3-hour render costs about the
same as rendering the loop itself plus encoding the audio.
"""

from __future__ import annotations

import functools
import json
import math
import random
import re
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass
class RenderSettings:
    width: int = 3840
    height: int = 2160
    fps: int = 60
    duration: float = 3 * 3600          # final video length, seconds
    loop_mode: str = "crossfade"        # crossfade | scenes | chain | chain_pingpong | pingpong | none (clips only)
    loop_crossfade: float = 1.5         # seconds of blend at the loop seam
    find_loop_point: bool = False       # chain: cut where the frame is most like the first
    speed: float = 1.0                  # 0.5 = twice slower (after a 60 fps upscale)
    saturation: float = 1.0
    color_drift: str = "none"           # none | soft (blue ± 40°) | full (all colours): slow change of tint
    color_period: float = 120.0         # seconds for one full round of the tint
    stabilize: bool = True              # remove the clip's own micro-shake (Veo jitters by ~0.2-1 px)
    image_segment: float = 10.0         # length of the still-image segment
    track_crossfade: float = 3.0        # seconds between tracks
    shuffle_tracks: bool = False        # reshuffle each pass over the album
    loudness: float = -14.0             # LUFS target (EBU R128)
    ambient_level: float = -12.0        # background sound, dB relative to the music
    video_bitrate: str = "15M"          # loop segment bitrate; not above the source
    codec: str = "h264"                 # h264 | h265
    audio_bitrate: str = "320k"
    seed: int | None = None


@dataclass
class Job:
    visuals: list[Path]                 # one picture, or one or more clips
    tracks: list[Path]
    output: Path
    settings: RenderSettings = field(default_factory=RenderSettings)
    ambient: Path | None = None         # background sound mixed under the music
    mask: Path | None = None            # black/white picture: white moves, black stays still
    still: Path | None = None           # the still picture under the mask (default: first frame)
    previews: list[Path] = field(default_factory=list)   # filled by render()
    timecodes: str = ""                 # filled by render(): track list for the description


Progress = Callable[[str, float], None]


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # progress lines ("frame= ... speed=") say nothing about the cause
        lines = [l for l in proc.stderr.splitlines() if not l.lstrip().startswith("frame=")]
        if proc.returncode < 0 or proc.returncode == 137:
            cause = "ffmpeg остановлен системой: скорее всего, не хватило памяти"
        else:
            cause = next((l for l in lines if "rror" in l or "nvalid" in l), lines[-1] if lines else "")
        # the page shows only the end of the message, so the cause goes last
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:6])} ...\n" + "\n".join(lines[-6:]) + f"\n{cause}")
    return proc.stderr


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def _video_codec_args(s: RenderSettings) -> list[str]:
    if s.codec == "work":  # the loop gets one more pass before the final encode
        return _work_codec_args(s)
    gop = str(s.fps * 2)
    if s.codec == "h265":
        return ["-c:v", "libx265", "-preset", "fast", "-b:v", s.video_bitrate,
                "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
                "-x265-params", f"keyint={gop}:min-keyint={gop}:open-gop=0:log-level=error"]
    # veryfast: about 2x faster than medium at this bitrate with no visible loss
    # (SSIM 0.986 vs 0.989 on a test clip); the loop is encoded only once anyway
    return ["-c:v", "libx264", "-preset", "veryfast", "-b:v", s.video_bitrate,
            "-maxrate", s.video_bitrate, "-bufsize", s.video_bitrate,
            "-pix_fmt", "yuv420p", "-g", gop, "-keyint_min", gop, "-sc_threshold", "0",
            "-profile:v", "high"]


def _work_codec_args(s: RenderSettings) -> list[str]:
    """For intermediate files only: near-lossless and several times faster than
    the final encode. A keyframe every second keeps 1-second cuts exact."""
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", "-pix_fmt", "yuv420p",
            "-g", str(s.fps), "-keyint_min", str(s.fps), "-sc_threshold", "0"]


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


@functools.cache
def _has_vidstab() -> bool:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return "vidstabdetect" in out


def _normalized_clip(src: Path, dst: Path, s: RenderSettings, skip_first: bool = False) -> float:
    # skip_first: a chained clip starts on the previous clip's last frame; drop the repeat
    head = "trim=start_frame=1,setpts=PTS-STARTPTS," if skip_first else ""
    stab = ""
    if s.stabilize and _has_vidstab():
        # tripod: every frame is held to the first one, as if on a tripod;
        # zoom 1% hides the edges the small shifts uncover
        trf = dst.with_suffix(".trf")
        _run(["ffmpeg", "-y", "-i", str(src), "-vf",
              f"{head}vidstabdetect=shakiness=3:accuracy=15:tripod=1:result={trf}", "-f", "null", "-"])
        stab = f"vidstabtransform=input={trf}:tripod=1:interpol=bicubic:crop=keep:optzoom=0:zoom=1,"
    _run(["ffmpeg", "-y", "-i", str(src), "-vf", head + stab + _frame_filter(s), "-an",
          *_work_codec_args(s), str(dst)])
    return probe_duration(dst)


def _encode_list(files: list[Path], dst: Path, s: RenderSettings, tmp: Path) -> None:
    """Join intermediate files and do the one final-quality encode."""
    lst = tmp / f"{dst.stem}_list.txt"
    lst.write_text("".join(f"file '{f}'\n" for f in files))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-an",
          *_video_codec_args(s), str(dst)])


def _crossfade_loop(clip: Path, dst: Path, d: float, s: RenderSettings) -> None:
    """Move the first `x` seconds to the end and blend them in: the last frame
    of the result is followed seamlessly by its first frame."""
    x = min(s.loop_crossfade, d / 2.5)
    flt = (
        # fps= after trim: ffmpeg 7 drops the frame rate there and xfade
        # refuses inputs without a constant one
        # the clip is opened twice: with one input ffmpeg would hold every
        # frame between the head and the seam in memory (GBs at 1080p60)
        f"[0:v]trim=start={x},setpts=PTS-STARTPTS,fps={s.fps}[main];"
        f"[1:v]trim=end={x},setpts=PTS-STARTPTS,fps={s.fps}[head];"
        f"[main][head]xfade=transition=fade:duration={x}:offset={d - 2 * x:.4f},format=yuv420p[v]"
    )
    _run(["ffmpeg", "-y", "-i", str(clip), "-i", str(clip), "-filter_complex", flt, "-map", "[v]",
          "-an", *_video_codec_args(s), str(dst)])


def _pingpong_parts(clip: Path, d: float, s: RenderSettings, tmp: Path) -> list[Path]:
    """Forward then backward, as a list of files to play in a row. Reversing is
    done in 1-second chunks so a 4K clip never has to sit in memory as a whole."""
    chunk = 1.0
    rev_parts = []
    for i in range(math.ceil(d / chunk)):
        part = tmp / f"rev_{i:04d}.mp4"
        _run(["ffmpeg", "-y", "-ss", str(i * chunk), "-t", str(chunk), "-i", str(clip),
              "-vf", "reverse", "-an", *_work_codec_args(s), str(part)])
        rev_parts.append(part)
    # backward pass: last chunk reversed first
    return [clip, *reversed(rev_parts)]


def _join_clips(clips: list[Path], dst: Path, s: RenderSettings, tmp: Path) -> float:
    """Several clips one after another, joined as they are. "chain": each clip
    was generated from the previous clip's last frame, so its first frame (a
    repeat) is dropped and only the loop seam is blended afterwards."""
    lst = tmp / "parts.txt"
    names = []
    for i, c in enumerate(clips):
        n = tmp / f"part_{i:02d}.mp4"
        _normalized_clip(c, n, s, skip_first=i > 0 and s.loop_mode.startswith("chain"))
        names.append(n)
    lst.write_text("".join(f"file '{n}'\n" for n in names))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dst)])
    return probe_duration(dst)


def _scene_key(p: Path) -> str:
    """"A1", "A2" -> "A"; "pink_01" -> "pink": the name without its number."""
    return re.sub(r"[\s_\-.]*\d+$", "", p.stem) or p.stem


def _scenes(clips: list[Path], s: RenderSettings, tmp: Path) -> list[tuple[Path, float]]:
    """Clips of one scene (same name, different number) were made as a chain,
    each from the previous one's last frame: they are joined as they are."""
    groups: dict[str, list[Path]] = {}
    for c in clips:
        groups.setdefault(_scene_key(c), []).append(c)
    out = []
    for g, members in enumerate(groups.values()):
        lst, names = tmp / f"scene_{g:03d}.txt", []
        for i, c in enumerate(members):
            n = tmp / f"scene_{g:03d}_{i:02d}.mp4"
            _normalized_clip(c, n, s, skip_first=i > 0)
            names.append(n)
        lst.write_text("".join(f"file '{n}'\n" for n in names))
        dst = tmp / f"scene_{g:03d}.mp4"
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dst)])
        out.append((dst, probe_duration(dst)))
    return out


def _crossfade_ring(parts: list[tuple[Path, float]], dst: Path, s: RenderSettings, tmp: Path) -> None:
    """Each clip blends into the next and the last one into the first, so the
    whole round repeats without a seam. Every joint is made by its own small
    ffmpeg run (this clip from x to its end + the head of the next one), so
    memory stays the same for 5 clips or 50."""
    # whole frames, so every piece ends exactly where the next one begins
    x = round(min([s.loop_crossfade] + [d / 2.5 for _, d in parts]) * s.fps) / s.fps
    pieces = []
    for i, (n, d) in enumerate(parts):
        nxt = parts[(i + 1) % len(parts)][0]
        piece = tmp / f"ring_{i:03d}.mp4"
        flt = (
            f"[0:v]trim=start={x},setpts=PTS-STARTPTS,fps={s.fps}[main];"
            f"[1:v]trim=end={x},setpts=PTS-STARTPTS,fps={s.fps}[head];"
            f"[main][head]xfade=transition=fade:duration={x}:offset={d - 2 * x:.4f},format=yuv420p[v]"
        )
        _run(["ffmpeg", "-y", "-i", str(n), "-i", str(nxt), "-filter_complex", flt, "-map", "[v]",
              "-an", *_work_codec_args(s), str(piece)])
        pieces.append(piece)
    _encode_list(pieces, dst, s, tmp)


def _best_loop_point(clip: Path, d: float, s: RenderSettings) -> float:
    """Time in the second half of `clip` whose frame looks most like the first
    frame: cutting there and blending back to the start hides the loop seam."""
    w, h = 48, 27
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(clip), "-vf", f"scale={w}:{h},format=gray",
         "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    n = w * h
    frames = [raw[i:i + n] for i in range(0, len(raw) - n + 1, n)]
    if len(frames) < 4:
        return d
    first = frames[0]
    start = len(frames) // 2
    best = min(range(start, len(frames)),
               key=lambda k: sum(abs(a - b) for a, b in zip(frames[k], first)))
    return min(d, best / s.fps)


DRIFT = {
    # hue shift in degrees over one round; both end where they start, so the loop has no seam
    "soft": "40*sin(2*PI*t/{p})",
    "full": "360*t/{p}",
}


def _masked(src: Path, dst: Path, still: Path, mask: Path, s: RenderSettings) -> None:
    """Only the white part of the mask moves; the rest is the still picture
    on every frame, so seams and stray clip details there cannot show."""
    fit = (f"scale={s.width}:{s.height}:force_original_aspect_ratio=increase:flags=lanczos,"
           f"crop={s.width}:{s.height},setsar=1")
    soft = max(2, round(8 * s.height / 1080))  # feathered edge, about 15-20 px at 1080p
    fr = ["-loop", "1", "-framerate", str(s.fps)]
    _run(["ffmpeg", "-y", "-i", str(src), *fr, "-i", str(still), *fr, "-i", str(mask),
          "-filter_complex",
          f"[0:v]format=gbrp[v];[1:v]{fit},format=gbrp[p];"
          f"[2:v]{fit},format=gray,gblur=sigma={soft},format=gbrp[m];"
          "[p][v][m]maskedmerge=planes=7,format=yuv420p[out]",
          "-map", "[out]", "-an", "-t", f"{probe_duration(src):.4f}", *_video_codec_args(s), str(dst)])


def build_loop_segment(visuals: list[Path], dst: Path, s: RenderSettings, tmp: Path,
                       mask: Path | None = None, still: Path | None = None) -> float:
    if mask:
        clips = [v for v in visuals if v.suffix.lower() not in IMAGE_EXTS]
        if not clips:
            raise ValueError("Для маски нужны клипы")
        if still is None:
            still = tmp / "still.png"
            _run(["ffmpeg", "-y", "-i", str(clips[0]), "-frames:v", "1", str(still)])
        raw = tmp / "loop_unmasked.mp4"
        _build_loop_segment(clips, raw, replace(s, codec="work"), tmp)
        if s.color_drift not in DRIFT:
            _masked(raw, dst, still, mask, s)
            return probe_duration(dst)
        masked = tmp / "loop_masked.mp4"
        _masked(raw, masked, still, mask, replace(s, codec="work"))
        return _drift(masked, dst, probe_duration(masked), s)
    if s.color_drift not in DRIFT:
        return _build_loop_segment(visuals, dst, s, tmp)
    raw = tmp / "loop_raw.mp4"
    d = _build_loop_segment(visuals, raw, replace(s, codec="work"), tmp)
    return _drift(raw, dst, d, s)


def _drift(raw: Path, dst: Path, d: float, s: RenderSettings) -> float:
    tmp = raw.parent
    # the tint must come back to its start at the end of the loop: a short
    # loop is repeated inside the segment so one round of colour is slow
    m = max(1, math.ceil(s.color_period / d - 0.01))
    lst = tmp / "drift_list.txt"
    lst.write_text(f"file '{raw}'\n" * m)
    hue = DRIFT[s.color_drift].format(p=f"{m * d:.4f}")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-an",
          "-vf", f"hue=h='{hue}'", *_video_codec_args(s), str(dst)])
    return probe_duration(dst)


def _build_loop_segment(visuals: list[Path], dst: Path, s: RenderSettings, tmp: Path) -> float:
    if len(visuals) == 1 and visuals[0].suffix.lower() in IMAGE_EXTS:
        _image_segment(visuals[0], dst, s)
        return probe_duration(dst)
    if any(v.suffix.lower() in IMAGE_EXTS for v in visuals):
        raise ValueError("Картинку можно загрузить только одну, без клипов")
    clip = tmp / "clip_norm.mp4"
    if len(visuals) > 1 and s.loop_mode == "pingpong":
        # each clip forward then back, so every clip ends on its own first
        # frame; clips made from the same picture then join without a seam
        parts = []
        for i, v in enumerate(visuals):
            norm = tmp / f"pp_src_{i:02d}.mp4"
            d = _normalized_clip(v, norm, s)
            sub = tmp / f"pp_tmp_{i:02d}"
            sub.mkdir()
            parts += _pingpong_parts(norm, d, s, sub)
        _encode_list(parts, dst, s, tmp)
        return probe_duration(dst)
    if s.loop_mode == "scenes":
        _crossfade_ring(_scenes(visuals, s, tmp), dst, s, tmp)
        return probe_duration(dst)
    if len(visuals) > 1 and s.loop_mode == "crossfade":
        parts = []
        for i, c in enumerate(visuals):
            n = tmp / f"ring_src_{i:03d}.mp4"
            parts.append((n, _normalized_clip(c, n, s)))
        _crossfade_ring(parts, dst, s, tmp)
        return probe_duration(dst)
    if len(visuals) == 1:
        d = _normalized_clip(visuals[0], clip, s)
    else:
        d = _join_clips(visuals, clip, s, tmp)
    if s.loop_mode == "chain" and s.find_loop_point and len(visuals) > 1:
        cut = _best_loop_point(clip, d, s)
        if cut < d - 0.1:
            cut_clip = tmp / "clip_cut.mp4"
            _run(["ffmpeg", "-y", "-i", str(clip), "-t", f"{cut:.4f}", "-an",
                  *_work_codec_args(s), str(cut_clip)])
            clip, d = cut_clip, probe_duration(cut_clip)
    if s.loop_mode in ("crossfade", "chain"):
        _crossfade_loop(clip, dst, d, s)
    elif s.loop_mode in ("pingpong", "chain_pingpong"):
        # chain_pingpong: the whole chain forward, then the whole chain backward
        _encode_list(_pingpong_parts(clip, d, s, tmp), dst, s, tmp)
    else:
        _encode_list([clip], dst, s, tmp)
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


def _blend_cycle(src: Path, dst: Path, xs: int, length: int) -> None:
    """`length` samples of `src` from `xs` on, with the first `xs` samples
    blended into the end: repeating the result back to back has no seam."""
    _run(["ffmpeg", "-y", "-i", str(src), "-i", str(src), "-filter_complex",
          f"[0:a]atrim=start_sample={xs}:end_sample={xs + length},asetpts=PTS-STARTPTS[body];"
          f"[1:a]atrim=end_sample={xs},asetpts=PTS-STARTPTS[head];"
          f"[body][head]acrossfade=ns={xs}:c1=tri:c2=tri[cycle]",
          "-map", "[cycle]", "-c:a", "pcm_s16le", str(dst)])


def _ambient_cycle(src: Path, dst: Path, n: int, s: RenderSettings, tmp: Path,
                   level: float | None = None) -> None:
    """Background sound looped seamlessly to exactly `n` samples (one music
    cycle), so music and background repeat together without a seam."""
    sr = 48000
    level = s.ambient_level if level is None else level
    gain = s.loudness + level - measure_loudness(src)
    wav = tmp / "ambient.wav"
    _run(["ffmpeg", "-y", "-i", str(src), "-af", f"volume={gain:.2f}dB",
          "-ac", "2", "-ar", str(sr), str(wav)])
    m = _samples(wav)
    xs = min(3 * sr, m // 3)
    if xs < sr // 10:
        raise ValueError("Фоновый звук слишком короткий")
    own = tmp / "ambient_own.wav"           # the file itself as a seamless loop
    _blend_cycle(wav, own, xs, m - xs)
    longer = tmp / "ambient_long.wav"       # repeated past one music cycle
    xa = min(3 * sr, n // 3)
    _run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(own), "-af",
          f"atrim=end_sample={n + xa}", "-c:a", "pcm_s16le", str(longer)])
    _blend_cycle(longer, dst, xa, n)


def build_ambient_only(ambient: Path, dst: Path, s: RenderSettings, tmp: Path) -> str:
    """No music: the background sound alone, at full loudness, as a seamless
    cycle of whole AAC frames (at least 10 minutes, so the blend is rare)."""
    sr, frame = 48000, 1024
    # limit peaks before the cycle is cut: a limiter on the cycle itself
    # shifts it by its lookahead and the repeat would click
    gain = s.loudness - measure_loudness(ambient)
    limited = tmp / "ambient_limited.wav"
    _run(["ffmpeg", "-y", "-i", str(ambient), "-af",
          f"volume={gain:.2f}dB,alimiter=limit=0.89:level=disabled:latency=1",
          "-ac", "2", "-ar", str(sr), "-c:a", "pcm_s16le", str(limited)])
    n = max(_samples(limited), 600 * sr) // frame * frame
    cycle = tmp / "ambient_only_cycle.wav"
    _ambient_cycle(limited, cycle, n, s, tmp, level=0.0)
    encode_seamless_aac(cycle, dst, s.duration, s.audio_bitrate, tmp)
    return ""


def _clock(t: float) -> str:
    t = int(t)
    h, m, sec = t // 3600, t // 60 % 60, t % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _track_title(p: Path) -> str:
    name = re.sub(r"^\s*\d+\s*[-._)]?\s*", "", p.stem).replace("_", " ").strip()
    return name or p.stem


def _timecodes(names: list[str], starts: list[float], cycle: float, duration: float) -> str:
    """Track list for the video description, over the whole video; only the
    first round if listing every repeat would be too long for YouTube."""
    rows, k = [], 0
    while k * cycle < duration:
        for name, t in zip(names, starts):
            if k * cycle + t < duration - 10:
                rows.append(f"{_clock(k * cycle + t)} {name}")
        k += 1
    if sum(len(r) + 1 for r in rows) > 4000:
        rows = rows[:len(names)]
    return "\n".join(rows)


def build_audio(tracks: list[Path], dst: Path, s: RenderSettings, tmp: Path,
                ambient: Path | None = None) -> str:
    """The album is normalised and crossfaded once into a seamless cycle (its
    end blends into its beginning); the cycle is then repeated as raw PCM and
    encoded once, so hours of audio cost about as much as one album.
    Returns the track list with times for the description."""
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
        _blend_cycle(album, cycle, xs, cycle_len)
    else:
        _run(["ffmpeg", "-y", "-i", str(album), "-af", f"atrim=end_sample={cycle_len}",
              "-c:a", "pcm_s16le", str(cycle)])
    if ambient:
        amb = tmp / "ambient_cycle.wav"
        _ambient_cycle(ambient, amb, cycle_len, s, tmp)
        mixed = tmp / "album_mixed.wav"
        _run(["ffmpeg", "-y", "-i", str(cycle), "-i", str(amb), "-filter_complex",
              "[0:a][1:a]amix=inputs=2:normalize=0:duration=first,"
              "alimiter=limit=0.89:level=disabled:latency=1[a]",
              "-map", "[a]", "-c:a", "pcm_s16le", str(mixed)])
        cycle = mixed
    encode_seamless_aac(cycle, dst, s.duration, s.audio_bitrate, tmp)

    # track k starts where its crossfade begins; the cycle starts x into the album
    starts, t = [], 0.0
    for w in wavs:
        starts.append(max(0.0, t - xs / sr))
        t += _samples(w) / sr - x
    names = [_track_title(tracks[i]) for i in order]
    return _timecodes(names, starts, cycle_len / sr, s.duration)


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

def make_previews(seg: Path, seg_len: float, output: Path, count: int = 4) -> list[Path]:
    """Frames spread over the loop, 1280x720 JPEG, to pick a thumbnail from."""
    out = []
    for i in range(count):
        p = output.with_name(f"{output.stem}_preview_{i + 1}.jpg")
        _run(["ffmpeg", "-y", "-ss", f"{seg_len * (i + 0.5) / count:.3f}", "-i", str(seg),
              "-frames:v", "1", "-vf", "scale=1280:720:flags=lanczos", "-q:v", "2", str(p)])
        out.append(p)
    return out


def source_fps(visuals: list[Path]) -> int:
    """Frame rate of the first clip (30 for a picture). Keeping it avoids
    the uneven 2-3 repeat of frames that 24 -> 60 fps gives (judder)."""
    clips = [v for v in visuals if v.suffix.lower() not in IMAGE_EXTS]
    if not clips:
        return 30
    rate = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=r_frame_rate", "-of", "csv=p=0", str(clips[0])],
                          capture_output=True, text=True).stdout.strip() or "30"
    num, _, den = rate.partition("/")
    fps = round(float(num) / float(den or 1))
    return min(max(fps, 15), 60)


def render(job: Job, progress: Progress | None = None) -> Path:
    if not job.settings.fps:  # 0 = same as the clips
        job.settings = replace(job.settings, fps=source_fps(job.visuals))
    s = job.settings
    say = progress or (lambda msg, frac: None)
    if not job.tracks and not job.ambient:
        raise ValueError("Нужен хотя бы один трек или фоновый звук")
    job.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render_") as td:
        tmp = Path(td)
        say("Готовлю петлю видео", 0.05)
        seg = tmp / "loop.mp4"
        seg_len = build_loop_segment(job.visuals, seg, s, tmp, job.mask, job.still)

        say("Делаю превью", 0.3)
        job.previews = make_previews(seg, seg_len, job.output)

        say("Собираю и выравниваю звук", 0.35)
        audio = tmp / "audio.m4a"
        if job.tracks:
            job.timecodes = build_audio(job.tracks, audio, s, tmp, job.ambient)
        else:
            job.timecodes = build_ambient_only(job.ambient, audio, s, tmp)
        job.output.with_suffix(".txt").write_text(job.timecodes + "\n", encoding="utf-8")

        say("Склеиваю видео до нужной длины", 0.8)
        repeats = math.ceil(s.duration / seg_len) + 1
        lst = tmp / "repeat.txt"
        lst.write_text(f"file '{seg}'\n" * repeats)
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio),
              "-map", "0:v", "-map", "1:a", "-c", "copy", "-t", str(s.duration),
              str(job.output)])
    say("Готово", 1.0)
    return job.output
