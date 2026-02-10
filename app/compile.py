"""End-of-day / End-of-week compilation of log entries + Toggl time."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from openai import OpenAI

from app import db, toggl
from app.config import get_openai_key, load_config
from app.log_setup import get_logger
from app.toggl_cache import get_cached_project_info

logger = get_logger("worklog.compile")

COMPILE_SYSTEM = """You are a professional report compiler for a consultant.
You receive a set of structured work notes grouped by client, plus Toggl time totals.
Produce a clean Markdown report per client with these sections:
- ✅ Completed (things done)
- 🔜 Next (planned next steps)
- ⚠️ Risks/Blockers
- ❓ Asks (questions for the client)
- ⏱️ Time spent

Rules:
- Do NOT invent items not present in the notes.
- Deduplicate and merge similar bullets.
- Keep a neutral, professional tone.
- If a section has no items omit it.
- Time spent should reflect the provided Toggl totals.
- Output valid Markdown only."""

COMPILE_USER = """Period: {period}

{client_sections}

Produce the compiled Markdown report now."""


def _parse_week(week_str: str) -> tuple[str, str]:
    """Parse YYYY-WW into start and end dates."""
    year, week = week_str.split("-W") if "-W" in week_str else week_str.split("-")
    year, week = int(year), int(week)
    # ISO week: Monday of week 1
    jan4 = datetime(year, 1, 4)
    start_of_week1 = jan4 - timedelta(days=jan4.isoweekday() - 1)
    start = start_of_week1 + timedelta(weeks=week - 1)
    end = start + timedelta(days=6)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _format_duration(seconds: int) -> str:
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def _get_toggl_time_totals(start_date: str, end_date: str) -> dict[str, dict[str, int]]:
    """
    Get Toggl time totals grouped by client -> project.
    Returns: {client_name: {project_name: total_seconds}}
    """
    entries = toggl.get_time_entries_range(start_date, end_date)
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for entry in entries:
        duration = entry.get("duration", 0)
        if duration < 0:
            # Running entry: duration is negative (seconds since epoch start)
            continue

        project_id = entry.get("project_id")
        project_name = "Unassigned"
        client_name = "Unassigned"

        if project_id:
            info = get_cached_project_info(project_id)
            if info:
                project_name = info.get("project_name", "Unassigned")
                client_name = info.get("client_name") or "Unassigned"

        totals[client_name][project_name] += duration

    return dict(totals)


def compile_report(
    date: Optional[str] = None,
    week: Optional[str] = None,
    output_format: str = "md",
) -> str:
    """
    Compile a report for a date or week.

    Args:
        date: YYYY-MM-DD for a single day
        week: YYYY-WW for a week
        output_format: 'md' or 'html'

    Returns: Markdown or HTML string
    """
    if date:
        start_date = date
        end_date = date
        period_label = f"Day: {date}"
    elif week:
        start_date, end_date = _parse_week(week)
        period_label = f"Week {week} ({start_date} to {end_date})"
    else:
        raise ValueError("Must specify either date or week")

    # Get log entries (exclude private)
    entries = db.list_entries(
        date_from=start_date,
        date_to=end_date,
        include_private=False,
        limit=1000,
    )

    # Get Toggl time totals
    time_totals = _get_toggl_time_totals(start_date, end_date)

    # Group entries by client
    by_client: dict[str, list] = defaultdict(list)
    for e in entries:
        client = e.toggl_client_name or "Unassigned"
        by_client[client].append(e)

    # Also include clients from time totals that might not have log entries
    for client in time_totals:
        if client not in by_client:
            by_client[client] = []

    cfg = load_config()
    use_llm = cfg["features"]["llm_compile"]

    if use_llm and entries:
        report = _compile_with_llm(period_label, by_client, time_totals)
    else:
        report = _compile_manual(period_label, by_client, time_totals)

    if output_format == "html":
        report = _md_to_html(report)

    return report


def _compile_manual(
    period_label: str,
    by_client: dict[str, list],
    time_totals: dict[str, dict[str, int]],
) -> str:
    """Manual (non-LLM) compilation."""
    lines = [f"# Work Report — {period_label}\n"]

    for client in sorted(by_client.keys()):
        entries = by_client[client]
        lines.append(f"\n## {client}\n")

        if entries:
            # Collect notes
            updates = []
            blockers = []
            asks = []
            nexts = []

            for e in entries:
                note = e.cleaned_note or e.transcript_raw or ""
                tags = e.tags

                if "blocker" in tags:
                    blockers.append(note)
                elif "ask" in tags:
                    asks.append(note)
                elif "next" in tags:
                    nexts.append(note)
                else:
                    updates.append(note)

            if updates:
                lines.append("### ✅ Completed")
                for u in updates:
                    for line in u.strip().split("\n"):
                        ln = line.strip().lstrip("- ").strip()
                        if ln:
                            lines.append(f"- {ln}")
                lines.append("")

            if nexts:
                lines.append("### 🔜 Next")
                for n in nexts:
                    for line in n.strip().split("\n"):
                        ln = line.strip().lstrip("- ").strip()
                        if ln:
                            lines.append(f"- {ln}")
                lines.append("")

            if blockers:
                lines.append("### ⚠️ Risks/Blockers")
                for b in blockers:
                    for line in b.strip().split("\n"):
                        ln = line.strip().lstrip("- ").strip()
                        if ln:
                            lines.append(f"- {ln}")
                lines.append("")

            if asks:
                lines.append("### ❓ Asks")
                for a in asks:
                    for line in a.strip().split("\n"):
                        ln = line.strip().lstrip("- ").strip()
                        if ln:
                            lines.append(f"- {ln}")
                lines.append("")

        # Time
        client_time = time_totals.get(client, {})
        if client_time:
            lines.append("### ⏱️ Time Spent")
            total = 0
            for proj, secs in sorted(client_time.items()):
                lines.append(f"- {proj}: {_format_duration(secs)}")
                total += secs
            lines.append(f"- **Total: {_format_duration(total)}**")
            lines.append("")

    return "\n".join(lines)


def _compile_with_llm(
    period_label: str,
    by_client: dict[str, list],
    time_totals: dict[str, dict[str, int]],
) -> str:
    """LLM-assisted compilation."""
    # Build client sections for the prompt
    sections = []
    for client in sorted(by_client.keys()):
        entries = by_client[client]
        section_lines = [f"### Client: {client}"]

        section_lines.append("\nNotes:")
        if entries:
            for e in entries:
                note = e.cleaned_note or e.transcript_raw or "(empty)"
                tags = e.tags
                section_lines.append(f"- [{', '.join(tags) or 'update'}] {note}")
        else:
            section_lines.append("- (no notes)")

        client_time = time_totals.get(client, {})
        if client_time:
            section_lines.append("\nToggl Time:")
            for proj, secs in sorted(client_time.items()):
                section_lines.append(f"- {proj}: {_format_duration(secs)}")

        sections.append("\n".join(section_lines))

    prompt = COMPILE_USER.format(
        period=period_label,
        client_sections="\n\n".join(sections),
    )

    try:
        cfg = load_config()["openai"]
        oai = OpenAI(api_key=get_openai_key())
        response = oai.chat.completions.create(
            model=cfg["llm_model"],
            temperature=cfg["llm_temperature"],
            messages=[
                {"role": "system", "content": COMPILE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        result = response.choices[0].message.content
        logger.info("LLM compilation complete")
        return result
    except Exception as e:
        logger.error("LLM compilation failed, falling back to manual: %s", e)
        return _compile_manual(period_label, by_client, time_totals)


def _md_to_html(md: str) -> str:
    """Minimal markdown to HTML conversion."""
    html_lines = [
        "<!DOCTYPE html>",
        '<html><head><meta charset="utf-8">',
        "<title>Work Report</title>",
        '<style>body{font-family:Segoe UI,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6}'
        "h1{border-bottom:2px solid #333}h2{color:#2c5282;border-bottom:1px solid #e2e8f0}"
        "ul{margin:0.5em 0}li{margin:0.2em 0}</style>",
        "</head><body>",
    ]

    for line in md.split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("- **"):
            content = stripped[2:].strip("*")
            html_lines.append(f"<li><strong>{content}</strong></li>")
        elif stripped.startswith("- "):
            html_lines.append(f"<li>{stripped[2:]}</li>")
        elif stripped:
            html_lines.append(f"<p>{stripped}</p>")

    html_lines.append("</body></html>")
    return "\n".join(html_lines)
