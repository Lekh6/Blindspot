"""BlindSpot Stage 3.4: Secret protection.

Redact passwords, tokens, API keys, credentials, and sensitive URL
components from LLM prompts, logs, reports, and cache data.

Non-sensitive evidence (host, port, db name, volume name, service name)
is preserved so reasoning remains possible.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

REDACTED = "***REDACTED***"

# Conservative secret-key matcher (case-insensitive substring on UPPER name).
_SECRET_SUBSTRINGS = (
    "PASSWORD",
    "PASSWD",
    "PASS",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "APIKEY",
    "PRIVATE_KEY",
    "PRIVATEKEY",
    "CREDENTIAL",
    "AUTH",
    "SESSION_KEY",
    "ACCESS_KEY",
    "REFRESH_TOKEN",
)

# Exact generic names that are *not* secrets even though they contain a
# substring above (e.g. None currently; kept for explicitness).
_SECRET_ALLOWLIST = frozenset()


def is_secret_key(name: str) -> bool:
    """Deterministic secret-key test on variable/resource name."""
    upper = (name or "").upper()
    if upper in _SECRET_ALLOWLIST:
        return False
    return any(s in upper for s in _SECRET_SUBSTRINGS)


def redact_url_credentials(value: Optional[str]) -> Optional[str]:
    """Strip userinfo (user:password@) from URIs; preserve host/port/db.

    Handles both single values and free-text blobs containing embedded URIs.
    Returns redacted string or original when no credentials present.
    Never raises on malformed input — returns original value.
    """
    if not value or "@" not in value or "://" not in value:
        return value
    try:
        # Regex over all scheme://...@ occurrences (free-text safe).
        # Matches userinfo without / ? # and replaces it with REDACTED.
        pattern = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@?#\s'\"]+)@")
        redacted, n = pattern.subn(lambda m: m.group(1) + REDACTED + "@", value)
        if n:
            return redacted
        # Fallback single-value path (no regex match but @ present).
        scheme, rest = value.split("://", 1)
        at = rest.rfind("@")
        if at == -1:
            return value
        before = rest[:at]
        if "/" in before or "?" in before or "#" in before:
            return value
        after = rest[at + 1:]
        return f"{scheme}://{REDACTED}@{after}"
    except Exception:
        return value


def redact_value_for_key(key: str, value: Optional[str]) -> Optional[str]:
    """Redact whole value when key looks secret; else redact URL userinfo."""
    if value is None:
        return None
    if is_secret_key(key):
        return REDACTED
    return redact_url_credentials(value)


def redact_mapping(mapping: Dict[str, Any]) -> Dict[str, Any]:
    """Redact a {var: value} mapping deterministically (sorted keys)."""
    out: Dict[str, Any] = {}
    for k in sorted(mapping.keys()):
        v = mapping[k]
        out[k] = redact_value_for_key(k, v) if isinstance(v, str) or v is None else v
    return out


def contains_secret_plaintext(payload: str, secrets: list[str]) -> bool:
    """Test helper: True if any non-empty secret appears verbatim."""
    for s in secrets:
        if s and len(s) >= 4 and s in payload:
            return True
    return False
