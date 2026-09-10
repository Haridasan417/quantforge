"""Walk-forward MA crossover: like `MACrossoverStrategy`, but its
fast/slow periods aren't fixed at construction time — they're
periodically re-fit from a small grid search over recent history, then
traded out-of-sample. No GPU/training involved; "fitting" is just
picking whichever candidate `(fast, slow)` pair would have performed
best mechanically over a trailing window.
"""
from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from app.strategy_engine.base_strategy import Position, PositionSide, Signal, SignalAction, Strategy
from app.strategy_engine.registry import register_strategy


class WalkForwardConfig(BaseModel):
    train_window: int = Field(60, gt=10, description="Bars used to re-fit the (fast, slow) MA periods")
    test_window: int = Field(
        20,
        gt=0,
        description="Bars of gap between the fit window and the current bar -- the out-of-sample window the fit is never allowed to see",
    )
    fast_candidates: list[int] = Field(
        default_factory=lambda: [5, 10, 15, 20], description="Candidate fast MA periods to search"
    )
    slow_candidates: list[int] = Field(
        default_factory=lambda: [20, 30, 40, 50], description="Candidate slow MA periods to search"
    )

    @model_validator(mode="after")
    def _some_valid_pair_exists(self) -> "WalkForwardConfig":
        if not any(fast < slow for fast in self.fast_candidates for slow in self.slow_candidates):
            raise ValueError("no (fast_candidates, slow_candidates) pair has fast < slow")
        return self


def _mechanical_return(closes: pd.Series, fast: int, slow: int) -> float:
    """Total return of naively going long whenever the fast MA is above
    the slow MA (flat otherwise) over `closes`, using *yesterday's*
    crossover state to earn *today's* return — the same no-lookahead
    shift `MACrossoverStrategy`/backtest already respect elsewhere in
    this project. Used only to score candidate `(fast, slow)` pairs
    against each other, not as a real backtest metric (no costs,
    sizing, or risk rules)."""
    fast_ma = closes.rolling(fast).mean()
    slow_ma = closes.rolling(slow).mean()
    long_signal = (fast_ma > slow_ma).astype(float)
    daily_returns = closes.pct_change()
    strategy_returns = (long_signal.shift(1).fillna(0.0) * daily_returns).fillna(0.0)
    return float((1.0 + strategy_returns).prod() - 1.0)


def _best_params(
    closes: pd.Series, fast_candidates: list[int], slow_candidates: list[int]
) -> tuple[int, int] | None:
    """Grid search: every valid `fast < slow` pair with enough bars in
    `closes` to actually compute a scored crossover, ranked by
    `_mechanical_return`. Iterates candidates in ascending order so a
    tie deterministically keeps the smallest (fast, slow) already seen
    (simpler models preferred over an arbitrary later tie). Returns
    `None` if no candidate pair had enough data."""
    best: tuple[int, int] | None = None
    best_score = float("-inf")
    for fast in sorted(fast_candidates):
        for slow in sorted(slow_candidates):
            if fast >= slow or len(closes) < slow + 2:
                continue
            score = _mechanical_return(closes, fast, slow)
            if score > best_score:
                best_score = score
                best = (fast, slow)
    return best


@register_strategy("walk_forward")
class WalkForwardStrategy(Strategy):
    """BUY when the *currently best-fit* fast MA crosses above the
    slow MA and we're not already long; SELL when it crosses back below
    and we are. "Best-fit" is re-derived on every call: a grid search
    over `config.fast_candidates`/`slow_candidates`, scored on the
    `train_window` bars ending `test_window` bars before the live bar
    (so the fit is always evaluated out-of-sample on the bars it's
    about to trade, never on the window it was fit on)."""

    @classmethod
    def config_schema(cls) -> type[BaseModel]:
        return WalkForwardConfig

    def generate_signal(self, df: pd.DataFrame, position: Position) -> Signal:
        cfg = self.config

        fit_end = len(df) - cfg.test_window
        if fit_end < cfg.train_window:
            return Signal(action=SignalAction.HOLD, reason="warm-up: not enough history to re-fit yet")

        fit_slice = df["close"].iloc[max(0, fit_end - cfg.train_window) : fit_end]
        best = _best_params(fit_slice, cfg.fast_candidates, cfg.slow_candidates)
        if best is None:
            return Signal(action=SignalAction.HOLD, reason="no candidate (fast, slow) pair had enough data to fit")
        fast, slow = best

        if len(df) < slow + 1:
            return Signal(
                action=SignalAction.HOLD, reason=f"not enough live data yet for the fitted slow period ({slow})"
            )

        closes = df["close"]
        fast_ma = closes.rolling(fast).mean()
        slow_ma = closes.rolling(slow).mean()

        prev_fast, prev_slow = fast_ma.iloc[-2], slow_ma.iloc[-2]
        curr_fast, curr_slow = fast_ma.iloc[-1], slow_ma.iloc[-1]

        if pd.isna(prev_fast) or pd.isna(prev_slow) or pd.isna(curr_fast) or pd.isna(curr_slow):
            return Signal(action=SignalAction.HOLD, reason="warm-up")

        crossed_up = prev_fast <= prev_slow and curr_fast > curr_slow
        crossed_down = prev_fast >= prev_slow and curr_fast < curr_slow

        if crossed_up and position.side != PositionSide.LONG:
            return Signal(action=SignalAction.BUY, reason=f"re-fit ({fast},{slow}): fast MA crossed above slow MA")
        if crossed_down and position.side == PositionSide.LONG:
            return Signal(action=SignalAction.SELL, reason=f"re-fit ({fast},{slow}): fast MA crossed below slow MA")

        return Signal(action=SignalAction.HOLD, reason=f"re-fit ({fast},{slow}): no new crossover")
