# AI Meeting Notes and Summary Generator

Production-ready meeting summarization app powered by **Google Gemini API**.

## Complete feature list

### Input
- Upload audio: MP3, WAV, M4A (max 25 MB)
- Drag & drop + browse
- Paste transcript (50–50,000 characters)

### AI processing (Gemini)
- Audio → transcript
- Structured summary: Overview, Discussion Points, Key Decisions, Action Items, Final Conclusion

### Results dashboard
- 30% / 50% / 20% layout (contents / summary / actions)
- Yellow-highlighted Key Decisions
- Action items checklist
- Transcript preview
- Per-section **Copy** buttons
- Copy full summary + **Share**
- PDF and TXT export
- New Summary

### Processing UI
- 3-step stepper (upload → transcribe → summarize)
- Progress bar + cancel
- Browser-close warning

### UX
- Dark mode toggle
- Toast notifications
- Feedback Yes/No + survey modal (saved to `exports/feedback.jsonl`)
- Privacy & Contact pages

### Security
- CSRF protection
- Rate limiting
- Secure file uploads (allowlist, random names)
- API key in `.env` only
- Session isolation, no database
- Auto-delete files after 60 minutes

### Deployment
- Development: `python app.py` or `START.bat`
- Production: `RUN_PRODUCTION.bat` (Waitress)
- HTTPS-ready: `PREFERRED_URL_SCHEME=https`, `SESSION_COOKIE_SECURE=true`

## Setup

```powershell
cd ai-meeting-notes
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`:

```env
SECRET_KEY=your-random-secret
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-1.5-flash
```

## Run

```powershell
python app.py
```

Open **http://127.0.0.1:5000**

## License

MIT
# Meet_mind
