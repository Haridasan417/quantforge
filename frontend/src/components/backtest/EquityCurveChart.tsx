import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { EquityPoint } from "./types";

function formatTick(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleDateString();
}

export default function EquityCurveChart({ equityCurve }: { equityCurve: EquityPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={equityCurve} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
        <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
        <XAxis
          dataKey="ts"
          tickFormatter={formatTick}
          stroke="#64748b"
          tick={{ fontSize: 11, fill: "#94a3b8" }}
          minTickGap={40}
        />
        <YAxis
          stroke="#64748b"
          tick={{ fontSize: 11, fill: "#94a3b8" }}
          domain={["auto", "auto"]}
          tickFormatter={(v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        />
        <Tooltip
          contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 6, fontSize: 12 }}
          labelStyle={{ color: "#94a3b8" }}
          labelFormatter={(label) => formatTick(String(label ?? ""))}
          formatter={(value) => [
            typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value),
            "Equity",
          ]}
        />
        <Line type="monotone" dataKey="equity" stroke="#38bdf8" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
