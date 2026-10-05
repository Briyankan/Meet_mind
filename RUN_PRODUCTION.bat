@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
set USE_WAITRESS=true
set FLASK_DEBUG=false
echo Starting production server (Waitress)...
python app.py
