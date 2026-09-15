#!/usr/bin/env python3
"""
BlindSpot — simple startup script.

Usage:
  python run.py

This hides the PYTHONPATH complexity and launches the interactive menu.
First time: it will set up venv/pip (see README) then just run this file every time.

Advanced (still works):
  python run.py "C:\\path\\to\\YourApp" --thinking low
  python run.py --help
"""
from pathlib import Path
import sys
import os

ROOT = Path(__file__).parent.resolve()
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Auto-use venv python if available and we're not already in it
# Use subprocess.call on Windows to keep console handles for input()
# (os.execv breaks stdin on Windows for interactive prompts)
VENV_CANDIDATES = [
    ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
    ROOT / ".venv" / "bin" / "python",          # Linux / macOS
]
for venv_py in VENV_CANDIDATES:
    if venv_py.exists():
        try:
            if Path(sys.executable).resolve() != venv_py.resolve():
                import subprocess

                # On Windows, use subprocess to preserve console for input()
                # On Unix, execv is fine, but subprocess is also safe
                ret = subprocess.call([str(venv_py), str(Path(__file__).resolve())] + sys.argv[1:])
                raise SystemExit(ret)
        except SystemExit:
            raise
        except Exception:
            # If re-launch fails, fall back to current interpreter
            # Will show helpful error if deps missing
            pass
        break

# Ensure src/ is on path without requiring PYTHONPATH env var (redundant if re-launched, but safe)
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from blindspot.cli import main  # noqa: E402
except ModuleNotFoundError as e:
    # Most common when system python has no venv deps
    if "yaml" in str(e) or "blindspot" in str(e):
        print(f"[error] {e}")
        print("")
        print("  It looks like dependencies are missing (PyYAML etc.).")
        print("  Windows: run  .venv\\Scripts\\activate  then  python run.py")
        print("  Or just double-click  run.bat  (it auto-uses .venv)")
        print("  Linux/macOS: source .venv/bin/activate && python run.py")
        print("  Or: bash run.sh")
        raise SystemExit(1)
    raise

if __name__ == "__main__":
    raise SystemExit(main())
