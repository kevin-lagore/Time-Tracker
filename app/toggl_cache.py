"""Toggl cache management: refresh and read cached workspaces/projects/clients."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from app import db
from app.config import load_config
from app.log_setup import get_logger
from app import toggl

logger = get_logger("worklog.toggl_cache")


def refresh_cache() -> dict:
    """Fetch all workspaces, projects, clients from Toggl and store in cache."""
    workspaces = toggl.get_workspaces()
    all_projects = []
    all_clients = []

    for ws in workspaces:
        ws_id = ws["id"]
        projects = toggl.get_projects(ws_id)
        clients = toggl.get_clients(ws_id)

        for p in projects:
            p["_workspace_id"] = ws_id
        for c in clients:
            c["_workspace_id"] = ws_id

        all_projects.extend(projects)
        all_clients.extend(clients)

    db.save_toggl_cache(workspaces, all_projects, all_clients)
    logger.info(
        "Refreshed Toggl cache: %d workspaces, %d projects, %d clients",
        len(workspaces), len(all_projects), len(all_clients),
    )
    return {"workspaces": workspaces, "projects": all_projects, "clients": all_clients}


def get_cache(auto_refresh: bool = True) -> Optional[dict]:
    """Get cached Toggl data. Auto-refresh if stale."""
    cache = db.get_toggl_cache()

    if cache and auto_refresh:
        cfg = load_config()
        ttl = cfg["toggl"]["cache_ttl_hours"]
        cached_at = datetime.fromisoformat(cache["cached_at"])
        if datetime.utcnow() - cached_at > timedelta(hours=ttl):
            logger.info("Toggl cache expired, refreshing...")
            try:
                return refresh_cache()
            except Exception as e:
                logger.warning("Failed to refresh Toggl cache: %s", e)
                return cache  # Return stale cache

    if not cache and auto_refresh:
        try:
            return refresh_cache()
        except Exception as e:
            logger.warning("Failed to initialize Toggl cache: %s", e)
            return None

    return cache


def get_cached_project_info(project_id) -> Optional[dict]:
    """Look up project name and client name from cache."""
    cache = get_cache(auto_refresh=False)
    if not cache:
        return None

    project_id = int(project_id) if project_id else None
    for p in cache.get("projects", []):
        if p.get("id") == project_id:
            client_name = None
            client_id = p.get("client_id")
            if client_id:
                for c in cache.get("clients", []):
                    if c.get("id") == client_id:
                        client_name = c.get("name")
                        break
            return {
                "project_name": p.get("name"),
                "client_name": client_name,
                "workspace_id": p.get("_workspace_id") or p.get("workspace_id"),
            }
    return None


def get_project_client_list() -> list[dict]:
    """Return a flat list of {project_id, project_name, client_name, workspace_id} for UI dropdowns."""
    cache = get_cache()
    if not cache:
        return []

    clients_map = {}
    for c in cache.get("clients", []):
        clients_map[c["id"]] = c.get("name", "")

    result = []
    for p in cache.get("projects", []):
        result.append({
            "project_id": str(p["id"]),
            "project_name": p.get("name", ""),
            "client_name": clients_map.get(p.get("client_id"), ""),
            "workspace_id": str(p.get("_workspace_id") or p.get("workspace_id", "")),
        })

    # Sort by client then project
    result.sort(key=lambda x: (x["client_name"].lower(), x["project_name"].lower()))
    return result
