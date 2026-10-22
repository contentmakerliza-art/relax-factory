"""«Вступление + чёрный экран»: a guided-breathing intro (a circle that grows
on the inhale and shrinks on the exhale, a voice over the quiet background
sound), then a black screen with the sleep sound for the rest of the video."""

from __future__ import annotations

import math
from dataclasses import dataclass
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
