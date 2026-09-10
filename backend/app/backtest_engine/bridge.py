"""Bridges any QuantForge `Strategy` — a built-in class instance or a
saved graph's `GraphStrategy` instance, doesn't matter which — into a
`backtrader.Strategy`.

backtrader owns bar iteration, order execution, cash/position
bookkeeping, and the analyzers computed in `runner.py`; this class's
only job is translating between the two interfaces once per bar, which
is what keeps the bridge thin per the phase brief.
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd

from app.strategy_engine import Position, PositionSide, Signal, SignalAction, Strategy


def _bt_position_to_position(bt_position: bt.position.Position) -> Position:
    if bt_position.size > 0:
        return Position(side=PositionSide.LONG, qty=float(bt_position.size), avg_price=float(bt_position.price))
    if bt_position.size < 0:
        return Position(side=PositionSide.SHORT, qty=float(abs(bt_position.size)), avg_price=float(bt_position.price))
    return Position(side=PositionSide.FLAT)


class StrategyBridge(bt.Strategy):
    """`params.strategy` is the QuantForge `Strategy` instance to run;
    `params.full_df` is the *exact* OHLCV DataFrame handed to Cerebro as
    the data feed (tz-naive, same index backtrader iterates).

    Every bar, `strategy.generate_signal` is given
    `full_df.iloc[:len(self)]` — the slice ending at the current bar.
    `len(self)` is backtrader's own running bar count, so this can never
    include a future row by construction: the same guarantee
    `Strategy.generate_signal`'s docstring already promises callers,
    just satisfied here by slicing instead of by trusting the caller.
    """

    # Named "qf_strategy" rather than "strategy" — backtrader's own
    # Cerebro.addstrategy(strategy, *args, **kwargs) already has a
    # positional parameter called `strategy` (the strategy *class*
    # itself), so passing `strategy=...` as a param kwarg collides with
    # it ("got multiple values for argument 'strategy'").
    params = (("qf_strategy", None), ("full_df", None))

    def __init__(self) -> None:
        self._strategy: Strategy = self.p.qf_strategy
        self.equity_curve: list[dict] = []
        self.trade_log: list[dict] = []

    def next(self) -> None:
        df_so_far: pd.DataFrame = self.p.full_df.iloc[: len(self)]
        position = _bt_position_to_position(self.position)
        signal: Signal = self._strategy.generate_signal(df_so_far, position)

        # Mirrors every built-in/graph strategy's own guard (BUY only
        # when not already long, SELL/close only when long) — belt and
        # suspenders, since a misbehaving strategy shouldn't be able to
        # get the bridge into a state backtrader can't fill sensibly.
        if signal.action == SignalAction.BUY and not self.position:
            self.buy()
        elif signal.action == SignalAction.SELL and self.position:
            self.close()

        self.equity_curve.append(
            {"ts": self.data.datetime.datetime(0).isoformat(), "equity": float(self.broker.getvalue())}
        )

    def notify_order(self, order: bt.Order) -> None:
        if order.status == order.Completed:
            self.trade_log.append(
                {
                    "ts": bt.num2date(order.executed.dt).isoformat(),
                    "side": "BUY" if order.isbuy() else "SELL",
                    "price": float(order.executed.price),
                    "qty": abs(float(order.executed.size)),
                }
            )
