import dagre from "@dagrejs/dagre";
import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { Classification, GraphData, GraphEdgeData, GraphNodeData } from "../types";

export type AppNode = Node<GraphNodeData, "service" | "resource">;
export type AppEdge = Edge<GraphEdgeData>;

const SERVICE_WIDTH = 196;
const SERVICE_HEIGHT = 66;
const RESOURCE_WIDTH = 236;
const RESOURCE_HEIGHT = 78;

function labelFor(classification: Classification): string | undefined {
  if (classification === "explicit") return "startup";
  if (classification === "rejected") return "rejected";
  return undefined;
}

function edgeStyle(classification: Classification): {
  stroke: string;
  strokeWidth: number;
  strokeDasharray?: string;
} {
  if (classification === "explicit") {
    return { stroke: "#8b8c95", strokeWidth: 1.4 };
  }
  if (classification === "potential_hidden") {
    return { stroke: "#f2c94c", strokeWidth: 1.7 };
  }
  if (classification === "rejected") {
    return { stroke: "#4c4c54", strokeWidth: 1, strokeDasharray: "2 4" };
  }
  return { stroke: "#8a7a3a", strokeWidth: 1.3, strokeDasharray: "5 4" };
}

export function buildFlow(
  graph: GraphData,
  showRejected: boolean,
): { nodes: AppNode[]; edges: AppEdge[] } {
  const hiddenTargets = new Set<string>();
  for (const edge of graph.edges) {
    if (edge.data?.classification === "potential_hidden") {
      hiddenTargets.add(edge.target);
    }
  }

  const visibleEdges = graph.edges.filter(
    (edge) => showRejected || edge.data?.classification !== "rejected",
  );
  const referenced = new Set<string>();
  for (const edge of visibleEdges) {
    referenced.add(edge.source);
    referenced.add(edge.target);
  }
  const visibleNodes =
    visibleEdges.length > 0
      ? graph.nodes.filter((node) => referenced.has(node.id))
      : graph.nodes;

  const flowNodes: AppNode[] = visibleNodes.map((node) => {
    const isResource = node.type === "resource";
    return {
      id: node.id,
      type: node.type,
      position: { x: 0, y: 0 },
      width: isResource ? RESOURCE_WIDTH : SERVICE_WIDTH,
      height: isResource ? RESOURCE_HEIGHT : SERVICE_HEIGHT,
      style: {
        width: isResource ? RESOURCE_WIDTH : SERVICE_WIDTH,
        height: isResource ? RESOURCE_HEIGHT : SERVICE_HEIGHT,
      },
      data: {
        ...node.data,
        _hasHidden: hiddenTargets.has(node.id),
      },
    };
  });

  const flowEdges: AppEdge[] = visibleEdges.map((edge) => {
    const classification = (edge.data?.classification ?? "uncertain") as Classification;
    const style = edgeStyle(classification);
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: "smoothstep",
      data: edge.data,
      label: labelFor(classification),
      labelShowBg: true,
      labelBgPadding: [4, 2],
      labelBgBorderRadius: 3,
      labelStyle: {
        fill: classification === "potential_hidden" ? "#f2c94c" : "#96969f",
        fontFamily: "SFMono-Regular, Consolas, monospace",
        fontSize: 9,
      },
      style,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: style.stroke,
        width: 14,
        height: 14,
      },
    };
  });

  const layout = new dagre.graphlib.Graph();
  layout.setDefaultEdgeLabel(() => ({}));
  layout.setGraph({
    rankdir: "LR",
    nodesep: 38,
    ranksep: 104,
    marginx: 48,
    marginy: 48,
  });
  for (const node of flowNodes) {
    layout.setNode(node.id, {
      width: node.width,
      height: node.height,
    });
  }
  for (const edge of flowEdges) {
    layout.setEdge(edge.source, edge.target);
  }
  dagre.layout(layout);

  const positionedNodes = flowNodes.map((node) => {
    const point = layout.node(node.id);
    if (!point) return node;
    return {
      ...node,
      position: {
        x: point.x - (node.width ?? 0) / 2,
        y: point.y - (node.height ?? 0) / 2,
      },
    };
  });

  return { nodes: positionedNodes, edges: flowEdges };
}
