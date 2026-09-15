"""
BlindSpot — Bounded Configuration Reference Resolution + Resource Identity Normalization

Pipeline position: Stage 3 Filtering+Evidence Resolution helper

Deterministic, bounded, no LLM. Provides:
  - distinction INTERNAL / EXTERNAL_CONFIRMED / UNRESOLVED / PARTIAL
  - bounded reference chain resolution with cycle & depth safeguards
  - connection-string parsing & normalized identity (credentials stripped)
  - identity strength EXACT_RESOURCE_IDENTITY / CONFIGURATION_IDENTITY / UNKNOWN
"""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Literal
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Public literal types (conceptual states from spec)
# ---------------------------------------------------------------------------

ResolutionStatus = Literal["internal", "external_confirmed", "unresolved", "partial"]
IdentityStrength = Literal["exact", "config", "unknown"]

# Canonical upper-case aliases for external consumption (report/judge)
STATUS_INTERNAL: ResolutionStatus = "internal"
STATUS_EXTERNAL_CONFIRMED: ResolutionStatus = "external_confirmed"
STATUS_UNRESOLVED: ResolutionStatus = "unresolved"
STATUS_PARTIAL: ResolutionStatus = "partial"

STRENGTH_EXACT: IdentityStrength = "exact"
STRENGTH_CONFIG: IdentityStrength = "config"
STRENGTH_UNKNOWN: IdentityStrength = "unknown"

# Bounded safeguards
MAX_RESOLUTION_DEPTH = 10

# Pattern for ${VAR} / ${VAR:-default} / $VAR  (same as parser)
_ENV_VAR_PATTERN = re.compile(
    r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}|\$(?P<unbraced>[A-Za-z_][A-Za-z0-9_]*)"
)

# Recognized URI schemes (lowercase)
SUPPORTED_SCHEMES = {
    "postgresql", "postgres",
    "mysql",
    "mongodb", "mongodb+srv",
    "redis", "rediss",
}

# Map postgres -> postgresql for normalization
SCHEME_CANONICAL = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "mongodb": "mongodb",
    "mongodb+srv": "mongodb+srv",
    "redis": "redis",
    "rediss": "redis",
}


@dataclass(frozen=True)
class ResolutionStep:
    """One bounded dereference step."""
    variable: str          # e.g. DATABASE_URL
    raw_reference: str     # e.g. ${DATABASE_URL} or $DATABASE_URL
    from_value: str        # value before this step
    to_value: str          # value after substitution (may still contain refs)
    source: str            # lookup source description, e.g. "env:calcom.DATABASE_URL"
    default_used: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variable": self.variable,
            "raw_reference": self.raw_reference,
            "from_value": self.from_value,
            "to_value": self.to_value,
            "source": self.source,
            "default_used": self.default_used,
        }


@dataclass(frozen=True)
class ResolutionResult:
    """Full bounded resolution trace + classification + normalized identity."""
    original_value: Optional[str]
    final_value: Optional[str]              # None if original was None, else resolved string (may contain unresolved ${...})
    chain: Tuple[ResolutionStep, ...]
    resolution_status: ResolutionStatus
    resource_protocol: Optional[str]        # e.g. postgresql, mysql, redis, None if unknown
    normalized_identity: Optional[str]      # deterministic string e.g. postgresql|host|5432|db
    identity_strength: IdentityStrength
    unresolved_vars: Tuple[str, ...]
    is_cyclic: bool = False
    depth_reached: int = 0
    # Internal lookup info
    resolved_service: Optional[str] = None
    resolved_image: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_value": self.original_value,
            "final_value": self.final_value,
            "chain": [s.to_dict() for s in self.chain],
            "resolution_status": self.resolution_status,
            "resource_protocol": self.resource_protocol,
            "normalized_identity": self.normalized_identity,
            "identity_strength": self.identity_strength,
            "unresolved_vars": list(self.unresolved_vars),
            "is_cyclic": self.is_cyclic,
            "depth_reached": self.depth_reached,
            "resolved_service": self.resolved_service,
            "resolved_image": self.resolved_image,
        }


