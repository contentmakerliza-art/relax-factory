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
RISE = 15.0       # seconds for the background to come back to full


# the text the voice reads, one phrase per line (channels/bedtime-rain script v1);
# only the lengths matter: they tell which pauses separate phrases
SCRIPT = """Welcome. Get comfortable, and let your eyes close whenever you're ready.
We'll breathe together for two minutes. Then the rain will carry you the rest of the way.
Breathe in through your nose…
…and slowly out…
In…
and out, longer…
In…
and out… let your shoulders drop.
In…
and out…
In…
slowly out… let the jaw soften.
In…
and out…
In…
and out… nothing to do now.
In…
and out…
One more. In…
and all the way out…
Now let your breath find its own rhythm.
Just listen to the rain… and let sleep come."""


@dataclass
class Breath:
    start: float = 16.0      # seconds before the first inhale
    inhale: float = 4.0
    exhale: float = 6.0
    cycles: int = 9          # cycles with «inhale» / «exhale» captions
    intro_lines: int = 2     # voice phrases before the first inhale
    outro_lines: int = 2     # voice phrases after the last exhale
    duck_db: float = -24.0   # background sound during the practice, under the voice
    after_db: float = -2.0   # background after the practice, against its usual loudness
    rise: float = 0.0        # when the background starts coming back (0: when the voice ends)
    script: str = SCRIPT     # what the voice says, a phrase per line




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
          f"fade=t=in:st=0:d=3,fade=t=out:st={voice_len:.2f}:d={FADE},format=yuv420p[v]")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black:s={width}x{height}:d={length}:r={fps}",
         "-loop", "1", "-framerate", str(fps), "-i", str(disc),
         "-filter_complex", vf, "-map", "[v]", "-an", *codec_args, str(dst)])
    return float(length)


def black_video(dst: Path, width: int, height: int, fps: int, codec_args: list[str], run) -> float:
    """10 s of black, repeated for the rest of the video (nearly zero bytes)."""
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black:s={width}x{height}:d=10:r={fps}",
         "-an", *codec_args, str(dst)])
    return 10.0


def head_block(cycle: Path, voice: Path, dst: Path, voice_len: float, b: Breath, run) -> None:
    """The start of the sound cycle with the voice over it: background low
    during the practice, back to full over RISE seconds from the closing
    lines (or from the end of the voice). Same length as `cycle`, so the
    plain cycle follows it without a seam."""
    duck = 10 ** ((b.duck_db - b.after_db) / 20)  # `cycle` is already at after_db
    r = f"{(b.rise or voice_len):.3f}"
    vol = f"if(lt(t,{r}),{duck:.4f},if(lt(t,{r}+{RISE}),{duck:.4f}+(1-{duck:.4f})*(t-{r})/{RISE},1))"
    run(["ffmpeg", "-y", "-i", str(cycle), "-i", str(voice), "-filter_complex",
         f"[0:a]volume='{vol}':eval=frame[bg];"
         "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[vo];"
         "[bg][vo]amix=inputs=2:normalize=0:duration=first[a]",
         "-map", "[a]", "-c:a", "pcm_s16le", str(dst)])


