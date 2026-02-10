"""Toggl Track API v9 client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import get_toggl_token, load_config
from app.log_setup import get_logger
from app.models import TogglContext

logger = get_logger("worklog.toggl")

BASE_URL = "https://api.track.toggl.com/api/v9"


def _auth() -> tuple[str, str]:
    return (get_toggl_token(), "api_token")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    reraise=True,
)
def _get(path: str, params: dict | None = None) -> httpx.Response:
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{BASE_URL}{path}", auth=_auth(), params=params)
        resp.raise_for_status()
        return resp


def get_current_entry() -> Optional[dict]:
    """GET /me/time_entries/current - returns the running time entry or None."""
    try:
        resp = _get("/me/time_entries/current")
        data = resp.json()
        if data is None:
            return None
        return data
    except Exception as e:
        logger.warning("Failed to get current Toggl entry: %s", e)
        return None


def get_recent_entries(minutes: int | None = None) -> list[dict]:
    """Get time entries from the last N minutes."""
    if minutes is None:
        cfg = load_config()
        minutes = cfg["toggl"]["recent_window_minutes"]

    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes)

    try:
        resp = _get("/me/time_entries", params={
            "start_date": start.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "end_date": now.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        })
        entries = resp.json()
        if not isinstance(entries, list):
            return []
        # Sort by start time descending
        entries.sort(key=lambda e: e.get("start", ""), reverse=True)
        return entries
    except Exception as e:
        logger.warning("Failed to get recent Toggl entries: %s", e)
        return []


def get_workspaces() -> list[dict]:
    try:
        resp = _get("/me/workspaces")
        return resp.json()
    except Exception as e:
        logger.warning("Failed to get Toggl workspaces: %s", e)
        return []


def get_projects(workspace_id: int) -> list[dict]:
    try:
        resp = _get(f"/workspaces/{workspace_id}/projects", params={"active": "true"})
        return resp.json() or []
    except Exception as e:
        logger.warning("Failed to get Toggl projects: %s", e)
        return []


def get_clients(workspace_id: int) -> list[dict]:
    try:
        resp = _get(f"/workspaces/{workspace_id}/clients")
        return resp.json() or []
    except Exception as e:
        logger.warning("Failed to get Toggl clients: %s", e)
        return []


def get_time_entries_range(start_date: str, end_date: str) -> list[dict]:
    """Get time entries for a date range. Dates as YYYY-MM-DD."""
    try:
        resp = _get("/me/time_entries", params={
            "start_date": f"{start_date}T00:00:00+00:00",
            "end_date": f"{end_date}T23:59:59+00:00",
        })
        return resp.json() or []
    except Exception as e:
        logger.warning("Failed to get Toggl entries for range: %s", e)
        return []


def resolve_context() -> TogglContext:
    """Determine Toggl context: current running entry or most recent."""
    # Try current entry
    current = get_current_entry()
    if current and current.get("id"):
        return _entry_to_context(current, "toggl_current")

    # Try recent
    recent = get_recent_entries()
    if recent:
        return _entry_to_context(recent[0], "toggl_recent")

    return TogglContext(source="none")


def _entry_to_context(entry: dict, source: str) -> TogglContext:
    """Convert a Toggl time entry dict to a TogglContext."""
    project_id = entry.get("project_id")
    project_name = None
    client_name = None
    workspace_id = entry.get("workspace_id")

    # Try to resolve project/client names from cache
    from app.toggl_cache import get_cached_project_info
    if project_id:
        info = get_cached_project_info(project_id)
        if info:
            project_name = info.get("project_name")
            client_name = info.get("client_name")

    return TogglContext(
        source=source,
        time_entry_id=str(entry.get("id", "")),
        project_id=str(project_id) if project_id else None,
        project_name=project_name,
        client_name=client_name,
        workspace_id=str(workspace_id) if workspace_id else None,
        description=entry.get("description"),
        raw_entry=entry,
    )
