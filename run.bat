@echo off
rem LangPal one-click start (ASCII only, no CJK in this file)
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q -r backend\requirements.txt
python -m uvicorn app.main:app --app-dir backend --port 8787
