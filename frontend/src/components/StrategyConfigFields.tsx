import type { StrategyInfo } from "./strategy-builder/types";

// Loose shape of the JSON Schema `GET /api/strategies` returns per
// strategy (backend/app/strategy_engine/*'s `config_schema()`) — just
// enough to drive a config form generically. Shared by Backtest.tsx and
// Deploy.tsx so both render the same "one input per required field"
// form for whichever built-in needs it (currently only `RLConfig
// .checkpoint_name`, which has no default — see CLAUDE.md's Phase 7
// part B "Follow-up fix" note) without either page hard-coding "rl".
interface JsonSchemaProperty {
  title?: string;
  description?: string;
}

interface ConfigJsonSchema {
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

// Only built-ins take a per-request config override at all — a saved
// graph's config lives on its own row (see resolve_strategy in
// backend/app/backtest_engine/resolve.py), so this is always empty for
// `source === "graph"`.
export function requiredConfigFieldsFor(strategy: StrategyInfo | undefined): string[] {
  if (!strategy || strategy.source !== "builtin") return [];
  const schema = (strategy.config_schema ?? {}) as ConfigJsonSchema;
  return schema.required ?? [];
}

export function StrategyConfigFields({
  strategy,
  fields,
  values,
  onChange,
}: {
  strategy: StrategyInfo | undefined;
  fields: string[];
  values: Record<string, string>;
  onChange: (field: string, value: string) => void;
}) {
  const schema = (strategy?.config_schema ?? {}) as ConfigJsonSchema;

  return (
    <>
      {fields.map((field) => {
        const meta = schema.properties?.[field];
        return (
          <div key={field}>
            <label className="mb-1 block text-xs text-slate-400" htmlFor={`config-${field}`}>
              {meta?.title ?? field}
            </label>
            <input
              id={`config-${field}`}
              value={values[field] ?? ""}
              onChange={(e) => onChange(field, e.target.value)}
              placeholder={meta?.description ?? field}
              title={meta?.description}
              className="w-56 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white"
            />
          </div>
        );
      })}
    </>
  );
}

export function missingRequiredField(
  fields: string[],
  values: Record<string, string>,
  strategy: StrategyInfo | undefined,
): string | null {
  const schema = (strategy?.config_schema ?? {}) as ConfigJsonSchema;
  const missing = fields.find((field) => !values[field]?.trim());
  if (!missing) return null;
  return schema.properties?.[missing]?.title ?? missing;
}
