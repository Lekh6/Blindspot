#!/usr/bin/env python3
"""
BlindSpot — one-click UI launcher.

Starts the local API server and the frontend, then opens the browser.
Same philosophy as run.py: hides the details, one command (or double-click).

Usage:
  python start_ui.py            # dev mode: API (127.0.0.1:8765) + Vite dev
                                # server (http://localhost:5173), opens browser
  python start_ui.py --build    # builds frontend/dist first, serves it via the
                                # API only at http://127.0.0.1:8765 (no Node at runtime)
  python start_ui.py --no-browser
  python start_ui.py --help

Ctrl+C stops everything it started.
First time setup is automatic: npm packages install on first run; the API uses
.venv when present (see README "First Time Setup" for the one-time venv step).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
FRONTEND = ROOT / "frontend"
API_SERVER = ROOT / "api" / "server.py"

API_PORT = int(os.environ.get("PORT", "8765"))
API_URL = f"http://127.0.0.1:{API_PORT}"
DEV_PORT = 5173
DEV_URL = f"http://localhost:{DEV_PORT}"

START_TIMEOUT = 90  # seconds to wait for each service to come up


def find_python() -> str:
    """Prefer .venv python (the API spouses the CLI, which needs PyYAML etc.)."""
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
        ROOT / ".venv" / "bin" / "python",          # Linux / macOS
    ]
    if getattr(sys, "frozen", False):
        return sys.executable
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def run_windows_kill(pid: int) -> None:
    """Kill a process tree on Windows (npm spawns child node processes)."""
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
    )


def spawn(command: list[str], **popen_kwargs) -> subprocess.Popen:
    return subprocess.Popen(command, **popen_kwargs)


def stop(shell_proc: subprocess.Popen | None) -> None:
    if shell_proc is None or shell_proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            run_windows_kill(shell_proc.pid)
        else:
            shell_proc.terminate()
        shell_proc.wait(timeout=10)
    except Exception:
        pass


def reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except Exception:
        return False


def wait_for(url: str, label: str) -> None:
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if reachable(url):
            print(f"  {label:<12}: ready    ({url})")
            return
        time.sleep(0.5)
    print(f"  {label:<12}: NOT READY after {START_TIMEOUT}s ({url})")


def npm_command(arguments: list[str]) -> list[str]:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        print("[error] npm not found on PATH.")
        print("  Install Node.js (https://nodejs.org) for dev/build mode.")
        raise SystemExit(1)
    return [npm, *arguments]


def ensure_node_modules() -> None:
    if (FRONTEND / "node_modules").is_dir():
        return
    print("  npm install: installing frontend dependencies (first run only)…")
    result = subprocess.run(
        npm_command(["install"]),
        cwd=str(FRONTEND),
    )
    if result.returncode != 0:
        print("[error] npm install failed. See output above.")
        raise SystemExit(1)


def start_api() -> subprocess.Popen | None:
    if reachable(f"{API_URL}/api/health"):
        print(f"  api server  : already running, reusing ({API_URL})")
        return None
    return spawn([find_python(), str(API_SERVER)], cwd=str(ROOT))


def console_flags() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="BlindSpot one-click UI launcher")
    parser.add_argument(
        "--build",
        action="store_true",
        help="build frontend/dist and serve it via the API only (no dev server)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the browser automatically",
    )
    args = parser.parse_args()

    print()
    print("========================================================")
    print("  BlindSpot — Dependency Graph UI")
    print("========================================================")

    api_proc: subprocess.Popen | None = None
    dev_proc: subprocess.Popen | None = None

    try:
        api_proc = start_api()

        if args.build:
            ensure_node_modules()
            print("  frontend    : building (tsc -b && vite build)…")
            build = subprocess.run(
                npm_command(["run", "build"]),
                cwd=str(FRONTEND),
            )
            if build.returncode != 0 or not (FRONTEND / "dist" / "index.html").exists():
                print("[error] frontend build failed. See output above.")
                raise SystemExit(1)
            print("  frontend    : built, served from frontend/dist")
            url = API_URL
        else:
            ensure_node_modules()
            dev_proc = spawn(
                npm_command(["run", "dev"]),
                cwd=str(FRONTEND),
                **console_flags(),
            )
            url = DEV_URL

        print()
        wait_for(f"{API_URL}/api/health", "api server")
        if args.build:
            wait_for(url, "web app")
        else:
            wait_for(url, "web app")
        print()
        print("  Press Ctrl+C to stop.")
        print()

        if not args.no_browser:
            webbrowser.open(url)
            print(f"  Opened {url}  (close this window or Ctrl+C to stop)")

        if api_proc is not None or dev_proc is not None:
            try:
                while api_proc is None or api_proc.poll() is None:
                    if dev_proc is not None and dev_proc.poll() is not None:
                        print("[warn] dev server exited — stopping.")
                        return 1
                    time.sleep(1)
                print("[warn] api server exited — stopping.")
                return 1
            except KeyboardInterrupt:
                raise
    except KeyboardInterrupt:
        pass
    except SystemExit as exit_event:
        stop(api_proc)
        stop(dev_proc)
        raise exit_event

    print()
    print("  Stopping services…")
    stop(dev_proc)
    stop(api_proc)
    print("  Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
