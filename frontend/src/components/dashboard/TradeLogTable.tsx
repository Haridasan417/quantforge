import type { TradeLogEntry } from "./types";

// Every symbol/strategy, newest first -- unlike Backtest's trade table
// (one symbol, one run), the live dashboard log spans every deployment,
// so Symbol is its own column here.
export default function TradeLogTable({ trades }: { trades: TradeLogEntry[] }) {
  if (trades.length === 0) {
    return <p className="mt-2 text-sm text-slate-500">No trades yet.</p>;
  }

  return (
    <div className="mt-2 overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-900 text-xs uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2">Time</th>
            <th className="px-3 py-2">Symbol</th>
            <th className="px-3 py-2">Side</th>
            <th className="px-3 py-2">Price</th>
            <th className="px-3 py-2">Qty</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {trades.map((t) => (
            <tr key={t.id} className="text-slate-300">
              <td className="px-3 py-1.5">{new Date(t.executed_at).toLocaleString()}</td>
              <td className="px-3 py-1.5">{t.symbol}</td>
              <td className={`px-3 py-1.5 font-medium ${t.side === "BUY" ? "text-emerald-400" : "text-red-400"}`}>
                {t.side}
              </td>
              <td className="px-3 py-1.5">{t.price.toFixed(2)}</td>
              <td className="px-3 py-1.5">{t.qty}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
