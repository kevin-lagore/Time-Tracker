"""Pydantic models for the work log system."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    audio_path: Optional[str] = None
    audio_sha256: Optional[str] = None
    transcript_raw: Optional[str] = None
    transcript_confidence: Optional[float] = None
    cleaned_note: Optional[str] = None
    tags_json: str = "[]"
    is_private: bool = False
    context_source: str = "none"  # toggl_current|toggl_recent|fallback_last|fallback_prompt|none
    toggl_time_entry_id: Optional[str] = None
    toggl_project_id: Optional[str] = None
    toggl_project_name: Optional[str] = None
    toggl_client_name: Optional[str] = None
    toggl_workspace_id: Optional[str] = None
    capture_context_json: Optional[str] = None
    error_json: Optional[str] = None

    @property
    def tags(self) -> list[str]:
        try:
            return json.loads(self.tags_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @tags.setter
    def tags(self, value: list[str]):
        self.tags_json = json.dumps(value)

    @property
    def errors(self) -> dict | None:
        if not self.error_json:
            return None
        try:
            return json.loads(self.error_json)
        except (json.JSONDecodeError, TypeError):
            return None

    def display_note(self) -> str:
        """Return best available note text."""
        return self.cleaned_note or self.transcript_raw or "(no transcript)"


class LogEntryEdit(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    log_entry_id: str
    edited_at: datetime = Field(default_factory=datetime.utcnow)
    field: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None


class TogglContext(BaseModel):
    """Toggl context attached to a capture."""
    source: str = "none"
    time_entry_id: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    client_name: Optional[str] = None
    workspace_id: Optional[str] = None
    description: Optional[str] = None
    raw_entry: Optional[dict] = None


class UserState(BaseModel):
    key: str
    value_json: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LastContext(BaseModel):
    workspace_id: Optional[str] = None
    client_name: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None


class LLMCleanResult(BaseModel):
    cleaned_note_md: Optional[str] = None
    tags: list[str] = []
    suggested_client: Optional[str] = None
    suggested_project: Optional[str] = None
    risks_blockers: list[str] = []
    asks: list[str] = []
    next_steps: list[str] = []
