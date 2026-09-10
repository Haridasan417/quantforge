// Shared shapes for the Strategy Builder canvas. Mirrors
// backend/app/schemas/strategies.py and backend/app/strategy_engine/
// graph_strategy.py — keep both sides in sync if either changes.

export interface IndicatorField {
  field: string;
  label: string;
  params: Record<string, number>;
}

export interface StrategyIndicatorsResponse {
  indicators: IndicatorField[];
  comparators: string[];
  actions: string[];
}

// The persisted, backend-facing shape of a condition/action node's
// `data` — no UI-only fields (onChange callbacks, the indicator
// catalog) ride along here; those get stripped out before a save (see
// StrategyBuilder.tsx's `serializeGraph`).
export interface ConditionFields {
  indicator: string;
  comparator: string;
  threshold: number;
  params: Record<string, number>;
}

export interface ActionFields {
  action: "BUY" | "SELL";
}

// What actually lives in a ReactFlow node's `data` while it's on the
// canvas: the persisted fields, plus the UI needs (the indicator
// catalog / comparator list so the node's own dropdowns can render
// without prop-drilling from the canvas) and an onChange callback bound
// to that node's id.
export interface ConditionData extends ConditionFields {
  indicatorCatalog: IndicatorField[];
  comparators: string[];
  onChange: (patch: Partial<ConditionFields>) => void;
}

export interface ActionData extends ActionFields {
  onChange: (patch: Partial<ActionFields>) => void;
}

export interface StrategyInfo {
  name: string;
  description: string;
  source: "builtin" | "graph";
  config_schema: Record<string, unknown>;
  config?: { nodes: unknown[]; edges: unknown[] } | null;
}

export interface StrategiesResponse {
  strategies: StrategyInfo[];
}
