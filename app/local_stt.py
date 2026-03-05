"""Local speech-to-text using faster-whisper (no API calls)."""

from __future__ import annotations

from pathlib import Path

from app.config import load_config
from app.log_setup import get_logger

logger = get_logger("worklog.local_stt")

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        cfg = load_config()["faster_whisper"]
        model_size = cfg["model_size"]
        device = cfg["device"]
        compute_type = cfg["compute_type"]

        logger.info("Loading faster-whisper model=%s device=%s", model_size, device)
        _model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info("Model loaded")
    return _model


def transcribe_local(audio_path: str | Path) -> str:
    """Transcribe an audio file locally. Returns plain text."""
    p = Path(audio_path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")

    cfg = load_config()
    language = cfg["openai"].get("language") or None

    model = _get_model()
    kwargs = {"beam_size": 5}
    if language:
        kwargs["language"] = language

    segments, _info = model.transcribe(str(p), **kwargs)
    text = " ".join(seg.text.strip() for seg in segments)

    logger.info("Local transcription: %d chars", len(text))
    return text.strip()
