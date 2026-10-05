"""
Secure temporary file handling with randomized names and session isolation.
"""

import secrets
import time
from pathlib import Path
from typing import Optional, Tuple
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

import config
from utils.validators import allowed_file, sanitize_filename


def generate_session_id() -> str:
    return secrets.token_urlsafe(24)


def session_upload_dir(session_id: str) -> Path:
    path = config.UPLOAD_FOLDER / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_uploaded_audio(file: FileStorage, session_id: str) -> Tuple[Path, str]:
    if not allowed_file(file.filename or ""):
        raise ValueError("Invalid file type.")

    original = sanitize_filename(file.filename or "audio.bin")
    ext = original.rsplit(".", 1)[-1].lower()
    random_name = f"{secrets.token_hex(16)}.{ext}"
    dest_dir = session_upload_dir(session_id)
    dest_path = dest_dir / random_name
    file.save(dest_path)

    meta_path = dest_dir / f"{random_name}.meta"
    meta_path.write_text(
        f"{original}\n{int(time.time())}",
        encoding="utf-8",
    )
    return dest_path, original


def save_transcript_text(text: str, session_id: str) -> Path:
    dest_dir = session_upload_dir(session_id)
    path = dest_dir / "transcript.txt"
    path.write_text(text.strip(), encoding="utf-8")
    meta_path = dest_dir / "transcript.txt.meta"
    meta_path.write_text(f"manual_transcript.txt\n{int(time.time())}", encoding="utf-8")
    return path


def get_session_files(session_id: str) -> list[Path]:
    folder = config.UPLOAD_FOLDER / session_id
    if not folder.exists():
        return []
    return [p for p in folder.iterdir() if p.is_file()]


def delete_session_files(session_id: str) -> None:
    folder = config.UPLOAD_FOLDER / session_id
    if not folder.exists():
        return
    for item in folder.iterdir():
        if item.is_file():
            try:
                item.unlink()
            except OSError:
                pass
    try:
        folder.rmdir()
    except OSError:
        pass
