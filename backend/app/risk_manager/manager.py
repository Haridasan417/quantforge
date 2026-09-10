"""Given a strategy's `Signal` and the account's current portfolio
state, decide whether to approve it as an order (and how big), adjust
its size, or reject it outright — stop-loss %, max position size %, and
max total exposure % are the three rules from the Phase 6 brief.

Deliberately config-object-driven (`RiskManagerSettings`, sourced from
`app.config.settings` by default) rather than hard-coded constants, so a
future settings-table override (per-user or per-deployment risk limits)
is a matter of constructing a different `RiskManagerSettings`, not
touching this module's logic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.strategy_engine import Position, PositionSide, Signal, SignalAction


class RiskManagerSettings(BaseModel):
    stop_loss_pct: float
    max_position_size_pct: float
    max_total_exposure_pct: float


@dataclass(frozen=True)
class ApprovedOrder:
    """A risk-approved, sized order — what the Executor actually fills.
    `side` is always BUY or SELL; a HOLD signal never reaches this far."""

    side: SignalAction
    symbol: str
    qty: float
    price: float
    reason: str


@dataclass(frozen=True)
class RiskDecision:
    order: ApprovedOrder | None
    reason: str

    @property
    def approved(self) -> bool:
        return self.order is not None


@dataclass(frozen=True)
class PortfolioState:
    """The Executor's account-wide view, derived from the single latest
    `PortfolioSnapshot` row (there's no per-strategy portfolio — see
    CLAUDE.md's Phase 6 section)."""

    cash: float
    equity: float
    holdings_value: dict[str, float] = field(default_factory=dict)  # symbol -> current market value

    @property
    def total_exposure(self) -> float:
        return sum(self.holdings_value.values())


def _default_settings() -> RiskManagerSettings:
    # Imported lazily (inside the function, not at module scope) so
    # tests can monkeypatch app.config.settings before a RiskManager is
    # constructed without needing to reload this module.
    from app.config import settings as app_settings

    return RiskManagerSettings(
        stop_loss_pct=app_settings.stop_loss_pct,
        max_position_size_pct=app_settings.max_position_size_pct,
        max_total_exposure_pct=app_settings.max_total_exposure_pct,
    )


class RiskManager:
    """Stateless — one instance can be reused across every event the
    Executor processes. `evaluate` is pure: given the same inputs it
    always returns the same decision, which is what makes the
    integration test's "assert correctly risk-adjusted sizing" possible
    without mocking anything inside this class."""

    def __init__(self, settings: RiskManagerSettings | None = None) -> None:
        self.settings = settings or _default_settings()

    def evaluate(
        self,
        signal: Signal,
        symbol: str,
        reference_price: float,
        position: Position,
        portfolio: PortfolioState,
    ) -> RiskDecision:
        # Protective stop-loss overrides everything else: if we're long
        # and the reference price has breached the stop, exit
        # regardless of what the strategy's signal says this bar.
        if position.side == PositionSide.LONG and position.qty > 0 and position.avg_price > 0:
            stop_price = position.avg_price * (1 - self.settings.stop_loss_pct)
            if reference_price <= stop_price:
                return RiskDecision(
                    order=ApprovedOrder(
                        side=SignalAction.SELL,
                        symbol=symbol,
                        qty=position.qty,
                        price=reference_price,
                        reason=f"stop-loss triggered ({reference_price:.2f} <= {stop_price:.2f})",
                    ),
                    reason="stop-loss triggered",
                )

        if signal.action == SignalAction.HOLD:
            return RiskDecision(order=None, reason="signal is HOLD, no action")

        if signal.action == SignalAction.SELL:
            if position.side != PositionSide.LONG or position.qty <= 0:
                return RiskDecision(order=None, reason="SELL signal but no open position to exit")
            return RiskDecision(
                order=ApprovedOrder(
                    side=SignalAction.SELL,
                    symbol=symbol,
                    qty=position.qty,
                    price=reference_price,
                    reason="strategy SELL signal",
                ),
                reason="approved",
            )

        # BUY
        if position.side == PositionSide.LONG and position.qty > 0:
            return RiskDecision(order=None, reason="already long, ignoring duplicate BUY signal")

        if portfolio.equity <= 0:
            return RiskDecision(order=None, reason="no equity available")

        max_position_value = portfolio.equity * self.settings.max_position_size_pct
        remaining_exposure_budget = (
            portfolio.equity * self.settings.max_total_exposure_pct - portfolio.total_exposure
        )
        if remaining_exposure_budget <= 0:
            return RiskDecision(
                order=None,
                reason=f"max total exposure ({self.settings.max_total_exposure_pct:.0%}) already reached",
            )

        position_value = min(max_position_value, remaining_exposure_budget, portfolio.cash)
        if position_value <= 0:
            return RiskDecision(order=None, reason="insufficient cash or exposure budget for a new position")

        if reference_price <= 0:
            return RiskDecision(order=None, reason="invalid reference price")

        qty = math.floor(position_value / reference_price)
        if qty <= 0:
            return RiskDecision(
                order=None,
                reason=f"position budget {position_value:.2f} too small to buy 1 share at {reference_price:.2f}",
            )

        return RiskDecision(
            order=ApprovedOrder(
                side=SignalAction.BUY,
                symbol=symbol,
                qty=qty,
                price=reference_price,
                reason="strategy BUY signal, sized within risk limits",
            ),
            reason="approved",
        )
