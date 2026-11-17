@echo off
REM Smart Archive - DESKTOP mode: native window + native system folder chooser
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
.venv\Scripts\python desktop.py
