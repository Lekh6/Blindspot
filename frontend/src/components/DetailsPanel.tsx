import { X } from "lucide-react";
import type {
  Classification,
  DecisionView,
  GraphData,
  GraphEdge,
  GraphNode,
  ReportData,
  ReportFinding,
  Selection,
} from "../types";

interface DetailsPanelProps {
  graph: GraphData;
  report: ReportData;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  onClose: () => void;
}

function classificationLabel(value: Classification | undefined): string {
  if (value === "explicit") return "explicit";
  if (value === "potential_hidden") return "potential hidden";
  if (value === "rejected") return "rejected";
  return "uncertain";
}

function classificationClass(value: Classification | undefined): string {
  if (value === "explicit") return "badge";
  if (value === "potential_hidden") return "badge yellow";
  if (value === "rejected") return "badge red";
  return "badge dim";
}

function decisionLabel(value: string | undefined): string {
  if (value === "potential_dependency") return "potential dependency";
  if (value === "insufficient_evidence") return "insufficient evidence";
  if (value === "review") return "review";
  return value ? value.replace(/_/g, " ") : "not judged";
}

function decisionClass(value: string | undefined): string {
  if (value === "potential_dependency") return "badge yellow";
  if (value === "insufficient_evidence") return "badge red";
  return "badge dim";
}

function typeLabel(value: string | undefined): string {
  if (!value) return "Resource";
  return value.replace(/_/g, " ");
}

function percent(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

function formatStep(step: Record<string, unknown>): string {
  return Object.entries(step)
    .map(([key, value]) => {
      const rendered = Array.isArray(value) ? value.join(" → ") : String(value);
      return `${key}: ${rendered}`;
    })
    .join(" · ");
}

function ConfidenceBar({ value }: { value: number | undefined }) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return <span className="muted small">No confidence applies.</span>;
  }
  const clamped = Math.max(0, Math.min(1, value));
  return (
    <div className="confidence">
      <div className="confidence-track">
        <div className="confidence-fill" style={{ width: `${clamped * 100}%` }} />
      </div>
      <span className="confidence-value">{percent(clamped)}</span>
    </div>
  );
}

function Evidence({ values }: { values: Record<string, string[]> }) {
  const rows = Object.entries(values).filter(([, value]) => value.length > 0);
  if (rows.length === 0) {
    return <span className="muted small">No configuration values recorded.</span>;
  }
  return (
    <div className="evidence-list">
      {rows.map(([key, value]) => (
        <div className="evidence-row" key={key}>
          <span className="evidence-key">{key}</span>
          <span className="evidence-vals">{value.join(", ")}</span>
        </div>
      ))}
    </div>
  );
}

