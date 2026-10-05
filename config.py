"""
Application configuration loaded from environment variables.
"""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Flask
SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me-in-production")
DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

# Paths
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
EXPORT_FOLDER = BASE_DIR / "exports"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
EXPORT_FOLDER.mkdir(parents=True, exist_ok=True)

# Accounts database — SQLite by default (a single local file, no setup required).
# Set DATABASE_URL in .env to point at Postgres or another server later without code changes.
SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Upload limits
MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = {"mp3", "wav", "m4a"}
MAX_TRANSCRIPT_CHARS = 50_000
MIN_TRANSCRIPT_CHARS = 50

# Cleanup
FILE_RETENTION_MINUTES = int(os.getenv("FILE_RETENTION_MINUTES", "60"))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "300"))

# Google Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_UPLOAD_TIMEOUT = int(os.getenv("GEMINI_UPLOAD_TIMEOUT", "120"))

# Rate limiting
RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "30 per hour;10 per minute")
RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")

# HTTPS / production
PREFERRED_URL_SCHEME = os.getenv("PREFERRED_URL_SCHEME", "https")
WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = 3600