# ---------------------------------------------------------------------------
# Helpers: lookup construction
# ---------------------------------------------------------------------------

def build_lookup(project: Any, service_a: str, service_b: str) -> Dict[str, Tuple[str, str]]:
    """
    Build bounded deterministic lookup for variables resolvable from config sources.

    Returns dict: var_name -> (value, source_description)
    Priority (deterministic, bounded):
      1) environments of service_a and service_b (alphabetical service order, later overrides earlier if duplicate — but deterministic)
      2) then all other services' environments (sorted) — so internal chain can use any compose-defined var
    Does NOT scan repo files beyond Compose/env_file/.env already normalized.

    We keep source trace for evidence: "env:<service>.<var>"
    """
    lookup: Dict[str, Tuple[str, str]] = {}
    if project is None or not hasattr(project, "services"):
        return {}
    # Deterministic ordering: sorted service names
    svc_names = sorted(project.services.keys())
    # Ensure a,b first for trace stability but still deterministic
    ordered = []
    for name in [service_a, service_b]:
        if name in svc_names and name not in ordered:
            ordered.append(name)
    for name in svc_names:
        if name not in ordered:
            ordered.append(name)
    for svc_name in ordered:
        svc = project.services.get(svc_name)
        if not svc or not svc.environment:
            continue
        for k, v in sorted(svc.environment.items()):
            if v is not None:
                # Keep first occurrence deterministically? Actually later services in ordered list override earlier
                # This mirrors compose merge but deterministic; we allow override so most specific wins but trace reflects last writer
                lookup[k] = (v, f"env:{svc_name}.{k}")
    return lookup


def _extract_vars(value: str) -> List[re.Match]:
    return list(_ENV_VAR_PATTERN.finditer(value))


# ---------------------------------------------------------------------------
# Connection string normalization
# ---------------------------------------------------------------------------

