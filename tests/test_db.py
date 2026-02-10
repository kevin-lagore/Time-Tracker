"""Tests for the database layer."""

import json
import os
import tempfile
from datetime import datetime

import pytest

# Point to temp DB before importing
_tmpdir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test.db")

from app import db
from app.models import LogEntry, LogEntryEdit


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize a fresh DB for each test."""
    db.init_db()
    yield
    # Cleanup entries between tests (edits first due to FK)
    with db.get_connection() as conn:
        conn.execute("DELETE FROM log_entry_edits")
        conn.execute("DELETE FROM log_entries")
        conn.execute("DELETE FROM user_state")
        conn.execute("DELETE FROM toggl_cache")


class TestLogEntries:
    def test_insert_and_get(self):
        entry = LogEntry(
            transcript_raw="test note",
            toggl_client_name="Acme",
            toggl_project_name="Website",
            context_source="toggl_current",
        )
        db.insert_entry(entry)

        fetched = db.get_entry(entry.id)
        assert fetched is not None
        assert fetched.id == entry.id
        assert fetched.transcript_raw == "test note"
        assert fetched.toggl_client_name == "Acme"

    def test_update_entry(self):
        entry = LogEntry(transcript_raw="original")
        db.insert_entry(entry)

        entry.transcript_raw = "updated"
        entry.cleaned_note = "cleaned"
        db.update_entry(entry)

        fetched = db.get_entry(entry.id)
        assert fetched.transcript_raw == "updated"
        assert fetched.cleaned_note == "cleaned"

    def test_delete_entry(self):
        entry = LogEntry(transcript_raw="to delete")
        db.insert_entry(entry)
        assert db.get_entry(entry.id) is not None

        db.delete_entry(entry.id)
        assert db.get_entry(entry.id) is None

    def test_find_by_sha256(self):
        entry = LogEntry(audio_sha256="abc123", transcript_raw="test")
        db.insert_entry(entry)

        found = db.find_by_sha256("abc123")
        assert found is not None
        assert found.id == entry.id

        assert db.find_by_sha256("nonexistent") is None

    def test_list_entries_filters(self):
        e1 = LogEntry(
            transcript_raw="alpha note",
            toggl_client_name="ClientA",
            toggl_project_name="ProjA",
            context_source="toggl_current",
            tags_json='["update"]',
        )
        e2 = LogEntry(
            transcript_raw="beta note",
            toggl_client_name="ClientB",
            toggl_project_name="ProjB",
            context_source="fallback_prompt",
            is_private=True,
        )
        db.insert_entry(e1)
        db.insert_entry(e2)

        # Filter by client
        results = db.list_entries(client="ClientA")
        assert len(results) == 1
        assert results[0].toggl_client_name == "ClientA"

        # Filter by keyword
        results = db.list_entries(keyword="beta")
        assert len(results) == 1

        # Filter by context_source
        results = db.list_entries(context_source="fallback_prompt")
        assert len(results) == 1

        # Exclude private
        results = db.list_entries(include_private=False)
        assert len(results) == 1
        assert results[0].toggl_client_name == "ClientA"

        # Filter by tag
        results = db.list_entries(tag="update")
        assert len(results) == 1

    def test_idempotency(self):
        entry = LogEntry(audio_sha256="dup123", transcript_raw="first")
        db.insert_entry(entry)

        found = db.find_by_sha256("dup123")
        assert found is not None


class TestEdits:
    def test_insert_and_get_edits(self):
        entry = LogEntry(transcript_raw="original")
        db.insert_entry(entry)

        edit = LogEntryEdit(
            log_entry_id=entry.id,
            field="transcript_raw",
            old_value="original",
            new_value="edited",
        )
        db.insert_edit(edit)

        edits = db.get_edits_for_entry(entry.id)
        assert len(edits) == 1
        assert edits[0].field == "transcript_raw"
        assert edits[0].old_value == "original"
        assert edits[0].new_value == "edited"


class TestUserState:
    def test_get_set_user_state(self):
        assert db.get_user_state("test_key") is None

        db.set_user_state("test_key", '{"foo": "bar"}')
        result = db.get_user_state("test_key")
        assert result == '{"foo": "bar"}'

        # Update
        db.set_user_state("test_key", '{"foo": "baz"}')
        result = db.get_user_state("test_key")
        assert result == '{"foo": "baz"}'


class TestTogglCache:
    def test_save_and_get_cache(self):
        workspaces = [{"id": 1, "name": "WS1"}]
        projects = [{"id": 10, "name": "Proj1", "client_id": 100}]
        clients = [{"id": 100, "name": "Client1"}]

        db.save_toggl_cache(workspaces, projects, clients)

        cache = db.get_toggl_cache()
        assert cache is not None
        assert len(cache["workspaces"]) == 1
        assert cache["workspaces"][0]["name"] == "WS1"
        assert len(cache["projects"]) == 1
        assert len(cache["clients"]) == 1
