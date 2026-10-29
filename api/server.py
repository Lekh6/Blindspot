"""Local BlindSpot API.

Serves generated analysis runs from out/ and can launch the existing CLI
against a local repository path. No cloud services, auth, or database.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, cast
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "out"
DIST_ROOT = ROOT / "frontend" / "dist"

RELATIONSHIP_TYPES = {
    "env_var": "shared_env",
    "named_volume": "shared_volume",
    "shared_endpoint": "shared_endpoint",
    "service_dependency": "explicit_dependency",
}
RELATIONSHIP_ORIGINS = {
    "env_var": "compose:environment",
    "named_volume": "compose:volumes",
    "shared_endpoint": "derived:endpoint-identity",
    "service_dependency": "compose:depends_on",
}
VERDICT_CLASSIFICATIONS = {
    "meaningful": "potential_hidden",
    "uncertain": "uncertain",
    "coincidental": "rejected",
}
DECISION_CLASSIFICATIONS = {
    "potential_dependency": "potential_hidden",
    "review": "uncertain",
    "insufficient_evidence": "rejected",
}


def _json_versions(directory: Path, base: str) -> Dict[int, Path]:
    pattern = re.compile(rf"^{re.escape(base)}(?:_(\d+))?\.json$")
    versions: Dict[int, Path] = {}
    if not directory.is_dir():
        return versions
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = pattern.match(path.name)
        if match:
            versions[int(match.group(1) or 0)] = path
    return versions


def _latest_pair(directory: Path) -> Optional[tuple[Path, Path]]:
    graphs = _json_versions(directory, "graph")
    reports = _json_versions(directory, "report")
    shared = sorted(set(graphs) & set(reports), reverse=True)
    if not shared:
        return None
    version = shared[0]
    return graphs[version], reports[version]


def _run_id(directory: Path) -> str:
    return directory.relative_to(OUT_ROOT).as_posix()


def _first_int(summary: Dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = summary.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _run_summary(directory: Path, report: Dict[str, Any], graph: Dict[str, Any]) -> Dict[str, Any]:
    raw_summary = report.get("summary")
    summary: Dict[str, Any] = cast(
        Dict[str, Any], raw_summary if isinstance(raw_summary, dict) else {}
    )
    raw_nodes = graph.get("nodes")
    nodes: List[Dict[str, Any]] = cast(
        List[Dict[str, Any]], raw_nodes if isinstance(raw_nodes, list) else []
    )
    raw_edges = graph.get("edges")
    edges: List[Dict[str, Any]] = cast(
        List[Dict[str, Any]], raw_edges if isinstance(raw_edges, list) else []
    )
    pair = _latest_pair(directory)
    modified = max(path.stat().st_mtime for path in pair) if pair else 0
    return {
        "id": _run_id(directory),
        "name": directory.name,
        "path": _run_id(directory),
        "modified": datetime.fromtimestamp(modified, tz=timezone.utc).isoformat(),
        "summary": {
            **summary,
            "nodes": len(nodes),
            "edges": len(edges),
            "service_nodes": len([n for n in nodes if n.get("type") == "service"]),
            "resource_nodes": len([n for n in nodes if n.get("type") == "resource"]),
            "explicit_edges": len(
                [e for e in edges if e.get("data", {}).get("classification") == "explicit"]
            ),
            "hidden_edges": len(
                [e for e in edges if e.get("data", {}).get("classification") != "explicit"]
            ),
        },
    }


def _load_run(directory: Path) -> Optional[Dict[str, Any]]:
    pair = _latest_pair(directory)
    if pair is None:
        return None
    graph_path, report_path = pair
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    graph, report = _normalize_payload(graph, report)
    return {
        "id": _run_id(directory),
        "name": directory.name,
        "path": _run_id(directory),
        "graph": graph,
        "report": report,
        "_summary": _run_summary(directory, report, graph),
    }


def _normalize_payload(
    graph: Dict[str, Any], report: Dict[str, Any]
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Add unified classification fields to older graph/report outputs."""
    raw_nodes = graph.get("nodes")
    nodes: List[Dict[str, Any]] = cast(
        List[Dict[str, Any]], raw_nodes if isinstance(raw_nodes, list) else []
    )
    raw_edges = graph.get("edges")
    edges: List[Dict[str, Any]] = cast(
        List[Dict[str, Any]], raw_edges if isinstance(raw_edges, list) else []
    )

    # Older outputs represent L0 depends_on as resource nodes. Convert them to
    # explicit service → service edges; the source edge already preserves direction.
    removed_resource_ids: set[str] = set()
    explicit_edges: List[Dict[str, Any]] = []
    for node in nodes:
        if node.get("type") != "resource":
            continue
        data = node.get("data") or {}
        if data.get("resource_type") != "service_dependency":
            continue
        resolved = bool(
            isinstance(data.get("resource_identity"), str)
            and data["resource_identity"].startswith("service|")
        )
        if resolved:
            target = data["resource_identity"].split("|", 1)[1]
        else:
            target = str(data.get("name") or "").split("=", 1)[0]
        if not target:
            continue
        removed_resource_ids.add(str(node.get("id")))
        for edge in edges:
            if edge.get("target") != node.get("id"):
                continue
            source_id = str(edge.get("source", ""))
            if not source_id.startswith("service:"):
                continue
            source = source_id.split(":", 1)[1]
            explicit_edges.append(
                {
                    "id": f"explicit:service:{source}->service:{target}",
                    "source": f"service:{source}",
                    "target": f"service:{target}",
                    "data": {
                        "relationship_type": "explicit_dependency",
                        "classification": "explicit",
                        "semantics": "startup_dependency",
                        "origin": "compose:depends_on",
                        "target_resolved": resolved,
                        "candidate_ids": [edge.get("id", "")],
                        "evidence": "Declared `depends_on` in the Compose configuration.",
                    },
                }
            )

    if explicit_edges:
        nodes = [n for n in nodes if str(n.get("id")) not in removed_resource_ids]
        existing_ids = {str(e.get("id")) for e in edges if e.get("source") != e.get("target")}
        explicit_by_id = {}
        for edge in explicit_edges:
            if edge["id"] not in existing_ids:
                explicit_by_id[edge["id"]] = edge
        edges = [e for e in edges if str(e.get("target")) not in removed_resource_ids]
        edges.extend(explicit_by_id.values())
        service_ids = {str(n.get("id")) for n in nodes if n.get("type") == "service"}
        for edge in explicit_by_id.values():
            target_id = str(edge["target"])
            if target_id not in service_ids:
                nodes.append(
                    {
                        "id": target_id,
                        "type": "service",
                        "data": {
                            "name": target_id.split(":", 1)[1],
                            "resolved": False,
                        },
                    }
                )
                service_ids.add(target_id)

    # Classification fallback from report findings for older hidden edges.
    raw_findings = report.get("findings")
    findings: List[Dict[str, Any]] = cast(
        List[Dict[str, Any]], raw_findings if isinstance(raw_findings, list) else []
    )
    finding_by_identity: Dict[str, Dict[str, Any]] = {}
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        key = finding.get("resource_identity")
        if isinstance(key, str):
            finding_by_identity[key] = finding
        grouping_key = finding.get("grouping_key")
        if isinstance(grouping_key, str):
            finding_by_identity[grouping_key] = finding
    node_by_id = {str(n.get("id")): n for n in nodes if isinstance(n, dict)}
    for edge in edges:
        data = edge.get("data")
        if not isinstance(data, dict) or data.get("classification"):
            continue
        target_node = node_by_id.get(str(edge.get("target")))
        target_data = target_node.get("data", {}) if target_node else {}
        resource_type = str(target_data.get("resource_type", ""))
        finding = finding_by_identity.get(str(target_data.get("resource_identity")))
        if finding is None:
            finding = finding_by_identity.get(str(target_data.get("grouping_key")))
        verdict = str(finding.get("verdict", "")) if finding else ""
        data["relationship_type"] = RELATIONSHIP_TYPES.get(resource_type, resource_type)
        data["origin"] = RELATIONSHIP_ORIGINS.get(resource_type, "unknown")
        data["semantics"] = "resource_mediated"
        data["classification"] = VERDICT_CLASSIFICATIONS.get(verdict, "uncertain")

    # Older reports do not list explicit relationships separately.
    if not report.get("explicit_relationships") and explicit_edges:
        rows = []
        for edge in explicit_edges:
            data = edge["data"]
            source = str(edge["source"]).split(":", 1)[1]
            target = str(edge["target"]).split(":", 1)[1]
            rows.append(
                {
                    "relationship_id": edge["id"],
                    "source": source,
                    "target": target,
                    "source_id": edge["source"],
                    "target_id": edge["target"],
                    "target_resolved": bool(data.get("target_resolved")),
                    "evidence": data.get("evidence", ""),
                    "relationship_type": "explicit_dependency",
                    "semantics": "startup_dependency",
                    "origin": "compose:depends_on",
                    "classification": "explicit",
                    "candidate_ids": data.get("candidate_ids", []),
                }
            )
        report["explicit_relationships"] = rows

    graph["nodes"] = sorted(nodes, key=lambda n: str(n.get("id", "")))
    graph["edges"] = sorted(edges, key=lambda e: str(e.get("id", "")))
    return graph, report