def _normalize_connection_identity(value: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Try to parse value as supported connection URI.
    Returns (protocol_canonical_or_None, normalized_identity_or_None, host_or_None)

    Credentials stripped. host lowercased, protocol lowercased.
    Identity forms:
      postgresql: postgresql|host|port|database
      mysql: mysql|host|port|database
      mongodb: mongodb|host|port|database  (host may contain comma cluster; port extracted if single host)
      mongodb+srv: mongodb+srv|host|port|database
      redis: redis|host|port|db_index  (db_index from path like /0 or /1)

    If scheme unsupported -> (None, None, None)
    If parse fails -> (None, None, None)
    """
    if not value or "://" not in value:
        return None, None, None
    try:
        parsed = urlparse(value)
    except Exception:
        return None, None, None
    scheme_raw = (parsed.scheme or "").lower()
    if scheme_raw not in SUPPORTED_SCHEMES:
        return None, None, None
    protocol = SCHEME_CANONICAL.get(scheme_raw, scheme_raw)
    # Host: parsed.hostname lowercased if available
    host = parsed.hostname.lower() if parsed.hostname else None
    # If still None, fallback to netloc handling for mongodb+srv edge where // parsing odd
    if host is None:
        # try to extract host from netloc without userinfo
        netloc = parsed.netloc
        # strip userinfo
        if "@" in netloc:
            netloc = netloc.split("@")[-1]
        # strip port
        if ":" in netloc:
            host = netloc.split(":")[0].lower()
        elif netloc:
            host = netloc.lower()
    port = parsed.port  # int or None
    # Database extraction: path without leading /, up to ?  (urlparse.path includes it)
    raw_path = parsed.path or ""
    # Remove leading /
    db = raw_path.lstrip("/")
    # For redis, path is db index; strip query
    if "?" in db:
        db = db.split("?")[0]
    if "?" in (host or ""):
        host = host.split("?")[0] if host else host
    # For mongodb+srv cluster strings like mongodb+srv://user:pass@cluster.mongodb.net/db
    # hostname handling already lowercased; port may be None
    # Build identity
    # Normalize empty to ""
    host_str = host or ""
    port_str = str(port) if port is not None else ""
    db_str = db or ""
    # For redis: db may be "0" etc; keep as is
    # For mongodb, if path had multiple hosts? ignore.
    # Detect partial: if host contains placeholder ${ or $ or empty and contains unresolved marker
    # But caller will already know unresolved_vars; we still produce identity if possible

    # If host empty and db empty and port empty -> not meaningful
    if not host_str and not db_str and not port_str:
        return protocol, None, host

    # Compose normalized identity deterministically
    # postgres/mysql/mongo/redis all use same pipe form for graph dedup stability
    # For postgresql we keep postgresql|host|port|db
    # For others we keep same shape but protocol distinguishes type
    normalized = f"{protocol}|{host_str}|{port_str}|{db_str}"
    return protocol, normalized, host


def _is_host_like_resource(resource: str) -> bool:
    upper = resource.upper()
    return any(k in upper for k in ("HOST", "URL", "ADDRESS", "ENDPOINT", "SERVER", "BROKER", "DATABASE_URL"))

def _is_unresolved_fragment(value: str) -> bool:
    """Does value still contain an unresolved ${VAR} or $VAR reference?"""
    return bool(_ENV_VAR_PATTERN.search(value or ""))


def _extract_unresolved_vars(value: Optional[str]) -> List[str]:
    if not value:
        return []
    vars_found = []
    for m in _ENV_VAR_PATTERN.finditer(value):
        braced = m.group("braced")
        unbraced = m.group("unbraced")
        var = braced if braced is not None else unbraced
        if var not in vars_found:
            vars_found.append(var)
    return sorted(vars_found)


# ---------------------------------------------------------------------------
# Core bounded resolver
# ---------------------------------------------------------------------------

def bounded_resolve(
    original_value: Optional[str],
    project: Any,
    service_a: str,
    service_b: str,
    resource: str = "",
    resource_type: str = "env_var",
    max_depth: int = MAX_RESOLUTION_DEPTH,
) -> ResolutionResult:
    """
    Bounded, deterministic reference resolution for one candidate value.

    Steps:
      while current contains resolvable reference:
        find all var refs in current (deterministic order: sorted by var name appearance? actually sequential)
        try to replace each with lookup value (if present)
        record step per variable resolved this iteration
        stop if no progress, cycle, depth, or no resolvable var

    Then classify status/normalized identity.

    Does NOT invent values for unresolved vars (preserves placeholder).
    Handles :-default by using default when var absent and default provided.
    """
    if original_value is None:
        return ResolutionResult(
            original_value=None,
            final_value=None,
            chain=(),
            resolution_status=STATUS_UNRESOLVED,
            resource_protocol=None,
            normalized_identity=None,
            identity_strength=STRENGTH_UNKNOWN,
            unresolved_vars=(),
            is_cyclic=False,
            depth_reached=0,
        )

    # Special path for named_volume: no URI resolution needed, but produce deterministic result
    if resource_type == "named_volume":
        # Named volume is internal by definition
        chain: Tuple[ResolutionStep, ...] = ()
        return ResolutionResult(
            original_value=original_value,
            final_value=original_value,
            chain=chain,
            resolution_status=STATUS_INTERNAL,
            resource_protocol=None,
            normalized_identity=f"named_volume|{resource}",
            identity_strength=STRENGTH_EXACT,
            unresolved_vars=(),
            is_cyclic=False,
            depth_reached=0,
        )

    lookup = build_lookup(project, service_a, service_b)
    # Also need to consider value itself could be a plain service name -> internal check later, not via chain

    current = original_value
    steps: List[ResolutionStep] = []
    seen_values: set = set()
    seen_vars_chain: set = set()  # for cycle detection on variable revisiting
    depth = 0
    is_cyclic = False

    while depth < max_depth and current is not None:
        matches = _extract_vars(current)
        if not matches:
            break
        # Deterministic: process matches in order found, but collect unique vars in sorted order for stability
        # We will attempt to resolve each var found this round
        # (removed dead variables: progressed/next_value — were unused)
        # For chain recording, group by variable but we record one step per distinct var resolved this iteration
        # Use deterministic sorted unique vars present in current that are resolvable this round
        vars_in_current = []
        for m in matches:
            braced = m.group("braced")
            default = m.group("default")
            unbraced = m.group("unbraced")
            var = braced if braced is not None else unbraced
            if var not in vars_in_current:
                vars_in_current.append(var)

        # Detect cycle: if we revisit same current value or same var at same depth chain loop
        if current in seen_values:
            is_cyclic = True
            break
        seen_values.add(current)

        # Check variable-level cycle: A->B->A loop would cause same var reappearing after resolution
        # We track seen_vars_chain as path; if var already in path and we are about to re-resolve it, cycle
        # Simpler: if all vars in current have been seen before and we loop, mark cyclic
        # We implement: if current contains a var that was previously resolved and now reappears unchanged -> cycle possibility

        # Attempt to resolve each var deterministically (sorted for determinism)
        # But replacement must respect original string positions, so we do regex sub with function
        # We need to know for each match if resolvable

        # Precompute resolvability for deterministic decision: which vars can be resolved this round
        resolvable_vars: Dict[str, Tuple[str, str, bool]] = {}  # var -> (value, source, default_used)
        for var in sorted(vars_in_current):
            # Find representative match for default handling (first occurrence)
            rep_match = next((m for m in matches if (m.group("braced") or m.group("unbraced")) == var), None)
            default = rep_match.group("default") if rep_match else None
            if var in lookup:
                v, src = lookup[var]
                resolvable_vars[var] = (v, src, False)
            elif default is not None:
                # fallback syntax provides concrete value even if var missing
                resolvable_vars[var] = (default, f"default:{var}:-{default}", True)
            else:
                # not resolvable this round
                pass

        if not resolvable_vars:
            # No var in current can be resolved -> stop, unresolved remains
            break

        # Build next_value by replacing all resolvable occurrences
        # Deterministic: iterate matches in order, replace with lookup value
        def _repl(m: re.Match) -> str:
            braced = m.group("braced")
            default = m.group("default")
            unbraced = m.group("unbraced")
            var = braced if braced is not None else unbraced
            if var in resolvable_vars:
                return resolvable_vars[var][0]
            if var in lookup:
                return lookup[var][0]
            if default is not None:
                return default
            return m.group(0)

        new_value = _ENV_VAR_PATTERN.sub(_repl, current)

        if new_value == current:
            break  # no progress

        # Record steps for each var resolved this iteration (sorted deterministic)
        for var in sorted(resolvable_vars.keys()):
            val, src, default_used = resolvable_vars[var]
            raw_ref = "${" + var + "}"  # canonical; actual may differ but keep var for trace
            # Find actual raw occurrence for reporting
            # Use first match's raw
            actual_raw = next((m.group(0) for m in matches if (m.group("braced") or m.group("unbraced")) == var), raw_ref)
            steps.append(ResolutionStep(
                variable=var,
                raw_reference=actual_raw,
                from_value=current,
                to_value=new_value,
                source=src,
                default_used=default_used,
            ))
            # Cycle check: if variable reintroduces itself
            if var in seen_vars_chain and new_value == current:
                is_cyclic = True
        # Update seen vars
        for var in resolvable_vars:
            seen_vars_chain.add(var)

        current = new_value
        depth += 1

        # Detect direct self-reference cycle: current now equals some earlier value and still has vars
        if current in seen_values and _is_unresolved_fragment(current):
            is_cyclic = True
            break

    # After loop, current is final_value (may still contain unresolved fragments)
    final_value = current

    # Collect unresolved vars remaining
    unresolved = tuple(_extract_unresolved_vars(final_value) if final_value else [])

    # Determine protocol / normalized identity
    protocol = None
    normalized = None
    host: Optional[str] = None
    has_unresolved = bool(unresolved)

    if final_value and "://" in final_value and not _is_unresolved_fragment(final_value.split("://")[0]):
        # Only attempt connection parsing if scheme part doesn't contain unresolved placeholder
        protocol, normalized, host = _normalize_connection_identity(final_value)
        # If parse failed due to unresolved inside host, protocol may be None but scheme recognized
        # Try fallback: extract scheme even if host contains placeholder
        if protocol is None and "://" in final_value:
            # Extract scheme prefix deterministically
            maybe_scheme = final_value.split("://")[0].split("/")[-1].split("?")[0].lower()
            # Clean unresolved placeholders from scheme part
            maybe_scheme_clean = re.sub(r"\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*", "", maybe_scheme).strip()
            if maybe_scheme_clean in SUPPORTED_SCHEMES:
                protocol = SCHEME_CANONICAL.get(maybe_scheme_clean, maybe_scheme_clean)
                # Still unresolved -> normalized is None, host unresolved

    # Check internal service match (plain host without scheme, or host from URI)
    resolved_service = None
    resolved_image = None
    internal_via_host = False
    if project and hasattr(project, "services"):
        # Case 1: final_value is plain service name (e.g. "database" or "postgres:5432/database")
        # For URI-derived host, always consider (structure determines host)
        plain_host = final_value.split(":")[0].split("/")[0].strip() if final_value else ""
        check_host = host if host else plain_host
        # For URI host, treat as internal if matches service regardless of resource name
        if host and check_host and check_host in project.services:
            resolved_service = check_host
            svc = project.services[check_host]
            resolved_image = svc.image
            internal_via_host = True
        # Plain value without scheme: only treat as internal if resource is host-like
        # (avoid DB_NAME=orders -> orders service false positive)
        elif not protocol and not host and final_value and not has_unresolved:
            is_host_like = _is_host_like_resource(resource)
            # Also allow host-like via value shape (contains dot/colon/slash suggests host)
            if not is_host_like and (":" in final_value or "/" in final_value):
                is_host_like = True
            if is_host_like:
                if final_value in project.services:
                    resolved_service = final_value
                    resolved_image = project.services[final_value].image
                    internal_via_host = True
                else:
                    base = final_value.split(":")[0].strip()
                    if base in project.services:
                        resolved_service = base
                        resolved_image = project.services[base].image
                        internal_via_host = True

    # Determine resolution_status
    # Priority:
    #   cyclic/unresolvable -> UNRESOLVED (with flag)
    #   internal host confirmed + protocol maybe -> INTERNAL (even if URI)
    #   supported URI fully resolved, host confirmed, db maybe -> EXTERNAL_CONFIRMED
    #   supported URI partially unresolved -> PARTIAL
    #   unsupported/unknown scheme or plain value unresolved -> UNRESOLVED or PARTIAL
    status: ResolutionStatus
    if is_cyclic:
        # Cycle detected -> UNRESOLVED (honest)
        status = STATUS_UNRESOLVED
        normalized = None
        # keep protocol if known but identity invalid
    elif internal_via_host and protocol:
        # URI whose host is internal service -> INTERNAL (strongest)
        status = STATUS_INTERNAL
        # normalized already computed (or compute)
        if not normalized and host:
            # compute with internal host
            protocol_try, norm_try, _ = _normalize_connection_identity(final_value)
            if norm_try:
                normalized = norm_try
    elif internal_via_host and not protocol:
        # Plain host pointing to compose service (e.g., DB_HOST=postgres)
        # But guard: only INTERNAL if host-like resource expectation? We treat any plain match as INTERNAL
        status = STATUS_INTERNAL
        normalized = f"service|{resolved_service}"
        protocol = protocol or None
    elif protocol and normalized and not has_unresolved:
        # Supported URI fully resolved and host external
        status = STATUS_EXTERNAL_CONFIRMED
    elif protocol and has_unresolved:
        # Supported scheme but unresolved vars remain (e.g., postgresql://${HOST}/db)
        # We have partial structure
        status = STATUS_PARTIAL
        # Keep normalized if we could compute partially, else attempt partial normalized with placeholders
        # For deterministic evidence, keep existing normalized if available else create placeholder identity
        if not normalized:
            # Try to build partial normalized with placeholder host
            # Use final_value's scheme + placeholder markers
            normalized = f"{protocol}|UNRESOLVED|{''}|{''}"
            # Keep as partial indicator but not exact identity
    elif has_unresolved:
        # Unresolved template with no recognized protocol -> UNRESOLVED, but may still be CONFIG identity
        # Distinguish: if unresolved template shared, that's CONFIG identity later, but status stays UNRESOLVED
        status = STATUS_UNRESOLVED
        normalized = None
    else:
        # Fully resolved but not a recognized connection string and not internal
        # e.g., shared-db that is not a service, or simple external host string without scheme
        # Honest: UNRESOLVED (cannot prove external resource identity)
        # However plain "prod-db.company.com" without scheme maybe considered external but not confirmed via protocol
        # We treat non-URI external host as UNRESOLVED to avoid inventing identity
        # Exception: if value looks like external hostname with dot and no unresolved, we could mark PARTIAL? But spec says do not invent.
        status = STATUS_UNRESOLVED
        normalized = None

    # Determine identity_strength
    strength: IdentityStrength
    if status == STATUS_INTERNAL and normalized:
        # Internal service deterministically identified -> EXACT if no unresolved
        if not has_unresolved:
            strength = STRENGTH_EXACT
        else:
            strength = STRENGTH_CONFIG
    elif status == STATUS_EXTERNAL_CONFIRMED and normalized and not has_unresolved:
        # External confirmed with full components
        # For postgres we want host+db at least; but if port missing we still consider EXACT? use presence of host+db
        # Check if normalized contains host and db non-empty
        parts = normalized.split("|") if normalized else []
        # parts: protocol|host|port|db
        host_part = parts[1] if len(parts) > 1 else ""
        db_part = parts[3] if len(parts) > 3 else ""
        if host_part and db_part and not has_unresolved:
            strength = STRENGTH_EXACT
        elif host_part and not has_unresolved:
            strength = STRENGTH_EXACT  # host alone enough for some resources (redis without db)
        else:
            strength = STRENGTH_CONFIG
    elif status in (STATUS_PARTIAL, STATUS_UNRESOLVED) and has_unresolved:
        # Shared config template but not proven physical resource
        # If final_value still deterministic string with unresolved placeholders, and both services share same template,
        # that's CONFIG strength if unresolved but template identical
        # We signal CONFIG if we have protocol or final_value stable
        if protocol or final_value:
            strength = STRENGTH_CONFIG
        else:
            strength = STRENGTH_UNKNOWN
    elif has_unresolved:
        strength = STRENGTH_CONFIG
    else:
        # No identity
        strength = STRENGTH_UNKNOWN

    # Edge: plain shared config that is unresolved but deterministic (same string across services)
    # should be CONFIG not UNKNOWN — they share same configuration expression even if physical not proven
    if status == STATUS_UNRESOLVED and not has_unresolved and not normalized and final_value:
        # No protocol, not internal, but deterministic final value exists — same config template
        # Distinguish from truly empty unknown
        strength = STRENGTH_CONFIG
    # Named volume already returned earlier
    if not normalized and status in (STATUS_UNRESOLVED, STATUS_PARTIAL):
        pass

    return ResolutionResult(
        original_value=original_value,
        final_value=final_value,
        chain=tuple(steps),
        resolution_status=status,
        resource_protocol=protocol,
        normalized_identity=normalized,
        identity_strength=strength,
        unresolved_vars=tuple(sorted(unresolved)),
        is_cyclic=is_cyclic,
        depth_reached=depth,
        resolved_service=resolved_service,
        resolved_image=resolved_image,
    )

