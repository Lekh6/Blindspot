import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { AppNode } from "../graph/layout";

function Kicker({ children }: { children: React.ReactNode }) {
  return <div className="bs-node-kicker">{children}</div>;
}

function titleFor(name: string, max = 30): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

function typeLabel(value: string | undefined): string {
  if (!value) return "Resource";
  return value.replace(/_/g, " ");
}

export function ServiceNode({ data, selected }: NodeProps<AppNode>) {
  const unresolved = data.resolved === false;
  return (
    <div className={`bs-node service${selected ? " selected" : ""}${unresolved ? " unresolved" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <Kicker>Service</Kicker>
      <div className="bs-node-title" title={data.name}>
        {titleFor(data.name, 26)}
      </div>
      <div className="bs-node-meta">
        {unresolved ? <span className="warn">unresolved reference</span> : "compose service"}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

export function ResourceNode({ data, selected }: NodeProps<AppNode>) {
  const hidden = data._hasHidden === true;
  const status = data.resolution_status;
  const decisions = data.decision_summary;
  const meta =
    status && status !== "resolved"
      ? status.replace(/_/g, " ")
      : decisions && decisions.total_candidates > 0
        ? `${decisions.total_candidates} candidate${decisions.total_candidates === 1 ? "" : "s"}`
        : "shared resource";
  return (
    <div
      className={`bs-node resource${hidden ? " has-hidden" : ""}${selected ? " selected" : ""}`}
    >
      <Handle type="target" position={Position.Left} />
      <Kicker>{typeLabel(data.resource_type)}</Kicker>
      <div className="bs-node-title" title={data.name}>
        {titleFor(data.name, 32)}
      </div>
      <div className={`bs-node-meta${hidden ? " warn" : ""}`}>{meta}</div>
    </div>
  );
}

export const nodeTypes = {
  service: ServiceNode,
  resource: ResourceNode,
};
