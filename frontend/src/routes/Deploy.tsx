import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import { StrategyConfigFields, missingRequiredField, requiredConfigFieldsFor } from "../components/StrategyConfigFields";
import type {
  DeploymentInfo,
  DeploymentsResponse,
  StrategiesResponse,
  StrategyInfo,
} from "../components/strategy-builder/types";

interface ActivateResponse {
  deployment_id: number;
  strategy_id: string;
  symbol: string;
  is_active: boolean;
}

// Phase 9 follow-up: the one piece of the paper-trading pipeline (Phase
// 6) that had no UI — POST /api/strategies/activate previously had to be
// hit with curl. This page is a thin form over that same endpoint, plus
// GET /api/strategies/deployments (added alongside this page) so
// existing deployments can be seen and paused/resumed without knowing
// their config from memory.
export default function Deploy() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [deployments, setDeployments] = useState<DeploymentInfo[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [strategyId, setStrategyId] = useState("");
  const [symbol, setSymbol] = useState("RELIANCE.NS");
  const [configValues, setConfigValues] = useState<Record<string, string>>({});

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<ActivateResponse | null>(null);

  const [toggling, setToggling] = useState<number | null>(null);

  const refresh = async () => {
    try {
      const [strategiesData, deploymentsData] = await Promise.all([
        api.get<StrategiesResponse>("/api/strategies"),
        api.get<DeploymentsResponse>("/api/strategies/deployments"),
      ]);
      setStrategies(strategiesData.strategies);
      setDeployments(deploymentsData.deployments);
      if (!strategyId && strategiesData.strategies.length > 0) {
        setStrategyId(strategiesData.strategies[0].name);
      }
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load strategies/deployments");
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedStrategy = strategies.find((s) => s.name === strategyId);
  const requiredConfigFields = requiredConfigFieldsFor(selectedStrategy);

  useEffect(() => {
    setConfigValues({});
  }, [strategyId]);

  const deploy = async () => {
    setFormError(null);
    setLastResult(null);

    if (!strategyId) {
      setFormError("Pick a strategy first.");
      return;
    }
    if (!symbol.trim()) {
      setFormError("Symbol is required.");
      return;
    }

    const missingLabel = missingRequiredField(requiredConfigFields, configValues, selectedStrategy);
    if (missingLabel) {
      setFormError(`${missingLabel} is required for this strategy.`);
      return;
    }

    setSubmitting(true);
    try {
      const data = await api.post<ActivateResponse>("/api/strategies/activate", {
        strategy_id: strategyId,
        symbol: symbol.trim().toUpperCase(),
        is_active: true,
        ...(requiredConfigFields.length > 0
          ? { config: Object.fromEntries(requiredConfigFields.map((field) => [field, configValues[field]?.trim()])) }
          : {}),
      });
      setLastResult(data);
      await refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to deploy strategy");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleDeployment = async (deployment: DeploymentInfo) => {
    setToggling(deployment.deployment_id);
    setLoadError(null);
    try {
      // Re-send the deployment's own stored config so toggling
      // is_active doesn't reset it to {} — see POST
      // /api/strategies/activate's built-in branch, which replaces
      // config with whatever's in the request body (or {} if omitted).
      await api.post<ActivateResponse>("/api/strategies/activate", {
        strategy_id: deployment.strategy_id,
        symbol: deployment.symbol,
        is_active: !deployment.is_active,
        config: deployment.config,
      });
      await refresh();
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Failed to update deployment");
    } finally {
      setToggling(null);
    }
  };

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-slate-100">Deploy Strategy</h1>
      <p className="mt-1 text-sm text-slate-400">
        Turn a registered strategy — built-in or a saved visual graph — into a live paper-trading
        deployment. Once active, the scheduled Trigger/Executor cycle evaluates it during NSE
        hours and simulated fills show up on the Dashboard in real time.
      </p>

      {loadError && (
        <div className="mt-4 rounded-md border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-300">
          {loadError}
        </div>
      )}

      <form
        className="mt-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          deploy();
        }}
      >
        <div>
          <label className="mb-1 block text-xs text-slate-400" htmlFor="deploy-strategy">
            Strategy
          </label>
          <select
            id="deploy-strategy"
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
          <label className="mb-1 block text-xs text-slate-400" htmlFor="deploy-symbol">
            Symbol
          </label>
          <input
            id="deploy-symbol"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="RELIANCE.NS"
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white"
          />
        </div>

        <StrategyConfigFields
          strategy={selectedStrategy}
          fields={requiredConfigFields}
          values={configValues}
          onChange={(field, value) => setConfigValues((prev) => ({ ...prev, [field]: value }))}
        />

        <button
          type="submit"
          disabled={submitting || !strategyId}
          className="rounded-md bg-sky-800 px-4 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
        >
          {submitting ? "Deploying…" : "Deploy"}
        </button>
      </form>

      {formError && (
        <div className="mt-4 rounded-md border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-300">
          {formError}
        </div>
      )}

      {lastResult && (
        <div className="mt-4 rounded-md border border-emerald-800 bg-emerald-950 px-3 py-2 text-sm text-emerald-300">
          Deployed <span className="font-medium">{lastResult.strategy_id}</span> on{" "}
          <span className="font-medium">{lastResult.symbol}</span> (deployment #{lastResult.deployment_id},{" "}
          {lastResult.is_active ? "active" : "paused"}).
        </div>
      )}

      <h2 className="mt-8 text-sm font-semibold text-slate-300">
        Deployments {deployments.length > 0 ? `(${deployments.length})` : ""}
      </h2>

      {deployments.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">Nothing deployed yet.</p>
      ) : (
        <div className="mt-2 overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-900 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Strategy</th>
                <th className="px-3 py-2">Symbol</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {deployments.map((d) => (
                <tr key={d.deployment_id} className="text-slate-300">
                  <td className="px-3 py-1.5">{d.strategy_id}</td>
                  <td className="px-3 py-1.5">{d.symbol}</td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        d.is_active
                          ? "bg-emerald-950 text-emerald-400"
                          : "bg-slate-800 text-slate-400"
                      }`}
                    >
                      {d.is_active ? "Active" : "Paused"}
                    </span>
                  </td>
                  <td className="px-3 py-1.5">
                    <button
                      onClick={() => toggleDeployment(d)}
                      disabled={toggling === d.deployment_id}
                      className="rounded-md border border-slate-700 px-3 py-1 text-xs font-medium text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                    >
                      {toggling === d.deployment_id ? "…" : d.is_active ? "Pause" : "Resume"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-6 text-xs text-slate-500">
        Fills need real SmartAPI credentials configured on the backend, and either NSE market
        hours (9:15-15:30 IST, Mon-Fri) or a manual off-hours trigger — see README.md's
        "Deployment" section for the scheduled GitHub Action that polls{" "}
        <code>/trigger/run-once</code>.
      </p>
    </div>
  );
}
