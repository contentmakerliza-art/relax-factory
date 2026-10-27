"""Byte map of a long video made by repeating a loop: which bytes of the final
MP4 come from the loop, which from the sound file and which are the file's own
(header and index). A browser can then rebuild the exact same file from the
small loop and sound, without downloading the whole long video."""

from __future__ import annotations

import json
import random
import struct
import sys
from array import array
from pathlib import Path

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf"}


def _boxes(data: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        head = 8
        if size == 1:
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            head = 16
        elif size == 0:
            size = end - pos
        yield kind, pos + head, pos + size
        pos += size


def _top_moov(path: Path) -> bytes:
    """The moov box of a file (read on its own: the file itself may be 40 GB)."""
    with path.open("rb") as f:
        pos, total = 0, path.stat().st_size
        while pos < total:
            f.seek(pos)
            size, kind = struct.unpack(">I4s", f.read(8))
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0]
            elif size == 0:
                size = total - pos
            if kind == b"moov":
                f.seek(pos)
                return f.read(size)
            pos += size
    raise ValueError(f"В {path.name} нет индекса moov")


def _track_samples(stbl: bytes) -> tuple[array, array]:
    """File offset and size of every sample of one track, in order (compact
    arrays: a 10-hour video has a few million samples)."""
    tables = {k: (s, e) for k, s, e in _boxes(stbl, 0, len(stbl))}
    s, _ = tables[b"stsz"]
    fixed, count = struct.unpack(">II", stbl[s + 4:s + 12])
    sizes = array("I", [fixed]) * count if fixed else _be("I", stbl[s + 12:s + 12 + 4 * count])
    if b"co64" in tables:
        s, _ = tables[b"co64"]
        n = struct.unpack(">I", stbl[s + 4:s + 8])[0]
        chunks = _be("Q", stbl[s + 8:s + 8 + 8 * n])
    else:
        s, _ = tables[b"stco"]
        n = struct.unpack(">I", stbl[s + 4:s + 8])[0]
        chunks = _be("I", stbl[s + 8:s + 8 + 4 * n])
    s, _ = tables[b"stsc"]
    m = struct.unpack(">I", stbl[s + 4:s + 8])[0]
    runs = [struct.unpack(">III", stbl[s + 8 + 12 * i:s + 20 + 12 * i])[:2] for i in range(m)]
    offsets, k = array("Q"), 0
    for r, (first, per) in enumerate(runs):
        last = runs[r + 1][0] - 1 if r + 1 < len(runs) else len(chunks)
        for c in range(first - 1, last):
            off = chunks[c]
            for _ in range(per):
                if k == len(sizes):
                    return offsets, sizes
                offsets.append(off)
                off += sizes[k]
                k += 1
    return offsets, sizes


def _be(code: str, raw: bytes) -> array:
    a = array(code, raw)
    if sys.byteorder == "little":
        a.byteswap()
    return a


def samples(path: Path) -> dict[str, tuple[array, array]]:
    """Samples of the video ("vide") and sound ("soun") tracks of a file."""
    moov = _top_moov(path)
    found = {}
    for kind, s, e in _boxes(moov, 8, len(moov)):
        if kind != b"trak":
            continue
        mdia = next((s2, e2) for k2, s2, e2 in _boxes(moov, s, e) if k2 == b"mdia")
        handler = stbl = None
        for k3, s3, e3 in _boxes(moov, *mdia):
            if k3 == b"hdlr":
                handler = moov[s3 + 8:s3 + 12].decode()
            elif k3 == b"minf":
                stbl = next(moov[s4:e4] for k4, s4, e4 in _boxes(moov, s3, e3) if k4 == b"stbl")
        if handler in ("vide", "soun") and handler not in found:
            found[handler] = _track_samples(stbl)
    return found


HEAD, SOUND = 0, 1  # piece kinds; 2 + n = video source n


class _Pieces:
    """The map being written: kind, source offset and length of each piece,
    neighbours from the same place joined into one."""

    def __init__(self, out, literal):
        self.kind, self.off, self.len = array("B"), array("d"), array("I")
        self.out, self.literal, self.lit_size = out, literal, 0

    def add(self, kind: int, off: int, size: int) -> None:
        if size <= 0:
            return
        if self.kind and self.kind[-1] == kind and self.off[-1] + self.len[-1] == off \
                and self.len[-1] + size < 1 << 32:
            self.len[-1] += size
        else:
            self.kind.append(kind)
            self.off.append(off)
            self.len.append(size)

    def own_bytes(self, data: bytes) -> None:
        """Bytes of the long file itself (header, index, inserted stream headers)."""
        self.literal.write(data)
        self.add(HEAD, self.lit_size, len(data))
        self.lit_size += len(data)

    def gap(self, start: int, end: int) -> None:
        if end > start:
            self.out.seek(start)
            self.own_bytes(self.out.read(end - start))

    def save(self, path: Path) -> None:
        """Count (uint32), kinds (bytes), padding to 8, offsets (float64), lengths (uint32), little-endian."""
        n = len(self.kind)
        off, ln = array("d", self.off), array("I", self.len)
        if sys.byteorder == "big":
            off.byteswap()
            ln.byteswap()
        head = struct.pack("<I", n) + self.kind.tobytes()
        head += b"\0" * (-len(head) % 8)
        path.write_bytes(head + off.tobytes() + ln.tobytes())


