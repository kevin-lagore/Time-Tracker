; Push-to-Talk Work Log — AutoHotkey v2 Script
; Hold CapsLock to record audio, release to stop and process.
; Uses Python sounddevice for recording (no ffmpeg needed for capture).
#Requires AutoHotkey v2.0
#SingleInstance Force

; ============ CONFIGURATION ============
; Path to project root (adjust if needed)
ProjectRoot := A_ScriptDir "\.."

; Python executable (use full path if not in PATH)
PythonExe := "python"

; Audio output directory
AudioDir := ProjectRoot "\audio_captures"

; ============ END CONFIG ============

; State
IsRecording := false
RecordPID := 0
CurrentAudioFile := ""
StopFile := ""
LogFile := ProjectRoot "\logs\ahk.log"

; Ensure directories exist
DirCreate(AudioDir)
DirCreate(ProjectRoot "\logs")
DirCreate(ProjectRoot "\reports")

; Log function
WriteLog(msg) {
    global LogFile
    try {
        timestamp := FormatTime(, "yyyy-MM-dd HH:mm:ss")
        FileAppend(timestamp " | " msg "`n", LogFile)
    }
}

; Show tooltip notification
ShowToast(title, msg, duration := 3000) {
    ToolTip(title "`n" msg)
    SetTimer(() => ToolTip(), -duration)
}

; Start recording using Python sounddevice
StartRecording() {
    global IsRecording, RecordPID, CurrentAudioFile, AudioDir, PythonExe, ProjectRoot, StopFile

    if IsRecording
        return

    ; Generate filename with timestamp
    timestamp := FormatTime(, "yyyy-MM-dd_HH-mm-ss")
    CurrentAudioFile := AudioDir "\" timestamp ".wav"

    ; Clean up signal files
    StopFile := AudioDir "\_stop_signal"
    ReadyFile := AudioDir "\_ready_signal"
    try FileDelete(StopFile)
    try FileDelete(ReadyFile)

    ; Launch Python recorder
    cmd := A_ComSpec ' /c cd /d "' ProjectRoot '" && ' PythonExe ' -m app.recorder "' CurrentAudioFile '"'
    WriteLog("Starting recording: " cmd)

    try {
        Run(cmd, , "Hide", &RecordPID)
        IsRecording := true
        ShowToast("Starting mic...", "Initializing recorder")

        ; Wait for recorder to signal it's ready (up to 5 seconds)
        waited := 0
        loop {
            if FileExist(ReadyFile)
                break
            if !ProcessExist(RecordPID) {
                WriteLog("ERROR: Recorder process died during startup")
                ShowToast("Error", "Recorder failed to start", 4000)
                IsRecording := false
                return
            }
            Sleep(100)
            waited += 100
            if (waited >= 5000) {
                WriteLog("WARNING: Recorder ready timeout, proceeding anyway")
                break
            }
        }

        ShowToast("Recording...", "Release CapsLock to stop")
        WriteLog("Recording ready after " waited "ms, PID=" RecordPID)
    } catch as e {
        WriteLog("ERROR starting recording: " e.Message)
        ShowToast("Error", "Failed to start recording: " e.Message, 5000)
    }
}

; Stop recording by creating a stop signal file
StopRecording() {
    global IsRecording, RecordPID, CurrentAudioFile, PythonExe, ProjectRoot, StopFile

    if !IsRecording
        return

    IsRecording := false
    ShowToast("Processing...", "Transcribing and saving...")
    WriteLog("Stopping recording, PID=" RecordPID)

    ; Create stop signal file — the Python recorder watches for this
    try {
        FileAppend("stop", StopFile)
        WriteLog("Stop signal written to " StopFile)
    } catch as e {
        WriteLog("Failed to write stop signal: " e.Message)
    }

    ; Wait for the recorder process to finish writing the file
    ; Poll until the process exits (max 5 seconds)
    waited := 0
    loop {
        if !ProcessExist(RecordPID)
            break
        Sleep(200)
        waited += 200
        if (waited >= 5000) {
            WriteLog("Recorder process did not exit, killing it")
            try Run('taskkill /PID ' RecordPID ' /F /T', , "Hide")
            Sleep(500)
            break
        }
    }

    WriteLog("Recorder exited after " waited "ms")

    ; Verify file exists and has content
    if !FileExist(CurrentAudioFile) {
        ShowToast("Error", "Audio file not created", 4000)
        WriteLog("ERROR: Audio file not created: " CurrentAudioFile)
        return
    }

    fileSize := FileGetSize(CurrentAudioFile)
    if (fileSize < 1000) {
        ShowToast("Warning", "Audio file too small (" fileSize " bytes), skipping", 4000)
        WriteLog("WARNING: Audio file too small: " fileSize " bytes")
        return
    }

    WriteLog("Audio file size: " fileSize " bytes")

    ; Call Python capture pipeline
    cmd := PythonExe ' -m app capture --audio "' CurrentAudioFile '"'
    WriteLog("Running: " cmd)

    try {
        result := RunWait(A_ComSpec ' /c cd /d "' ProjectRoot '" && ' cmd, , "Hide")

        if (result = 0) {
            ShowToast("Captured!", "Note saved successfully", 3000)
            WriteLog("Capture successful")
        } else {
            ShowToast("Warning", "Capture completed with warnings (exit " result ")", 4000)
            WriteLog("Capture exited with code: " result)
        }
    } catch as e {
        ShowToast("Error", "Capture failed: " e.Message, 5000)
        WriteLog("ERROR in capture: " e.Message)
    }
}

