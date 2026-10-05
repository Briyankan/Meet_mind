"""
Google Gemini API client for audio transcription and meeting summarization.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import config

logger = logging.getLogger(__name__)

TRANSCRIBE_PROMPT = (
    "Transcribe this meeting audio completely and accurately. "
    "Identify each distinct speaker by their voice and prefix every line with a "
    "consistent speaker label such as 'Speaker 1:', 'Speaker 2:', etc. "
    "Return only the verbatim transcript text with these speaker labels — "
    "no other commentary, headers, or markdown."
)

MIME_MAP = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
}


class GeminiError(Exception):
    """Base exception for Gemini integration failures."""

    def __init__(self, message: str, code: str = "gemini_error", hint: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.hint = hint or ""


class GeminiNotConfiguredError(GeminiError):
    def __init__(self):
        super().__init__(
            "Gemini API key is not configured. Add GEMINI_API_KEY to your .env file.",
            code="api_key_missing",
            hint="Get a key at https://aistudio.google.com/apikey",
        )


def _configure():
    if not config.GEMINI_API_KEY:
        raise GeminiNotConfiguredError()
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise GeminiError(
            "Google Generative AI package not installed. Run: pip install google-generativeai",
            code="package_missing",
        ) from exc
    genai.configure(api_key=config.GEMINI_API_KEY)
    return genai


def _get_model(genai, *, json_output: bool = False):
    gen_config = None
    if json_output:
        gen_config = genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.2,
        )
    return genai.GenerativeModel(config.GEMINI_MODEL, generation_config=gen_config)


def is_api_configured() -> bool:
    return bool(config.GEMINI_API_KEY)


def get_health_status() -> Dict[str, Any]:
    configured = is_api_configured()
    return {
        "configured": configured,
        "ready": configured,
        "model": config.GEMINI_MODEL,
        "message": "Gemini API ready" if configured else "Set GEMINI_API_KEY in .env",
        "hint": "" if configured else "https://aistudio.google.com/apikey",
    }


def _classify_error(exc: Exception) -> Optional[GeminiError]:
    """Map a raw Gemini SDK exception to a GeminiError, or None if unrecognized."""
    exc_type = type(exc).__name__
    err = str(exc).lower()
    if (
        exc_type in ("PermissionDenied", "Unauthenticated")
        or "api_key_invalid" in err
        or "api key not valid" in err
        or "permission" in err
    ):
        return GeminiError(
            "Invalid Gemini API key. Check GEMINI_API_KEY in .env.",
            code="invalid_api_key",
        )
    if (
        exc_type in ("ResourceExhausted", "TooManyRequests")
        or "resource_exhausted" in err
        or "429" in err
        or "rate limit" in err
        or "quota exceeded" in err
    ):
        return GeminiError(
            "Gemini quota or rate limit exceeded. Try again later.",
            code="rate_limit",
        )
    return None


def transcribe_audio_file(audio_path: Path) -> str:
    """Transcribe audio using Gemini multimodal model.

    Sends the audio inline in the generateContent request rather than through
    the separate File Upload API, which currently rejects newer "AQ."-format
    API keys (a known Google-side issue as of 2026).
    """
    genai = _configure()
    try:
        mime = MIME_MAP.get(audio_path.suffix.lower(), "audio/mpeg")
        audio_bytes = audio_path.read_bytes()

        model = _get_model(genai)
        response = model.generate_content([
            {"mime_type": mime, "data": audio_bytes},
            TRANSCRIBE_PROMPT,
        ])
        text = (response.text or "").strip()
        if not text or len(text) < 10:
            raise GeminiError("Empty or invalid transcription returned.", code="empty_transcript")
        return text
    except GeminiNotConfiguredError:
        raise
    except GeminiError:
        raise
    except Exception as exc:
        classified = _classify_error(exc)
        if classified:
            raise classified from exc
        logger.exception("Gemini transcription failed: %s", exc)
        raise GeminiError(f"Transcription failed: {exc}", code="transcribe_failed") from exc


def generate_json_completion(prompt: str, system: str) -> Dict[str, Any]:
    """Generate structured JSON summary using Gemini."""
    genai = _configure()
    try:
        model = _get_model(genai, json_output=True)
        full_prompt = f"{system}\n\n{prompt}"
        response = model.generate_content(full_prompt)
        raw = (response.text or "").strip()
        if not raw:
            raise GeminiError("Empty response from Gemini.", code="empty_response")
        return json.loads(raw)
    except GeminiNotConfiguredError:
        raise
    except json.JSONDecodeError as exc:
        raise GeminiError(
            "Could not parse JSON from Gemini response.",
            code="invalid_json",
        ) from exc
    except GeminiError:
        raise
    except Exception as exc:
        classified = _classify_error(exc)
        if classified:
            raise classified from exc
        logger.exception("Gemini summarization failed: %s", exc)
        raise GeminiError(f"Summarization failed: {exc}", code="summarize_failed") from exc
