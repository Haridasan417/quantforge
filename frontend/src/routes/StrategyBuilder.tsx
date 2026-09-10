import { useCallback, useEffect, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import { ApiError, api } from "../api/client";
import ActionNode from "../components/strategy-builder/ActionNode";
import ConditionNode from "../components/strategy-builder/ConditionNode";
import type {
  ActionData,
  ActionFields,
  ConditionData,
  ConditionFields,
  StrategiesResponse,
  StrategyIndicatorsResponse,
  StrategyInfo,
} from "../components/strategy-builder/types";

const nodeTypes: NodeTypes = { condition: ConditionNode, action: ActionNode };

// Drops the UI-only fields (onChange callbacks, the indicator catalog
// each ConditionNode carries so its own dropdown can render) so what
// gets POSTed is exactly what GraphStrategyConfig expects on the
// backend: plain id/type/position/data per node, id/source/target per
// edge.
function serializeGraph(nodes: Node[], edges: Edge[]) {
  return {
    nodes: nodes.map((node) => {
      if (node.type === "condition") {
        const { indicator, comparator, threshold, params } = node.data as ConditionData;
        const fields: ConditionFields = { indicator, comparator, threshold, params };
        return { id: node.id, type: "condition", position: node.position, data: fields };
      }
      const { action } = node.data as ActionData;
      const fields: ActionFields = { action };
      return { id: node.id, type: "action", position: node.position, data: fields };
    }),
    edges: edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
  };
}

function StrategyBuilderCanvas() {
  const [nodes, setNodes, onNodesChange] = useNodesState<ConditionData | ActionData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const [catalog, setCatalog] = useState<StrategyIndicatorsResponse | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  const [strategyName, setStrategyName] = useState("My Strategy");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedStrategies, setSavedStrategies] = useState<StrategyInfo[]>([]);

  // A plain counter, not state — node/edge ids just need to be unique
  // on this canvas, and bumping it shouldn't itself trigger a render.
  const counter = useRef(0);
  const nextId = (prefix: string) => `${prefix}-${++counter.current}`;

  const refreshSavedStrategies = useCallback(async () => {
    try {
      const data = await api.get<StrategiesResponse>("/api/strategies");
      setSavedStrategies(data.strategies.filter((s) => s.source === "graph"));
    } catch {
      // Best-effort — the save button surfaces the real error when it matters.
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setCatalog(await api.get<StrategyIndicatorsResponse>("/api/strategies/indicators"));
      } catch (err) {
        setCatalogError(err instanceof Error ? err.message : "Failed to load indicators");
      }
    })();
    refreshSavedStrategies();
  }, [refreshSavedStrategies]);

  const updateNodeData = useCallback(
    (id: string, patch: Record<string, unknown>) => {
      setNodes((nds) =>
        nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)),
      );
    },
    [setNodes],
  );

  const addConditionNode = useCallback(() => {
    if (!catalog || catalog.indicators.length === 0) return;
    const id = nextId("condition");
    const first = catalog.indicators[0];
    const newNode: Node<ConditionData> = {
      id,
      type: "condition",
      position: { x: 60 + ((counter.current * 37) % 260), y: 40 + ((counter.current * 83) % 340) },
      data: {
        indicator: first.field,
        comparator: catalog.comparators[0] ?? "<",
        threshold: 0,
        params: { ...first.params },
        indicatorCatalog: catalog.indicators,
        comparators: catalog.comparators,
        onChange: (patch) => updateNodeData(id, patch),
      },
    };
    setNodes((nds) => nds.concat(newNode));
  }, [catalog, setNodes, updateNodeData]);

  const addActionNode = useCallback(() => {
    const id = nextId("action");
    const newNode: Node<ActionData> = {
      id,
      type: "action",
      position: { x: 440, y: 40 + ((counter.current * 83) % 340) },
      data: {
        action: "BUY",
        onChange: (patch) => updateNodeData(id, patch),
      },
    };
    setNodes((nds) => nds.concat(newNode));
  }, [setNodes, updateNodeData]);

  // Only Condition -> Action connections are meaningful to the graph
  // interpreter (see GraphStrategy._conditions_by_action on the
  // backend), so refuse anything else at the canvas level rather than
  // letting a user wire something that would just be silently ignored.
  const isValidConnection = useCallback(
    (connection: Connection | Edge) => {
      const source = nodes.find((n) => n.id === connection.source);
      const target = nodes.find((n) => n.id === connection.target);
      return source?.type === "condition" && target?.type === "action";
    },
    [nodes],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => addEdge({ ...connection, id: nextId("edge") }, eds));
    },
    [setEdges],
  );

  const clearCanvas = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setSaveMessage(null);
    setSaveError(null);
  }, [setNodes, setEdges]);

  const saveStrategy = useCallback(async () => {
    setSaveError(null);
    setSaveMessage(null);

    if (!strategyName.trim()) {
      setSaveError("Give the strategy a name first.");
      return;
    }
    if (nodes.length === 0) {
      setSaveError("Add at least one condition and one action before saving.");
      return;
    }

    setSaving(true);
    try {
      const result = await api.post<{ name: string }>("/api/strategies/custom", {
        name: strategyName.trim(),
        graph: serializeGraph(nodes, edges),
      });
      setSaveMessage(`Saved as "${strategyName.trim()}" (${result.name}).`);
      await refreshSavedStrategies();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Failed to save strategy");
    } finally {
      setSaving(false);
    }
  }, [strategyName, nodes, edges, refreshSavedStrategies]);

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-slate-100">Strategy Builder</h1>
      <p className="mt-1 text-sm text-slate-400">
        Add Condition and Action nodes, then drag from a condition's right edge to an action's
        left edge. Every condition wired into an action must hold — an AND-chain — for that
        action to fire.
      </p>

      {catalogError && (
        <div className="mt-4 rounded-md border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-300">
          Couldn't load the indicator list: {catalogError}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <button
          type="button"
          onClick={addConditionNode}
          disabled={!catalog}
          className="rounded-md bg-sky-900 px-3 py-1.5 text-sm font-medium text-sky-100 hover:bg-sky-800 disabled:opacity-50"
        >
          + Condition
        </button>
        <button
          type="button"
          onClick={addActionNode}
          className="rounded-md bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          + Action
        </button>
        <button
          type="button"
          onClick={clearCanvas}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
        >
          Clear
        </button>

        <div className="ml-auto flex items-end gap-2">
          <div>
            <label className="mb-1 block text-xs text-slate-400" htmlFor="strategy-name">
              Strategy name
            </label>
            <input
              id="strategy-name"
              value={strategyName}
              onChange={(e) => setStrategyName(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white"
            />
          </div>
          <button
            type="button"
            onClick={saveStrategy}
            disabled={saving}
            className="rounded-md bg-emerald-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Strategy"}
          </button>
        </div>
      </div>

      {saveError && (
        <div className="mt-3 rounded-md border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-300">
          {saveError}
        </div>
      )}
      {saveMessage && (
        <div className="mt-3 rounded-md border border-emerald-800 bg-emerald-950 px-3 py-2 text-sm text-emerald-300">
          {saveMessage}
        </div>
      )}

      <div className="qf-flow-dark mt-4 h-[560px] w-full overflow-hidden rounded-lg border border-slate-800">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          nodeTypes={nodeTypes}
          fitView
        >
          <Background color="#1e293b" gap={20} />
          <Controls />
        </ReactFlow>
      </div>

      {savedStrategies.length > 0 && (
        <div className="mt-6">
          <h2 className="text-sm font-semibold text-slate-300">Saved visual strategies</h2>
          <ul className="mt-2 space-y-1 text-sm text-slate-400">
            {savedStrategies.map((s) => (
              <li key={s.name}>
                <span className="text-slate-200">{s.display_name ?? s.name}</span>{" "}
                <span className="text-xs text-slate-600">({s.name})</span> — {s.description}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ReactFlow ships a light-mode stylesheet; these overrides scope
          it to QuantForge's dark theme without touching global CSS. */}
      <style>{`
        .qf-flow-dark { background: #0b1120; }
        .qf-flow-dark .react-flow__controls-button {
          background: #1e293b;
          border-bottom: 1px solid #334155;
          fill: #e2e8f0;
        }
        .qf-flow-dark .react-flow__controls-button:hover { background: #334155; }
        .qf-flow-dark .react-flow__edge-path { stroke: #64748b; }
        .qf-flow-dark .react-flow__attribution { background: transparent; color: #475569; }
      `}</style>
    </div>
  );
}

export default function StrategyBuilder() {
  return (
    <ReactFlowProvider>
      <StrategyBuilderCanvas />
    </ReactFlowProvider>
  );
}
