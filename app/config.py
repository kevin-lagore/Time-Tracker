"""Configuration loading from .env and config.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _find_env_file() -> Path:
    """Find .env file, checking project root then cwd."""
    for base in [PROJECT_ROOT, Path.cwd()]:
        p = base / ".env"
        if p.exists():
            return p
    return PROJECT_ROOT / ".env"


def _find_config_file() -> Path:
    """Find config.yaml, checking project root then cwd."""
    for base in [PROJECT_ROOT, Path.cwd()]:
        p = base / "config.yaml"
        if p.exists():
            return p
    return PROJECT_ROOT / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Load merged configuration from config.yaml with env overrides."""
    load_dotenv(_find_env_file())

    config_path = _find_config_file()
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    # Apply defaults
    defaults = {
        "audio": {
            "dir": str(PROJECT_ROOT / "audio_captures"),
            "format": "wav",
            "sample_rate": 16000,
            "input_device": "",
        },
        "database": {"path": str(PROJECT_ROOT / "data" / "worklog.db")},
        "logging": {
            "path": str(PROJECT_ROOT / "logs" / "app.log"),
            "level": "INFO",
            "max_bytes": 5_242_880,
            "backup_count": 3,
        },
        "toggl": {"recent_window_minutes": 15, "cache_ttl_hours": 24},
        "openai": {
            "stt_model": "whisper-1",
            "language": "",
            "llm_model": "gpt-4o-mini",
            "llm_temperature": 0.2,
        },
        "features": {"llm_cleanup": True, "llm_compile": True},
        "editor": {"host": "127.0.0.1", "port": 8765},
        "hotkey": {"key": "CapsLock"},
    }

    def _merge(base: dict, override: dict) -> dict:
        merged = dict(base)
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = _merge(merged[k], v)
            else:
                merged[k] = v
        return merged

    cfg = _merge(defaults, cfg)

    # Env overrides
    if os.getenv("AUDIO_DIR"):
        cfg["audio"]["dir"] = os.getenv("AUDIO_DIR")
    if os.getenv("DB_PATH"):
        cfg["database"]["path"] = os.getenv("DB_PATH")
    if os.getenv("LOG_PATH"):
        cfg["logging"]["path"] = os.getenv("LOG_PATH")

    return cfg


def get_toggl_token() -> str:
    load_dotenv(_find_env_file())
    token = os.getenv("TOGGL_API_TOKEN", "")
    if not token:
        raise RuntimeError("TOGGL_API_TOKEN not set in .env")
    return token


def get_openai_key() -> str:
    load_dotenv(_find_env_file())
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set in .env")
    return key
