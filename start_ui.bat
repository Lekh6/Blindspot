@echo off
REM BlindSpot — one-click UI launcher (API server + frontend, opens browser)
REM First time setup: see README "First Time Setup" (one-time venv step)
REM Everyday use: just double-click this file or run "start_ui.bat"

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
  echo [error] python not found on PATH. Create venv first: python -m venv .venv
  pause
  exit /b 1
)

REM Prefer venv python if it exists
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "%~dp0start_ui.py" %*
) else (
  python "%~dp0start_ui.py" %*
)

REM Keep the window open on failure so the error is readable when double-clicked
if %ERRORLEVEL% neq 0 (
  echo.
  echo [start_ui] exited with an error — see messages above.
  pause
)
