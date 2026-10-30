"""Speech to text for voice comments from the Telegram bot (Russian), on the
server's CPU with faster-whisper. The model is downloaded once into the data
folder (it survives updates) and loaded only while there is something to
transcribe, so it does not hold memory the renders need."""
from __future__ import annotations

import gc
import os
import subprocess
from pathlib import Path

import numpy as np

MODEL = os.environ.get("RELAX_WHISPER_MODEL", "small")  # small: good Russian, ~0.5 GB RAM in int8


def transcribe(paths: list[Path], models: Path, language: str = "ru") -> list[str]:
    from faster_whisper import WhisperModel  # heavy import: only when needed

    model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=1,
                         download_root=str(models))
    try:
        out = []
        for p in paths:
            segments, _ = model.transcribe(load(p), language=language, beam_size=1, vad_filter=True)
            out.append(" ".join(s.text.strip() for s in segments).strip())
        return out
    finally:
        del model
        gc.collect()


def load(path: Path) -> np.ndarray:
    """16 kHz mono float samples, decoded by ffmpeg (Telegram voice is OGG/Opus).
    Not faster-whisper's own decoder: it breaks with newer PyAV versions."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
