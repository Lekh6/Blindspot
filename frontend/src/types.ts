export type Selection = { kind: "node" | "edge"; id: string } | null;

export type Classification =
  | "explicit"
  | "potential_hidden"
  | "uncertain"
  | "rejected";

export interface DecisionView {
  candidate_id: string;
  service_a: string;
  service_b: string;
  resource: string;
  resource_type: string;
  resource_identity: string | null;
  resolution_status: string;
  identity_strength: string;
  stage4_verdict: string;
  stage4_confidence: number;
  decision: "potential_dependency" | "review" | "insufficient_evidence";
  processing_status: string;
  score: number | null;
  evidence_references: string[];
  counter_evidence_references: string[];
  missing_information: string[];
  policy_rules_applied: string[];
  rationale: string;
  decision_schema_version?: string;
  policy_version?: string;
}

export interface DecisionSummary {
  overall: "potential_dependency" | "review" | "insufficient_evidence" | null;
  total_candidates: number;
  counts: {
    potential_dependency: number;
    review: number;
    insufficient_evidence: number;
  };
  processing_status_counts: Record<string, number>;
  candidate_ids: string[];
}

export interface GraphNodeData {
  name: string;
  resource_type?: string;
  resource_protocol?: string;
  resolution_status?: string;
  identity_strength?: string;
  grouping_key?: string;
  resource_identity?: string | null;
  relationship_type?: string;
  semantics?: string;
  origin?: string;
  evidence_count?: number;
  service_count?: number;
  configuration_evidence?: Record<string, string[]>;
  unresolved_vars?: string[];
  observation_resources?: string[];
  representative_chain?: Array<Record<string, unknown>>;
  decision_summary?: DecisionSummary;
  decisions?: DecisionView[];
  candidate_ids?: string[];
  resolved?: boolean;
  [key: string]: unknown;
}

export interface GraphEdgeData {
  classification?: Classification;
  relationship_type?: string;
  semantics?: string;
  origin?: string;
  confidence?: number;
  decision?: string | null;
  decision_counts?: DecisionSummary["counts"];
  processing_status_counts?: Record<string, number>;
  candidate_ids?: string[];
  target_resolved?: boolean;
  evidence?: string;
  provenance?: string;
  [key: string]: unknown;
}

export interface GraphNode {
  id: string;
  type: "service" | "resource";
  data: GraphNodeData;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  data: GraphEdgeData;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ReportFinding {
  title: string;
  resource_identity: string | null;
  resource_protocol: string | null;
  resource_type: string;
  resolution_status: string;
  identity_strength: string;
  services: string[];
  configuration_evidence: Record<string, string[]>;
  unresolved_vars: string[];
  representative_chain: Array<Record<string, unknown>>;
  evidence_count: number;
  service_count: number;
  observation_resources: string[];
  verdict: string;
  confidence: number;
  reason: string;
  classification?: Classification;
  relationship_type?: string;
  semantics?: string;
  origin?: string;
  decisions?: DecisionView[];
  decision_summary?: DecisionSummary | null;
}

export interface ExplicitRelationship {
  source: string;
  target: string;
  relationship_id?: string;
  source_id?: string;
  target_id?: string;
  candidate_id?: string;
  candidate_ids?: string[];
  target_resolved: boolean;
  evidence: string;
  provenance?: string | null;
  relationship_type: string;
  semantics: string;
  origin: string;
  classification: "explicit";
}

export interface ReportData {
  summary: Record<string, number | string>;
  graph_summary?: Record<string, number> | null;
  generated_at?: string;
  findings: ReportFinding[];
  explicit_relationships?: ExplicitRelationship[];
  decisions?: DecisionView[];
  application?: { root?: string } | null;
  inputs?: { sources_used?: string[] } | null;
  analysis?: Record<string, unknown> | null;
}

export interface RunSummary {
  id: string;
  name: string;
  path: string;
  modified: string;
  summary: Record<string, unknown>;
}

export interface RunPayload {
  id: string;
  name: string;
  path: string;
  graph: GraphData;
  report: ReportData;
}

export interface AnalyzeResponse {
  ok: boolean;
  message: string;
  run?: RunSummary;
  stdout?: string;
  stderr?: string;
}
