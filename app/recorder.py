"""Audio recording using sounddevice + soundfile. No ffmpeg needed."""

from __future__ import annotations

import sys
import signal
import threading
from datetime import datetime
from pathlib import Path

import sounddevice as sd
import soundfile as sf
import numpy as np

from app.config import load_config
from app.log_setup import get_logger

logger = get_logger("worklog.recorder")

_stop_event = threading.Event()


def record_until_stopped(output_path: str | None = None) -> str:
    """
    Record audio until a stop signal file appears.
    Creates a _ready_signal file when recording has started.
    """
    cfg = load_config()
    sample_rate = cfg["audio"].get("sample_rate", 16000)
    audio_dir = Path(cfg["audio"]["dir"])
    audio_dir.mkdir(parents=True, exist_ok=True)

    if not output_path:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = str(audio_dir / f"{timestamp}.wav")

    stop_file = audio_dir / "_stop_signal"
    ready_file = audio_dir / "_ready_signal"

    # Clean up signals from previous runs
    for f in [stop_file, ready_file]:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass

    logger.info("Recording to %s at %d Hz", output_path, sample_rate)

    # Signal handlers
    def handle_stop(signum, frame):
        _stop_event.set()

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    # Watch for stop file
    def watch_stop_file():
        while not _stop_event.is_set():
            if stop_file.exists():
                logger.info("Stop signal file detected")
                _stop_event.set()
                try:
                    stop_file.unlink()
                except OSError:
                    pass
                return
            _stop_event.wait(0.1)

    _stop_event.clear()
    frames = []

    def callback(indata, frame_count, time_info, status):
        if status:
            logger.warning("Recording status: %s", status)
        frames.append(indata.copy())

    try:
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16", callback=callback):
            # Signal that recording is active
            ready_file.write_text("ready")
            logger.info("Recording started, ready signal written")
            print(f"RECORDING:{output_path}", flush=True)

            # Now start watching for stop
            watcher = threading.Thread(target=watch_stop_file, daemon=True)
            watcher.start()

            _stop_event.wait()  # Block until stop signal
    except Exception as e:
        logger.error("Recording failed: %s", e)
        print(f"ERROR:{e}", flush=True)
        sys.exit(1)
    finally:
        try:
            ready_file.unlink(missing_ok=True)
        except OSError:
            pass

    # Write to file
    if frames:
        audio_data = np.concatenate(frames, axis=0)
        sf.write(output_path, audio_data, sample_rate)
        duration = len(audio_data) / sample_rate
        logger.info("Saved %.1fs of audio (%d samples) to %s", duration, len(audio_data), output_path)
        print(f"SAVED:{output_path}:{len(audio_data)}", flush=True)
    else:
        logger.warning("No audio frames captured")
        print("ERROR:No audio captured", flush=True)
        sys.exit(1)

    return output_path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else None
    record_until_stopped(out)
