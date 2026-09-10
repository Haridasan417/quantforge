import CandleChart from "../components/CandleChart";

// P&L summary, trade log, and equity curve arrive in Phase 8, pushed live
// over WebSocket by the Executor. Until then, the chart is the default view.
export default function Dashboard() {
  return (
    <div>
      <h1 className="px-6 pt-6 text-2xl font-semibold text-slate-100">Dashboard</h1>
      <CandleChart />
    </div>
  );
}