def _list_runs() -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    if not OUT_ROOT.exists():
        return runs
    ignored_prefixes = ("test_", "calcom_grouped")
    directories = {path.parent for path in OUT_ROOT.rglob("graph*.json")}
    for directory in sorted(directories):
        relative = directory.relative_to(OUT_ROOT).as_posix()
        if relative.split("/", 1)[0].startswith(ignored_prefixes):
            continue
        loaded = _load_run(directory)
        if loaded is None:
            continue
        runs.append(loaded["_summary"])
    runs.sort(key=lambda r: (r["modified"], r["id"]), reverse=True)
    return runs


def _run_by_id(run_id: str) -> Optional[Dict[str, Any]]:
    if not run_id:
        return None
    candidate = (OUT_ROOT / run_id).resolve()
    try:
        candidate.relative_to(OUT_ROOT.resolve())
    except ValueError:
        return None
    if not candidate.is_dir():
        return None
    loaded = _load_run(candidate)
    if loaded is None:
        return None
    loaded.pop("_summary", None)
    return loaded


def _analyze(repo_path: str, thinking: str) -> Dict[str, Any]:
    repo = Path(repo_path).expanduser().resolve()
    if not repo.is_dir():
        return {"ok": False, "message": f"Repository path is not a directory: {repo}"}
    if thinking not in ("low", "medium", "high"):
        thinking = "low"
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + existing_pythonpath if existing_pythonpath else ""
    )
    command = [
        sys.executable,
        "-m",
        "blindspot.cli",
        str(repo),
        "--out",
        str(OUT_ROOT),
        "--thinking",
        thinking,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            input="n\n",
            text=True,
            capture_output=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Analysis timed out after 15 minutes."}
    except OSError as exc:
        return {"ok": False, "message": f"Could not start analysis: {exc}"}

    if completed.returncode != 0:
        return {
            "ok": False,
            "message": f"Analysis failed (exit {completed.returncode}).",
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }

    run_dir = OUT_ROOT / repo.name
    loaded = _load_run(run_dir) if run_dir.is_dir() else None
    return {
        "ok": True,
        "message": "Analysis completed.",
        "run": loaded["_summary"] if loaded else None,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "BlindSpotLocal/0.1"

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._send_json({"error": "Not found"}, 404)
            return
        mime, _ = mimetypes.guess_type(str(path))
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> bool:
        if not DIST_ROOT.is_dir():
            return False
        relative = path.lstrip("/") or "index.html"
        candidate = (DIST_ROOT / relative).resolve()
        try:
            candidate.relative_to(DIST_ROOT.resolve())
        except ValueError:
            return False
        if candidate.is_file():
            self._send_file(candidate)
            return True
        index = DIST_ROOT / "index.html"
        if index.is_file():
            self._send_file(index)
            return True
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "out": str(OUT_ROOT)})
            return
        if parsed.path == "/api/runs":
            self._send_json({"runs": _list_runs()})
            return
        if parsed.path == "/api/run":
            run_id = parse_qs(parsed.query).get("id", [""])[0]
            payload = _run_by_id(run_id)
            if payload is None:
                self._send_json({"error": f"Run not found: {run_id}"}, 404)
            else:
                self._send_json(payload)
            return
        if self._serve_static(parsed.path):
            return
        self._send_json(
            {
                "error": "Frontend build not found. Run `npm run build` in frontend/ "
                "or use the Vite dev server."
            },
            404,
        )

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/analyze":
            self._send_json({"error": "Not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send_json({"error": "Invalid JSON body"}, 400)
            return
        repo_path = str(payload.get("path", "")).strip()
        if not repo_path:
            self._send_json({"error": "Missing repository path"}, 400)
            return
        self._send_json(_analyze(repo_path, str(payload.get("thinking", "low"))))

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[api] " + format % args + "\n")


def main() -> None:
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"BlindSpot API listening on http://127.0.0.1:{port}")
    print(f"Serving runs from {OUT_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
