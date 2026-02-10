"""Centralized logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import load_config

_configured = False


def setup_logging() -> logging.Logger:
    global _configured
    if _configured:
        return logging.getLogger("worklog")

    cfg = load_config()["logging"]
    log_path = Path(cfg["path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("worklog")
    logger.setLevel(getattr(logging, cfg["level"].upper(), logging.INFO))

    # File handler with rotation
    fh = RotatingFileHandler(
        log_path,
        maxBytes=cfg["max_bytes"],
        backupCount=cfg["backup_count"],
        encoding="utf-8",
    )
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(fh)

    # Console handler (minimal)
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    _configured = True
    return logger


def get_logger(name: str = "worklog") -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
