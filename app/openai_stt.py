"""OpenAI Speech-to-Text transcription."""

from __future__ import annotations

from pathlib import Path

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import get_openai_key, load_config
from app.log_setup import get_logger

logger = get_logger("worklog.openai_stt")


def _client() -> OpenAI:
    return OpenAI(api_key=get_openai_key())


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True,
)
def transcribe(audio_path: str | Path) -> dict:
    """
    Transcribe an audio file using OpenAI Whisper.

    Returns: {"text": str, "confidence": float|None}
    """
    cfg = load_config()["openai"]
    model = cfg["stt_model"]
    language = cfg.get("language") or None

    p = Path(audio_path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")

    logger.info("Transcribing %s with model=%s", p.name, model)

    client = _client()
    kwargs = {
        "model": model,
        "file": open(p, "rb"),
        "response_format": "verbose_json",
    }
    if language:
        kwargs["language"] = language

    try:
        result = client.audio.transcriptions.create(**kwargs)

        text = result.text if hasattr(result, "text") else str(result)
        # verbose_json may include avg_logprob for confidence estimate
        confidence = None
        if hasattr(result, "segments") and result.segments:
            logprobs = [s.avg_logprob for s in result.segments if hasattr(s, "avg_logprob") and s.avg_logprob is not None]
            if logprobs:
                import math
                avg_logprob = sum(logprobs) / len(logprobs)
                confidence = round(math.exp(avg_logprob), 4)

        logger.info("Transcription complete: %d chars, confidence=%s", len(text), confidence)
        return {"text": text.strip(), "confidence": confidence}

    except Exception as e:
        logger.error("Transcription failed: %s", e)
        raise
    finally:
        kwargs["file"].close()
