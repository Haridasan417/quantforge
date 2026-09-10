"""GraphStrategy: interprets a saved Strategy Builder graph (nodes +
edges, straight from React Flow) at `generate_signal` time.

Unlike MACrossoverStrategy/RSIThresholdStrategy, this class is never
registered with `@register_strategy` — a fixed name would imply one
shared set of parameters, but every *saved graph* has its own
nodes/edges. Instead `app.api.strategies` builds one `GraphStrategy`
instance per saved `Strategy` DB row (`type="graph"`) and registers
that instance under `f"graph:{row.id}"` via
`registry.register_strategy_instance` — so it shows up anywhere
registered strategies are listed, and the backtest engine (Phase 5) /
executor (Phase 6) never need to know this one came from the visual
builder rather than a decorated class.
"""
from __future__ import annotations

import operator
from collections import defaultdict
from typing import Any, Callable

import pandas as pd
from pydantic import BaseModel, Field

from app.data_service.indicators import (
    DEFAULT_EMA_LENGTH,
    DEFAULT_MACD_FAST,
    DEFAULT_MACD_SIGNAL,
    DEFAULT_MACD_SLOW,
    DEFAULT_RSI_LENGTH,
)
from app.data_service.indicators import ema as compute_ema
from app.data_service.indicators import macd as compute_macd
from app.data_service.indicators import rsi as compute_rsi
from app.strategy_engine.base_strategy import Position, PositionSide, Signal, SignalAction, Strategy

# The indicator "fields" a ConditionNode can compare against, plus the
# default params each one needs. This is exactly what GET
# /api/strategies/indicators hands the frontend to populate the
# indicator dropdown — data_service.indicators stays the single source
# of truth for both, so the builder UI can never drift out of sync with
# what the backend can actually compute.
INDICATOR_FIELDS: dict[str, dict[str, Any]] = {
    "close": {"label": "Close Price", "params": {}},
    "rsi": {"label": "RSI", "params": {"length": DEFAULT_RSI_LENGTH}},
    "ema": {"label": "EMA", "params": {"length": DEFAULT_EMA_LENGTH}},
    "macd_line": {
        "label": "MACD Line",
        "params": {"fast": DEFAULT_MACD_FAST, "slow": DEFAULT_MACD_SLOW, "signal": DEFAULT_MACD_SIGNAL},
    },
    "macd_signal": {
        "label": "MACD Signal",
        "params": {"fast": DEFAULT_MACD_FAST, "slow": DEFAULT_MACD_SLOW, "signal": DEFAULT_MACD_SIGNAL},
    },
    "macd_hist": {
        "label": "MACD Histogram",
        "params": {"fast": DEFAULT_MACD_FAST, "slow": DEFAULT_MACD_SLOW, "signal": DEFAULT_MACD_SIGNAL},
    },
}

COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


class GraphStrategyConfig(BaseModel):
    """Nodes/edges verbatim from React Flow (`{id, type, data, position}`
    / `{id, source, target}`). Positions and any other frontend-only
    fields ride along unused by the interpreter so the builder can
    reload a saved graph exactly as the user left it."""

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class GraphStrategyError(ValueError):
    """A malformed graph. Raised by `validate_graph()` (the API layer
    turns this into a 422 at save time, so a broken graph is rejected
    immediately rather than discovered later inside a backtest) and by
    `generate_signal` if a condition node's indicator/comparator is
    invalid."""


def _validate_condition_shape(data: dict[str, Any]) -> None:
    field = data.get("indicator")
    comparator = data.get("comparator")
    threshold = data.get("threshold")
    if field not in INDICATOR_FIELDS:
        raise GraphStrategyError(f"Condition node has unknown indicator {field!r}")
    if comparator not in COMPARATORS:
        raise GraphStrategyError(f"Condition node has unknown comparator {comparator!r}")
    if threshold is None:
        raise GraphStrategyError("Condition node is missing a threshold")


