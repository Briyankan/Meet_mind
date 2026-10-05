"""
Scheduled cleanup of temporary uploads and exports older than retention period.
"""

import logging
import shutil
import time
from pathlib import Path
from threading import Lock, Thread

import config

logger = logging.getLogger(__name__)

_cleanup_lock = Lock()
_cleanup_started = False


def _folder_age_minutes(folder: Path) -> float:
    try:
        mtime = folder.stat().st_mtime
        return (time.time() - mtime) / 60.0
    except OSError:
        return 0.0


def cleanup_expired_files() -> int:
    """
    Remove session upload and export folders older than FILE_RETENTION_MINUTES.
    Returns number of folders removed.
    """
    removed = 0
    retention = config.FILE_RETENTION_MINUTES

    for base in (config.UPLOAD_FOLDER, config.EXPORT_FOLDER):
        if not base.exists():
            continue
        for item in base.iterdir():
            if not item.is_dir() or item.name.startswith("."):
                continue
            age = _folder_age_minutes(item)
            if age >= retention:
                try:
                    shutil.rmtree(item, ignore_errors=True)
                    removed += 1
                    logger.info("Cleaned expired folder: %s (age %.1f min)", item.name, age)
                except OSError as exc:
                    logger.warning("Failed to remove %s: %s", item, exc)

    return removed


def _cleanup_loop() -> None:
    while True:
        try:
            with _cleanup_lock:
                cleanup_expired_files()
        except Exception as exc:
            logger.exception("Cleanup error: %s", exc)
        time.sleep(config.CLEANUP_INTERVAL_SECONDS)


def start_cleanup_scheduler() -> None:
    """Start background cleanup thread once per process."""
    global _cleanup_started
    if _cleanup_started:
        return
    _cleanup_started = True
    thread = Thread(target=_cleanup_loop, name="file-cleanup", daemon=True)
    thread.start()
    logger.info(
        "Cleanup scheduler started (retention=%s min, interval=%s s)",
        config.FILE_RETENTION_MINUTES,
        config.CLEANUP_INTERVAL_SECONDS,
    )
