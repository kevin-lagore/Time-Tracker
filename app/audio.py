"""Audio file utilities: hashing, path management."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import load_config
from app.log_setup import get_logger

logger = get_logger("worklog.audio")


def audio_dir() -> Path:
    cfg = load_config()
    d = Path(cfg["audio"]["dir"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def sha256_file(path: str | Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_audio(path: str | Path) -> Path:
    """Validate that an audio file exists and is non-empty."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")
    if p.stat().st_size == 0:
        raise ValueError(f"Audio file is empty: {p}")
    return p
