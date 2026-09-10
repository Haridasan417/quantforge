import { useCallback, useEffect, useRef, useState } from "react";
import { api, wsUrl } from "../api/client";
import CandleChart from "../components/CandleChart";
import MetricCard from "../components/MetricCard";
import EquityCurveChart from "../components/backtest/EquityCurveChart";
import TradeLogTable from "../components/dashboard/TradeLogTable";
import type { DashboardOverview, DashboardUpdateEvent, TradeLogEntry, TradeLogResponse } from "../components/dashboard/types";

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

function formatCurrency(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// How long to wait before retrying a dropped WebSocket connection.
const RECONNECT_DELAY_MS = 3000;

// Live P&L summary, Sharpe/max-drawdown/win-rate cards, equity curve, and
// trade log (Phase 8) -- all computed by the backend over the *real*
// paper-trading history the Executor (Phase 6) has actually written, not a
// backtest replay (see app.dashboard.metrics). GET /api/dashboard/overview
// + GET /api/dashboard/trades load the initial state; /api/ws/dashboard then
// pushes one message per Executor fill. Rather than duplicating the
// backend's Sharpe/drawdown/win-rate math in the browser to update those
// cards incrementally, each WebSocket message is treated as a "something
// changed" signal and both REST endpoints are simply re-fetched -- trades
// land at most a few times a minute (Trigger/Executor's own poll interval),
// so the extra round trip is unnoticeable and the backend stays the one
// source of truth for every number on this page.
export default function Dashboard() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [trades, setTrades] = useState<TradeLogEntry[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<DashboardUpdateEvent | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [overviewData, tradesData] = await Promise.all([
        api.get<DashboardOverview>("/api/dashboard/overview"),
        api.get<TradeLogResponse>("/api/dashboard/trades"),
      ]);
      setOverview(overviewData);
      setTrades(tradesData.trades);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load dashboard data");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(wsUrl("/api/ws/dashboard"));
      wsRef.current = ws;

      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => {
        setWsConnected(false);
        if (!cancelled) reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (event) => {
        try {
          const update = JSON.parse(event.data) as DashboardUpdateEvent;
          setLastUpdate(update);
          refresh();
        } catch {
          // A malformed push shouldn't take the page down -- just drop it.
        }
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [refresh]);

  const pnl = overview?.pnl;
  const metrics = overview?.metrics;
  const holdingsEntries = pnl ? Object.entries(pnl.holdings) : [];

  return (
    <div className="p-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold text-slate-100">Dashboard</h1>
        <span
          className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs ${
            wsConnected
              ? "border-emerald-800 bg-emerald-950 text-emerald-400"
              : "border-slate-700 bg-slate-900 text-slate-500"
          }`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${wsConnected ? "bg-emerald-400" : "bg-slate-600"}`} />
          {wsConnected ? "Live" : "Reconnecting…"}
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-400">
        Live paper-trading P&amp;L, computed over real Executor fills — not a backtest.
      </p>

      {loadError && (
        <div className="mt-4 rounded-md border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-300">
          Couldn't load dashboard data: {loadError}
        </div>
      )}

      {lastUpdate && (
        <div className="mt-4 rounded-md border border-sky-900 bg-sky-950/50 px-3 py-2 text-sm text-sky-300">
          Live update: {lastUpdate.trade.side} {lastUpdate.trade.qty} {lastUpdate.trade.symbol} @{" "}
          {lastUpdate.trade.price.toFixed(2)}
        </div>
      )}

      {pnl && (
        <>
          <h2 className="mt-6 text-sm font-semibold text-slate-300">P&amp;L Summary</h2>
          <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MetricCard label="Current Equity" value={formatCurrency(pnl.current_equity)} />
            <MetricCard
              label="Total P&L"
              value={formatCurrency(pnl.total_pnl)}
              tone={pnl.total_pnl >= 0 ? "good" : "bad"}
            />
            <MetricCard
              label="Total P&L %"
              value={formatPercent(pnl.total_pnl_pct)}
              tone={pnl.total_pnl_pct >= 0 ? "good" : "bad"}
            />
            <MetricCard label="Cash" value={formatCurrency(pnl.cash)} />
          </div>
        </>
      )}

      {metrics && (
        <>
          <h2 className="mt-6 text-sm font-semibold text-slate-300">Performance</h2>
          <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MetricCard
              label="Sharpe"
              value={metrics.sharpe === null ? "—" : metrics.sharpe.toFixed(2)}
              tone={metrics.sharpe === null ? undefined : metrics.sharpe >= 0 ? "good" : "bad"}
            />
            <MetricCard label="Max Drawdown" value={formatPercent(metrics.max_drawdown)} tone="bad" />
            <MetricCard
              label="Win Rate"
              value={metrics.closed_trades === 0 ? "—" : formatPercent(metrics.win_rate)}
              tone={metrics.closed_trades === 0 ? undefined : metrics.win_rate >= 0.5 ? "good" : "bad"}
            />
            <MetricCard label="Total Trades" value={String(metrics.total_trades)} />
          </div>
        </>
      )}

      {holdingsEntries.length > 0 && (
        <>
          <h2 className="mt-6 text-sm font-semibold text-slate-300">Open Positions</h2>
          <div className="mt-2 overflow-x-auto rounded-lg border border-slate-800">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-900 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2">Qty</th>
                  <th className="px-3 py-2">Avg Price</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {holdingsEntries.map(([symbol, holding]) => (
                  <tr key={symbol} className="text-slate-300">
                    <td className="px-3 py-1.5">{symbol}</td>
                    <td className="px-3 py-1.5">{holding.qty}</td>
                    <td className="px-3 py-1.5">{holding.avg_price.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {overview && overview.equity_curve.length > 0 && (
        <>
          <h2 className="mt-6 text-sm font-semibold text-slate-300">Equity Curve</h2>
          <div className="mt-2 rounded-lg border border-slate-800 bg-slate-900 p-2">
            <EquityCurveChart equityCurve={overview.equity_curve} />
          </div>
        </>
      )}

      <h2 className="mt-6 text-sm font-semibold text-slate-300">
        Trade Log {trades.length > 0 ? `(${trades.length})` : ""}
      </h2>
      <TradeLogTable trades={trades} />

      <h2 className="mt-6 text-sm font-semibold text-slate-300">Live Chart</h2>
      <div className="mt-2 rounded-lg border border-slate-800">
        <CandleChart />
      </div>
    </div>
  );
}
