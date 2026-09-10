// Shared by Backtest and Dashboard (Phase 8) -- one small stat tile, so
// backtest results and live paper-trading metrics read as the same kind
// of number at a glance.
export default function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  const toneClass = tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-red-400" : "text-slate-100";
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
