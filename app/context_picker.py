"""Quick Capture Fallback: keyboard-first popup to select client/project."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from typing import Optional

from app import db
from app.log_setup import get_logger
from app.models import LastContext
from app.toggl_cache import get_project_client_list

logger = get_logger("worklog.context_picker")


def get_last_context() -> Optional[LastContext]:
    """Retrieve the last-used context from user_state."""
    raw = db.get_user_state("last_context")
    if raw:
        try:
            data = json.loads(raw)
            return LastContext(**data)
        except Exception:
            pass
    return None


def save_last_context(ctx: LastContext):
    """Save selected context as last-used."""
    db.set_user_state("last_context", ctx.model_dump_json())
    logger.info("Saved last context: %s / %s", ctx.client_name, ctx.project_name)


def show_context_picker() -> Optional[LastContext]:
    """
    Show a small tkinter popup for selecting client/project.
    Returns LastContext or None if cancelled.
    """
    projects = get_project_client_list()
    last = get_last_context()
    result: list[Optional[LastContext]] = [None]

    root = tk.Tk()
    root.title("Select Client / Project")
    root.geometry("420x380")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    # Center on screen
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - 210
    y = (root.winfo_screenheight() // 2) - 190
    root.geometry(f"+{x}+{y}")

    frame = ttk.Frame(root, padding=10)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Type to filter, Enter to select, Esc to cancel", font=("Segoe UI", 9)).pack(anchor=tk.W)

    # Search
    search_var = tk.StringVar()
    search_entry = ttk.Entry(frame, textvariable=search_var, font=("Segoe UI", 11))
    search_entry.pack(fill=tk.X, pady=(5, 5))

    # Listbox with scrollbar
    list_frame = ttk.Frame(frame)
    list_frame.pack(fill=tk.BOTH, expand=True)

    scrollbar = ttk.Scrollbar(list_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    listbox = tk.Listbox(list_frame, font=("Segoe UI", 10), yscrollcommand=scrollbar.set, selectmode=tk.SINGLE)
    listbox.pack(fill=tk.BOTH, expand=True)
    scrollbar.config(command=listbox.yview)

    # Build display items
    display_items: list[dict] = []

    # Add "Use last chosen" if available
    if last and last.project_name:
        display_items.append({
            "label": f"[Last] {last.client_name or '?'} → {last.project_name}",
            "data": last,
            "is_last": True,
        })

    # Add "No client/project"
    display_items.append({
        "label": "(No client/project)",
        "data": LastContext(),
        "is_last": False,
    })

    # Add all projects
    for p in projects:
        ctx = LastContext(
            workspace_id=p["workspace_id"],
            client_name=p["client_name"],
            project_id=p["project_id"],
            project_name=p["project_name"],
        )
        label = f"{p['client_name'] or '(no client)'} → {p['project_name']}"
        display_items.append({"label": label, "data": ctx, "is_last": False})

    filtered_items: list[dict] = list(display_items)

    def refresh_list():
        nonlocal filtered_items
        query = search_var.get().lower().strip()
        listbox.delete(0, tk.END)
        filtered_items = [
            item for item in display_items
            if not query or query in item["label"].lower()
        ]
        for item in filtered_items:
            listbox.insert(tk.END, item["label"])
        if filtered_items:
            listbox.selection_set(0)
            listbox.see(0)

    def on_search_change(*_):
        refresh_list()

    search_var.trace_add("write", on_search_change)

    def select_current():
        sel = listbox.curselection()
        if sel and filtered_items:
            chosen = filtered_items[sel[0]]["data"]
            result[0] = chosen
            if chosen.project_name:
                save_last_context(chosen)
            root.destroy()

    def on_enter(event):
        select_current()

    def on_escape(event):
        root.destroy()

    def on_double_click(event):
        select_current()

    root.bind("<Return>", on_enter)
    root.bind("<Escape>", on_escape)
    listbox.bind("<Double-Button-1>", on_double_click)

    # Arrow key navigation from search to list
    def on_down(event):
        if listbox.size() > 0:
            listbox.focus_set()
            if not listbox.curselection():
                listbox.selection_set(0)

    search_entry.bind("<Down>", on_down)

    def on_list_key(event):
        if event.keysym == "Return":
            select_current()

    listbox.bind("<Key>", on_list_key)

    # Populate
    refresh_list()
    search_entry.focus_set()

    # Button row
    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill=tk.X, pady=(5, 0))
    ttk.Button(btn_frame, text="Select (Enter)", command=select_current).pack(side=tk.LEFT, padx=(0, 5))
    ttk.Button(btn_frame, text="Cancel (Esc)", command=root.destroy).pack(side=tk.LEFT)

    root.mainloop()
    return result[0]
