// Phase 2 wires this up to lightweight-charts + GET /api/candles.
export default function Chart() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-slate-100">Chart</h1>
      <p className="mt-2 text-slate-400">
        Candlestick chart with RSI/MACD/EMA overlays arrives in Phase 2.
      </p>
    </div>
  );
}