def build_map(output: Path, video_parts: list[Path], repeat: Path, audio: Path,
              literal: Path, map_file: Path) -> None:
    """Describe `output` as pieces of the video sources (the parts, then the
    loop repeated), of the sound file and of the file's own bytes (saved to
    `literal`). Writes map_file (JSON: size, source names) and its .bin pieces."""
    out_s = samples(output)
    sources = [*video_parts, repeat]
    src_v = [samples(p)["vide"] for p in sources]
    a_off, a_size = samples(audio)["soun"]
    v_off, v_size = out_s["vide"]
    o_aoff, o_asize = out_s["soun"]
    if len(o_aoff) > len(a_off):
        raise ValueError("Звука в длинном видео больше, чем в звуковом файле")
    order = [(i, j) for i, (offs, _) in enumerate(src_v[:-1]) for j in range(len(offs))]
    loop_n = len(src_v[-1][0])

    def video_source(k: int) -> tuple[int, int, int]:
        n, j = order[k] if k < len(order) else (len(sources) - 1, (k - len(order)) % loop_n)
        return n, src_v[n][0][j], src_v[n][1][j]

    handles = [p.open("rb") for p in sources]
    total = output.stat().st_size
    with output.open("rb") as out, literal.open("wb") as lit:
        pieces, pos, k, j = _Pieces(out, lit), 0, 0, 0
        while k < len(v_off) or j < len(o_aoff):
            if j >= len(o_aoff) or (k < len(v_off) and v_off[k] < o_aoff[j]):
                off, size = v_off[k], v_size[k]
                n, soff, ssize = video_source(k)
                pieces.gap(pos, off)
                if size == ssize:
                    pieces.add(2 + n, soff, size)
                else:
                    _changed_frame(out, handles[n], off, size, soff, ssize, n, pieces)
                k += 1
            else:
                off, size = o_aoff[j], o_asize[j]
                if size != a_size[j]:
                    raise ValueError("Звук в длинном видео не совпал со звуковым файлом")
                pieces.gap(pos, off)
                pieces.add(SOUND, a_off[j], size)
                j += 1
            pos = off + size
        pieces.gap(pos, total)
    for h in handles:
        h.close()
    pieces.save(map_file.with_suffix(".bin"))
    kit = [literal, audio, *sources, map_file.with_suffix(".bin")]
    map_file.write_text(json.dumps({"size": total, "sources": [p.name for p in sources],
                                    "sound": audio.name, "head": literal.name,
                                    "bytes": {p.name: p.stat().st_size for p in kit}}))
    _spot_check(output, pieces, sources, audio, literal)


def _changed_frame(out, src, off, size, soff, ssize, n, pieces: _Pieces) -> None:
    """The muxer puts the stream headers (SPS/PPS) into each key frame: the
    frame is the loop's frame with a few bytes inserted."""
    out.seek(off)
    a = out.read(size)
    src.seek(soff)
    b = src.read(ssize)
    cut = next((i for i in range(len(b)) if a[i] != b[i]), len(b))
    extra = size - ssize
    if extra < 0 or a[cut + extra:] != b[cut:]:
        raise ValueError("Кадры в длинном видео не совпали с петлёй")
    pieces.add(2 + n, soff, cut)
    pieces.own_bytes(a[cut:cut + extra])
    pieces.add(2 + n, soff + cut, ssize - cut)


def _spot_check(output: Path, pieces: _Pieces, sources: list[Path], audio: Path, literal: Path) -> None:
    """Compare a few hundred random pieces with the real file."""
    files = [literal.open("rb"), audio.open("rb"), *(p.open("rb") for p in sources)]
    try:
        starts, pos = array("Q"), 0
        for ln in pieces.len:
            starts.append(pos)
            pos += ln
        if pos != output.stat().st_size:
            raise ValueError("Карта сборки не совпала с видео по размеру")
        with output.open("rb") as out:
            for i in random.sample(range(len(starts)), min(300, len(starts))):
                length = min(pieces.len[i], 1 << 16)
                src = files[pieces.kind[i]]
                src.seek(int(pieces.off[i]))
                out.seek(starts[i])
                if src.read(length) != out.read(length):
                    raise ValueError("Карта сборки не совпала с видео")
    finally:
        for f in files:
            f.close()
