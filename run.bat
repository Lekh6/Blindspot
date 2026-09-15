@echo off
REM BlindSpot — simple startup for Windows
REM First time setup: see README "First Time Setup"
REM Everyday use: just double-click this file or run "run.bat"

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
  echo [error] python not found on PATH. Create venv first: python -m venv .venv
  pause
  exit /b 1
)

REM Prefer venv python if it exists
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "%~dp0run.py" %*
) else (
  python "%~dp0run.py" %*
)
