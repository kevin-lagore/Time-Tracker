# Push-to-Talk Work Log

A Windows-native push-to-talk system for capturing, transcribing, and organizing
consultant work notes. Uses AutoHotkey v2 for hotkey-driven audio capture, Python
for processing, and a local web editor for managing entries.

## Features

- **Push-to-talk capture** — Hold CapsLock to record, release to process
- **Toggl integration** — Auto-detects project/client from running time entries
- **AI transcription** — OpenAI Whisper for speech-to-text
- **LLM cleanup** — Optional structured note cleanup with tagging
- **Local editor** — FastAPI web UI for browsing, editing, reassigning entries
- **Reports** — End-of-day/week compilation with Toggl time totals
- **Offline resilient** — Captures succeed even when APIs are down

## Prerequisites

- Windows 10 or 11
- [AutoHotkey v2](https://www.autohotkey.com/) (v2.0+)
- [Python 3.11+](https://www.python.org/downloads/)
- [ffmpeg](https://ffmpeg.org/download.html) in PATH
- Toggl Track account with API token
- OpenAI API key

## Installation

### 1. Clone / download the project

```
cd "C:\Users\you\Projects"
git clone <repo-url> "Time Tracker"
cd "Time Tracker"
```

### 2. Install Python dependencies

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Install ffmpeg

Download a static build from https://www.gyan.dev/ffmpeg/builds/ (the
`ffmpeg-release-essentials.zip`). Extract and add the `bin` folder to your
system PATH.

Verify:
```
ffmpeg -version
```

#### Finding your microphone device name

```
ffmpeg -list_devices true -f dshow -i dummy
```

Look for your microphone under `DirectShow audio devices`. Copy the exact name
(e.g., `Microphone (Realtek Audio)`) and set it in `config.yaml` under
`audio.input_device`, or leave blank to use the system default.

**Common device names:**
- `Microphone (Realtek(R) Audio)` — built-in laptop mic
- `Microphone (USB Audio Device)` — USB headset
- `Headset Microphone (Plantronics .Audio 628 USB)` — brand-specific
- `Microphone Array (Intel® Smart Sound Technology)` — array mic

If the default device doesn't work, set the exact name in config.yaml:
```yaml
audio:
  input_device: "Microphone (Realtek(R) Audio)"
```

### 4. Configure environment

```
copy .env.example .env
copy config.yaml.example config.yaml
```

Edit `.env` and set:
```
TOGGL_API_TOKEN=your_toggl_api_token
OPENAI_API_KEY=sk-your_openai_key
```

Find your Toggl API token at: https://track.toggl.com/profile (scroll to
"API Token" at the bottom).

### 5. Run doctor check

```
python -m app doctor
```

This verifies your `.env`, ffmpeg, Toggl connectivity, and database setup.

### 6. Initialize Toggl cache

```
python -m app refresh-toggl
```

### 7. Launch the AHK script

Double-click `ahk\pushtotalk.ahk` (requires AutoHotkey v2 installed).

You should see a tooltip: "Work Log Active".

## Usage

### Capture a note (Push-to-talk)

1. **Hold CapsLock** — recording starts (tooltip shows "Recording...")
2. **Release CapsLock** — recording stops, audio is transcribed and stored
3. A toast notification shows the detected project and a summary

If Toggl has a running timer, the entry auto-links to that project/client.
If no timer is running, a popup appears to select client/project.

### Hotkeys

| Hotkey | Action |
|---|---|
| Hold CapsLock | Record audio |
| Release CapsLock | Stop & process |
| Ctrl+Shift+E | Open web editor |
| Ctrl+Shift+R | Emergency stop recording |

### CLI Commands

Activate the virtual environment first: `.venv\Scripts\activate`

```bash
# Capture (normally called by AHK, but can be used manually)
python -m app capture --audio "path\to\recording.wav"
python -m app capture --audio "file.wav" --no-llm
python -m app capture --audio "file.wav" --use-last-context
python -m app capture --audio "file.wav" --prompt-context

# Compile reports
python -m app compile --date 2025-01-15 --out report.md
python -m app compile --week 2025-W03 --out weekly.md --format html

# Start the web editor
python -m app editor
# Opens at http://127.0.0.1:8765

# Refresh Toggl cache
python -m app refresh-toggl

# Reprocess an entry (retry transcription/LLM)
python -m app reprocess --id <entry-uuid>

# Export entries
python -m app export --format json --date 2025-01-15
python -m app export --format csv --week 2025-W03 --out export.csv

# System health check
python -m app doctor
```

### Web Editor

Start with `python -m app editor` or press `Ctrl+Shift+E`.

Features:
- **List view** with filters (date, client, project, tags, keyword, errors)
- **Edit** transcript, cleaned note, project assignment, tags, privacy
- **Bulk operations** — select multiple entries and reassign/retag
- **Merge tool** — combine two entries into one
- **Retry** — re-run transcription or LLM cleanup on individual entries
- **Refresh Toggl cache** button
- **Set as last context** — update the fallback context from any entry
- Badges showing context source (Toggl current/recent, fallback, none)
- Error indicators for entries with failed processing steps

### Compiled Reports

Reports group entries by client with sections:
- ✅ Completed
- 🔜 Next
- ⚠️ Risks/Blockers
- ❓ Asks
- ⏱️ Time spent (from Toggl)

Private entries are automatically excluded.

## Configuration

### config.yaml

| Section | Key | Default | Description |
|---|---|---|---|
| audio.dir | | ./audio_captures | Where recordings are saved |
| audio.input_device | | "" | ffmpeg audio device (blank = default) |
| toggl.recent_window_minutes | | 15 | Fallback: look back N minutes for recent entry |
| toggl.cache_ttl_hours | | 24 | Auto-refresh Toggl cache after N hours |
| openai.stt_model | | whisper-1 | Whisper model for transcription |
| openai.llm_model | | gpt-4o-mini | Model for cleanup/compilation |
| features.llm_cleanup | | true | Enable LLM note cleanup |
| features.llm_compile | | true | Enable LLM-assisted compilation |
| editor.port | | 8765 | Local editor port |

### Environment overrides

Set in `.env` to override config.yaml paths:
- `AUDIO_DIR`
- `DB_PATH`
- `LOG_PATH`

## Context Source Resolution

When capturing, the system determines project/client context in this order:

1. **toggl_current** — A Toggl timer is currently running
2. **toggl_recent** — No running timer, but one stopped within the last N minutes
3. **fallback_prompt** — No Toggl context; user selects from a popup
4. **fallback_last** — Uses the last selected context (with `--use-last-context`)
5. **none** — No context could be determined

## File Structure

```
Time Tracker/
├── ahk/
│   └── pushtotalk.ahk          # AHK v2 push-to-talk script
├── app/
│   ├── __init__.py
│   ├── __main__.py              # python -m app entry point
│   ├── main.py                  # Typer CLI commands
│   ├── config.py                # Config loading (.env + yaml)
│   ├── log_setup.py             # Logging setup
│   ├── models.py                # Pydantic models
│   ├── db.py                    # SQLite access layer
│   ├── audio.py                 # Audio file utilities
│   ├── toggl.py                 # Toggl Track API client
│   ├── toggl_cache.py           # Cache management
│   ├── openai_stt.py            # OpenAI transcription
│   ├── llm_clean.py             # LLM note cleanup
│   ├── compile.py               # Report compilation
│   ├── context_picker.py        # Fallback context popup (tkinter)
│   └── editor/
│       ├── __init__.py
│       ├── server.py            # FastAPI editor app
│       ├── templates/
│       │   ├── base.html
│       │   ├── list.html
│       │   └── detail.html
│       └── static/
│           ├── style.css
│           └── app.js
├── tests/
│   ├── test_db.py
│   ├── test_models.py
│   ├── test_compile.py
│   └── test_audio.py
├── audio_captures/              # Recorded audio files
├── data/                        # SQLite database
├── logs/                        # Application logs
├── .env.example
├── config.yaml.example
├── requirements.txt
└── README.md
```

## Acceptance Test Script

Run these steps to verify the system works end-to-end:

### 1. Capture with active Toggl timer
1. Start a Toggl timer on project X
2. Hold CapsLock, speak a note, release
3. Open editor (`Ctrl+Shift+E`) or `python -m app editor`
4. Verify the entry shows project X with `context_source=toggl_current`

### 2. Capture with fallback popup
1. Stop the Toggl timer
2. Hold CapsLock, speak a note, release
3. The context picker popup appears — select project Y
4. Verify entry shows project Y with `context_source=fallback_prompt`

### 3. Capture with last context
1. With Toggl timer stopped, run:
   ```
   python -m app capture --audio "test.wav" --use-last-context
   ```
2. Verify it uses project Y with `context_source=fallback_last`

### 4. Edit entries
1. Open the editor
2. Click an entry to open detail view
3. Reassign to project Z
4. Add the "blocker" tag
5. Mark one entry as private
6. Save and verify changes persist

### 5. Compile report
1. Run: `python -m app compile --date <today> --out report.md`
2. Open `report.md`
3. Verify private entries are excluded
4. Verify client sections include correct Toggl time totals

### 6. Bulk operations
1. In the editor list view, select multiple entries
2. Expand "Bulk Operations"
3. Reassign to a different project
4. Click "Apply to Selected"

## Troubleshooting

### "ffmpeg not found"
- Download from https://www.gyan.dev/ffmpeg/builds/
- Extract and add the `bin` folder to your system PATH
- Restart your terminal / AHK script

### Audio not recording / wrong microphone
- Run `ffmpeg -list_devices true -f dshow -i dummy`
- Copy the exact device name into `config.yaml` under `audio.input_device`
- Ensure the device is not muted in Windows sound settings

### "TOGGL_API_TOKEN not set"
- Ensure `.env` file exists (copy from `.env.example`)
- Set your token from https://track.toggl.com/profile

### Transcription fails
- Verify `OPENAI_API_KEY` is set in `.env`
- Check `logs/app.log` for error details
- Entries with failed transcription can be retried from the editor

### CapsLock still toggles caps
- The AHK script disables CapsLock's toggle behavior
- If CapsLock is stuck on, press it once with the script running
- Exiting the AHK script restores normal CapsLock behavior

### Editor won't start / port in use
- Check if port 8765 is already in use: `netstat -an | findstr 8765`
- Change the port in `config.yaml` under `editor.port`

### Database errors
- Run `python -m app doctor` to verify database setup
- The database auto-creates on first run
- Location: `data/worklog.db` (configurable in config.yaml)

## Running Tests

```
python -m pytest tests/ -v
```

## Logs

- Application log: `logs/app.log` (rotated at 5MB, keeps 3 backups)
- AHK log: `logs/ahk.log`
