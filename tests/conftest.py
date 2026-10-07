import os
import sys
from pathlib import Path

import pytest

# Ensure src/ is on sys.path so `import blindspot` works without install
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# API-key env vars that BlindSpot reads (directly or via load_dotenv(".env")).
# run_one_repo() loads the developer's real .env on purpose in production, but
# under pytest that would leak live keys across tests and even trigger real
# network LLM calls. Snapshot/restore around every test so tests stay hermetic
# regardless of execution order or ambient environment.
_KEY_VARS = (
    "OPENROUTER_API_KEY",
    "OR_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _restore_api_key_env():
    saved = {k: os.environ.get(k) for k in _KEY_VARS}
    try:
        yield
    finally:
        for k in _KEY_VARS:
            if saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]
