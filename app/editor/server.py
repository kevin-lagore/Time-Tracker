"""FastAPI editor server for work log entries."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db
from app.log_setup import get_logger
from app.models import LogEntry, LogEntryEdit
from app.toggl_cache import get_project_client_list, refresh_cache, get_cache
from app.context_picker import save_last_context
from app.models import LastContext

logger = get_logger("worklog.editor")

EDITOR_DIR = Path(__file__).parent
TEMPLATES_DIR = EDITOR_DIR / "templates"
STATIC_DIR = EDITOR_DIR / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Work Log Editor", docs_url=None, redoc_url=None)

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # --- Template filters ---
    def format_datetime(value):
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M")
        return str(value)

    def parse_json(value):
        if not value:
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []

    templates.env.filters["format_datetime"] = format_datetime
    templates.env.filters["parse_json"] = parse_json

    # ==================== LIST VIEW ====================

    @app.get("/", response_class=HTMLResponse)
    async def list_entries(
        request: Request,
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        client: Optional[str] = Query(None),
        project: Optional[str] = Query(None),
        tag: Optional[str] = Query(None),
        keyword: Optional[str] = Query(None),
        context_source: Optional[str] = Query(None),
        has_errors: Optional[str] = Query(None),
        page: int = Query(1, ge=1),
    ):
        per_page = 50
        offset = (page - 1) * per_page

        has_errors_bool = None
        if has_errors == "yes":
            has_errors_bool = True
        elif has_errors == "no":
            has_errors_bool = False

        entries = db.list_entries(
            date_from=date_from,
            date_to=date_to,
            client=client,
            project=project,
            tag=tag,
            keyword=keyword,
            context_source=context_source,
            has_errors=has_errors_bool,
            limit=per_page,
            offset=offset,
        )

        # Get unique clients/projects for filter dropdowns
        projects_list = get_project_client_list()
        clients = sorted(set(p["client_name"] for p in projects_list if p["client_name"]))
        projects = sorted(set(p["project_name"] for p in projects_list if p["project_name"]))

        return templates.TemplateResponse("list.html", {
            "request": request,
            "entries": entries,
            "filters": {
                "date_from": date_from or "",
                "date_to": date_to or "",
                "client": client or "",
                "project": project or "",
                "tag": tag or "",
                "keyword": keyword or "",
                "context_source": context_source or "",
                "has_errors": has_errors or "",
            },
            "clients": clients,
            "projects": projects,
            "page": page,
            "has_more": len(entries) == per_page,
            "tags_list": ["update", "decision", "blocker", "ask", "next"],
            "context_sources": ["toggl_current", "toggl_recent", "fallback_last", "fallback_prompt", "none"],
        })

    # ==================== DETAIL / EDIT ====================

    @app.get("/entry/{entry_id}", response_class=HTMLResponse)
    async def entry_detail(request: Request, entry_id: str):
        entry = db.get_entry(entry_id)
        if not entry:
            return HTMLResponse("<h1>Not found</h1>", status_code=404)

        edits = db.get_edits_for_entry(entry_id)
        projects_list = get_project_client_list()

        return templates.TemplateResponse("detail.html", {
            "request": request,
            "entry": entry,
            "edits": edits,
            "projects_list": projects_list,
            "tags_list": ["update", "decision", "blocker", "ask", "next"],
        })

    @app.post("/entry/{entry_id}/save")
    async def save_entry(
        request: Request,
        entry_id: str,
        transcript_raw: str = Form(""),
        cleaned_note: str = Form(""),
        toggl_project_id: str = Form(""),
        toggl_project_name: str = Form(""),
        toggl_client_name: str = Form(""),
        toggl_workspace_id: str = Form(""),
        tags: list[str] = Form([]),
        is_private: Optional[str] = Form(None),
    ):
        entry = db.get_entry(entry_id)
        if not entry:
            return HTMLResponse("<h1>Not found</h1>", status_code=404)

        # Track edits
        if transcript_raw != (entry.transcript_raw or ""):
            db.insert_edit(LogEntryEdit(
                log_entry_id=entry_id, field="transcript_raw",
                old_value=entry.transcript_raw, new_value=transcript_raw,
            ))
            entry.transcript_raw = transcript_raw

        if cleaned_note != (entry.cleaned_note or ""):
            db.insert_edit(LogEntryEdit(
                log_entry_id=entry_id, field="cleaned_note",
                old_value=entry.cleaned_note, new_value=cleaned_note,
            ))
            entry.cleaned_note = cleaned_note

        if toggl_project_name != (entry.toggl_project_name or ""):
            db.insert_edit(LogEntryEdit(
                log_entry_id=entry_id, field="toggl_project_name",
                old_value=entry.toggl_project_name, new_value=toggl_project_name,
            ))
            entry.toggl_project_id = toggl_project_id or None
            entry.toggl_project_name = toggl_project_name or None
            entry.toggl_client_name = toggl_client_name or None
            entry.toggl_workspace_id = toggl_workspace_id or None

        new_tags = json.dumps(tags)
        if new_tags != entry.tags_json:
            db.insert_edit(LogEntryEdit(
                log_entry_id=entry_id, field="tags_json",
                old_value=entry.tags_json, new_value=new_tags,
            ))
            entry.tags_json = new_tags

        new_private = is_private == "on"
        if new_private != entry.is_private:
            db.insert_edit(LogEntryEdit(
                log_entry_id=entry_id, field="is_private",
                old_value=str(entry.is_private), new_value=str(new_private),
            ))
            entry.is_private = new_private

        db.update_entry(entry)
        return RedirectResponse(f"/entry/{entry_id}?saved=1", status_code=303)

    # ==================== DELETE ====================

    @app.post("/entry/{entry_id}/delete")
    async def delete_entry(entry_id: str):
        db.delete_entry(entry_id)
        return RedirectResponse("/?deleted=1", status_code=303)

    # ==================== MERGE ====================

    @app.post("/merge")
    async def merge_entries(
        primary_id: str = Form(...),
        secondary_id: str = Form(...),
    ):
        primary = db.get_entry(primary_id)
        secondary = db.get_entry(secondary_id)
        if not primary or not secondary:
            return JSONResponse({"error": "Entry not found"}, status_code=404)

        # Append secondary text to primary
        sep = "\n\n---\n\n"
        if primary.transcript_raw and secondary.transcript_raw:
            primary.transcript_raw += sep + secondary.transcript_raw
        elif secondary.transcript_raw:
            primary.transcript_raw = secondary.transcript_raw

        if primary.cleaned_note and secondary.cleaned_note:
            primary.cleaned_note += sep + secondary.cleaned_note
        elif secondary.cleaned_note:
            primary.cleaned_note = secondary.cleaned_note

        # Merge tags
        primary_tags = set(primary.tags)
        primary_tags.update(secondary.tags)
        primary.tags = list(primary_tags)

        # Audit
        db.insert_edit(LogEntryEdit(
            log_entry_id=primary.id, field="merge",
            old_value=None, new_value=f"Merged with {secondary.id}",
        ))

        db.update_entry(primary)
        db.delete_entry(secondary.id)

        return RedirectResponse(f"/entry/{primary_id}?merged=1", status_code=303)

    # ==================== BULK OPERATIONS ====================

    @app.post("/bulk/reassign")
    async def bulk_reassign(
        entry_ids: str = Form(...),
        toggl_project_id: str = Form(""),
        toggl_project_name: str = Form(""),
        toggl_client_name: str = Form(""),
        toggl_workspace_id: str = Form(""),
        bulk_tags: list[str] = Form([]),
        bulk_is_private: Optional[str] = Form(None),
    ):
        ids = [i.strip() for i in entry_ids.split(",") if i.strip()]
        for eid in ids:
            entry = db.get_entry(eid)
            if not entry:
                continue

            if toggl_project_name:
                entry.toggl_project_id = toggl_project_id or None
                entry.toggl_project_name = toggl_project_name
                entry.toggl_client_name = toggl_client_name or None
                entry.toggl_workspace_id = toggl_workspace_id or None

            if bulk_tags:
                entry.tags = bulk_tags

            if bulk_is_private is not None:
                entry.is_private = bulk_is_private == "on"

            db.update_entry(entry)
            db.insert_edit(LogEntryEdit(
                log_entry_id=eid, field="bulk_reassign",
                old_value=None, new_value=f"project={toggl_project_name}, tags={bulk_tags}",
            ))

        return RedirectResponse("/?bulk=1", status_code=303)

    # ==================== RETRY ACTIONS ====================

    @app.post("/entry/{entry_id}/retry-transcribe")
    async def retry_transcribe(entry_id: str):
        entry = db.get_entry(entry_id)
        if not entry or not entry.audio_path:
            return JSONResponse({"error": "No audio file"}, status_code=400)

        try:
            from app.openai_stt import transcribe
            result = transcribe(entry.audio_path)
            old = entry.transcript_raw
            entry.transcript_raw = result["text"]
            entry.transcript_confidence = result.get("confidence")

            errors = json.loads(entry.error_json) if entry.error_json else {}
            errors.pop("transcription", None)
            entry.error_json = json.dumps(errors) if errors else None

            db.insert_edit(LogEntryEdit(
                log_entry_id=entry_id, field="transcript_raw",
                old_value=old, new_value=entry.transcript_raw,
            ))
            db.update_entry(entry)
            return RedirectResponse(f"/entry/{entry_id}?retried=1", status_code=303)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/entry/{entry_id}/retry-llm")
    async def retry_llm(entry_id: str):
        entry = db.get_entry(entry_id)
        if not entry or not entry.transcript_raw:
            return JSONResponse({"error": "No transcript"}, status_code=400)

        try:
            from app.llm_clean import clean_note
            llm_result = clean_note(
                transcript=entry.transcript_raw,
                client_name=entry.toggl_client_name,
                project_name=entry.toggl_project_name,
                timestamp=entry.created_at.isoformat(),
            )
            old = entry.cleaned_note
            entry.cleaned_note = llm_result.cleaned_note_md
            if llm_result.tags:
                entry.tags = llm_result.tags

            errors = json.loads(entry.error_json) if entry.error_json else {}
            errors.pop("llm_cleanup", None)
            entry.error_json = json.dumps(errors) if errors else None

            db.insert_edit(LogEntryEdit(
                log_entry_id=entry_id, field="cleaned_note",
                old_value=old, new_value=entry.cleaned_note,
            ))
            db.update_entry(entry)
            return RedirectResponse(f"/entry/{entry_id}?retried=1", status_code=303)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ==================== SET LAST CONTEXT ====================

    @app.post("/entry/{entry_id}/set-last-context")
    async def set_last_context(entry_id: str):
        entry = db.get_entry(entry_id)
        if not entry:
            return JSONResponse({"error": "Not found"}, status_code=404)

        ctx = LastContext(
            workspace_id=entry.toggl_workspace_id,
            client_name=entry.toggl_client_name,
            project_id=entry.toggl_project_id,
            project_name=entry.toggl_project_name,
        )
        save_last_context(ctx)
        return RedirectResponse(f"/entry/{entry_id}?context_set=1", status_code=303)

    # ==================== TOGGL CACHE ====================

    @app.post("/refresh-toggl")
    async def refresh_toggl_cache():
        try:
            result = refresh_cache()
            return RedirectResponse("/?toggl_refreshed=1", status_code=303)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ==================== API ENDPOINTS ====================

    @app.get("/api/projects")
    async def api_projects():
        return get_project_client_list()

    @app.get("/api/entries")
    async def api_entries(
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
    ):
        entries = db.list_entries(date_from=date_from, date_to=date_to, limit=limit)
        return [e.model_dump(mode="json") for e in entries]

    return app