; ============ HOTKEY DEFINITIONS ============

; CapsLock: push-to-talk
; Hold to record, release to stop
SetCapsLockState("AlwaysOff")

*CapsLock:: {
    ; Prevent re-entry from auto-repeat
    global IsRecording
    if IsRecording
        return
    StartRecording()
    ; Wait for physical key release
    KeyWait("CapsLock")
    StopRecording()
}

; Ctrl+Shift+R: Emergency stop recording
^+r:: {
    global IsRecording, RecordPID
    if IsRecording {
        try {
            Run('taskkill /PID ' RecordPID ' /F /T', , "Hide")
        }
        IsRecording := false
        ShowToast("Stopped", "Recording force-stopped", 3000)
        WriteLog("Force stopped recording")
    }
}

; Ctrl+Shift+E: Open editor
^+e:: {
    global PythonExe, ProjectRoot
    try {
        Run(A_ComSpec ' /c cd /d "' ProjectRoot '" && ' PythonExe ' -m app editor', , "Hide")
        Sleep(2000)
        Run("http://127.0.0.1:8765")
    } catch as e {
        ShowToast("Error", "Failed to start editor: " e.Message, 5000)
    }
}

; Ctrl+Alt+D: Generate End-of-Day report
^!d:: {
    global PythonExe, ProjectRoot
    ShowToast("Compiling EOD...", "Reprocessing errors + generating report")
    WriteLog("Generating EOD report")

    today := FormatTime(, "yyyy-MM-dd")
    outFile := ProjectRoot "\reports\eod_" today ".html"

    cmd := PythonExe ' -m app compile --date "' today '" --format html --out "' outFile '"'
    WriteLog("Running: " cmd)

    try {
        result := RunWait(A_ComSpec ' /c cd /d "' ProjectRoot '" && ' cmd, , "Hide")
        if (result = 0) {
            Run(outFile)
            ShowToast("EOD Report", "Opened in browser", 3000)
            WriteLog("EOD report generated: " outFile)
        } else {
            ShowToast("Error", "EOD report failed (exit " result ")", 5000)
            WriteLog("EOD report failed with exit code: " result)
        }
    } catch as e {
        ShowToast("Error", "Failed to generate EOD: " e.Message, 5000)
        WriteLog("ERROR generating EOD: " e.Message)
    }
}

; Ctrl+Alt+W: Generate End-of-Week report
^!w:: {
    global PythonExe, ProjectRoot
    ShowToast("Compiling EOW...", "Reprocessing errors + generating report")
    WriteLog("Generating EOW report")

    yw := FormatTime(, "YWeek")
    weekStr := SubStr(yw, 1, 4) "-W" SubStr(yw, 5, 2)
    outFile := ProjectRoot "\reports\eow_" weekStr ".html"

    cmd := PythonExe ' -m app compile --week "' weekStr '" --format html --out "' outFile '"'
    WriteLog("Running: " cmd)

    try {
        result := RunWait(A_ComSpec ' /c cd /d "' ProjectRoot '" && ' cmd, , "Hide")
        if (result = 0) {
            Run(outFile)
            ShowToast("EOW Report", "Opened in browser", 3000)
            WriteLog("EOW report generated: " outFile)
        } else {
            ShowToast("Error", "EOW report failed (exit " result ")", 5000)
            WriteLog("EOW report failed with exit code: " result)
        }
    } catch as e {
        ShowToast("Error", "Failed to generate EOW: " e.Message, 5000)
        WriteLog("ERROR generating EOW: " e.Message)
    }
}

; Startup notification
ShowToast("Work Log Active", "CapsLock=Record | ^!D=EOD | ^!W=EOW | ^+E=Editor | ^+R=Stop", 5000)
WriteLog("=== Push-to-Talk Work Log started ===")
