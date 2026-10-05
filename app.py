"""
AI Meeting Notes and Summary Generator — Flask application.
Google Gemini API for transcription and summarization. Summaries are session-scoped
and temporary by default; creating an account persists them in a local database.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_wtf.csrf import CSRFProtect, generate_csrf
from sqlalchemy import func
from werkzeug.exceptions import RequestEntityTooLarge

import config
from models import Review, Summary, User, db
from utils.cleanup import cleanup_expired_files, start_cleanup_scheduler
from utils.file_handler import (
    delete_session_files,
    generate_session_id,
    save_transcript_text,
    save_uploaded_audio,
)
from utils.gemini_client import GeminiError, GeminiNotConfiguredError, get_health_status
from utils.pdf_generator import generate_pdf, generate_txt
from utils.summarizer import generate_summary
from utils.transcriber import transcribe_audio
from utils.validators import validate_audio_upload, validate_transcript

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(config)

CORS(app, resources={r"/api/*": {"origins": "*"}})
csrf = CSRFProtect(app)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login_page"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


with app.app_context():
    db.create_all()

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[config.RATELIMIT_DEFAULT],
    storage_uri=config.RATELIMIT_STORAGE_URI,
)

# HTTPS behind reverse proxy
if config.PREFERRED_URL_SCHEME == "https":
    try:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    except ImportError:
        pass

# In-memory job status for async-style progress polling (session-scoped)
_processing_jobs: dict[str, dict] = {}

# In-memory summary history, keyed by a stable history_id (survives "New Summary",
# unlike session_id which is deliberately rotated for upload isolation)
_summary_history: dict[str, list[dict]] = {}
MAX_HISTORY_ITEMS = 10


def _ensure_session() -> str:
    if "session_id" not in session:
        session["session_id"] = generate_session_id()
        session.permanent = True
    return session["session_id"]


def _ensure_history_id() -> str:
    if "history_id" not in session:
        session["history_id"] = generate_session_id()
    return session["history_id"]


def _add_history_entry(*, source: str, summary: dict, transcript_preview: str, generated_at: str) -> None:
    """Persist a generated summary. Logged-in users get permanent DB storage;
    guests get the existing in-memory, session-scoped history (unchanged)."""
    if current_user.is_authenticated:
        row = Summary(
            user_id=current_user.id,
            source=source,
            summary_json=summary,
            transcript_preview=transcript_preview,
            generated_at=generated_at,
        )
        db.session.add(row)
        db.session.commit()
        return

    hid = _ensure_history_id()
    items = _summary_history.setdefault(hid, [])
    items.append({
        "id": generate_session_id(),
        "source": source,
        "summary": summary,
        "transcript_preview": transcript_preview,
        "generated_at": generated_at,
    })
    del items[:-MAX_HISTORY_ITEMS]


def _get_job(session_id: str) -> dict:
    if session_id not in _processing_jobs:
        _processing_jobs[session_id] = {
            "status": "idle",
            "step": 0,
            "message": "",
            "error": None,
            "cancelled": False,
        }
    return _processing_jobs[session_id]


@app.context_processor
def inject_globals():
    return {
        "csrf_token": generate_csrf,
        "app_name": "AI Meeting Notes Generator",
        "current_year": datetime.now().year,
    }


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_exc):
    if request.path.startswith("/api/"):
        return jsonify({"error": "File too large. Maximum size is 25 MB.", "code": "file_too_large"}), 413
    flash("File too large. Maximum size is 25 MB.", "danger")
    return redirect(url_for("index"))


@app.errorhandler(429)
def handle_rate_limit(_exc):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Too many requests. Please wait and try again.", "code": "rate_limit"}), 429
    flash("Too many requests. Please wait and try again.", "warning")
    return redirect(url_for("index"))


@app.route("/")
def index():
    health = get_health_status()
    return render_template("index.html", api_health=health)


@app.route("/welcome")
def welcome_page():
    return render_template("landing.html")


@app.route("/processing")
def processing_page():
    _ensure_session()
    return render_template("processing.html")


@app.route("/results")
def results_page():
    summary = session.get("summary")
    transcript_preview = session.get("transcript_preview", "")
    if not summary:
        flash("No summary available. Please generate one first.", "warning")
        return redirect(url_for("index"))
    return render_template(
        "results.html",
        summary=summary,
        transcript_preview=transcript_preview,
        generated_at=session.get("generated_at", ""),
    )


@app.route("/api/health")
@limiter.limit("60 per minute")
def api_health():
    return jsonify(get_health_status())


@app.route("/api/csrf-token")
@limiter.limit("30 per minute")
def api_csrf_token():
    return jsonify({"csrf_token": generate_csrf()})


@app.route("/api/status")
@limiter.limit("120 per minute")
def api_status():
    sid = _ensure_session()
    job = _get_job(sid)
    return jsonify(job)


@app.route("/api/cancel", methods=["POST"])
@limiter.limit("30 per minute")
def api_cancel():
    sid = _ensure_session()
    job = _get_job(sid)
    job["cancelled"] = True
    job["status"] = "cancelled"
    job["message"] = "Processing cancelled."
    return jsonify({"ok": True})


def _check_cancelled(sid: str) -> bool:
    return _get_job(sid).get("cancelled", False)


def _update_job(sid: str, *, status: str, step: int, message: str, error: str | None = None):
    job = _get_job(sid)
    job.update({"status": status, "step": step, "message": message, "error": error})


@app.route("/api/upload-audio", methods=["POST"])
@limiter.limit("10 per hour")
def api_upload_audio():
    sid = _ensure_session()
    job = _get_job(sid)
    job.update({"cancelled": False, "status": "starting", "step": 0, "error": None})

    health = get_health_status()
    if not health.get("ready"):
        return jsonify({
            "error": health.get("message", "Gemini API key not configured."),
            "code": "api_key_missing",
            "hint": health.get("hint", ""),
        }), 503

    file = request.files.get("audio")
    valid, err = validate_audio_upload(file)
    if not valid:
        return jsonify({"error": err, "code": "invalid_file"}), 400

    try:
        audio_path, _original = save_uploaded_audio(file, sid)
        session["audio_path"] = str(audio_path)
        session["source"] = "audio"
        return jsonify({"ok": True, "session_id": sid, "redirect": url_for("processing_page")})
    except ValueError as exc:
        return jsonify({"error": str(exc), "code": "invalid_file"}), 400
    except Exception as exc:
        logger.exception("Upload failed: %s", exc)
        return jsonify({"error": "Upload failed. Please try again.", "code": "upload_error"}), 500


@app.route("/api/process-audio", methods=["POST"])
@limiter.limit("10 per hour")
def api_process_audio():
    sid = _ensure_session()
    audio_path_str = session.get("audio_path")
    if not audio_path_str:
        return jsonify({"error": "No audio file in session. Upload again.", "code": "no_audio"}), 400

    audio_path = Path(audio_path_str)
    if not audio_path.exists():
        return jsonify({"error": "Audio file expired. Please upload again.", "code": "file_missing"}), 400

    try:
        _update_job(sid, status="processing", step=1, message="Upload complete")
        if _check_cancelled(sid):
            return jsonify({"cancelled": True})

        _update_job(sid, status="processing", step=2, message="Transcribing audio with Gemini...")
        transcript = transcribe_audio(audio_path)
        session["transcript"] = transcript
        session["transcript_preview"] = transcript[:500] + ("..." if len(transcript) > 500 else "")

        if _check_cancelled(sid):
            return jsonify({"cancelled": True})

        _update_job(sid, status="processing", step=3, message="Generating AI summary...")
        summary = generate_summary(transcript)
        session["summary"] = summary
        session["generated_at"] = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        _add_history_entry(
            source="audio",
            summary=summary,
            transcript_preview=session["transcript_preview"],
            generated_at=session["generated_at"],
        )
        _update_job(sid, status="complete", step=4, message="Summary ready!")

        return jsonify({"ok": True, "redirect": url_for("results_page")})
    except GeminiNotConfiguredError as exc:
        _update_job(sid, status="error", step=0, message=str(exc), error=exc.code)
        return jsonify({"error": str(exc), "code": exc.code, "hint": exc.hint}), 503
    except GeminiError as exc:
        _update_job(sid, status="error", step=0, message=str(exc), error=exc.code)
        return jsonify({"error": str(exc), "code": exc.code, "hint": exc.hint}), 502
    except ValueError as exc:
        _update_job(sid, status="error", step=0, message=str(exc), error="validation")
        return jsonify({"error": str(exc), "code": "validation"}), 400
    except Exception as exc:
        logger.exception("Process audio failed: %s", exc)
        _update_job(sid, status="error", step=0, message="Processing failed.", error="server_error")
        return jsonify({"error": "Processing failed. Please try again.", "code": "server_error"}), 500


@app.route("/api/submit-transcript", methods=["POST"])
@limiter.limit("15 per hour")
def api_submit_transcript():
    sid = _ensure_session()
    data = request.get_json(silent=True) or {}
    text = data.get("transcript", request.form.get("transcript", ""))

    valid, err = validate_transcript(text)
    if not valid:
        return jsonify({"error": err, "code": "empty_transcript"}), 400

    health = get_health_status()
    if not health.get("ready"):
        return jsonify({
            "error": health.get("message", "Gemini API key not configured."),
            "code": "api_key_missing",
            "hint": health.get("hint", ""),
        }), 503

    job = _get_job(sid)
    job.update({"cancelled": False})

    try:
        save_transcript_text(text, sid)
        session["transcript"] = text.strip()
        session["transcript_preview"] = text.strip()[:500]
        session["source"] = "text"

        _update_job(sid, status="processing", step=2, message="Generating AI summary...")
        summary = generate_summary(text)
        session["summary"] = summary
        session["generated_at"] = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        _add_history_entry(
            source="text",
            summary=summary,
            transcript_preview=session["transcript_preview"],
            generated_at=session["generated_at"],
        )
        _update_job(sid, status="complete", step=4, message="Done")

        return jsonify({"ok": True, "redirect": url_for("results_page")})
    except GeminiError as exc:
        return jsonify({"error": str(exc), "code": exc.code, "hint": exc.hint}), 502
    except Exception as exc:
        logger.exception("Transcript processing failed: %s", exc)
        return jsonify({"error": "Summarization failed.", "code": "server_error"}), 500


@app.route("/api/export/<export_type>")
@limiter.limit("30 per hour")
def api_export(export_type: str):
    sid = _ensure_session()
    summary = session.get("summary")
    if not summary:
        return jsonify({"error": "No summary to export.", "code": "no_summary"}), 400

    try:
        if export_type == "pdf":
            path = generate_pdf(summary, sid)
            return send_file(
                path,
                as_attachment=True,
                download_name=path.name,
                mimetype="application/pdf",
            )
        if export_type == "txt":
            path = generate_txt(summary, sid)
            return send_file(
                path,
                as_attachment=True,
                download_name=path.name,
                mimetype="text/plain",
            )
        return jsonify({"error": "Invalid export type.", "code": "invalid_type"}), 400
    except Exception as exc:
        logger.exception("Export failed: %s", exc)
        return jsonify({"error": "Export failed.", "code": "export_error"}), 500


@app.route("/api/copy-summary")
@limiter.limit("60 per hour")
def api_copy_summary():
    summary = session.get("summary")
    if not summary:
        return jsonify({"error": "No summary available."}), 400

    lines = [
        "MEETING OVERVIEW",
        summary.get("overview", ""),
        "",
        "DISCUSSION POINTS",
    ]
    for p in summary.get("discussion_points", []):
        lines.append(f"• {p}")
    lines.append("\nKEY DECISIONS")
    for d in summary.get("decisions", []):
        lines.append(f"• {d}")
    lines.append("\nACTION ITEMS")
    for a in summary.get("action_items", []):
        lines.append(f"• {a}")
    lines.append("\nFINAL CONCLUSION")
    lines.append(summary.get("final_conclusion", ""))

    return jsonify({"text": "\n".join(lines)})


@app.route("/api/feedback", methods=["POST"])
@limiter.limit("30 per hour")
def api_feedback():
    sid = _ensure_session()
    data = request.get_json(silent=True) or {}
    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        rating = 0
    if not 1 <= rating <= 5:
        return jsonify({"error": "Rating must be between 1 and 5.", "code": "validation"}), 400

    comment = str(data.get("comment", ""))[:2000].strip()
    review = Review(
        user_id=current_user.id if current_user.is_authenticated else None,
        session_id=sid,
        rating=rating,
        comment=comment,
    )
    db.session.add(review)
    db.session.commit()
    session["feedback_submitted"] = True
    return jsonify({"ok": True, "message": "Thank you for your review."})


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html", api_health=get_health_status())


@app.route("/contact")
def contact_page():
    return render_template("contact.html", api_health=get_health_status())


@app.route("/dashboard")
@login_required
def dashboard_page():
    uid = current_user.id
    recent = (
        Summary.query.filter_by(user_id=uid)
        .order_by(Summary.created_at.desc())
        .limit(5)
        .all()
    )
    items = [
        {
            "id": str(s.id),
            "source": s.source,
            "summary": s.summary_json,
            "generated_at": s.generated_at,
        }
        for s in recent
    ]

    total_count = Summary.query.filter_by(user_id=uid).count()
    audio_count = Summary.query.filter_by(user_id=uid, source="audio").count()
    text_count = Summary.query.filter_by(user_id=uid, source="text").count()

    avg_rating = (
        db.session.query(func.avg(Review.rating))
        .filter(Review.user_id == uid)
        .scalar()
    )
    review_count = Review.query.filter_by(user_id=uid).count()

    # Activity over the last 7 days, bucketed in Python for cross-database portability.
    today = datetime.utcnow().date()
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    counts_by_day = dict.fromkeys(days, 0)
    week_start = datetime.combine(days[0], datetime.min.time())
    recent_creations = (
        Summary.query.filter(Summary.user_id == uid, Summary.created_at >= week_start)
        .with_entities(Summary.created_at)
        .all()
    )
    for (created_at,) in recent_creations:
        day = created_at.date()
        if day in counts_by_day:
            counts_by_day[day] += 1
    max_day_count = max(counts_by_day.values()) or 1
    activity = [
        {
            "label": day.strftime("%a"),
            "count": count,
            "pct": round(count / max_day_count * 100),
        }
        for day, count in counts_by_day.items()
    ]

    stats = {
        "total_count": total_count,
        "audio_count": audio_count,
        "text_count": text_count,
        "avg_rating": round(avg_rating, 1) if avg_rating else None,
        "review_count": review_count,
    }

    return render_template("dashboard.html", items=items, stats=stats, activity=activity)


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def register_page():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard_page"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not email or "@" not in email:
            flash("Enter a valid email address.", "danger")
            return redirect(url_for("register_page"))
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return redirect(url_for("register_page"))
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register_page"))
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
            return redirect(url_for("register_page"))

        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Account created — welcome!", "success")
        return redirect(url_for("dashboard_page"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard_page"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login_page"))
        login_user(user)
        flash("Logged in.", "success")
        return redirect(url_for("dashboard_page"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout_page():
    logout_user()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


@app.route("/new-summary", methods=["POST"])
def new_summary():
    sid = session.get("session_id")
    if sid:
        delete_session_files(sid)
        _processing_jobs.pop(sid, None)
    # Pop only the per-summary keys — preserves history_id, and (importantly)
    # Flask-Login's own session keys, so this no longer logs the user out.
    for key in (
        "audio_path", "source", "transcript", "transcript_preview",
        "summary", "generated_at", "feedback_submitted",
    ):
        session.pop(key, None)
    session["session_id"] = generate_session_id()
    flash("Ready for a new summary.", "success")
    return redirect(url_for("index"))


@app.route("/history")
def history_page():
    if current_user.is_authenticated:
        rows = (
            Summary.query.filter_by(user_id=current_user.id)
            .order_by(Summary.created_at.desc())
            .all()
        )
        items = [
            {
                "id": str(s.id),
                "source": s.source,
                "summary": s.summary_json,
                "transcript_preview": s.transcript_preview,
                "generated_at": s.generated_at,
            }
            for s in rows
        ]
    else:
        hid = session.get("history_id")
        items = list(reversed(_summary_history.get(hid, []))) if hid else []
    return render_template("history.html", items=items)


@app.route("/history/<entry_id>")
def view_history_entry(entry_id: str):
    entry = None
    if current_user.is_authenticated:
        try:
            row = db.session.get(Summary, int(entry_id))
        except ValueError:
            row = None
        if row and row.user_id == current_user.id:
            entry = {
                "summary": row.summary_json,
                "transcript_preview": row.transcript_preview,
                "generated_at": row.generated_at,
                "source": row.source,
            }
    else:
        hid = session.get("history_id")
        items = _summary_history.get(hid, []) if hid else []
        entry = next((e for e in items if e["id"] == entry_id), None)

    if not entry:
        flash("That summary is no longer available.", "warning")
        return redirect(url_for("history_page"))

    _ensure_session()
    session["summary"] = entry["summary"]
    session["transcript_preview"] = entry["transcript_preview"]
    session["generated_at"] = entry["generated_at"]
    session["source"] = entry["source"]
    return redirect(url_for("results_page"))


@app.route("/history/<entry_id>/delete", methods=["POST"])
def delete_history_entry(entry_id: str):
    if current_user.is_authenticated:
        try:
            row = db.session.get(Summary, int(entry_id))
        except ValueError:
            row = None
        if row and row.user_id == current_user.id:
            db.session.delete(row)
            db.session.commit()
    else:
        hid = session.get("history_id")
        if hid and hid in _summary_history:
            _summary_history[hid] = [e for e in _summary_history[hid] if e["id"] != entry_id]
    return redirect(url_for("history_page"))


@app.route("/upload-audio", methods=["POST"])
@limiter.limit("10 per hour")
def upload_audio_form():
    """Form fallback when JavaScript is disabled."""
    sid = _ensure_session()
    file = request.files.get("audio")
    valid, err = validate_audio_upload(file)
    if not valid:
        flash(err, "danger")
        return redirect(url_for("index"))
    try:
        audio_path, _ = save_uploaded_audio(file, sid)
        session["audio_path"] = str(audio_path)
        session["source"] = "audio"
        return redirect(url_for("processing_page"))
    except Exception:
        flash("Upload failed. Please try again.", "danger")
        return redirect(url_for("index"))


@app.route("/submit-transcript", methods=["POST"])
@limiter.limit("15 per hour")
def submit_transcript_form():
    text = request.form.get("transcript", "")
    valid, err = validate_transcript(text)
    if not valid:
        flash(err, "danger")
        return redirect(url_for("index"))

    with app.test_request_context(
        json={"transcript": text},
        method="POST",
    ):
        pass

    sid = _ensure_session()
    try:
        health = get_health_status()
        if not health.get("ready"):
            flash(health.get("message", "Set GEMINI_API_KEY in .env"), "danger")
            return redirect(url_for("index"))

        save_transcript_text(text, sid)
        session["transcript"] = text.strip()
        session["transcript_preview"] = text.strip()[:500]
        session["source"] = "text"
        summary = generate_summary(text)
        session["summary"] = summary
        session["generated_at"] = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        _add_history_entry(
            source="text",
            summary=summary,
            transcript_preview=session["transcript_preview"],
            generated_at=session["generated_at"],
        )
        return redirect(url_for("results_page"))
    except GeminiError as exc:
        flash(str(exc), "danger")
    except Exception:
        flash("Summarization failed. Please try again.", "danger")
    return redirect(url_for("index"))


if __name__ == "__main__":
    import os

    start_cleanup_scheduler()
    cleanup_expired_files()
    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")

    if os.getenv("USE_WAITRESS", "").lower() in ("1", "true", "yes"):
        from waitress import serve
        logger.info("Starting production server (Waitress) on %s:%s", host, port)
        serve(app, host=host, port=port, threads=4)
    else:
        app.run(host=host, port=port, debug=config.DEBUG)
