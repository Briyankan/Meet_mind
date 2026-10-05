"""
Audio transcription via Google Gemini API.
"""

import logging
from pathlib import Path

from utils.gemini_client import GeminiError, GeminiNotConfiguredError, transcribe_audio_file

logger = logging.getLogger(__name__)


def transcribe_audio(file_path: Path) -> str:
    """Transcribe meeting audio using Gemini."""
    if not file_path.exists():
        raise ValueError("Audio file not found. Please upload again.")

    try:
        transcript = transcribe_audio_file(file_path)
        transcript = transcript.strip()
        if not transcript or len(transcript) < 10:
            raise ValueError(
                "No speech detected. Try a clearer recording or paste the transcript manually."
            )
        logger.info("Transcribed %s characters from %s", len(transcript), file_path.name)
        return transcript
    except (GeminiError, GeminiNotConfiguredError):
        raise
    except ValueError:
        raise
    except Exception as exc:
        logger.exception("Transcription error: %s", exc)
        raise RuntimeError("Transcription failed. Check your Gemini API key.") from exc
