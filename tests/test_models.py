"""Tests for pydantic models."""

import json
from app.models import LogEntry, TogglContext, LLMCleanResult, LastContext


class TestLogEntry:
    def test_defaults(self):
        entry = LogEntry()
        assert entry.id is not None
        assert entry.tags == []
        assert entry.is_private is False
        assert entry.context_source == "none"

    def test_tags_property(self):
        entry = LogEntry()
        entry.tags = ["update", "blocker"]
        assert entry.tags_json == '["update", "blocker"]'
        assert entry.tags == ["update", "blocker"]

    def test_display_note(self):
        entry = LogEntry()
        assert entry.display_note() == "(no transcript)"

        entry.transcript_raw = "raw text"
        assert entry.display_note() == "raw text"

        entry.cleaned_note = "clean text"
        assert entry.display_note() == "clean text"

    def test_errors_property(self):
        entry = LogEntry()
        assert entry.errors is None

        entry.error_json = json.dumps({"transcription": "failed"})
        assert entry.errors == {"transcription": "failed"}


class TestTogglContext:
    def test_defaults(self):
        ctx = TogglContext()
        assert ctx.source == "none"
        assert ctx.project_name is None


class TestLLMCleanResult:
    def test_defaults(self):
        result = LLMCleanResult()
        assert result.tags == []
        assert result.cleaned_note_md is None


class TestLastContext:
    def test_serialization(self):
        ctx = LastContext(
            workspace_id="123",
            client_name="Acme",
            project_id="456",
            project_name="Website",
        )
        data = json.loads(ctx.model_dump_json())
        assert data["client_name"] == "Acme"

        restored = LastContext(**data)
        assert restored.project_name == "Website"
