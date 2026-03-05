"""Typer CLI entry point for the work log system."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

import typer
from rich.console import Console
from rich.table import Table

from app import db
from app.audio import sha256_file, validate_audio
from app.config import load_config, get_toggl_token, get_openai_key, PROJECT_ROOT
from app.log_setup import get_logger, setup_logging
from app.models import LogEntry, LogEntryEdit, TogglContext
from app.toggl import resolve_context
from app.toggl_cache import refresh_cache as _refresh_toggl_cache

app = typer.Typer(name="worklog", help="Push-to-talk work log system.")
console = Console(highlight=False)
logger = get_logger("worklog.cli")

OK = "[green]OK[/green]"
FAIL = "[red]FAIL[/red]"
WARN = "[yellow]![/yellow]"


def _notify(title: str, message: str):
    """Show a Windows toast notification (best effort)."""
    try:
        # Use PowerShell for toast
        ps_script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] > $null; "
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            "$textNodes = $template.GetElementsByTagName('text'); "
            f"$textNodes.Item(0).AppendChild($template.CreateTextNode('{title}')); "
            f"$textNodes.Item(1).AppendChild($template.CreateTextNode('{message}')); "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('WorkLog').Show($toast)"
        )
        subprocess.Popen(
            ["powershell", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass  # Non-critical


@app.command()
def capture(
    audio: str = typer.Option(..., help="Path to audio file"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM cleanup"),
    force: bool = typer.Option(False, "--force", help="Force processing even if duplicate"),
    use_last_context: bool = typer.Option(False, "--use-last-context", help="Use last chosen context if Toggl missing"),
    prompt_context: bool = typer.Option(False, "--prompt-context", help="Force context picker popup"),
):
    """Capture a voice note: transcribe, clean, store."""
    setup_logging()
    db.init_db()

    try:
        audio_path = validate_audio(audio)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    audio_hash = sha256_file(audio_path)

    # Idempotency check
    if not force:
        existing = db.find_by_sha256(audio_hash)
        if existing:
            console.print(f"[yellow]Duplicate audio detected (entry {existing.id}). Use --force to reprocess.[/yellow]")
            raise typer.Exit(0)

    # Create entry shell
    entry = LogEntry(
        audio_path=str(audio_path.resolve()),
        audio_sha256=audio_hash,
    )
    errors: dict = {}

    # --- Resolve context ---
    ctx = TogglContext(source="none")

    if prompt_context:
        # Force popup
        ctx = _resolve_via_picker()
    else:
        # Try Toggl first
        try:
            ctx = resolve_context()
        except Exception as e:
            logger.warning("Toggl context resolution failed: %s", e)
            errors["toggl"] = str(e)

        # If no Toggl context, use fallback
        if ctx.source == "none":
            if use_last_context:
                ctx = _resolve_via_last()
            else:
                ctx = _resolve_via_picker()

    _apply_context(entry, ctx)

    # --- Transcribe ---
    try:
        from app.openai_stt import transcribe
        result = transcribe(audio_path)
        entry.transcript_raw = result["text"]
        entry.transcript_confidence = result.get("confidence")
    except Exception as e:
        logger.error("Transcription failed: %s", e)
        errors["transcription"] = str(e)
        entry.transcript_raw = None

    # --- LLM cleanup ---
    cfg = load_config()
    if not no_llm and cfg["features"]["llm_cleanup"] and entry.transcript_raw:
        try:
            from app.llm_clean import clean_note
            llm_result = clean_note(
                transcript=entry.transcript_raw,
                client_name=entry.toggl_client_name,
                project_name=entry.toggl_project_name,
                timestamp=entry.created_at.isoformat(),
            )
            entry.cleaned_note = llm_result.cleaned_note_md
            if llm_result.tags:
                entry.tags = llm_result.tags
        except Exception as e:
            logger.error("LLM cleanup failed: %s", e)
            errors["llm_cleanup"] = str(e)

    # Store errors
    if errors:
        entry.error_json = json.dumps(errors)

    # Save
    db.insert_entry(entry)

    # Notification
    summary = (entry.transcript_raw or "(no transcript)")[:80]
    project = entry.toggl_project_name or "No project"
    client = entry.toggl_client_name or "No client"
    _notify("Work Log Captured", f"{client}/{project}: {summary}")

    console.print(f"[green]OK[/green] Captured: {client} / {project}")
    console.print(f"  ID: {entry.id}")
    console.print(f"  Context: {entry.context_source}")
    if entry.transcript_raw:
        console.print(f"  Transcript: {summary}...")
    if errors:
        console.print(f"  [yellow]Warnings: {', '.join(errors.keys())}[/yellow]")

    # Print status for AHK to parse
    print(f"STATUS:OK:{entry.id}")


def _resolve_via_last() -> TogglContext:
    """Use last stored context."""
    from app.context_picker import get_last_context
    last = get_last_context()
    if last and last.project_name:
        return TogglContext(
            source="fallback_last",
            project_id=last.project_id,
            project_name=last.project_name,
            client_name=last.client_name,
            workspace_id=last.workspace_id,
        )
    return TogglContext(source="none")


def _resolve_via_picker() -> TogglContext:
    """Show the context picker popup."""
    try:
        from app.context_picker import show_context_picker
        chosen = show_context_picker()
        if chosen and chosen.project_name:
            return TogglContext(
                source="fallback_prompt",
                project_id=chosen.project_id,
                project_name=chosen.project_name,
                client_name=chosen.client_name,
                workspace_id=chosen.workspace_id,
            )
    except Exception as e:
        logger.warning("Context picker failed: %s", e)
    return TogglContext(source="none")


def _apply_context(entry: LogEntry, ctx: TogglContext):
    """Apply Toggl context to a log entry."""
    entry.context_source = ctx.source
    entry.toggl_time_entry_id = ctx.time_entry_id
    entry.toggl_project_id = ctx.project_id
    entry.toggl_project_name = ctx.project_name
    entry.toggl_client_name = ctx.client_name
    entry.toggl_workspace_id = ctx.workspace_id
    if ctx.raw_entry:
        entry.capture_context_json = json.dumps(ctx.raw_entry, default=str)


def _reprocess_entry(entry: LogEntry) -> bool:
    """Reprocess a single entry with errors. Returns True if anything was fixed."""
    errors = json.loads(entry.error_json) if entry.error_json else {}
    if not errors:
        return False

    fixed = False
    cfg = load_config()

    # Re-transcribe if needed
    if entry.audio_path and (not entry.transcript_raw or "transcription" in errors):
        try:
            from app.openai_stt import transcribe
            result = transcribe(entry.audio_path)
            entry.transcript_raw = result["text"]
            entry.transcript_confidence = result.get("confidence")
            errors.pop("transcription", None)
            fixed = True
            logger.info("Reprocessed transcription for %s", entry.id)
        except Exception as e:
            errors["transcription"] = str(e)

    # Re-clean if needed
    if cfg["features"]["llm_cleanup"] and entry.transcript_raw and (not entry.cleaned_note or "llm_cleanup" in errors):
        try:
            from app.llm_clean import clean_note
            llm_result = clean_note(
                transcript=entry.transcript_raw,
                client_name=entry.toggl_client_name,
                project_name=entry.toggl_project_name,
                timestamp=entry.created_at.isoformat(),
            )
            entry.cleaned_note = llm_result.cleaned_note_md
            if llm_result.tags:
                entry.tags = llm_result.tags
            errors.pop("llm_cleanup", None)
            fixed = True
            logger.info("Reprocessed LLM cleanup for %s", entry.id)
        except Exception as e:
            errors["llm_cleanup"] = str(e)

    entry.error_json = json.dumps(errors) if errors else None
    db.update_entry(entry)
    return fixed


def _reprocess_errors(date_from: str, date_to: str):
    """Find and reprocess all entries with errors in the date range."""
    errored = db.list_entries(date_from=date_from, date_to=date_to, has_errors=True, limit=1000)
    if not errored:
        return

    console.print(f"[yellow]Found {len(errored)} entries with errors, reprocessing...[/yellow]")
    fixed = sum(1 for e in errored if _reprocess_entry(e))
    if fixed:
        console.print(f"[green]OK[/green] Fixed {fixed}/{len(errored)} entries")
    else:
        console.print(f"[dim]Could not fix any entries (still offline?)[/dim]")


@app.command("compile")
def compile_cmd(
    date: Optional[str] = typer.Option(None, help="Date YYYY-MM-DD"),
    week: Optional[str] = typer.Option(None, help="Week YYYY-WW"),
    out: Optional[str] = typer.Option(None, help="Output file path"),
    format: str = typer.Option("md", help="Output format: md or html"),
):
    """Compile end-of-day or end-of-week report."""
    setup_logging()
    db.init_db()

    if not date and not week:
        date = datetime.now().strftime("%Y-%m-%d")
        console.print(f"[dim]No date/week specified, using today: {date}[/dim]")

    # Determine date range and reprocess any errored entries first
    if date:
        _reprocess_errors(date, date)
    elif week:
        from app.compile import _parse_week
        wk_start, wk_end = _parse_week(week)
        _reprocess_errors(wk_start, wk_end)

    from app.compile import compile_report
    report = compile_report(date=date, week=week, output_format=format)

    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(report, encoding="utf-8")
        console.print(f"[green]OK[/green] Report written to {out}")
    else:
        console.print(report)


@app.command()
def editor():
    """Start the local web editor."""
    setup_logging()
    db.init_db()

    cfg = load_config()["editor"]
    console.print(f"Starting editor at http://{cfg['host']}:{cfg['port']}")

    import uvicorn
    from app.editor.server import create_app
    uvicorn.run(create_app(), host=cfg["host"], port=cfg["port"], log_level="info")


@app.command("refresh-toggl")
def refresh_toggl():
    """Refresh the Toggl cache (workspaces, projects, clients)."""
    setup_logging()
    db.init_db()

    console.print("Refreshing Toggl cache...")
    result = _refresh_toggl_cache()
    console.print(
        f"[green]OK[/green] Cached: "
        f"{len(result['workspaces'])} workspaces, "
        f"{len(result['projects'])} projects, "
        f"{len(result['clients'])} clients"
    )


@app.command()
def reprocess(
    id: str = typer.Option(..., help="Log entry UUID"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM cleanup"),
):
    """Retry transcription and/or LLM cleanup for an entry."""
    setup_logging()
    db.init_db()

    entry = db.get_entry(id)
    if not entry:
        console.print(f"[red]Entry not found: {id}[/red]")
        raise typer.Exit(1)

    errors: dict = json.loads(entry.error_json) if entry.error_json else {}

    # Re-transcribe if needed
    if entry.audio_path and (not entry.transcript_raw or "transcription" in errors):
        try:
            from app.openai_stt import transcribe
            result = transcribe(entry.audio_path)
            old = entry.transcript_raw
            entry.transcript_raw = result["text"]
            entry.transcript_confidence = result.get("confidence")
            errors.pop("transcription", None)

            db.insert_edit(LogEntryEdit(
                log_entry_id=entry.id,
                field="transcript_raw",
                old_value=old,
                new_value=entry.transcript_raw,
            ))
            console.print("[green]OK[/green] Transcription updated")
        except Exception as e:
            errors["transcription"] = str(e)
            console.print(f"[red]Transcription failed: {e}[/red]")

    # Re-clean if needed
    cfg = load_config()
    if not no_llm and cfg["features"]["llm_cleanup"] and entry.transcript_raw:
        try:
            from app.llm_clean import clean_note
            llm_result = clean_note(
                transcript=entry.transcript_raw,
                client_name=entry.toggl_client_name,
                project_name=entry.toggl_project_name,
                timestamp=entry.created_at.isoformat(),
            )
            old_note = entry.cleaned_note
            old_tags = entry.tags_json
            entry.cleaned_note = llm_result.cleaned_note_md
            if llm_result.tags:
                entry.tags = llm_result.tags
            errors.pop("llm_cleanup", None)

            db.insert_edit(LogEntryEdit(
                log_entry_id=entry.id, field="cleaned_note",
                old_value=old_note, new_value=entry.cleaned_note,
            ))
            console.print("[green]OK[/green] LLM cleanup updated")
        except Exception as e:
            errors["llm_cleanup"] = str(e)
            console.print(f"[red]LLM cleanup failed: {e}[/red]")

    entry.error_json = json.dumps(errors) if errors else None
    db.update_entry(entry)
    console.print(f"[green]OK[/green] Entry {id} reprocessed")


@app.command()
def export(
    format: str = typer.Option("json", help="Export format: csv or json"),
    date: Optional[str] = typer.Option(None, help="Date YYYY-MM-DD"),
    week: Optional[str] = typer.Option(None, help="Week YYYY-WW"),
    out: Optional[str] = typer.Option(None, help="Output file path"),
):
    """Export log entries as CSV or JSON."""
    setup_logging()
    db.init_db()

    date_from = None
    date_to = None

    if date:
        date_from = date
        date_to = date
    elif week:
        from app.compile import _parse_week
        date_from, date_to = _parse_week(week)

    entries = db.list_entries(date_from=date_from, date_to=date_to, limit=10000)

    if format == "json":
        data = [e.model_dump(mode="json") for e in entries]
        output = json.dumps(data, indent=2, default=str)
    elif format == "csv":
        import csv
        import io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "id", "created_at", "client", "project", "context_source",
            "transcript_raw", "cleaned_note", "tags", "is_private",
        ])
        for e in entries:
            writer.writerow([
                e.id, e.created_at.isoformat(), e.toggl_client_name,
                e.toggl_project_name, e.context_source, e.transcript_raw,
                e.cleaned_note, e.tags_json, e.is_private,
            ])
        output = buf.getvalue()
    else:
        console.print(f"[red]Unknown format: {format}[/red]")
        raise typer.Exit(1)

    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(output, encoding="utf-8")
        console.print(f"[green]OK[/green] Exported {len(entries)} entries to {out}")
    else:
        console.print(output)


@app.command()
def dictate(
    audio: str = typer.Option(..., help="Path to audio file"),
):
    """Transcribe audio locally and print to stdout (for clipboard use)."""
    setup_logging()

    try:
        audio_path = validate_audio(audio)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}", stderr=True)
        raise typer.Exit(1)

    try:
        from app.local_stt import transcribe_local
        text = transcribe_local(audio_path)
        if text:
            print(text)
        else:
            print("(no speech detected)", file=sys.stderr)
            raise typer.Exit(1)
    except Exception as e:
        print(f"Transcription failed: {e}", file=sys.stderr)
        raise typer.Exit(1)


@app.command()
def doctor():
    """Run sanity checks for the system."""
    setup_logging()
    console.print("[bold]Work Log Doctor[/bold]\n")
    all_ok = True

    # Check .env
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        console.print("[green]OK[/green] .env file found")
    else:
        console.print("[red]FAIL[/red] .env file not found (copy .env.example to .env)")
        all_ok = False

    # Check config.yaml
    cfg_path = PROJECT_ROOT / "config.yaml"
    if cfg_path.exists():
        console.print("[green]OK[/green] config.yaml found")
    else:
        console.print("[yellow]![/yellow] config.yaml not found (using defaults)")

    # Check ffmpeg
    if shutil.which("ffmpeg"):
        console.print("[green]OK[/green] ffmpeg found in PATH")
    else:
        console.print("[red]FAIL[/red] ffmpeg not found in PATH (needed for audio recording)")
        all_ok = False

    # Check Toggl token
    try:
        token = get_toggl_token()
        console.print("[green]OK[/green] TOGGL_API_TOKEN set")
        # Test connectivity
        from app.toggl import get_workspaces
        ws = get_workspaces()
        if ws:
            console.print(f"[green]OK[/green] Toggl connected ({len(ws)} workspace(s))")
        else:
            console.print("[yellow]![/yellow] Toggl returned no workspaces")
    except Exception as e:
        console.print(f"[red]FAIL[/red] Toggl: {e}")
        all_ok = False

    # Check OpenAI key
    try:
        get_openai_key()
        console.print("[green]OK[/green] OPENAI_API_KEY set")
    except Exception as e:
        console.print(f"[red]FAIL[/red] OpenAI: {e}")
        all_ok = False

    # Check DB
    try:
        db.init_db()
        console.print("[green]OK[/green] Database initialized")
    except Exception as e:
        console.print(f"[red]FAIL[/red] Database: {e}")
        all_ok = False

    # Check audio dir
    cfg = load_config()
    audio_dir = Path(cfg["audio"]["dir"])
    audio_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]OK[/green] Audio directory: {audio_dir}")

    if all_ok:
        console.print("\n[green bold]All checks passed![/green bold]")
    else:
        console.print("\n[red bold]Some checks failed. Fix the issues above.[/red bold]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
