"""Unit tests for the Risk Manager (Phase 6) — pure, DB-free, matching
the rest of the suite's convention. Uses fixed `RiskManagerSettings`
rather than `app.config.settings` so cases don't depend on env vars."""
from __future__ import annotations

import pytest

from app.risk_manager import ApprovedOrder, PortfolioState, RiskManager, RiskManagerSettings
from app.strategy_engine import Position, PositionSide, Signal, SignalAction

SETTINGS = RiskManagerSettings(
    stop_loss_pct=0.05,
    max_position_size_pct=0.20,
    max_total_exposure_pct=0.60,
)


@pytest.fixture
def manager() -> RiskManager:
    return RiskManager(settings=SETTINGS)


def flat_portfolio(equity: float = 100_000.0, cash: float | None = None) -> PortfolioState:
    return PortfolioState(cash=cash if cash is not None else equity, equity=equity, holdings_value={})


def test_hold_signal_is_a_no_op(manager: RiskManager) -> None:
    decision = manager.evaluate(
        Signal(action=SignalAction.HOLD),
        "RELIANCE.NS",
        100.0,
        Position(),
        flat_portfolio(),
    )
    assert decision.approved is False
    assert decision.order is None


def test_buy_signal_sized_within_max_position_pct(manager: RiskManager) -> None:
    # equity=100_000, max_position_size_pct=0.20 -> budget 20_000 @ price 100 -> 200 shares
    decision = manager.evaluate(
        Signal(action=SignalAction.BUY),
        "RELIANCE.NS",
        100.0,
        Position(),
        flat_portfolio(equity=100_000.0),
    )
    assert decision.approved is True
    assert isinstance(decision.order, ApprovedOrder)
    assert decision.order.side == SignalAction.BUY
    assert decision.order.qty == 200
    assert decision.order.price == 100.0


def test_buy_signal_capped_by_remaining_exposure_budget(manager: RiskManager) -> None:
    # equity=100_000, max_total_exposure_pct=0.60 -> exposure budget 60_000.
    # Already holding 55_000 worth elsewhere -> only 5_000 of headroom left,
    # even though max_position_size_pct alone would allow 20_000.
    portfolio = PortfolioState(
        cash=45_000.0,
        equity=100_000.0,
        holdings_value={"TCS.NS": 55_000.0},
    )
    decision = manager.evaluate(
        Signal(action=SignalAction.BUY),
        "RELIANCE.NS",
        100.0,
        Position(),
        portfolio,
    )
    assert decision.approved is True
    assert decision.order.qty == 50  # 5_000 / 100


def test_buy_signal_rejected_when_exposure_budget_exhausted(manager: RiskManager) -> None:
    portfolio = PortfolioState(
        cash=1_000.0,
        equity=100_000.0,
        holdings_value={"TCS.NS": 60_000.0},
    )
    decision = manager.evaluate(
        Signal(action=SignalAction.BUY),
        "RELIANCE.NS",
        100.0,
        Position(),
        portfolio,
    )
    assert decision.approved is False
    assert "exposure" in decision.reason


def test_buy_signal_capped_by_available_cash(manager: RiskManager) -> None:
    # max_position_size_pct budget would be 20_000, but only 1_500 cash on hand.
    portfolio = PortfolioState(cash=1_500.0, equity=100_000.0, holdings_value={})
    decision = manager.evaluate(
        Signal(action=SignalAction.BUY),
        "RELIANCE.NS",
        100.0,
        Position(),
        portfolio,
    )
    assert decision.approved is True
    assert decision.order.qty == 15  # 1_500 / 100


def test_buy_signal_rejected_when_already_long(manager: RiskManager) -> None:
    decision = manager.evaluate(
        Signal(action=SignalAction.BUY),
        "RELIANCE.NS",
        100.0,
        Position(side=PositionSide.LONG, qty=10, avg_price=90.0),
        flat_portfolio(),
    )
    assert decision.approved is False
    assert "already long" in decision.reason


def test_buy_signal_rejected_when_budget_too_small_for_one_share(manager: RiskManager) -> None:
    portfolio = PortfolioState(cash=50.0, equity=100_000.0, holdings_value={})
    decision = manager.evaluate(
        Signal(action=SignalAction.BUY),
        "RELIANCE.NS",
        100.0,
        Position(),
        portfolio,
    )
    assert decision.approved is False
    assert "too small" in decision.reason


def test_sell_signal_approved_when_long(manager: RiskManager) -> None:
    decision = manager.evaluate(
        Signal(action=SignalAction.SELL),
        "RELIANCE.NS",
        120.0,
        Position(side=PositionSide.LONG, qty=50, avg_price=100.0),
        flat_portfolio(),
    )
    assert decision.approved is True
    assert decision.order.side == SignalAction.SELL
    assert decision.order.qty == 50
    assert decision.order.price == 120.0


def test_sell_signal_rejected_when_flat(manager: RiskManager) -> None:
    decision = manager.evaluate(
        Signal(action=SignalAction.SELL),
        "RELIANCE.NS",
        120.0,
        Position(),
        flat_portfolio(),
    )
    assert decision.approved is False
    assert "no open position" in decision.reason


def test_stop_loss_triggers_exit_even_on_hold_signal(manager: RiskManager) -> None:
    # avg_price=100, stop_loss_pct=0.05 -> stop at 95. Price at 94 breaches it.
    decision = manager.evaluate(
        Signal(action=SignalAction.HOLD),
        "RELIANCE.NS",
        94.0,
        Position(side=PositionSide.LONG, qty=30, avg_price=100.0),
        flat_portfolio(),
    )
    assert decision.approved is True
    assert decision.order.side == SignalAction.SELL
    assert decision.order.qty == 30
    assert "stop-loss" in decision.reason


def test_stop_loss_does_not_trigger_above_threshold(manager: RiskManager) -> None:
    decision = manager.evaluate(
        Signal(action=SignalAction.HOLD),
        "RELIANCE.NS",
        96.0,
        Position(side=PositionSide.LONG, qty=30, avg_price=100.0),
        flat_portfolio(),
    )
    assert decision.approved is False


def test_stop_loss_overrides_a_buy_signal_too(manager: RiskManager) -> None:
    decision = manager.evaluate(
        Signal(action=SignalAction.BUY),
        "RELIANCE.NS",
        90.0,
        Position(side=PositionSide.LONG, qty=30, avg_price=100.0),
        flat_portfolio(),
    )
    assert decision.approved is True
    assert decision.order.side == SignalAction.SELL
    assert "stop-loss" in decision.reason


def test_uses_app_settings_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.config as config_module

    monkeypatch.setattr(config_module.settings, "stop_loss_pct", 0.10)
    monkeypatch.setattr(config_module.settings, "max_position_size_pct", 0.5)
    monkeypatch.setattr(config_module.settings, "max_total_exposure_pct", 0.9)

    manager = RiskManager()
    assert manager.settings.stop_loss_pct == 0.10
    assert manager.settings.max_position_size_pct == 0.5
    assert manager.settings.max_total_exposure_pct == 0.9