def _resolve_field(field: str, params: dict[str, Any], df: pd.DataFrame) -> float | None:
    """The latest value of `field` for the current row of `df`, or None
    if it hasn't warmed up yet (not enough bars for the indicator)."""
    if df.empty:
        return None

    if field == "close":
        return float(df["close"].iloc[-1])

    if field == "rsi":
        length = int(params.get("length", DEFAULT_RSI_LENGTH))
        value = compute_rsi(df, length=length).iloc[-1]
    elif field == "ema":
        length = int(params.get("length", DEFAULT_EMA_LENGTH))
        value = compute_ema(df, length=length).iloc[-1]
    elif field in ("macd_line", "macd_signal", "macd_hist"):
        fast = int(params.get("fast", DEFAULT_MACD_FAST))
        slow = int(params.get("slow", DEFAULT_MACD_SLOW))
        signal_len = int(params.get("signal", DEFAULT_MACD_SIGNAL))
        frame = compute_macd(df, fast=fast, slow=slow, signal=signal_len)
        column = {
            "macd_line": f"MACD_{fast}_{slow}_{signal_len}",
            "macd_signal": f"MACDs_{fast}_{slow}_{signal_len}",
            "macd_hist": f"MACDh_{fast}_{slow}_{signal_len}",
        }[field]
        value = frame[column].iloc[-1]
    else:  # pragma: no cover - guarded by _validate_condition_shape everywhere this is reachable
        raise GraphStrategyError(f"Unknown indicator field {field!r}")

    return None if pd.isna(value) else float(value)


def _evaluate_condition(data: dict[str, Any], df: pd.DataFrame) -> bool | None:
    """True/False if the condition could be evaluated against the
    latest row, or None if its indicator is still warming up."""
    _validate_condition_shape(data)
    value = _resolve_field(data["indicator"], data.get("params") or {}, df)
    if value is None:
        return None
    return COMPARATORS[data["comparator"]](value, float(data["threshold"]))


class GraphStrategy(Strategy):
    """Interprets a Strategy Builder graph: every ConditionNode wired
    into an ActionNode must hold — an AND-chain — for that action to
    fire. Multiple independent action nodes (e.g. one BUY chain, one
    SELL chain) are supported; the first whose conditions are all true
    *and* makes sense given the current position wins."""

    @classmethod
    def config_schema(cls) -> type[BaseModel]:
        return GraphStrategyConfig

    def _nodes_by_id(self) -> dict[str, dict[str, Any]]:
        return {n["id"]: n for n in self.config.nodes if "id" in n}

    def _conditions_by_action(self) -> dict[str, list[str]]:
        nodes = self._nodes_by_id()
        condition_ids = {nid for nid, n in nodes.items() if n.get("type") == "condition"}
        action_ids = {nid for nid, n in nodes.items() if n.get("type") == "action"}

        incoming: dict[str, list[str]] = defaultdict(list)
        for edge in self.config.edges:
            source, target = edge.get("source"), edge.get("target")
            if source in condition_ids and target in action_ids:
                incoming[target].append(source)
        return incoming

    def validate_graph(self) -> None:
        """Structural validation beyond what `GraphStrategyConfig`
        checks: every node has a known type and well-formed data, every
        edge references real nodes, there's at least one action node,
        and at least one action node has a condition wired into it.
        Called by the API layer before persisting a save."""
        nodes = self._nodes_by_id()

        for node_id, node in nodes.items():
            node_type = node.get("type")
            data = node.get("data") or {}
            if node_type == "condition":
                _validate_condition_shape(data)
            elif node_type == "action":
                if data.get("action") not in ("BUY", "SELL"):
                    raise GraphStrategyError(f"Action node {node_id!r} must have action BUY or SELL")
            else:
                raise GraphStrategyError(f"Node {node_id!r} has unknown type {node_type!r}")

        for edge in self.config.edges:
            if edge.get("source") not in nodes or edge.get("target") not in nodes:
                raise GraphStrategyError(f"Edge {edge!r} references a node that doesn't exist")

        if not any(node.get("type") == "action" for node in nodes.values()):
            raise GraphStrategyError("Graph has no action node")
        if not any(self._conditions_by_action().values()):
            raise GraphStrategyError("No action node has any condition wired into it")

    def generate_signal(self, df: pd.DataFrame, position: Position) -> Signal:
        if df.empty:
            return Signal(action=SignalAction.HOLD, reason="no data")

        nodes = self._nodes_by_id()
        incoming = self._conditions_by_action()

        warming_up = False
        for action_id, condition_ids in incoming.items():
            if not condition_ids:
                continue

            results = [_evaluate_condition(nodes[cid]["data"], df) for cid in condition_ids]
            if any(r is None for r in results):
                warming_up = True
                continue
            if not all(results):
                continue

            action = nodes[action_id]["data"]["action"]
            if action == "BUY" and position.side != PositionSide.LONG:
                return Signal(action=SignalAction.BUY, reason=f"graph node {action_id} conditions met")
            if action == "SELL" and position.side == PositionSide.LONG:
                return Signal(action=SignalAction.SELL, reason=f"graph node {action_id} conditions met")

        if warming_up:
            return Signal(action=SignalAction.HOLD, reason="warm-up")
        return Signal(action=SignalAction.HOLD, reason="no action's conditions satisfied")