def _chunks(voice: Path) -> list[tuple[float, float]]:
    """Stretches of speech between every pause, however short."""
    vol = subprocess.run(["ffmpeg", "-nostats", "-i", str(voice), "-af", "volumedetect",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", vol)
    floor = (float(m.group(1)) if m else -25.0) - 20  # well under the speech, above room tone
    err = subprocess.run(["ffmpeg", "-nostats", "-i", str(voice), "-af",
                          f"silencedetect=noise={floor:.0f}dB:d=0.12", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [max(0.0, float(x)) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(voice)], capture_output=True, text=True)
    total = float(out.stdout.strip())
    ends += [total] * (len(starts) - len(ends))  # silence to the end of the file
    talk, t = [], 0.0
    for a, e in zip(starts, ends):
        if a - t > 0.05:
            talk.append((t, a))
        t = e
    if total - t > 0.05:
        talk.append((t, total))
    return talk


K_CHARS = 3     # a phrase takes a little time beyond its letters
W_PAUSE = 1.0   # how much a long pause before a phrase is preferred as its start


def _fit(dur: float, want: float, pause: float) -> float:
    """How unlikely a phrase of `dur` seconds is where `want` was expected,
    starting after a pause of `pause` seconds (long pauses separate phrases)."""
    return math.log(dur / want) ** 2 - W_PAUSE * min(pause, 1.5)


def _phrases(voice: Path, lines: list[str]) -> list[tuple[float, float]] | None:
    """Group the speech into one piece per script line: the grouping whose
    piece lengths best follow the lines' lengths, cutting at long pauses.
    None if there are fewer pauses than lines."""
    talk = _chunks(voice)
    n, k = len(talk), len(lines)
    if n < k:
        return None
    chars = [len(x) for x in lines]
    span = talk[-1][1] - talk[0][0]
    gaps = sorted((talk[i + 1][0] - talk[i][1] for i in range(n - 1)), reverse=True)
    rate = (span - sum(gaps[: k - 1])) / sum(c + K_CHARS for c in chars)
    # best[j][i]: cost of the first i chunks as the first j lines
    inf = float("inf")
    best = [[inf] * (n + 1) for _ in range(k + 1)]
    back = [[0] * (n + 1) for _ in range(k + 1)]
    best[0][0] = 0.0
    for j in range(1, k + 1):
        want = rate * (chars[j - 1] + K_CHARS)
        for i in range(j, n - (k - j) + 1):
            for h in range(j - 1, i):
                if best[j - 1][h] == inf:
                    continue
                dur = talk[i - 1][1] - talk[h][0]
                pause = talk[h][0] - talk[h - 1][1] if h else 1.0
                cost = best[j - 1][h] + _fit(dur, want, pause)
                if cost < best[j][i]:
                    best[j][i], back[j][i] = cost, h
    cuts, i = [], n
    for j in range(k, 0, -1):
        h = back[j][i]
        cuts.append((talk[h][0], talk[i - 1][1]))
        i = h
    # keep a breath of room tone around each phrase
    return [(max(0.0, a - 0.05), e + 0.15) for a, e in reversed(cuts)]


def arrange_voice(voice: Path, b: Breath, dst: Path, run) -> tuple[Path, Breath, str]:
    """Lay a compact voice recording onto the breathing timeline: intro lines
    first, then each «in» phrase on an inhale and each «out» phrase on an
    exhale, then the closing lines. Returns the new voice file, the breath
    timing (the start moves later if the intro lines need it) and a warning;
    when the pauses do not match the script, the voice is used as it is."""
    lines = [x.strip() for x in b.script.splitlines() if x.strip()]
    cycles = (len(lines) - b.intro_lines - b.outro_lines) // 2
    if cycles < 1 or len(lines) != b.intro_lines + 2 * cycles + b.outro_lines:
        return voice, b, "Текст голоса не подходит под схему вступление + вдох/выдох + концовка"
    b = replace(b, cycles=cycles)
    parts = _phrases(voice, lines)
    if not parts:
        return voice, b, (f"В голосе меньше пауз, чем фраз в тексте ({len(lines)}), "
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
    rise = 0.0
    for i, (a, e) in enumerate(parts[b.intro_lines + 2 * b.cycles:]):
        t = max(end + i * 6.0, t + 1.2)
        rise = rise or t  # the sound comes back from the first closing line
        at.append(t)
        t += e - a
    chains = "".join(f"[0:a]atrim={a:.3f}:{e:.3f},asetpts=PTS-STARTPTS,"
                     f"adelay={round(d * 1000)}:all=1[p{i}];"
                     for i, ((a, e), d) in enumerate(zip(parts, at)))
    run(["ffmpeg", "-y", "-i", str(voice), "-filter_complex",
         chains + "".join(f"[p{i}]" for i in range(len(parts)))
         + f"amix=inputs={len(parts)}:normalize=0:duration=longest[a]",
         "-map", "[a]", "-c:a", "pcm_s16le", str(dst)])
    return dst, replace(b, start=float(start), rise=rise), ""
