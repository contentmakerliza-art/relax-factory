"""«Вступление + чёрный экран»: a guided-breathing intro (a circle that grows
on the inhale and shrinks on the exhale, a voice over the quiet background
sound), then a black screen with the sleep sound for the rest of the video."""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FADE = 20.0       # seconds for the circle to fade out after the voice ends
DUCK_DB = -6.0    # background sound under the voice


@dataclass
class Breath:
    start: float = 16.0      # seconds before the first inhale
    inhale: float = 4.0
    exhale: float = 6.0
    cycles: int = 9          # cycles with «inhale» / «exhale» captions
    intro_lines: int = 2     # voice phrases before the first inhale
    outro_lines: int = 2     # voice phrases after the last exhale


def _size_expr(b: Breath, d: int) -> str:
    """Circle diameter at time t: smallest before the first inhale, then
    eased up over the inhale and down over the exhale, forever."""
    p = f"mod(t-{b.start},{b.inhale + b.exhale})"
    grow = f"(1-cos(PI*{p}/{b.inhale}))/2"
    shrink = f"(1+cos(PI*({p}-{b.inhale})/{b.exhale}))/2"
    f = f"if(lt(t,{b.start}),0,if(lt({p},{b.inhale}),{grow},{shrink}))"
    return f"trunc({d}*(0.35+0.65*({f}))/2)*2"


def intro_video(dst: Path, voice_len: float, b: Breath, width: int, height: int,
                fps: int, codec_args: list[str], run) -> float:
    """Returns the intro length: the voice, then the fade to black."""
    length = math.ceil(voice_len + FADE + 1)
    d = round(height * 0.45) // 2 * 2
    size = _size_expr(b, d)
    # soft lavender disc: bright core, glowing edge, transparent outside
    r = f"hypot(X-{d}/2,Y-{d}/2)/({d}/2)"
    disc = dst.with_name("disc.png")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black@0:s={d}x{d},format=rgba", "-vf",
         f"geq=r=200:g=205:b=255:a='255*clip((1-{r})*6,0,1)*(0.55+0.45*(1-{r}))'",
         "-frames:v", "1", str(disc)])
    end = b.start + b.cycles * (b.inhale + b.exhale)
    phase = f"mod(t-{b.start},{b.inhale + b.exhale})"
    on = f"between(t,{b.start},{end})"
    text = (f"fontfile={FONT}:fontsize={round(height * 0.035)}:fontcolor=white@0.6:"
            f"x=(w-text_w)/2:y=h*0.5+{d}*0.6")
    vf = (f"[1:v]scale=w='{size}':h='{size}':eval=frame[c];[0:v][c]overlay=x=(W-w)/2:y=(H-h)/2:shortest=1,"
          f"drawtext={text}:text='inhale':enable='{on}*lt({phase},{b.inhale})',"
          f"drawtext={text}:text='exhale':enable='{on}*gte({phase},{b.inhale})',"
          f"fade=t=out:st={voice_len:.2f}:d={FADE},format=yuv420p[v]")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black:s={width}x{height}:d={length}:r={fps}",
         "-loop", "1", "-framerate", str(fps), "-i", str(disc),
         "-filter_complex", vf, "-map", "[v]", "-an", *codec_args, str(dst)])
    return float(length)


def black_video(dst: Path, width: int, height: int, fps: int, codec_args: list[str], run) -> float:
    """10 s of black, repeated for the rest of the video (nearly zero bytes)."""
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black:s={width}x{height}:d=10:r={fps}",
         "-an", *codec_args, str(dst)])
    return 10.0


