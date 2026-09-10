import { Handle, Position, type NodeProps } from "reactflow";
import type { ActionData } from "./types";

export default function ActionNode({ data }: NodeProps<ActionData>) {
  return (
    <div
      className={`w-36 rounded-lg border px-3 py-2 text-slate-100 shadow-lg ${
        data.action === "BUY" ? "border-emerald-700 bg-emerald-950" : "border-red-700 bg-red-950"
      }`}
    >
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-300">
        Action
      </div>
      <select
        className="nodrag w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs font-semibold text-white"
        value={data.action}
        onChange={(e) => data.onChange({ action: e.target.value as "BUY" | "SELL" })}
      >
        <option value="BUY">BUY</option>
        <option value="SELL">SELL</option>
      </select>

      {/* Multiple ConditionNodes can connect to this one handle — every
          one of them must hold for this action to fire (AND-chain). */}
      <Handle type="target" position={Position.Left} className="!h-3 !w-3 !bg-slate-400" />
    </div>
  );
}
