"""
Input validation helpers.
"""

import re
from pathlib import Path
from typing import Optional, Tuple
from werkzeug.datastructures import FileStorage

import config


def allowed_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in config.ALLOWED_EXTENSIONS


def validate_audio_upload(file: FileStorage) -> Tuple[bool, Optional[str]]:
    if not file or not file.filename:
        return False, "No audio file selected."

    if not allowed_file(file.filename):
        return (
            False,
            "Invalid file type. Allowed formats: MP3, WAV, M4A.",
        )

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)

    if size == 0:
        return False, "The uploaded file is empty."

    if size > config.MAX_CONTENT_LENGTH:
        return False, "File too large. Maximum size is 25 MB."

    return True, None


def validate_transcript(text: str) -> Tuple[bool, Optional[str]]:
    cleaned = (text or "").strip()
    if not cleaned:
        return False, "Transcript cannot be empty."
    if len(cleaned) < config.MIN_TRANSCRIPT_CHARS:
        return (
            False,
            f"Transcript is too short. Please provide at least {config.MIN_TRANSCRIPT_CHARS} characters.",
        )
    if len(cleaned) > config.MAX_TRANSCRIPT_CHARS:
        return (
            False,
            f"Transcript exceeds maximum length of {config.MAX_TRANSCRIPT_CHARS:,} characters.",
        )
    return True, None


def sanitize_filename(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[:120] if name else "upload.bin"