function DecisionCards({ decisions }: { decisions: DecisionView[] }) {
  if (decisions.length === 0) {
    return (
      <span className="muted small">
        No Stage 5 decision record. The LLM verdict is shown without policy projection.
      </span>
    );
  }
  return (
    <div>
      {decisions.map((decision) => (
        <div
          className={`decision-card${
            decision.decision === "potential_dependency" ? " hidden" : ""
          }`}
          key={decision.candidate_id}
        >
          <div className="decision-head">
            <span className="decision-title">
              {decision.service_a} → {decision.service_b}
            </span>
            <span className={decisionClass(decision.decision)}>
              {decisionLabel(decision.decision)}
            </span>
          </div>
          <div className="decision-rationale">{decision.rationale}</div>
          <div className="decision-facts">
            <span className="badge dim">
              stage 4: {decision.stage4_verdict} · {percent(decision.stage4_confidence)}
            </span>
            {typeof decision.score === "number" ? (
              <span className="badge dim">score {decision.score.toFixed(2)}</span>
            ) : null}
            {decision.processing_status ? (
              <span className="badge dim">
                {decision.processing_status.replace(/_/g, " ")}
              </span>
            ) : null}
          </div>
          {decision.missing_information.length > 0 ? (
            <ul className="missing-list">
              {decision.missing_information.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function findingForResource(
  report: ReportData,
  node: GraphNode | undefined,
): ReportFinding | undefined {
  if (!node) return undefined;
  const identity = node.data.resource_identity;
  const groupingKey = node.data.grouping_key;
  return report.findings.find(
    (finding) =>
      (identity && finding.resource_identity === identity) ||
      (groupingKey && (finding as ReportFinding & { grouping_key?: string }).grouping_key === groupingKey),
  );
}

function decisionsForNode(
  report: ReportData,
  node: GraphNode,
  finding: ReportFinding | undefined,
): DecisionView[] {
  if (node.data.decisions?.length) return node.data.decisions;
  if (finding?.decisions?.length) return finding.decisions;
  const candidateIds = new Set(node.data.candidate_ids ?? []);
  return (report.decisions ?? []).filter((decision) =>
    candidateIds.has(decision.candidate_id),
  );
}

function Header({
  kicker,
  title,
  subtitle,
  onClose,
}: {
  kicker: string;
  title: string;
  subtitle?: string;
  onClose: () => void;
}) {
  return (
    <div className="details-head">
      <div className="details-head-text">
        <div className="details-kicker">{kicker}</div>
        <h2 className="details-title">{title}</h2>
        {subtitle ? <p className="details-sub">{subtitle}</p> : null}
      </div>
      <button className="icon-button" onClick={onClose} aria-label="Close details">
        <X size={14} />
      </button>
    </div>
  );
}

function ServiceDetails({
  node,
  graph,
  onSelect,
}: {
  node: GraphNode;
  graph: GraphData;
  onSelect: (selection: Selection) => void;
}) {
  const nodeById = new Map(graph.nodes.map((item) => [item.id, item]));
  const relationships = graph.edges.filter(
    (edge) => edge.source === node.id || edge.target === node.id,
  );
  return (
    <>
      <div className="details-section">
        <div className="section-label">Service</div>
        <dl className="kv">
          <dt>Name</dt>
          <dd>{node.data.name}</dd>
          <dt>Reference</dt>
          <dd>{node.data.resolved === false ? "Unresolved target" : "Compose service"}</dd>
          <dt>Relationships</dt>
          <dd>{relationships.length}</dd>
        </dl>
      </div>
      <div className="details-section">
        <div className="section-label">Relationships</div>
        {relationships.length === 0 ? (
          <span className="muted small">
            No rendered relationships reference this service.
          </span>
        ) : (
          <div className="rel-list">
            {relationships.map((edge) => {
              const classification = edge.data?.classification;
              const otherId = edge.source === node.id ? edge.target : edge.source;
              const other = nodeById.get(otherId);
              const direction =
                edge.data?.classification === "explicit"
                  ? edge.source === node.id
                    ? "depends on"
                    : "required by"
                  : edge.source === node.id
                    ? "references"
                    : "referenced by";
              return (
                <button
                  className="rel-item"
                  key={edge.id}
                  onClick={() => onSelect({ kind: "edge", id: edge.id })}
                >
                  <span className="rel-top">
                    <span className="rel-name">
                      {direction} {other?.data.name ?? otherId}
                    </span>
                    <span className={classificationClass(classification)}>
                      {classificationLabel(classification)}
                    </span>
                  </span>
                  <span className="rel-meta">
                    {other?.data.resource_identity ?? edge.data?.relationship_type ?? otherId}
                    {typeof edge.data?.confidence === "number"
                      ? ` · ${percent(edge.data.confidence)}`
                      : ""}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}

function ResourceDetails({
  node,
  graph,
  report,
  onSelect,
}: {
  node: GraphNode;
  graph: GraphData;
  report: ReportData;
  onSelect: (selection: Selection) => void;
}) {
  const finding = findingForResource(report, node);
  const decisions = decisionsForNode(report, node, finding);
  const summary = node.data.decision_summary;
  const configuration = node.data.configuration_evidence ?? finding?.configuration_evidence ?? {};
  const unresolved = node.data.unresolved_vars ?? finding?.unresolved_vars ?? [];
  const observations = node.data.observation_resources ?? finding?.observation_resources ?? [];
  const chain = node.data.representative_chain ?? finding?.representative_chain ?? [];
  const confidence = finding?.confidence;
  return (
    <>
      <div className="details-section">
        <div className="section-label">
          Shared resource
          {node.data.resource_type ? (
            <span className="badge dim">{typeLabel(node.data.resource_type)}</span>
          ) : null}
        </div>
        <dl className="kv">
          <dt>Identity</dt>
          <dd className="mono">{node.data.resource_identity ?? node.data.name}</dd>
          <dt>Resolution</dt>
          <dd>{node.data.resolution_status?.replace(/_/g, " ") ?? "unknown"}</dd>
          <dt>Evidence strength</dt>
          <dd>{node.data.identity_strength ?? "unknown"}</dd>
          <dt>Services</dt>
          <dd>{node.data.service_count ?? finding?.service_count ?? "—"}</dd>
          <dt>Observations</dt>
          <dd>{node.data.evidence_count ?? finding?.evidence_count ?? "—"}</dd>
        </dl>
      </div>

      {finding ? (
        <>
          <div className="details-section">
            <div className="section-label">
              Semantic judgment
              <span className={finding.verdict === "meaningful" ? "badge yellow" : "badge dim"}>
                {finding.verdict}
              </span>
            </div>
            <div className={`reason${finding.verdict === "meaningful" ? " hidden" : ""}`}>
              {finding.reason}
            </div>
            <div style={{ marginTop: 10 }}>
              <ConfidenceBar value={confidence} />
            </div>
          </div>
          {summary ? (
            <div className="details-section">
              <div className="section-label">
                Stage 5 decision
                <span className={decisionClass(summary.overall ?? undefined)}>
                  {decisionLabel(summary.overall ?? undefined)}
                </span>
              </div>
              <div className="decision-facts" style={{ marginTop: 0 }}>
                <span className="badge dim">
                  {summary.counts.potential_dependency} potential
                </span>
                <span className="badge dim">{summary.counts.review} review</span>
                <span className="badge dim">
                  {summary.counts.insufficient_evidence} insufficient
                </span>
              </div>
            </div>
          ) : null}
        </>
      ) : (
        <div className="details-section">
          <span className="muted small">
            No matching report finding. This resource is shown from the graph only.
          </span>
        </div>
      )}

      <div className="details-section">
        <div className="section-label">Configuration evidence</div>
        <Evidence values={configuration} />
        {unresolved.length > 0 ? (
          <p className="small muted" style={{ marginBottom: 0 }}>
            Unresolved variables: <span className="mono">{unresolved.join(", ")}</span>
          </p>
        ) : null}
      </div>

      {observations.length > 0 ? (
        <div className="details-section">
          <div className="section-label">Observed as</div>
          <div className="decision-facts" style={{ marginTop: 0 }}>
            {observations.map((observation) => (
              <span className="badge dim mono" key={observation}>
                {observation}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {chain.length > 0 ? (
        <div className="details-section">
          <div className="section-label">Resolution chain</div>
          <div className="chain">
            {chain.map((step, index) => (
              <div className="chain-step" key={index}>
                <span className="chain-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="chain-text">{formatStep(step)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="details-section">
        <div className="section-label">Decisions</div>
        <DecisionCards decisions={decisions} />
      </div>

      <div className="details-section">
        <div className="section-label">Connected services</div>
        <div className="rel-list">
          {graph.edges
            .filter((edge) => edge.target === node.id)
            .map((edge) => {
              const source = graph.nodes.find((item) => item.id === edge.source);
              return (
                <button
                  className="rel-item"
                  key={edge.id}
                  onClick={() => onSelect({ kind: "edge", id: edge.id })}
                >
                  <span className="rel-top">
                    <span className="rel-name">{source?.data.name ?? edge.source}</span>
                    <span className={classificationClass(edge.data?.classification)}>
                      {classificationLabel(edge.data?.classification)}
                    </span>
                  </span>
                  <span className="rel-meta">
                    {edge.data?.relationship_type ?? "resource reference"}
                    {typeof edge.data?.confidence === "number"
                      ? ` · ${percent(edge.data.confidence)}`
                      : ""}
                  </span>
                </button>
              );
            })}
          {graph.edges.every((edge) => edge.target !== node.id) ? (
            <span className="muted small">No service references are rendered.</span>
          ) : null}
        </div>
      </div>
    </>
  );
}

function EdgeDetails({ edge, graph, report }: { edge: GraphEdge; graph: GraphData; report: ReportData }) {
  const classification = edge.data?.classification;
  const source = graph.nodes.find((node) => node.id === edge.source);
  const target = graph.nodes.find((node) => node.id === edge.target);
  const finding = findingForResource(report, target);
  const explicit = classification === "explicit";
  const decisions = finding?.decisions ?? [];
  return (
    <>
      <div className="details-section">
        <div className="section-label">
          Relationship
          <span className={classificationClass(classification)}>
            {classificationLabel(classification)}
          </span>
        </div>
        <dl className="kv">
          <dt>Source</dt>
          <dd>{source?.data.name ?? edge.source}</dd>
          <dt>Target</dt>
          <dd>{target?.data.name ?? edge.target}</dd>
          <dt>Type</dt>
          <dd>{typeLabel(edge.data?.relationship_type)}</dd>
          <dt>Semantics</dt>
          <dd>{typeLabel(edge.data?.semantics)}</dd>
          <dt>Origin</dt>
          <dd className="mono">{edge.data?.origin ?? "unknown"}</dd>
          {!explicit ? (
            <>
              <dt>Confidence</dt>
              <dd>
                <ConfidenceBar value={edge.data?.confidence} />
              </dd>
            </>
          ) : null}
          {edge.data?.target_resolved === false ? (
            <>
              <dt>Target</dt>
              <dd style={{ color: "var(--yellow)" }}>Unresolved Compose service</dd>
            </>
          ) : null}
        </dl>
      </div>

      {explicit ? (
        <div className="details-section">
          <div className="section-label">Meaning</div>
          <div className="reason explicit">
            This relationship is declared explicitly in the Compose configuration via
            <span className="mono"> depends_on</span>. It is not an LLM judgment, so it has
            no confidence score or semantic verdict.
          </div>
          {edge.data?.evidence ? (
            <p className="small muted" style={{ marginBottom: 0 }}>
              {edge.data.evidence}
            </p>
          ) : null}
        </div>
      ) : (
        <>
          <div className="details-section">
            <div className="section-label">Assessment</div>
            {finding ? (
              <>
                <div className={`reason${finding.verdict === "meaningful" ? " hidden" : ""}`}>
                  {finding.reason}
                </div>
                <div className="decision-facts">
                  <span className="badge dim">verdict: {finding.verdict}</span>
                  {finding.classification ? (
                    <span className={classificationClass(finding.classification)}>
                      {classificationLabel(finding.classification)}
                    </span>
                  ) : null}
                </div>
              </>
            ) : (
              <span className="muted small">
                No matching report finding for this relationship.
              </span>
            )}
          </div>
          <div className="details-section">
            <div className="section-label">Configuration evidence</div>
            <Evidence values={finding?.configuration_evidence ?? target?.data.configuration_evidence ?? {}} />
          </div>
          <div className="details-section">
            <div className="section-label">Decisions</div>
            <DecisionCards decisions={decisions} />
          </div>
        </>
      )}
    </>
  );
}

export function DetailsPanel({
  graph,
  report,
  selection,
  onSelect,
  onClose,
}: DetailsPanelProps) {
  if (!selection) {
    return (
      <aside className="details">
        <div className="details-empty">
          Select a service, resource, or relationship to inspect its evidence,
          classification, and reasoning.
        </div>
      </aside>
    );
  }

  if (selection.kind === "node") {
    const node = graph.nodes.find((item) => item.id === selection.id);
    if (!node) {
      return (
        <aside className="details">
          <div className="details-empty">This node is no longer in the graph.</div>
        </aside>
      );
    }
    const isResource = node.type === "resource";
    return (
      <aside className="details">
        <Header
          kicker={isResource ? typeLabel(node.data.resource_type) : "Service"}
          title={node.data.name}
          subtitle={isResource ? (node.data.resource_identity ?? node.id) : node.id}
          onClose={onClose}
        />
        <div className="details-body">
          {isResource ? (
            <ResourceDetails
              node={node}
              graph={graph}
              report={report}
              onSelect={onSelect}
            />
          ) : (
            <ServiceDetails node={node} graph={graph} onSelect={onSelect} />
          )}
        </div>
      </aside>
    );
  }

  const edge = graph.edges.find((item) => item.id === selection.id);
  if (!edge) {
    return (
      <aside className="details">
        <div className="details-empty">This relationship is no longer in the graph.</div>
      </aside>
    );
  }
  const source = graph.nodes.find((node) => node.id === edge.source);
  const target = graph.nodes.find((node) => node.id === edge.target);
  return (
    <aside className="details">
      <Header
        kicker="Relationship"
        title={`${source?.data.name ?? "?"} → ${target?.data.name ?? "?"}`}
        subtitle={edge.id}
        onClose={onClose}
      />
      <div className="details-body">
        <EdgeDetails edge={edge} graph={graph} report={report} />
      </div>
    </aside>
  );
}