def head_block(cycle: Path, voice: Path, dst: Path, voice_len: float, run) -> None:
    """The start of the sound cycle with the voice over it: background lowered
    under the voice, back to full over the fade. Same length as `cycle`, so the
    plain cycle follows it without a seam."""
    duck = 10 ** (DUCK_DB / 20)
    v = f"{voice_len:.3f}"
    vol = f"if(lt(t,{v}),{duck:.4f},if(lt(t,{v}+{FADE}),{duck:.4f}+(1-{duck:.4f})*(t-{v})/{FADE},1))"
    run(["ffmpeg", "-y", "-i", str(cycle), "-i", str(voice), "-filter_complex",
         f"[0:a]volume='{vol}':eval=frame[bg];"
         "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[vo];"
         "[bg][vo]amix=inputs=2:normalize=0:duration=first[a]",
         "-map", "[a]", "-c:a", "pcm_s16le", str(dst)])


def _phrases(voice: Path, count: int) -> list[tuple[float, float]] | None:
    """Split a voice file at its `count - 1` longest pauses. None if it has
    fewer pauses than that."""
    err = subprocess.run(["ffmpeg", "-nostats", "-i", str(voice), "-af",
                          "silencedetect=noise=-40dB:d=0.2", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(voice)], capture_output=True, text=True)
    total = float(out.stdout.strip())
    gaps = [(a, b) for a, b in zip(starts, ends) if a > 0.05 and b < total - 0.05]
    if len(gaps) < count - 1:
        return None
    cuts = sorted(sorted(gaps, key=lambda g: g[1] - g[0])[-(count - 1):])
    lead = next((b for a, b in zip(starts, ends) if a <= 0.05), 0.0)
    # silence running to the end of the file has a start but no end
    tail = starts[-1] if len(starts) > len(ends) else total
    bounds = [lead] + [x for g in cuts for x in g] + [tail]
    # keep a breath of the room tone around each phrase
    return [(max(0.0, a - 0.05), b + 0.15) for a, b in zip(bounds[::2], bounds[1::2])]


def arrange_voice(voice: Path, b: Breath, dst: Path, run) -> tuple[Path, Breath, str]:
    """Lay a compact voice recording onto the breathing timeline: intro lines
    first, then each «in» phrase on an inhale and each «out» phrase on an
    exhale, then the closing lines. Returns the new voice file, the breath
    timing (the start moves later if the intro lines need it) and a warning;
    when the pauses do not match the script, the voice is used as it is."""
    count = b.intro_lines + 2 * b.cycles + b.outro_lines
    parts = _phrases(voice, count) if b.cycles else None
    if not parts:
        return voice, b, (f"Голос не разделился на {count} фраз по паузам, "
                          "оставил его как есть, без подгонки к дыханию")
    at, t = [], 0.0
    intro = parts[: b.intro_lines]
    slot = b.start / max(1, len(intro))
    for i, (a, e) in enumerate(intro):  # spread over the time before the first inhale
        t = max(i * slot, t)
        at.append(t)
        t += e - a + 1.0
    start = max(b.start, math.ceil(t))
    period = b.inhale + b.exhale
    t = 0.0
    for k in range(b.cycles):
        for j, (a, e) in enumerate(parts[b.intro_lines + 2 * k: b.intro_lines + 2 * k + 2]):
            t = max(start + k * period + j * b.inhale, t)
            at.append(t)
            t += e - a + 0.3
    end = start + b.cycles * period
    for i, (a, e) in enumerate(parts[b.intro_lines + 2 * b.cycles:]):
        t = max(end + i * 6.0, t + 1.2)
        at.append(t)
        t += e - a
    chains = "".join(f"[0:a]atrim={a:.3f}:{e:.3f},asetpts=PTS-STARTPTS,"
                     f"adelay={round(d * 1000)}:all=1[p{i}];"
                     for i, ((a, e), d) in enumerate(zip(parts, at)))
    run(["ffmpeg", "-y", "-i", str(voice), "-filter_complex",
         chains + "".join(f"[p{i}]" for i in range(len(parts)))
         + f"amix=inputs={len(parts)}:normalize=0:duration=longest[a]",
         "-map", "[a]", "-c:a", "pcm_s16le", str(dst)])
    return dst, replace(b, start=float(start)), ""
