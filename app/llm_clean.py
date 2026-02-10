"""LLM-based note cleanup and tagging."""

from __future__ import annotations

import json
from typing import Optional

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import get_openai_key, load_config
from app.log_setup import get_logger
from app.models import LLMCleanResult

logger = get_logger("worklog.llm_clean")

CLEAN_NOTE_SYSTEM = """You are a structured note assistant for a consultant's work log.
You receive a raw voice transcript and optionally some context (project, client, timestamp).
Your job is to clean and structure the note. Output ONLY valid JSON, no other text.

Output schema:
{
  "cleaned_note_md": "string - clean markdown bullets summarizing the note",
  "tags": ["array of tags from: update, decision, blocker, ask, next"],
  "suggested_client": "string or null - only if clearly mentioned",
  "suggested_project": "string or null - only if clearly mentioned",
  "risks_blockers": ["array of risk/blocker strings, empty if none"],
  "asks": ["array of ask/question strings, empty if none"],
  "next_steps": ["array of next-step strings, empty if none"]
}

Rules:
- Do NOT invent information not present in the transcript.
- Keep cleaned_note_md concise: prefer bullet points.
- If anything is unclear, leave the field null or empty array.
- Tags must only be from: update, decision, blocker, ask, next.
- Never hallucinate client or project names; only suggest if explicitly said."""

CLEAN_NOTE_USER = """Timestamp: {timestamp}
Toggl context: client="{client}", project="{project}"
Raw transcript:
---
{transcript}
---

Output the structured JSON now."""


def _client() -> OpenAI:
    return OpenAI(api_key=get_openai_key())


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True,
)
def clean_note(
    transcript: str,
    client_name: Optional[str] = None,
    project_name: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> LLMCleanResult:
    """Clean and structure a transcript using LLM."""
    cfg = load_config()["openai"]

    prompt = CLEAN_NOTE_USER.format(
        timestamp=timestamp or "unknown",
        client=client_name or "unknown",
        project=project_name or "unknown",
        transcript=transcript,
    )

    logger.info("Running LLM cleanup (model=%s)", cfg["llm_model"])

    oai = _client()
    response = oai.chat.completions.create(
        model=cfg["llm_model"],
        temperature=cfg["llm_temperature"],
        messages=[
            {"role": "system", "content": CLEAN_NOTE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("LLM returned invalid JSON: %s", raw[:200])
        return LLMCleanResult()

    result = LLMCleanResult(
        cleaned_note_md=data.get("cleaned_note_md"),
        tags=[t for t in data.get("tags", []) if t in ("update", "decision", "blocker", "ask", "next")],
        suggested_client=data.get("suggested_client"),
        suggested_project=data.get("suggested_project"),
        risks_blockers=data.get("risks_blockers", []),
        asks=data.get("asks", []),
        next_steps=data.get("next_steps", []),
    )

    logger.info("LLM cleanup complete: tags=%s", result.tags)
    return result
