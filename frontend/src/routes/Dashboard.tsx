// Phase 8 wires this up to live P&L / trade log / equity curve data,
// pushed over WebSocket from the Executor service.
export default function Dashboard() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-slate-100">Dashboard</h1>
      <p className="mt-2 text-slate-400">
        P&amp;L, trade log, and equity curve arrive in Phase 8. Chart (Phase 2)
        will become the default view once it exists.
      </p>
    </div>
  );
}
