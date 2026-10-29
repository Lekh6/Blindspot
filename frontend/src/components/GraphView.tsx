import { useEffect, useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type NodeMouseHandler,
  type EdgeMouseHandler,
} from "@xyflow/react";
import { Network } from "lucide-react";
import "@xyflow/react/dist/style.css";
import { buildFlow, type AppEdge, type AppNode } from "../graph/layout";
import { nodeTypes } from "./FlowNodes";
import type { GraphData, Selection } from "../types";

interface GraphViewProps {
  graph: GraphData;
  selection: Selection;
  onSelect: (selection: Selection) => void;
}

export function GraphView({ graph, selection, onSelect }: GraphViewProps) {
  const [showRejected, setShowRejected] = useState(false);
  const base = useMemo(() => buildFlow(graph, showRejected), [graph, showRejected]);
  const [nodes, setNodes, onNodesChange] = useNodesState<AppNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<AppEdge>([]);

  useEffect(() => {
    setNodes(base.nodes);
    setEdges(base.edges);
  }, [base, setNodes, setEdges]);

  useEffect(() => {
    setNodes((current) =>
      current.map((node) => ({
        ...node,
        selected: selection?.kind === "node" && selection.id === node.id,
      })),
    );
    setEdges((current) =>
      current.map((edge) => ({
        ...edge,
        selected: selection?.kind === "edge" && selection.id === edge.id,
      })),
    );
  }, [selection, setNodes, setEdges]);

  const handleNodeClick: NodeMouseHandler<AppNode> = (_event, node) => {
    onSelect({ kind: "node", id: node.id });
  };
  const handleEdgeClick: EdgeMouseHandler<AppEdge> = (_event, edge) => {
    onSelect({ kind: "edge", id: edge.id });
  };

  if (graph.nodes.length === 0) {
    return (
      <div className="graph-stage">
        <div className="empty-graph">
          <div className="empty-graph-inner">
            <span className="empty-icon">
              <Network size={20} />
            </span>
            <h2>No relationships found</h2>
            <p>
              This analysis produced an empty graph. BlindSpot did not detect shared
              configuration, shared volumes, or declared service dependencies.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="graph-stage">
      <div className="toolbar">
        <label className="toggle">
          <input
            type="checkbox"
            checked={showRejected}
            onChange={(event) => setShowRejected(event.target.checked)}
          />
          Show rejected
        </label>
      </div>
      <ReactFlow<AppNode, AppEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onEdgeClick={handleEdgeClick}
        onPaneClick={() => onSelect(null)}
        fitView
        fitViewOptions={{ padding: 0.26, maxZoom: 1.15 }}
        minZoom={0.25}
        maxZoom={1.8}
        nodesDraggable
        nodesConnectable={false}
        edgesFocusable
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1c1c21" />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) => (node.type === "resource" ? "#2a2a22" : "#26262c")}
          nodeStrokeColor={(node) => (node.type === "resource" ? "#5a5430" : "#3b3b44")}
          nodeBorderRadius={3}
          maskColor="rgba(0, 0, 0, 0.6)"
        />
      </ReactFlow>
      <div className="legend">
        <span className="legend-item">
          <span className="legend-line" />
          explicit
        </span>
        <span className="legend-item">
          <span className="legend-line hidden" />
          potential hidden
        </span>
        <span className="legend-item">
          <span className="legend-line uncertain" />
          uncertain
        </span>
      </div>
    </div>
  );
}
