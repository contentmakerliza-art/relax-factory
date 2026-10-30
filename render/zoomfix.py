"""Undo a slow camera push-in (AI clips often zoom toward the subject), so the
last frame has the same framing as the first and the loop seam does not jump
from close-up back to wide."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

W, H = 320, 180          # analysis size
STEP = 1.0               # seconds between measured frames


def _frames(src: Path, head: str) -> tuple[np.ndarray, float]:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf",
                          f"{head}scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    frames = np.frombuffer(raw, np.uint8)[: len(raw) // (W * H) * W * H].reshape(-1, H, W)
    rate = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=r_frame_rate", "-of", "csv=p=0", str(src)],
                          capture_output=True, text=True).stdout.strip() or "30"
    num, _, den = rate.partition("/")
    return frames.astype(np.float32), float(num) / float(den or 1)


def _zoomed(img: np.ndarray, z: float) -> np.ndarray:
    """`img` enlarged z times about its centre (bilinear), same size."""
    ys = (np.arange(H) - H / 2) / z + H / 2
    xs = (np.arange(W) - W / 2) / z + W / 2
    y0 = np.clip(np.floor(ys).astype(int), 0, H - 2)
    x0 = np.clip(np.floor(xs).astype(int), 0, W - 2)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    a = img[y0][:, x0]
    b = img[y0][:, x0 + 1]
    c = img[y0 + 1][:, x0]
    d = img[y0 + 1][:, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def _blur(img: np.ndarray, r: int = 3) -> np.ndarray:
    k = np.ones(2 * r + 1, np.float32) / (2 * r + 1)
    img = np.apply_along_axis(lambda v: np.convolve(v, k, "same"), 0, img)
    return np.apply_along_axis(lambda v: np.convolve(v, k, "same"), 1, img)


def _match(a: np.ndarray, b: np.ndarray, reach: int = 40) -> tuple[float, float, float]:
    """Best correlation of b with a over shifts up to `reach` pixels, and the
    shift (dy, dx) where b shows a's content: b(p) ~ a(p - shift)."""
    m = 24  # ignore the edges
    a, b = a[m:-m, m:-m], b[m:-m, m:-m]
    a, b = a - a.mean(), b - b.mean()
    cc = np.fft.ifft2(np.fft.fft2(a) * np.conj(np.fft.fft2(b))).real
    ys = np.r_[0:reach + 1, -reach:0]
    near = cc[np.ix_(ys, ys)]
    k = np.unravel_index(near.argmax(), near.shape)
    score = near[k] / np.sqrt((a * a).sum() * (b * b).sum() + 1e-9)
    return float(score), -(ys[k[0]] + _peak(cc[:, ys[k[1]]], ys[k[0]])), \
        -(ys[k[1]] + _peak(cc[ys[k[0]]], ys[k[1]]))


def _peak(line: np.ndarray, i: int) -> float:
    """Sub-pixel offset of a correlation peak at `i` (parabola through 3 points)."""
    l, c, r = line[i - 1], line[i], line[(i + 1) % len(line)]
    d = l - 2 * c + r
    return float(0.5 * (l - r) / d) if d < 0 else 0.0


def _scale(first: np.ndarray, frame: np.ndarray, around: float) -> tuple[float, float, float]:
    """How many times bigger `frame` shows things than `first`, and its shift."""
    best = (around, 0, 0)
    for step, span in ((0.004, 0.06), (0.0005, 0.004)):
        zs = np.arange(best[0] - span, best[0] + span + step / 2, step)
        scored = [(_match(_zoomed(first, z), frame), z) for z in zs]
        (_, dy, dx), z = max(scored, key=lambda t: t[0][0])
        best = (float(z), dy, dx)
    return best


def _ramp(idx: list[int], vals: list[float]) -> str:
    """Piecewise-linear expression of the input frame number `in`."""
    expr = f"{vals[-1]:.5f}"
    for i in range(len(idx) - 2, -1, -1):
        i0, i1, v0, v1 = idx[i], idx[i + 1], vals[i], vals[i + 1]
        expr = f"if(lt(in,{i1}),{v0:.5f}+({v1 - v0:.5f})*(in-{i0})/{i1 - i0},{expr})"
    return f"({expr})"


def _measure(src: Path, head: str):
    """Measured frames and (scale, dy, dx) against the first frame, or None
    when the clip does not zoom."""
    frames, fps = _frames(src, head)
    if len(frames) < fps * 2:
        return None
    first = _blur(frames[:2].mean(axis=0))
    idx = list(range(0, len(frames), max(1, round(fps * STEP))))
    if idx[-1] != len(frames) - 1:
        idx.append(len(frames) - 1)
    found, z = [], 1.0
    for i in idx:
        found.append((1.0, 0, 0) if i == 0 else _scale(first, _blur(frames[i]), z))
        z = found[-1][0]
    zs = [f[0] for f in found]
    if max(zs) - min(zs) < 0.006:
        return None
    return idx, found


def _perspective(c: str, dx: str, dy: str) -> str:
    x0, y0 = f"(W/2*(1-1/{c})+W*{dx})", f"(H/2*(1-1/{c})+H*{dy})"
    x1, y1 = f"(W-W/2*(1-1/{c})+W*{dx})", f"(H-H/2*(1-1/{c})+H*{dy})"
    return (f"perspective=x0='{x0}':y0='{y0}':x1='{x1}':y1='{y0}':"
            f"x2='{x0}':y2='{y1}':x3='{x1}':y3='{y1}':interpolation=cubic:eval=frame,")


def zoom_filter(src: Path, head: str) -> str:
    """A perspective filter that enlarges and shifts each frame to the tightest
    framing in the clip, so a slow push-in turns into a still camera and the
    last frame lines up with the first. Empty if the clip does not zoom."""
    m = _measure(src, head)
    if not m:
        return ""
    idx, found = m
    top = max(f[0] for f in found)
    c = _ramp(idx, [top / f[0] for f in found])
    dx = _ramp(idx, [f[2] / W for f in found])   # share of the frame width
    dy = _ramp(idx, [f[1] / H for f in found])
    return _perspective(c, dx, dy)


def start_filter(src: Path, head: str) -> str:
    """The framing zoom_filter gives the clip's FIRST frame, held still: for an
    intro that ends on that frame, so both are framed the same."""
    m = _measure(src, head)
    if not m:
        return ""
    top = max(f[0] for f in m[1])
    return _perspective(f"{top:.6f}", "0", "0")
