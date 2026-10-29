import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FolderOpen,
  FolderSearch,
  Loader2,
  Play,
  RefreshCw,
} from "lucide-react";
import { analyzeRepository } from "../api";
import type { RunSummary } from "../types";

interface AnalyzeTabProps {
  runs: RunSummary[];
  currentId: string | null;
  onOpenRun: (id: string) => void;
  onRefresh: () => Promise<void>;
}

function count(run: RunSummary, key: string): number {
  const value = run.summary[key];
  return typeof value === "number" ? value : 0;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AnalyzeTab({ runs, currentId, onOpenRun, onRefresh }: AnalyzeTabProps) {
  const [path, setPath] = useState(
    () => window.localStorage.getItem("blindspot.analyze.path") ?? "",
  );
  const [thinking, setThinking] = useState<"low" | "medium" | "high">("low");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const repoPath = path.trim();
    if (!repoPath || busy) return;
    window.localStorage.setItem("blindspot.analyze.path", repoPath);
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await analyzeRepository(repoPath, thinking);
      if (!response.ok) {
        setError(
          [response.message, response.stderr, response.stdout]
            .filter(Boolean)
            .join("\n")
            .trim(),
        );
        return;
      }
      setResult(response.message);
      await onRefresh();
      if (response.run) {
        onOpenRun(response.run.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="analyze">
      <div className="analyze-inner">
        <h2>Analyze a repository</h2>
        <p className="analyze-intro">
          Point BlindSpot at a local repository containing Docker Compose files. The
          existing pipeline runs locally and writes a new deterministic run into
          <code> out/</code>. Nothing is uploaded to a cloud service.
        </p>

        <form className="panel" onSubmit={submit}>
          <h3>Local repository</h3>
          <p className="panel-sub">
            The path is resolved on the machine running the local API. Only Compose and
            environment files are read; Docker does not need to be running.
          </p>
          <div className="field">
            <label htmlFor="repo-path">Repository path</label>
            <input
              id="repo-path"
              className="input"
              value={path}
              onChange={(event) => setPath(event.target.value)}
              placeholder="C:\projects\my-microservices"
              spellCheck={false}
              autoComplete="off"
            />
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="thinking">LLM thinking level</label>
              <select
                id="thinking"
                className="input"
                value={thinking}
                onChange={(event) =>
                  setThinking(event.target.value as "low" | "medium" | "high")
                }
              >
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </div>
          </div>

          {error ? (
            <div className="notice error">
              <AlertTriangle size={14} />
              <span style={{ whiteSpace: "pre-wrap" }}>{error}</span>
            </div>
          ) : null}
          {result ? (
            <div className="notice ok">
              <CheckCircle2 size={14} />
              <span>{result}</span>
            </div>
          ) : null}

          <div className="button-row">
            <button className="primary-button" type="submit" disabled={busy || !path.trim()}>
              {busy ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
              {busy ? "Analyzing…" : "Run analysis"}
            </button>
            <button
              className="toggle"
              type="button"
              onClick={() => void onRefresh()}
              disabled={busy}
            >
              <RefreshCw size={13} />
              Refresh runs
            </button>
          </div>
          <p className="hint" style={{ marginTop: 10 }}>
            If no LLM API key is configured, the CLI continues in deterministic-only mode.
            Potential hidden dependencies are then reported with lower certainty.
          </p>
        </form>

        <div className="panel">
          <h3>Existing runs</h3>
          <p className="panel-sub">
            Generated analyses found under <code>out/</code>. Open one to inspect its
            unified relationship graph.
          </p>
          {runs.length === 0 ? (
            <div className="notice">
              <FolderSearch size={14} />
              <span>No runs found yet. Analyze a repository above to create one.</span>
            </div>
          ) : (
            <div className="recent-list">
              {runs.map((run) => (
                <button
                  className="recent-item"
                  key={run.id}
                  onClick={() => onOpenRun(run.id)}
                  style={
                    run.id === currentId
                      ? { background: "var(--bg-elevated)" }
                      : undefined
                  }
                >
                  <FolderOpen size={15} style={{ color: "var(--text-dim)", flex: "0 0 auto" }} />
                  <span className="recent-main">
                    <span className="recent-name">{run.path}</span>
                    <span className="recent-meta">
                      {formatDate(run.modified)} · {count(run, "service_nodes")} services ·{" "}
                      {count(run, "explicit_edges")} explicit ·{" "}
                      {count(run, "hidden_edges")} hidden/review
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
