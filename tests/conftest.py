import sys
from pathlib import Path

# Ensure src/ is on sys.path so `import blindspot` works without install
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
