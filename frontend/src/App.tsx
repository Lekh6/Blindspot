import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  FolderSearch,
  Loader2,
  Network,
  RefreshCw,
  Waypoints,
} from "lucide-react";
import { listRuns, loadRun } from "./api";
import { AnalyzeTab } from "./components/AnalyzeTab";
import { DetailsPanel } from "./components/DetailsPanel";
import { GraphView } from "./components/GraphView";
import type { RunPayload, RunSummary, Selection } from "./types";

type Tab = "graph" | "analyze";

function runCounts(payload: RunPayload | null) {
  if (!payload) return { explicit: 0, hidden: 0, uncertain: 0 };
  let explicit = 0;
  let hidden = 0;
  let uncertain = 0;
  for (const edge of payload.graph.edges) {
    if (edge.data?.classification === "explicit") explicit += 1;
    else if (edge.data?.classification === "potential_hidden") hidden += 1;
    else if (edge.data?.classification === "uncertain") uncertain += 1;
  }
  return { explicit, hidden, uncertain };
}

export default function App() {
  const [tab, setTab] = useState<Tab>(() =>
    new URLSearchParams(window.location.search).get("view") === "analyze"
      ? "analyze"
      : "graph",
  );
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(() => {
    const requested = new URLSearchParams(window.location.search).get("run");
    return requested || null;
  });
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [selection, setSelection] = useState<Selection>(() => {
    const requested = new URLSearchParams(window.location.search).get("select");
    if (!requested) return null;
    return {
      kind:
        requested.startsWith("service:") || requested.startsWith("resource:")
          ? "node"
          : "edge",
      id: requested,
    };
  });
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refreshRuns = useCallback(async () => {
    try {
      const next = await listRuns();
      setRuns(next);
      setApiError(null);
    } catch (err) {
      setApiError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  useEffect(() => {
    if (runs.length === 0) return;
    if (!currentId || !runs.some((run) => run.id === currentId)) {
      setCurrentId(runs[0].id);
    }
  }, [runs, currentId]);

  useEffect(() => {
    if (!currentId) {
      setPayload(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    loadRun(currentId)
      .then((next) => {
        if (!cancelled) {
          setPayload(next);
          setApiError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setPayload(null);
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentId]);

  const counts = runCounts(payload);

  function openRun(id: string) {
    setTab("graph");
    setSelection(null);
    setCurrentId(id);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Waypoints size={16} />
          </span>
          <div>
            <div className="brand-name">BlindSpot</div>
            <div className="brand-sub">implicit coupling explorer</div>
          </div>
        </div>

        <nav className="nav">
          <button
            className={`nav-item${tab === "graph" ? " active" : ""}`}
            onClick={() => setTab("graph")}
          >
            <Network size={15} />
            Dependency graph
          </button>
          <button
            className={`nav-item${tab === "analyze" ? " active" : ""}`}
            onClick={() => setTab("analyze")}
          >
            <FolderSearch size={15} />
            Analyze repository
          </button>
        </nav>

        <div className="sidebar-section">
          <div className="sidebar-label">
            <span>Runs</span>
            <span>{runs.length}</span>
          </div>
          <div className="run-list">
            {runs.map((run) => (
              <button
                className={`run-item${run.id === currentId ? " active" : ""}`}
                key={run.id}
                onClick={() => openRun(run.id)}
                title={run.path}
              >
                <span className="run-name">{run.name}</span>
                <span className="run-meta">
                  {run.id.includes("/") ? run.id : "out/"}
                  {String(
                    (run.summary as Record<string, unknown>).nodes ?? "",
                  ) && (
                    <>
                      {" · "}
                      {String((run.summary as Record<string, unknown>).nodes)} nodes
                    </>
                  )}
                </span>
              </button>
            ))}
            {runs.length === 0 && !apiError ? (
              <span className="run-meta" style={{ padding: "6px 9px" }}>
                No runs yet.
              </span>
            ) : null}
          </div>
        </div>

        <div className="sidebar-footer">
          Local analysis only.
          <br />
          Reading <span className="mono">out/</span> through the local API.
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar-title">
            <h1>
              {tab === "graph"
                ? payload
                  ? payload.name
                  : "Dependency graph"
                : "Analyze repository"}
            </h1>
            <p>
              {tab === "graph"
                ? payload
                  ? `out/${payload.path}`
                  : "Waiting for a run"
                : "Runs the existing local BlindSpot pipeline"}
            </p>
          </div>
          <div className="topbar-spacer" />
          {tab === "graph" && payload ? (
            <div className="stat-row">
              <span className="stat">
                <strong>{counts.explicit}</strong> explicit
              </span>
              <span className="stat hidden">
                <strong>{counts.hidden}</strong> potential
              </span>
              <span className="stat">
                <strong>{counts.uncertain}</strong> uncertain
              </span>
            </div>
          ) : null}
          {tab === "graph" ? (
            <button
              className="icon-button"
              onClick={() => void refreshRuns()}
              title="Refresh runs"
            >
              <RefreshCw size={14} />
            </button>
          ) : null}
        </header>

        {tab === "analyze" ? (
          <div className="content">
            <AnalyzeTab
              runs={runs}
              currentId={currentId}
              onOpenRun={openRun}
              onRefresh={refreshRuns}
            />
          </div>
        ) : apiError ? (
          <div className="error-state">
            <div>
              <AlertTriangle
                size={22}
                style={{ color: "var(--yellow)", marginBottom: 8 }}
              />
              <div>Could not reach the local BlindSpot API.</div>
              <div className="hint" style={{ marginTop: 8 }}>
                Start it with{" "}
                <code>python api/server.py</code> and run{" "}
                <code>npm run dev</code> in <code>frontend/</code>.
              </div>
              <div className="hint" style={{ marginTop: 6 }}>
                {apiError}
              </div>
            </div>
          </div>
        ) : loading ? (
          <div className="loading">
            <span>
              <Loader2 size={18} className="spin" style={{ marginBottom: 8 }} />
              <br />
              Loading graph…
            </span>
          </div>
        ) : loadError ? (
          <div className="error-state">{loadError}</div>
        ) : !payload ? (
          <div className="empty-graph">
            <div className="empty-graph-inner">
              <span className="empty-icon">
                <Network size={20} />
              </span>
              <h2>No analysis loaded</h2>
              <p>
                Generate a run in the Analyze tab, or place an existing{" "}
                <span className="mono">graph.json</span> and{" "}
                <span className="mono">report.json</span> under{" "}
                <span className="mono">out/</span>.
              </p>
              <button
                className="primary-button"
                style={{ marginTop: 16 }}
                onClick={() => setTab("analyze")}
              >
                <FolderSearch size={14} />
                Analyze a repository
              </button>
            </div>
          </div>
        ) : (
          <div className="content">
            <GraphView
              key={payload.id}
              graph={payload.graph}
              selection={selection}
              onSelect={setSelection}
            />
            <DetailsPanel
              graph={payload.graph}
              report={payload.report}
              selection={selection}
              onSelect={setSelection}
              onClose={() => setSelection(null)}
            />
          </div>
        )}
      </main>
    </div>
  );
}
