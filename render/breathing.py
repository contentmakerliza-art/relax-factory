"""«Вступление + чёрный экран»: a guided-breathing intro (a circle that grows
on the inhale and shrinks on the exhale, a voice over the quiet background
sound), then a black screen with the sleep sound for the rest of the video."""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from render.scripts import DEFAULT, PRESETS

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FADE = 20.0       # seconds for the circle to fade out after the voice ends
RISE = 15.0       # seconds for the background to come back to full


SIGH = (2.0, 1.0, 6.0)   # physiological sigh: inhale, top-up inhale, long exhale


@dataclass
class Breath:
    start: float = 16.0      # seconds before the first inhale
    inhale: float = 4.0      # rhythm for a script without its own
    exhale: float = 6.0
    cycles: int = 9
    hold: float = 0.0
    intro_lines: int = 2     # a script without [sections]: phrases before the first inhale
    outro_lines: int = 2     # ... and after the last exhale
    duck_db: float = -24.0   # background sound during the practice, under the voice
    after_db: float = -2.0   # background after the practice, against its usual loudness
    rise: float = 0.0        # when the background starts coming back (0: when the voice ends)
    script: str = PRESETS[DEFAULT]   # what the voice says, a phrase per line
    phases: tuple = ()       # filled by arrange_voice: (start, end, size from, size to, caption)


@dataclass
class Plan:
    intro: list[str]
    breaths: list[tuple[list[tuple[str, float, float]], list[str], list[int]]]
    # each breath: phases (caption, seconds, size at the end 0..1), its lines,
    # and the phase each line starts on
    outro: list[str]
    tail: list[tuple[str, float, float]]   # the rhythm the circle keeps after the practice

    @property
    def lines(self) -> list[str]:
        return self.intro + [x for _, ls, _ in self.breaths for x in ls] + self.outro


SECTION = re.compile(r"^\[\s*(intro|outro|cycles|sighs)\s*(?:x\s*(\d+))?\s*"
                     r"(?:,\s*([\d.]+(?:\s*-\s*[\d.]+){1,2}))?\s*\]$", re.I)


def _rhythm(kind: str, nums: list[float]) -> list[tuple[str, float, float]]:
    if kind == "sighs":
        i1, i2, ex = nums if len(nums) == 3 else SIGH
        return [("inhale", i1, 0.75), ("inhale", i2, 1.0), ("exhale", ex, 0.0)]
    if len(nums) == 3:
        return [("inhale", nums[0], 1.0), ("hold", nums[1], 1.0), ("exhale", nums[2], 0.0)]
    return [("inhale", nums[0], 1.0), ("exhale", nums[1], 0.0)]


def _cues(phases: list, n: int) -> list[int]:
    """Which phase each of a breath's n lines starts on."""
    if n == 1:
        return [0]
    if n == 2:
        return [0, len(phases) - 1]   # in, out (a hold or top-up has no line)
    if n == len(phases):
        return list(range(n))
    raise ValueError


def parse_script(b: Breath) -> Plan:
    """The script's sections; a plain list of lines is intro + cycles + outro
    in the form's rhythm. ValueError with a message for the user."""
    rows = [x.strip() for x in b.script.splitlines() if x.strip()]
    default = [b.inhale, b.hold, b.exhale] if b.hold else [b.inhale, b.exhale]
    if not any(SECTION.match(r) for r in rows):
        n = len(rows) - b.intro_lines - b.outro_lines
        if n < 2 or n % 2:
            raise ValueError("Текст голоса не подходит: нужно вступление, пары вдох/выдох и концовка "
                             "(или разметка [intro], [cycles x9, 4-6], [outro])")
        rows = (["[intro]"] + rows[: b.intro_lines] + [f"[cycles x{n // 2}]"]
                + rows[b.intro_lines: -b.outro_lines] + ["[outro]"] + rows[-b.outro_lines:])
    sections, cur = [], None
    for r in rows:
        if m := SECTION.match(r):
            cur = (m.group(1).lower(), int(m.group(2) or 1),
                   [float(x) for x in re.split(r"\s*-\s*", m.group(3))] if m.group(3) else None, [])
            sections.append(cur)
        elif cur is None:
            raise ValueError("Текст голоса должен начинаться с разметки, например [intro]")
        else:
            cur[3].append(r)
    intro, outro, breaths, tail = [], [], [], None
    for kind, count, nums, lines in sections:
        if kind == "intro":
            intro += lines
        elif kind == "outro":
            outro += lines
        else:
            phases = _rhythm(kind, nums or default)
            if not lines or len(lines) % count:
                raise ValueError(f"В секции [{kind} x{count}] {len(lines)} строк: не делится на {count}")
            per = len(lines) // count
            try:
                cues = _cues(phases, per)
            except ValueError:
                raise ValueError(f"В секции [{kind} x{count}] по {per} строки на дыхание: "
                                 f"нужно 1, 2 или {len(phases)}") from None
            for k in range(count):
                breaths.append((phases, lines[k * per:(k + 1) * per], cues))
            if kind == "cycles":
                tail = phases
    if not breaths:
        raise ValueError("В тексте голоса нет секции [cycles] или [sighs]")
    return Plan(intro, breaths, outro, tail or breaths[-1][0])


