import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import CandleChart from "../components/CandleChart";
import MetricCard from "../components/MetricCard";
import EquityCurveChart from "../components/backtest/EquityCurveChart";
import type { BacktestResponse } from "../components/backtest/types";
import type { StrategiesResponse, StrategyInfo } from "../components/strategy-builder/types";

function defaultDateRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 1);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

// Loose shape of the JSON Schema `GET /api/strategies` returns per strategy
// (backend/app/strategy_engine/*'s `config_schema()`) — just enough to
// drive a config form generically, without hard-coding which built-in
// needs what. Right now only RLConfig.checkpoint_name has no default (see
// CLAUDE.md's "Follow-up fix" note under Phase 7 part B), so this ends up
// rendering exactly one field for the "rl" strategy and nothing for every
// other built-in — but it isn't special-cased to "rl": any future
// built-in with a required config field gets a form field here for free.
interface JsonSchemaProperty {
  title?: string;
  description?: string;
}

interface ConfigJsonSchema {
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

export default function Backtest() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [strategiesError, setStrategiesError] = useState<string | null>(null);

  const initialRange = defaultDateRange();
  const [strategyId, setStrategyId] = useState("");
  const [symbol, setSymbol] = useState("RELIANCE.NS");
  const [start, setStart] = useState(initialRange.start);
  const [end, setEnd] = useState(initialRange.end);
  const [configValues, setConfigValues] = useState<Record<string, string>>({});

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [runCount, setRunCount] = useState(0);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.get<StrategiesResponse>("/api/strategies");
        setStrategies(data.strategies);
        if (data.strategies.length > 0) setStrategyId(data.strategies[0].name);
      } catch (err) {
        setStrategiesError(err instanceof Error ? err.message : "Failed to load strategies");
      }
    })();
  }, []);

  const selectedStrategy = strategies.find((s) => s.name === strategyId);
  const configSchema = (selectedStrategy?.config_schema ?? {}) as ConfigJsonSchema;
  // Only built-ins take a per-request config override at all (a saved
  // graph's config lives on its own row — see resolve_strategy in
  // backend/app/backtest_engine/resolve.py); required fields on a graph's
  // schema describe its *saved* nodes/edges shape, not something to fill
  // in here, so this stays empty for source === "graph".
  const requiredConfigFields = selectedStrategy?.source === "builtin" ? configSchema.required ?? [] : [];

  // Reset any typed-in config values when the strategy selection changes,
  // so switching away from "rl" and back doesn't resubmit a stale value.
  useEffect(() => {
    setConfigValues({});
  }, [strategyId]);

  const runBacktest = async () => {
    setRunError(null);

    if (!strategyId) {
      setRunError("Pick a strategy first.");
      return;
    }

    const missingField = requiredConfigFields.find((field) => !configValues[field]?.trim());
    if (missingField) {
      const label = configSchema.properties?.[missingField]?.title ?? missingField;
      setRunError(`${label} is required for this strategy.`);
      return;
    }

    setRunning(true);
    try {
      const startIso = new Date(`${start}T00:00:00Z`).toISOString();
      const endIso = new Date(`${end}T00:00:00Z`).toISOString();
      const data = await api.post<BacktestResponse>("/api/backtest", {
        strategy_id: strategyId,
        symbol: symbol.trim().toUpperCase(),
        start: startIso,
        end: endIso,
        ...(requiredConfigFields.length > 0
          ? { config: Object.fromEntries(requiredConfigFields.map((field) => [field, configValues[field]?.trim()])) }
          : {}),
      });
      setResult(data);
      setRunCount((n) => n + 1);
    } catch (err) {
      setResult(null);
      setRunError(err instanceof ApiError ? err.message : "Failed to run backtest");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-slate-100">Backtest</h1>
      <p className="mt-1 text-sm text-slate-400">
        Run any registered strategy — built-in or a saved visual graph — against historical
        candles through backtrader.
      </p>

      {strategiesError && (
        <div className="mt-4 rounded-md border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-300">
          Couldn't load strategies: {strategiesError}
        </div>
      )}

      <form
        className="mt-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          runBacktest();
        }}
      >
        <div>
          <label className="mb-1 block text-xs text-slate-400" htmlFor="strategy">
            Strategy
          </label>
          <select
            id="strategy"
            value={strategyId}
            onChange={(e) => setStrategyId(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white"
          >
            {strategies.length === 0 && <option value="">No strategies available</option>}
            {strategies.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name} {s.source === "graph" ? "(visual)" : ""}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs text-slate-400" htmlFor="symbol">
            Symbol
          </label>
          <input
            id="symbol"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="RELIANCE.NS"
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs text-slate-400" htmlFor="start">
            Start
          </label>
          <input
            id="start"
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs text-slate-400" htmlFor="end">
            End
          </label>
          <input
            id="end"
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white"
          />
        </div>

        {requiredConfigFields.map((field) => {
          const schema = configSchema.properties?.[field];
          return (
            <div key={field}>
              <label className="mb-1 block text-xs text-slate-400" htmlFor={`config-${field}`}>
                {schema?.title ?? field}
              </label>
              <input
                id={`config-${field}`}
                value={configValues[field] ?? ""}
                onChange={(e) => setConfigValues((prev) => ({ ...prev, [field]: e.target.value }))}
                placeholder={schema?.description ?? field}
                title={schema?.description}
                className="w-56 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white"
              />
            </div>
          );
        })}

        <button
          type="submit"
          disabled={running || !strategyId}
          className="rounded-md bg-sky-800 px-4 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
        >
          {running ? "Running…" : "Run Backtest"}
        </button>
      </form>

      {runError && (
        <div className="mt-4 rounded-md border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-300">
          {runError}
        </div>
      )}

      {result && (
        <div className="mt-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MetricCard
              label="Sharpe"
              value={result.sharpe === null ? "—" : result.sharpe.toFixed(2)}
              tone={result.sharpe === null ? undefined : result.sharpe >= 0 ? "good" : "bad"}
            />
            <MetricCard label="Max Drawdown" value={formatPercent(result.max_drawdown)} tone="bad" />
            <MetricCard
              label="Win Rate"
              value={formatPercent(result.win_rate)}
              tone={result.win_rate >= 0.5 ? "good" : "bad"}
            />
            <MetricCard
              label="Final Equity"
              value={result.final_equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            />
          </div>

          <h2 className="mt-6 text-sm font-semibold text-slate-300">Equity curve</h2>
          <div className="mt-2 rounded-lg border border-slate-800 bg-slate-900 p-2">
            <EquityCurveChart equityCurve={result.equity_curve} />
          </div>

          <h2 className="mt-6 text-sm font-semibold text-slate-300">
            Price chart with trade markers ({result.trades.length} fill{result.trades.length === 1 ? "" : "s"})
          </h2>
          <div className="mt-2 rounded-lg border border-slate-800">
            <CandleChart
              key={runCount}
              initialSymbol={result.symbol}
              initialInterval={result.interval as "1d" | "1h" | "15m"}
              fixedRange={{ start, end }}
              markers={result.trades}
            />
          </div>

          {result.trades.length > 0 && (
            <div className="mt-4 overflow-x-auto rounded-lg border border-slate-800">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-900 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Time</th>
                    <th className="px-3 py-2">Side</th>
                    <th className="px-3 py-2">Price</th>
                    <th className="px-3 py-2">Qty</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {result.trades.map((t, i) => (
                    <tr key={`${t.ts}-${i}`} className="text-slate-300">
                      <td className="px-3 py-1.5">{new Date(t.ts).toLocaleString()}</td>
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
          )}
        </div>
      )}
    </div>
  );
}
