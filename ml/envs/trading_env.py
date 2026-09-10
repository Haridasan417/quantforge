"""A Gymnasium environment for training an RL trading policy on one
symbol's historical OHLCV, built entirely on the backend's own
feature-engineering code (`app.strategy_engine.features`) — the exact
same `build_features`/`observation_at` that will drive live inference
once Phase 7 part B wires a trained checkpoint into an `RLStrategy`.
Train-time and serve-time state must never drift apart (see CLAUDE.md's
Conventions); this env is what proves it by construction, not by
convention alone.

**Action space: `Discrete(3)`, for DQN** — 0=HOLD, 1=BUY (go/stay
long), 2=SELL (go/stay flat). Chosen over a continuous position-delta
action (which would call for PPO) because it mirrors this project's
existing `SignalAction` vocabulary (`BUY`/`SELL`/`HOLD`, the same three
values every rule-based `Strategy.generate_signal` already returns) and
this project's long/flat-only position model (`PositionSide` has no
short anywhere the Risk Manager or Executor act on) — so a trained
policy's output slots into the same `Signal`/`RiskManager.evaluate`
pipeline as any other strategy without a translation layer. See
CLAUDE.md's "RL Environment" section for the full rationale.

**Reward: risk-adjusted (Sharpe-shaped) return.** Each step's raw
reward is the position's realized return on the *next* bar (the fill
happens on the action bar; the return is only known going into the
following bar) minus a transaction-cost penalty on any position
change, then divided by a trailing realized-volatility estimate — a
simple differential-Sharpe-style shaping that rewards *consistent*
risk-adjusted gains rather than raw return-chasing (a policy that earns
the same average return with less variance scores higher).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import gymnasium as gym
from gymnasium import spaces

import sys
from pathlib import Path

# Makes this importable either as part of an installed/path-configured
# `ml` package, or directly (e.g. `from trading_env import TradingEnv`
# after `sys.path.insert(0, ".../ml/envs")`) -- both `app.strategy_engine`
# (the backend package) need to be reachable either way, so fall back to
# adding the sibling `backend/` directory to `sys.path` if the import
# fails, which is exactly what the Colab notebook's own sys.path setup
# does too (see ml/notebooks/train_rl_agent.ipynb).
try:
    from app.strategy_engine.features import FEATURE_WINDOW, OBSERVATION_SIZE, build_features, observation_at
except ImportError:  # pragma: no cover - exercised only outside a configured sys.path
    _backend_dir = Path(__file__).resolve().parents[2] / "backend"
    if str(_backend_dir) not in sys.path:
        sys.path.insert(0, str(_backend_dir))
    from app.strategy_engine.features import FEATURE_WINDOW, OBSERVATION_SIZE, build_features, observation_at

HOLD = 0
BUY = 1
SELL = 2
ACTION_NAMES = {HOLD: "HOLD", BUY: "BUY", SELL: "SELL"}

# Action -> resulting position (0=flat, 1=long). HOLD is a no-op on
# position; BUY/SELL set it outright rather than "toggle", so a
# repeated BUY while already long (or SELL while already flat) is
# simply a no-op step, same as every rule-based Strategy's own
# already-long/already-flat guard.
_ACTION_TO_POSITION = {HOLD: None, BUY: 1, SELL: 0}


def chronological_split(
    df: pd.DataFrame, train_frac: float = 0.7, val_frac: float = 0.15
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Splits `df` (assumed already sorted ascending by time) into
    contiguous train/val/test slices by position, never by shuffling —
    shuffling a time series before a train/test split leaks the future
    into training. `train_frac + val_frac` must be < 1.0; the remainder
    is the test split."""
    if not 0.0 < train_frac < 1.0 or not 0.0 < val_frac < 1.0 or train_frac + val_frac >= 1.0:
        raise ValueError("train_frac and val_frac must each be in (0, 1) and sum to less than 1.0")

    n = len(df)
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)
    return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]


class TradingEnv(gym.Env):
    """One episode = one full pass through `df`, oldest to newest.

    `df` must be raw OHLCV (open/high/low/close/volume, ascending —
    exactly what `data_service.fetch_candles`/`get_candles_cached`
    return) for a single symbol and a single, already-chosen split
    (train/val/test) — this env does not split or shuffle data itself,
    see `chronological_split`.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        df: pd.DataFrame,
        *,
        window: int = FEATURE_WINDOW,
        transaction_cost: float = 0.001,
        vol_window: int = 20,
    ) -> None:
        super().__init__()
        if len(df) < window + 2:
            raise ValueError(f"Need at least {window + 2} bars to run an episode (got {len(df)})")

        self.window = window
        self.transaction_cost = transaction_cost
        self.vol_window = vol_window

        self._features_df = build_features(df)
        self._returns = self._features_df["ret"].to_numpy(dtype=np.float64)

        self._valid_start = self._first_valid_index()
        self._last_index = len(df) - 1
        if self._valid_start >= self._last_index:
            raise ValueError("Not enough warmed-up bars in `df` to run even a single step")

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(OBSERVATION_SIZE,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)

        self._t: int | None = None
        self._position: int = 0  # 0 flat, 1 long

    def _first_valid_index(self) -> int:
        for i in range(len(self._features_df)):
            if observation_at(self._features_df, i, self.window) is not None:
                return i
        raise ValueError("Not enough bars to form a single observation window")

    def _rolling_vol(self, t: int) -> float:
        start = max(0, t - self.vol_window + 1)
        window_returns = self._returns[start : t + 1]
        window_returns = window_returns[~np.isnan(window_returns)]
        if len(window_returns) < 2:
            return 1.0
        vol = float(np.std(window_returns))
        return vol if vol > 1e-8 else 1.0

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        self._t = self._valid_start
        self._position = 0
        obs = observation_at(self._features_df, self._t, self.window)
        assert obs is not None  # guaranteed by _first_valid_index
        return obs, {"t": self._t, "position": self._position}

    def step(self, action: int):
        if self._t is None:
            raise RuntimeError("call reset() before step()")
        if action not in _ACTION_TO_POSITION:
            raise ValueError(f"invalid action {action!r}, expected one of {list(_ACTION_TO_POSITION)}")

        prev_position = self._position
        target = _ACTION_TO_POSITION[action]
        new_position = prev_position if target is None else target

        # The fill happens "now" (this bar's close); the return it
        # earns is realized going into the *next* bar -- so advance
        # first, then look up the return at the new `_t`.
        self._t += 1
        next_return = self._returns[self._t] if self._t < len(self._returns) else 0.0
        if np.isnan(next_return):
            next_return = 0.0

        raw_reward = new_position * next_return - abs(new_position - prev_position) * self.transaction_cost
        vol = self._rolling_vol(self._t)
        reward = raw_reward / vol

        self._position = new_position
        terminated = self._t >= self._last_index
        truncated = False

        if terminated:
            obs = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
        else:
            obs = observation_at(self._features_df, self._t, self.window)
            if obs is None:  # pragma: no cover - shouldn't happen once past _valid_start
                obs = np.zeros(OBSERVATION_SIZE, dtype=np.float32)

        info = {
            "t": self._t,
            "position": new_position,
            "raw_reward": raw_reward,
            "action_name": ACTION_NAMES[action],
        }
        return obs, float(reward), terminated, truncated, info
