"""Sanity checks for TradingEnv (Phase 7 part A) -- run with `cd ml &&
pytest` (see ml/pytest.ini for how both `envs.trading_env` and
`app.strategy_engine.features` end up importable). Uses gymnasium's own
`check_env` (no stable-baselines3 needed just to validate the
Gymnasium API contract) plus a full episode rollout checking shapes,
dtypes, and termination.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from gymnasium.utils.env_checker import check_env

from envs.trading_env import HOLD, BUY, SELL, TradingEnv, chronological_split
from app.strategy_engine.features import FEATURE_WINDOW, OBSERVATION_SIZE


def _make_df(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # A gentle random walk -- enough variation for RSI/EMA/MACD to be
    # meaningful, no huge jumps that would blow up pct_change-based
    # features.
    steps = rng.normal(loc=0.0005, scale=0.01, size=n)
    closes = 100.0 * np.cumprod(1.0 + steps)
    index = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.002,
            "low": closes * 0.998,
            "close": closes,
            "volume": 1_000_000,
        },
        index=index,
    )


def test_chronological_split_is_contiguous_and_never_shuffles() -> None:
    df = _make_df(1000)
    train, val, test = chronological_split(df, train_frac=0.7, val_frac=0.15)

    assert len(train) + len(val) + len(test) == len(df)
    # Contiguous, time-ordered: train ends exactly where val begins, etc.
    assert train.index[-1] < val.index[0]
    assert val.index[-1] < test.index[0]
    pd.testing.assert_frame_equal(pd.concat([train, val, test]), df)


def test_chronological_split_rejects_bad_fractions() -> None:
    df = _make_df(100)
    with pytest.raises(ValueError):
        chronological_split(df, train_frac=0.7, val_frac=0.4)  # sums to >= 1.0


def test_env_rejects_too_short_a_dataframe() -> None:
    with pytest.raises(ValueError):
        TradingEnv(_make_df(5))


def test_gymnasium_check_env_passes() -> None:
    env = TradingEnv(_make_df(300))
    check_env(env.unwrapped, skip_render_check=True)


def test_reset_returns_a_valid_observation() -> None:
    env = TradingEnv(_make_df(300))
    obs, info = env.reset(seed=42)
    assert obs.shape == (OBSERVATION_SIZE,)
    assert obs.dtype == np.float32
    assert np.isfinite(obs).all()
    assert info["position"] == 0


def test_full_episode_rollout_terminates_and_keeps_valid_shapes() -> None:
    env = TradingEnv(_make_df(250))
    obs, _ = env.reset(seed=0)
    rng = np.random.default_rng(1)

    steps = 0
    terminated = False
    while not terminated:
        action = int(rng.integers(0, 3))
        obs, reward, terminated, truncated, info = env.step(action)
        assert obs.shape == (OBSERVATION_SIZE,)
        assert obs.dtype == np.float32
        assert isinstance(reward, float)
        assert np.isfinite(reward)
        assert truncated is False
        steps += 1
        assert steps < 10_000  # guard against an infinite loop if termination logic regresses

    assert steps > 0


def test_buy_then_hold_keeps_position_long() -> None:
    env = TradingEnv(_make_df(300))
    env.reset(seed=0)
    _, _, _, _, info = env.step(BUY)
    assert info["position"] == 1
    _, _, _, _, info = env.step(HOLD)
    assert info["position"] == 1  # HOLD is a no-op on position, not "go flat"


def test_sell_while_flat_is_a_no_op_on_position() -> None:
    env = TradingEnv(_make_df(300))
    env.reset(seed=0)
    _, _, _, _, info = env.step(SELL)
    assert info["position"] == 0


def test_transaction_cost_penalizes_flipping_every_step() -> None:
    # Flipping position every single step should score worse (lower
    # cumulative raw reward) than just holding flat throughout, given a
    # non-trivial transaction cost -- confirms the cost term actually
    # bites rather than being a no-op in the reward calculation.
    df = _make_df(300)

    env_flip = TradingEnv(df, transaction_cost=0.01)
    env_flip.reset(seed=0)
    flip_raw_total = 0.0
    action = BUY
    terminated = False
    while not terminated:
        _, _, terminated, _, info = env_flip.step(action)
        flip_raw_total += info["raw_reward"]
        action = SELL if action == BUY else BUY

    env_flat = TradingEnv(df, transaction_cost=0.01)
    env_flat.reset(seed=0)
    flat_raw_total = 0.0
    terminated = False
    while not terminated:
        _, _, terminated, _, info = env_flat.step(HOLD)
        flat_raw_total += info["raw_reward"]

    assert flat_raw_total == pytest.approx(0.0)
    assert flip_raw_total < flat_raw_total
