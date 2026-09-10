import { Handle, Position, type NodeProps } from "reactflow";
import type { ConditionData } from "./types";

// "nodrag"/"nowheel" are ReactFlow's own convention: any element with
// that className stops the node-drag/canvas-zoom handlers from
// swallowing the interaction, so selects/inputs inside a node stay
// clickable and typeable.
export default function ConditionNode({ data }: NodeProps<ConditionData>) {
  const selected = data.indicatorCatalog.find((f) => f.field === data.indicator);
  const paramKeys = Object.keys(selected?.params ?? data.params);

  return (
    <div className="w-56 rounded-lg border border-sky-800 bg-slate-900 px-3 py-2 text-slate-100 shadow-lg">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-sky-400">
        Condition
      </div>

      <label className="mb-1 block text-[11px] text-slate-400">Indicator</label>
      <select
        className="nodrag mb-2 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-white"
        value={data.indicator}
        onChange={(e) => {
          const field = e.target.value;
          const next = data.indicatorCatalog.find((f) => f.field === field);
          data.onChange({ indicator: field, params: next ? { ...next.params } : {} });
        }}
      >
        {data.indicatorCatalog.map((f) => (
          <option key={f.field} value={f.field}>
            {f.label}
          </option>
        ))}
      </select>

      {paramKeys.length > 0 && (
        <div className="mb-2 grid grid-cols-2 gap-1">
          {paramKeys.map((key) => (
            <label key={key} className="text-[11px] text-slate-400">
              {key}
              <input
                type="number"
                className="nodrag mt-0.5 w-full rounded border border-slate-700 bg-slate-950 px-1.5 py-1 text-xs text-white"
                value={data.params[key] ?? selected?.params[key] ?? 0}
                onChange={(e) =>
                  data.onChange({ params: { ...data.params, [key]: Number(e.target.value) } })
                }
              />
            </label>
          ))}
        </div>
      )}

      <div className="flex items-center gap-1">
        <select
          className="nodrag rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-white"
          value={data.comparator}
          onChange={(e) => data.onChange({ comparator: e.target.value })}
        >
          {data.comparators.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <input
          type="number"
          className="nodrag w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-white"
          value={data.threshold}
          onChange={(e) => data.onChange({ threshold: Number(e.target.value) })}
        />
      </div>

      {/* Feeds into an ActionNode's target handle — one or more
          ConditionNodes can connect to the same action, which is what
          makes an AND-chain: the graph interpreter requires every
          condition wired into an action to hold before it fires. */}
      <Handle type="source" position={Position.Right} className="!h-3 !w-3 !bg-sky-500" />
    </div>
  );
}
