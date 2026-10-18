"""BlindSpot Stage 4: Resource Investigation Context Contract.

Formal, typed, deterministic, bounded investigation contexts for grouped
LLM judgment. Replaces informal prompt-string assembly with a versioned
schema covering:

  A. Investigation metadata
  B. Resource summary
  C. Participating services
  D. Candidate evidence
  E. Conflicting / differentiating evidence
  F. Evidence boundaries

Secrets are redacted. Serialization is deterministic. Oversized groups
split deterministically; single-candidate overflow fails safely.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .filtering import EvidencePackage, EVIDENCE_SCHEMA_VERSION
from .secrets import redact_value_for_key, redact_mapping, redact_url_credentials, REDACTED

CONTEXT_SCHEMA_VERSION = "1"
PROMPT_VERSION = "stage4-v1"

# Conservative estimation when no provider tokenizer is available.
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class ContextBudget:
    """Configurable limits for one investigation context payload."""

    max_serialized_chars: int = 12000
    max_estimated_tokens: int = 4000
    reserved_output_tokens: int = 500
    max_candidates_per_group: int = 8

    def estimate_tokens(self, serialized_chars: int) -> int:
        return (serialized_chars + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


@dataclass(frozen=True)
class ServiceParticipation:
    service_id: str
    service_name: str
    reason: str
    config_values: Tuple[Tuple[str, Optional[str]], ...]  # sorted, redacted
    provenance: Optional[str]
    candidate_refs: Tuple[str, ...]
    service_refs: Tuple[str, ...]
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_id": self.service_id,
            "service_name": self.service_name,
            "reason": self.reason,
            "config_values": [{"key": k, "value": v} for k, v in self.config_values],
            "provenance": self.provenance,
            "candidate_refs": list(self.candidate_refs),
            "service_refs": list(self.service_refs),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class CandidateEvidenceView:
    candidate_id: str
    relationship_type: str
    origin: str
    original_evidence: str
    normalized_evidence: Dict[str, Any]  # redacted EvidencePackage.to_dict()
    resolution_status: str
    evidence_refs: Tuple[str, ...]
    uncertainty: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "relationship_type": self.relationship_type,
            "origin": self.origin,
            "original_evidence": self.original_evidence,
            "normalized_evidence": self.normalized_evidence,
            "resolution_status": self.resolution_status,
            "evidence_refs": list(self.evidence_refs),
            "uncertainty": list(self.uncertainty),
        }


@dataclass(frozen=True)
class InvestigationContext:
    """One bounded resource-investigation context (sections A–F)."""

    # A. metadata
    investigation_id: str
    context_schema_version: str
    evidence_schema_version: str
    prompt_version: str
    resource_identity: Optional[str]
    resource_type: str
    resolution_status: str
    group_reason: str
    candidate_ids: Tuple[str, ...]
    # B. resource summary
    resource_kind: str  # service | db_server | logical_db | volume | other | unknown
    resource_summary: str
    identity_facts: Tuple[str, ...]
    identity_unknowns: Tuple[str, ...]
    infra_vs_logical: str
    # C. services
    services: Tuple[ServiceParticipation, ...]
    # D. candidates
    candidates: Tuple[CandidateEvidenceView, ...]
    # E. conflicting evidence
    conflicting_evidence: Tuple[str, ...]
    # F. boundaries
    config_facts: Tuple[str, ...]
    resolution_results: Tuple[str, ...]
    interpretations_requested: Tuple[str, ...]
    unavailable_info: Tuple[str, ...]
    # budget bookkeeping
    omitted_context: Tuple[str, ...] = ()
    truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "a_metadata": {
                "investigation_id": self.investigation_id,
                "context_schema_version": self.context_schema_version,
                "evidence_schema_version": self.evidence_schema_version,
                "prompt_version": self.prompt_version,
                "resource_identity": self.resource_identity,
                "resource_type": self.resource_type,
                "resolution_status": self.resolution_status,
                "group_reason": self.group_reason,
                "candidate_ids": list(self.candidate_ids),
            },
            "b_resource_summary": {
                "resource_kind": self.resource_kind,
                "summary": self.resource_summary,
                "identity_facts": list(self.identity_facts),
                "identity_unknowns": list(self.identity_unknowns),
                "infra_vs_logical": self.infra_vs_logical,
            },
            "c_services": [s.to_dict() for s in self.services],
            "d_candidates": [c.to_dict() for c in self.candidates],
            "e_conflicting_evidence": list(self.conflicting_evidence),
            "f_boundaries": {
                "config_facts": list(self.config_facts),
                "resolution_results": list(self.resolution_results),
                "interpretations_requested": list(self.interpretations_requested),
                "unavailable_info": list(self.unavailable_info),
            },
            "budget": {
                "omitted_context": list(self.omitted_context),
                "truncated": self.truncated,
            },
        }

    def to_canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def cache_key_dict(self) -> Dict[str, Any]:
        return {
            "investigation_id": self.investigation_id,
            "context_schema_version": self.context_schema_version,
            "evidence_schema_version": self.evidence_schema_version,
            "prompt_version": self.prompt_version,
            "resource_identity": self.resource_identity,
            "resource_type": self.resource_type,
            "resolution_status": self.resolution_status,
            "candidate_ids": list(self.candidate_ids),
            "services": [s.to_dict() for s in self.services],
            "candidates": [c.to_dict() for c in self.candidates],
            "conflicting_evidence": list(self.conflicting_evidence),
        }


def _stable_group_id(grouping_key: str, candidate_ids: List[str]) -> str:
    payload = json.dumps(
        {"grouping_key": grouping_key, "candidates": sorted(candidate_ids)},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _resource_kind_for(pkg: EvidencePackage, normalized: Optional[str]) -> str:
    if pkg.resource_type == "named_volume":
        return "volume"
    if pkg.resource_type == "service_dependency":
        return "service"
    if pkg.resource_type == "shared_endpoint" or pkg.resource_protocol:
        proto = (pkg.resource_protocol or "").lower()
        if proto in ("postgresql", "postgres", "mysql", "mongodb", "mongodb+srv", "redis"):
            # Full identity with db → logical db; server-only handled by caller
            # when conflicting DB names exist (still logical_db kind with note).
            return "logical_db"
        return "other"
    if pkg.resolved_service and pkg.resolution_status == "internal":
        return "service"
    return "unknown"


def _build_conflicting_evidence(pkgs: List[EvidencePackage]) -> List[str]:
    conflicts: List[str] = []
    # Different logical DB names sharing same server.
    by_server: Dict[str, set] = {}
    for p in pkgs:
        norm = p.normalized_identity
        if not norm or norm.startswith(("named_volume|", "service|", "raw:")):
            continue
        parts = norm.split("|")
        if len(parts) >= 4:
            server = "|".join(parts[:3])
            db = parts[3]
            by_server.setdefault(server, set()).add(db or "(empty)")
    for server, dbs in sorted(by_server.items()):
        if len(dbs) > 1:
            conflicts.append(
                f"same server {server!r} but different logical databases {sorted(dbs)!r} — "
                "not the same logical database"
            )
    # Different endpoints / identities in one group (shouldn't happen after
    # identity grouping, but surface if it does).
    norms = sorted({p.normalized_identity for p in pkgs if p.normalized_identity})
    if len(norms) > 1:
        # Only flag when server differs (db-only difference already covered).
        servers = sorted({n.split("|")[1] if "|" in (n or "") else n for n in norms})
        if len(servers) > 1:
            conflicts.append(f"different resource identities in group: {norms}")
    # Different volume targets.
    targets = set()
    for p in pkgs:
        if p.volume_targets:
            targets.add(tuple(sorted(p.volume_targets.items())))
    if len(targets) > 1:
        conflicts.append(f"different volume mount targets: {sorted(map(str, targets))}")
    # Different raw values for same key (redacted when secret).
    raws = sorted({str(redact_value_for_key(pkgs[0].resource, redact_url_credentials(p.raw_value or p.value)))
                   for p in pkgs if (p.raw_value or p.value)})
    if len(raws) > 1 and all(p.resource == pkgs[0].resource for p in pkgs):
        conflicts.append(f"different configuration values for {pkgs[0].resource!r}: {raws}")
    # Generic-only signal.
    if pkgs and all(p.generic_variable for p in pkgs):
        conflicts.append("candidates share only a generic variable name — weak signal")
    # Unresolved.
    unresolved = sorted({v for p in pkgs for v in p.unresolved_vars})
    if unresolved:
        conflicts.append(f"unresolved interpolation/external refs: {unresolved}")
    return sorted(conflicts)


def _redacted_grouping_key(key: str) -> str:
    """Redact secret values embedded in raw fallback grouping keys."""
    try:
        if key.startswith("raw:"):
            # raw:{type}:{resource}:{value} — value may contain colons (URLs).
            parts = key.split(":", 3)
            if len(parts) == 4:
                _, rtype, resource, val = parts
                red = redact_value_for_key(resource, redact_url_credentials(val))
                return f"raw:{rtype}:{resource}:{red}"
        return redact_url_credentials(key) or key
    except Exception:
        return key


def build_investigation_context(
    grouping_key: str,
    pkgs: List[EvidencePackage],
    group_reason: str = "",
    budget: Optional[ContextBudget] = None,
) -> InvestigationContext:
    """Build one deterministic, secret-safe investigation context.

    pkgs must already share a defensible resource relationship (caller groups
    by stable identity). Unrelated resources must not be merged by callers.
    """
    pkgs_sorted = sorted(pkgs, key=lambda p: (p.candidate_id or "", p.service_a, p.service_b, p.resource))
    candidate_ids = tuple(p.candidate_id or f"{p.service_a}/{p.service_b}/{p.resource}" for p in pkgs_sorted)
    investigation_id = _stable_group_id(grouping_key, list(candidate_ids))
    safe_key = _redacted_grouping_key(grouping_key)
    if not group_reason:
        group_reason = f"grouped by {safe_key}"
    else:
        group_reason = group_reason.replace(grouping_key, safe_key)

    first = pkgs_sorted[0]
    normalized = first.normalized_identity
    # If group mixes identities, identity is ambiguous → keep first + flag conflict.
    mixed = len({p.normalized_identity for p in pkgs_sorted}) > 1
    if mixed and not normalized:
        resource_identity = None
    elif normalized:
        resource_identity = normalized
    elif first.value:
        # Secret-safe fallback: redact secret-keyed values and URL credentials.
        red_val = redact_value_for_key(first.resource, redact_url_credentials(first.value))
        resource_identity = f"{first.resource}={red_val}" if red_val else first.resource
    else:
        resource_identity = first.resource

    kind = _resource_kind_for(first, normalized)
    facts: List[str] = []
    unknowns: List[str] = []
    if normalized and normalized.startswith("named_volume|"):
        facts.append(f"named volume {normalized.split('|', 1)[-1]!r} mounted by participating services")
    elif normalized and "|" in normalized and not normalized.startswith("service|"):
        parts = normalized.split("|")
        facts.append(f"normalized identity {normalized!r} (protocol {parts[0]!r})")
        if len(parts) >= 4 and parts[3]:
            facts.append(f"logical database {parts[3]!r} on host {parts[1]!r}")
        else:
            unknowns.append("logical database name unknown")
        if not parts[1]:
            unknowns.append("host unknown")
    elif normalized and normalized.startswith("service|"):
        facts.append(f"Compose service {normalized.split('|', 1)[-1]!r}")
    else:
        unknowns.append("final resource identity unresolved from configuration")
    if first.unresolved_vars:
        unknowns.append(f"unresolved vars: {', '.join(sorted(first.unresolved_vars))}")
    if first.resolution_status in ("unresolved", "partial"):
        unknowns.append(f"resolution {first.resolution_status} (strength {first.identity_strength})")

    infra_vs_logical = (
        "Infrastructure resource (server/volume/service) vs logical application resource "
        "(database/schema/table) are distinct: sharing a server does not prove sharing a logical database; "
        "sharing a volume does not prove file-level reliance."
    )
    summary = (
        f"Resource {resource_identity!r} ({kind}, {first.resolution_status}) "
        f"referenced by {len({s for p in pkgs_sorted for s in (p.service_a, p.service_b)})} service(s) "
        f"across {len(pkgs_sorted)} candidate(s)."
    )

    # C. services: union of participants, deterministic.
    svc_names = sorted({s for p in pkgs_sorted for s in (p.service_a, p.service_b)})
    svc_views: List[ServiceParticipation] = []
    for svc in svc_names:
        related: Dict[str, Optional[str]] = {}
        prov: Optional[str] = None
        refs: List[str] = []
        svc_ref_list: List[str] = []
        limits: List[str] = []
        cand_refs: List[str] = []
        for p in pkgs_sorted:
            if svc in (p.service_a, p.service_b):
                cid = p.candidate_id or f"{p.service_a}/{p.service_b}/{p.resource}"
                cand_refs.append(cid)
                refs.append(f"candidate:{cid}")
                cfg = p.related_config.get(svc, {})
                for k in sorted(cfg.keys()):
                    # Redact secrets; keep non-sensitive.
                    related[k] = redact_value_for_key(k, cfg[k])
                if p.provenance and not prov:
                    prov = p.provenance
                if p.resolved_service:
                    svc_ref_list.append(f"service:{p.resolved_service}")
                for m in p.missing_info:
                    if m not in limits:
                        limits.append(m)
        # Reason for participation.
        reason = f"participant in {len([p for p in pkgs_sorted if svc in (p.service_a, p.service_b)])} candidate(s)"
        svc_views.append(
            ServiceParticipation(
                service_id=f"service:{svc}",
                service_name=svc,
                reason=reason,
                config_values=tuple(sorted(related.items())),
                provenance=prov,
                candidate_refs=tuple(sorted(set(cand_refs))),
                service_refs=tuple(sorted(set(svc_ref_list))),
                limitations=tuple(sorted(limits)),
            )
        )

    # D. candidates: preserve identity, redact secrets.
    cand_views: List[CandidateEvidenceView] = []
    for p in pkgs_sorted:
        cid = p.candidate_id or f"{p.service_a}/{p.service_b}/{p.resource}"
        # Relationship/origin best-effort from resource_type.
        rel = {"env_var": "shared_env", "named_volume": "shared_volume",
               "service_dependency": "explicit_dependency",
               "shared_endpoint": "shared_endpoint"}.get(p.resource_type, "unknown")
        origin = {"env_var": "compose:environment", "named_volume": "compose:volumes",
                  "service_dependency": "compose:depends_on",
                  "shared_endpoint": "derived:endpoint-identity"}.get(p.resource_type, "unknown")
        unc = tuple(sorted(set(list(p.missing_info) + ([f"unresolved: {', '.join(sorted(p.unresolved_vars))}"] if p.unresolved_vars else []))))
        # Redact free-text original evidence (may embed secret values/URLs).
        raw_ev = redact_url_credentials(p.evidence) or ""
        for key, val in ((p.resource, p.value), (p.resource, p.raw_value)):
            if val and isinstance(val, str) and len(val) >= 4 and val in raw_ev:
                try:
                    from .secrets import is_secret_key as _iss2

                    if _iss2(key) or ("@" in val and "://" in val):
                        raw_ev = raw_ev.replace(val, REDACTED)
                except Exception:
                    pass
        cand_views.append(
            CandidateEvidenceView(
                candidate_id=cid,
                relationship_type=rel,
                origin=origin,
                original_evidence=raw_ev,
                normalized_evidence=p.to_dict(),
                resolution_status=p.resolution_status,
                evidence_refs=tuple(p.evidence_refs),
                uncertainty=unc,
            )
        )

    conflicts = tuple(_build_conflicting_evidence(pkgs_sorted))

    config_facts = tuple(sorted({
        f"{p.service_a}/{p.service_b} share {p.resource_type} {p.resource!r}"
        + (f" (normalized {p.normalized_identity!r})" if p.normalized_identity else "")
        for p in pkgs_sorted
    }))
    resolution_results = tuple(sorted({
        f"{p.resource}: {p.resolution_status}/{p.identity_strength}"
        + (f" -> {p.resolved_service}" if p.resolved_service else "")
        for p in pkgs_sorted
    }))
    interpretations = (
        "Assess whether each candidate is meaningful (shared resource implies implicit coupling), "
        "coincidental (same name/value by chance), or uncertain (insufficient evidence). "
        "Use only supplied evidence refs; consider conflicting evidence; distinguish "
        "database server from logical database and infrastructure sharing from proven "
        "application-level interaction.",
    )
    unavailable = (
        "Runtime connectivity, actual reads/writes, data ownership, and application-level "
        "coupling cannot be inferred from configuration alone and are unavailable.",
    )

    return InvestigationContext(
        investigation_id=investigation_id,
        context_schema_version=CONTEXT_SCHEMA_VERSION,
        evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
        prompt_version=PROMPT_VERSION,
        resource_identity=resource_identity,
        resource_type=first.resource_type,
        resolution_status=first.resolution_status,
        group_reason=group_reason or f"grouped by {grouping_key}",
        candidate_ids=candidate_ids,
        resource_kind=kind,
        resource_summary=summary,
        identity_facts=tuple(sorted(facts)),
        identity_unknowns=tuple(sorted(unknowns)),
        infra_vs_logical=infra_vs_logical,
        services=tuple(svc_views),
        candidates=tuple(cand_views),
        conflicting_evidence=conflicts,
        config_facts=config_facts,
        resolution_results=resolution_results,
        interpretations_requested=interpretations,
        unavailable_info=unavailable,
    )


def context_fits_budget(ctx: InvestigationContext, budget: ContextBudget) -> Tuple[bool, int, int]:
    """Return (fits, serialized_chars, estimated_tokens)."""
    serialized = ctx.to_canonical_json()
    chars = len(serialized)
    tokens = budget.estimate_tokens(chars) + budget.reserved_output_tokens
    fits = chars <= budget.max_serialized_chars and tokens <= budget.max_estimated_tokens
    return fits, chars, tokens


def split_group_deterministically(
    grouping_key: str,
    pkgs: List[EvidencePackage],
    budget: ContextBudget,
    group_reason: str = "",
) -> List[InvestigationContext]:
    """Split an oversized group along candidate boundaries (deterministic).

    Chunks of max_candidates_per_group; each chunk rebuilt + budget-validated.
    Single-candidate overflow that still exceeds budget raises ContextTooLarge
    (explicit failure) instead of silent truncation.
    """
    ordered = sorted(pkgs, key=lambda p: (p.candidate_id or "", p.service_a, p.service_b, p.resource))
    chunks = [ordered[i:i + budget.max_candidates_per_group] for i in range(0, len(ordered), budget.max_candidates_per_group)] or [[]]
    out: List[InvestigationContext] = []
    for idx, chunk in enumerate(chunks):
        if not chunk:
            continue
        reason = group_reason or f"grouped by {grouping_key}"
        if len(chunks) > 1:
            reason = f"{reason} (part {idx + 1}/{len(chunks)}, deterministic split)"
        ctx = build_investigation_context(grouping_key, chunk, group_reason=reason, budget=budget)
        fits, chars, _ = context_fits_budget(ctx, budget)
        if not fits:
            if len(chunk) == 1:
                raise ContextTooLarge(
                    f"single candidate {chunk[0].candidate_id!r} exceeds budget "
                    f"({chars} chars > {budget.max_serialized_chars})"
                )
            # Recurse with smaller chunks (halve deterministically).
            mid = len(chunk) // 2
            out.extend(split_group_deterministically(grouping_key, chunk[:mid], budget, group_reason))
            out.extend(split_group_deterministically(grouping_key, chunk[mid:], budget, group_reason))
        else:
            out.append(ctx)
    return out


class ContextTooLarge(Exception):
    """Essential evidence cannot fit safely — explicit construction failure."""


def build_contexts_for_packages(
    packages: List[EvidencePackage],
    budget: Optional[ContextBudget] = None,
) -> Tuple[List[InvestigationContext], List[Dict[str, Any]]]:
    """Group packages by stable identity then build bounded contexts.

    Returns (contexts, failures). Unresolved candidates without identity are
    kept separate per raw resource (never merged). No candidate is dropped:
    overflow yields explicit failure entries.
    """
    from .aggregation import _grouping_key  # local import to avoid cycle

    budget = budget or ContextBudget()
    groups: Dict[str, List[EvidencePackage]] = {}
    for p in packages:
        groups.setdefault(_grouping_key(p), []).append(p)
    contexts: List[InvestigationContext] = []
    failures: List[Dict[str, Any]] = []
    for key in sorted(groups.keys()):
        chunk = sorted(groups[key], key=lambda p: (p.candidate_id or "", p.service_a, p.service_b, p.resource))
        try:
            contexts.extend(split_group_deterministically(key, chunk, budget))
        except ContextTooLarge as e:
            for p in chunk:
                failures.append({
                    "candidate_id": p.candidate_id,
                    "error_type": "context_too_large",
                    "message": str(e),
                })
    # Deterministic order by investigation_id.
    contexts.sort(key=lambda c: c.investigation_id)
    return contexts, failures
