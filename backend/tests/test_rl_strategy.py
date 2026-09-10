"""RLStrategy (Phase 7 part B): loads a trained stable-baselines3 DQN
checkpoint and turns its action into the same `Signal` every other
strategy uses. Trains its own tiny, fast checkpoint against a minimal
synthetic Gymnasium env (NOT `ml/envs/trading_env.py` -- this package
deliberately never imports anything under `ml/`, see
`rl_strategy.py`'s module docstring) rather than depending on a real
pretrained checkpoint, since `ml/checkpoints/*.zip` is gitignored
(trained artifacts, not source) and never present in CI.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import DQN

import app.strategy_engine.strategies.rl_strategy as rl_mod
from app.strategy_engine.base_strategy import Position, PositionSide, SignalAction
from app.strategy_engine.features import OBSERVATION_SIZE
from app.strategy_engine.registry import get_strategy
from app.strategy_engine.strategies.rl_strategy import RLConfig, RLStrategy


class _TinyObsActionEnv(gym.Env):
    """Matches RLStrategy's expected observation/action shapes
    (`Box(OBSERVATION_SIZE,)`, `Discrete(3)`) without importing
    `ml/envs/trading_env.py` or needing real market data -- just
    enough for stable-baselines3 to train a handful of steps and
    produce a real, loadable checkpoint."""

    metadata = {"render_modes": []}

    def __init__(self) -> None:
        super().__init__()
        self.observation_space = spaces.Box(low=-1.0, high=1.0, shape=(OBSERVATION_SIZE,), dtype=np.float32)
        self.action_space = spaces.Discrete(3)
        self._t = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._t = 0
        return self.observation_space.sample(), {}

    def step(self, action):
        self._t += 1
        terminated = self._t >= 20
        return self.observation_space.sample(), 0.0, terminated, False, {}


@pytest.fixture(scope="module")
def tiny_checkpoint(tmp_path_factory):
    """Trains a tiny DQN for a handful of steps -- just enough to
    exercise a real save/load round trip, not to learn anything useful
    -- and returns (checkpoints_dir, checkpoint_name)."""
    env = _TinyObsActionEnv()
    model = DQN(
        "MlpPolicy",
        env,
        buffer_size=200,
        learning_starts=16,
        batch_size=8,
        train_freq=4,
        verbose=0,
    )
    model.learn(total_timesteps=64)

    checkpoints_dir = tmp_path_factory.mktemp("checkpoints")
    checkpoint_name = "test_dqn_checkpoint"
    model.save(checkpoints_dir / checkpoint_name)  # sb3 appends .zip itself
    return checkpoints_dir, checkpoint_name


def _make_df(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(loc=0.0005, scale=0.01, size=n)
    closes = 100.0 * np.cumprod(1.0 + steps)
    index = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
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


def test_registered_under_rl() -> None:
    assert get_strategy("rl") is RLStrategy


def test_config_requires_checkpoint_name() -> None:
    with pytest.raises(Exception):
        RLStrategy()


def test_insufficient_warmup_returns_hold_without_touching_disk(monkeypatch) -> None:
    # Points at a directory that doesn't exist -- if warm-up weren't
    # checked first, this would raise FileNotFoundError instead of
    # returning HOLD.
    monkeypatch.setattr(rl_mod, "DEFAULT_CHECKPOINTS_DIR", "/does/not/exist")
    strategy = RLStrategy(RLConfig(checkpoint_name="whatever"))
    df = _make_df(3)
    signal = strategy.generate_signal(df, Position())
    assert signal.action == SignalAction.HOLD
    assert "warm-up" in signal.reason


def test_missing_checkpoint_raises_clear_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rl_mod, "DEFAULT_CHECKPOINTS_DIR", tmp_path)
    strategy = RLStrategy(RLConfig(checkpoint_name="does_not_exist"))
    df = _make_df(60)
    with pytest.raises(FileNotFoundError):
        strategy.generate_signal(df, Position())


def test_loads_checkpoint_and_produces_a_valid_signal(tiny_checkpoint, monkeypatch) -> None:
    checkpoints_dir, checkpoint_name = tiny_checkpoint
    monkeypatch.setattr(rl_mod, "DEFAULT_CHECKPOINTS_DIR", checkpoints_dir)
    strategy = RLStrategy(RLConfig(checkpoint_name=checkpoint_name))
    df = _make_df(60)
    signal = strategy.generate_signal(df, Position())
    assert signal.action in (SignalAction.BUY, SignalAction.SELL, SignalAction.HOLD)


def test_model_is_loaded_once_and_cached(tiny_checkpoint, monkeypatch) -> None:
    checkpoints_dir, checkpoint_name = tiny_checkpoint
    monkeypatch.setattr(rl_mod, "DEFAULT_CHECKPOINTS_DIR", checkpoints_dir)
    strategy = RLStrategy(RLConfig(checkpoint_name=checkpoint_name))
    df = _make_df(60)
    strategy.generate_signal(df, Position())
    loaded_model = strategy._model
    assert loaded_model is not None
    strategy.generate_signal(df, Position())
    assert strategy._model is loaded_model  # not reloaded on a second call


def test_buy_suppressed_when_already_long(tiny_checkpoint, monkeypatch) -> None:
    checkpoints_dir, checkpoint_name = tiny_checkpoint
    monkeypatch.setattr(rl_mod, "DEFAULT_CHECKPOINTS_DIR", checkpoints_dir)
    strategy = RLStrategy(RLConfig(checkpoint_name=checkpoint_name))
    df = _make_df(60)
    strategy.generate_signal(df, Position())  # loads the real model once
    strategy._model.predict = lambda obs, deterministic=True: (np.array(1), None)  # force BUY

    signal = strategy.generate_signal(df, Position(side=PositionSide.LONG, qty=1, avg_price=100.0))
    assert signal.action == SignalAction.HOLD


def test_sell_suppressed_when_already_flat(tiny_checkpoint, monkeypatch) -> None:
    checkpoints_dir, checkpoint_name = tiny_checkpoint
    monkeypatch.setattr(rl_mod, "DEFAULT_CHECKPOINTS_DIR", checkpoints_dir)
    strategy = RLStrategy(RLConfig(checkpoint_name=checkpoint_name))
    df = _make_df(60)
    strategy.generate_signal(df, Position())  # loads the real model once
    strategy._model.predict = lambda obs, deterministic=True: (np.array(2), None)  # force SELL

    signal = strategy.generate_signal(df, Position())  # already flat
    assert signal.action == SignalAction.HOLD


def test_buy_and_sell_pass_through_when_position_allows_it(tiny_checkpoint, monkeypatch) -> None:
    checkpoints_dir, checkpoint_name = tiny_checkpoint
    monkeypatch.setattr(rl_mod, "DEFAULT_CHECKPOINTS_DIR", checkpoints_dir)
    strategy = RLStrategy(RLConfig(checkpoint_name=checkpoint_name))
    df = _make_df(60)
    strategy.generate_signal(df, Position())  # loads the real model once

    strategy._model.predict = lambda obs, deterministic=True: (np.array(1), None)  # BUY
    buy_signal = strategy.generate_signal(df, Position())  # flat
    assert buy_signal.action == SignalAction.BUY

    strategy._model.predict = lambda obs, deterministic=True: (np.array(2), None)  # SELL
    sell_signal = strategy.generate_signal(df, Position(side=PositionSide.LONG, qty=1, avg_price=100.0))
    assert sell_signal.action == SignalAction.SELL


def test_hold_action_is_always_a_no_op(tiny_checkpoint, monkeypatch) -> None:
    checkpoints_dir, checkpoint_name = tiny_checkpoint
    monkeypatch.setattr(rl_mod, "DEFAULT_CHECKPOINTS_DIR", checkpoints_dir)
    strategy = RLStrategy(RLConfig(checkpoint_name=checkpoint_name))
    df = _make_df(60)
    strategy.generate_signal(df, Position())  # loads the real model once
    strategy._model.predict = lambda obs, deterministic=True: (np.array(0), None)  # HOLD

    assert strategy.generate_signal(df, Position()).action == SignalAction.HOLD
    assert (
        strategy.generate_signal(df, Position(side=PositionSide.LONG, qty=1, avg_price=100.0)).action
        == SignalAction.HOLD
    )