def timeline(plan: Plan, b: Breath, durs: list[float] | None, until: float):
    """When each voice line starts and how the circle moves. A breath waits
    for the voice if a line runs longer than the phase before it, so the
    words and the circle stay together. `durs`: the lines' lengths (None:
    the voice is not split, keep the plain rhythm)."""
    at, free, i = [], 0.0, 0
    slot = b.start / max(1, len(plan.intro))
    for k in range(len(plan.intro)):  # spread over the time before the first inhale
        t = max(k * slot, free)
        at.append(t)
        free = t + (durs[i] + 1.0 if durs else 0)
        i += 1
    t = max(b.start, math.ceil(free))
    phases = []
    for ph, lines, cues in plan.breaths:
        size = 0.0
        for p, (cap, sec, to) in enumerate(ph):
            for _ in [j for j, q in enumerate(cues) if q == p]:
                t = max(t, free)
                at.append(t)
                free = t + (durs[i] + 0.3 if durs else 0)
                i += 1
            phases.append((t, t + sec, size, to, cap))
            t, size = t + sec, to
    end = t
    rise = 0.0
    for k in range(len(plan.outro)):
        t = max(end + k * 6.0, free + 1.2 if durs else 0)
        rise = rise or t
        at.append(t)
        free = t + (durs[i] if durs else 0)
        i += 1
    t = end  # the circle keeps breathing, without captions, while it fades
    while t < until:
        size = 0.0
        for cap, sec, to in plan.tail:
            phases.append((t, t + sec, size, to, ""))
            t, size = t + sec, to
    return at, phases, rise


def _size_expr(phases: tuple, d: int) -> str:
    """Circle diameter at time t: smallest before the first inhale, eased
    between the sizes of each phase."""
    f = "0"
    for t0, t1, s0, s1, _ in reversed(phases):
        seg = f"{s0}+({s1 - s0})*(1-cos(PI*(t-{t0:.2f})/{t1 - t0:.2f}))/2" if s0 != s1 else f"{s0}"
        f = f"if(lt(t,{t1:.2f}),{seg},{f})"
    if phases:
        f = f"if(lt(t,{phases[0][0]:.2f}),0,{f})"
    return f"trunc({d}*(0.35+0.65*({f}))/2)*2"


def intro_video(dst: Path, voice_len: float, b: Breath, width: int, height: int,
                fps: int, codec_args: list[str], run) -> float:
    """Returns the intro length: the voice, then the fade to black."""
    length = math.ceil(voice_len + FADE + 1)
    d = round(height * 0.45) // 2 * 2
    size = _size_expr(b.phases, d)
    # soft lavender disc: bright core, glowing edge, transparent outside
    r = f"hypot(X-{d}/2,Y-{d}/2)/({d}/2)"
    disc = dst.with_name("disc.png")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black@0:s={d}x{d},format=rgba", "-vf",
         f"geq=r=200:g=205:b=255:a='255*clip((1-{r})*6,0,1)*(0.55+0.45*(1-{r}))'",
         "-frames:v", "1", str(disc)])
    text = (f"fontfile={FONT}:fontsize={round(height * 0.035)}:fontcolor=white@0.6:"
            f"x=(w-text_w)/2:y=h*0.5+{d}*0.6")
    captions = ""
    for cap in ("inhale", "hold", "exhale"):
        # one caption over consecutive phases (sigh: two inhales) shows once
        spans = []
        for t0, t1, _, _, c in b.phases:
            if c != cap:
                continue
            if spans and abs(spans[-1][1] - t0) < 0.01:
                spans[-1] = (spans[-1][0], t1)
            else:
                spans.append((t0, t1))
        if spans:
            on = "+".join(f"between(t,{t0:.2f},{t1 - 0.01:.2f})" for t0, t1 in spans)
            captions += f"drawtext={text}:text='{cap}':enable='{on}',"
    vf = (f"[1:v]scale=w='{size}':h='{size}':eval=frame[c];[0:v][c]overlay=x=(W-w)/2:y=(H-h)/2:shortest=1,"
          f"{captions}fade=t=in:st=0:d=3,fade=t=out:st={voice_len:.2f}:d={FADE},format=yuv420p[v]")
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
    first, each breath's lines on its inhale / hold / exhale, then the closing
    lines. Returns the new voice file, the breath timing and a warning; when
    the voice cannot be matched to the script, it is used as it is."""
    plan = parse_script(b)
    lines = plan.lines
    parts = _phrases(voice, lines)
    if not parts:
        length = _duration(voice)
        at, phases, rise = timeline(plan, b, None, length + FADE)
        return voice, replace(b, phases=tuple(phases)), (
            f"В голосе меньше пауз, чем фраз в тексте ({len(lines)}): оставил его как есть, "
            "без подгонки к кругу")
    at, _, _ = timeline(plan, b, [e - a for a, e in parts], 0)
    length = at[-1] + parts[-1][1] - parts[-1][0]
    at, phases, rise = timeline(plan, b, [e - a for a, e in parts], length + FADE)
    chains = "".join(f"[0:a]atrim={a:.3f}:{e:.3f},asetpts=PTS-STARTPTS,"
                     f"adelay={round(d * 1000)}:all=1[p{i}];"
                     for i, ((a, e), d) in enumerate(zip(parts, at)))
    run(["ffmpeg", "-y", "-i", str(voice), "-filter_complex",
         chains + "".join(f"[p{i}]" for i in range(len(parts)))
         + f"amix=inputs={len(parts)}:normalize=0:duration=longest[a]",
         "-map", "[a]", "-c:a", "pcm_s16le", str(dst)])
    return dst, replace(b, phases=tuple(phases), rise=rise), ""


def _duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(out.stdout.strip())
