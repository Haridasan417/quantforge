"""RLStrategy -- Phase 7 part B: wires a trained DQN checkpoint
(`ml/checkpoints/<name>.zip`, produced by `ml/notebooks/train_rl_agent.ipynb`)
into the same `Strategy` interface every other strategy implements.

Calls the *same* `build_observation` feature function part A's
`TradingEnv` trains against (`app.strategy_engine.features`), so there
is no train/serve skew -- see CLAUDE.md's Conventions.

Deliberately does NOT import `ml.envs.trading_env` (or anything else
under `ml/`): this project's dependency direction is ml/ -> backend/
(the training env and notebook import backend code, e.g.
`app.strategy_engine.features`), never the other way -- `ml/` is a
training-time/Colab-only concern, not part of what ships as the
backend service. The action encoding (0=HOLD, 1=BUY, 2=SELL) is
therefore duplicated here as a small constant instead of imported --
it MUST stay in sync with `ml/envs/trading_env.py`'s
`HOLD`/`BUY`/`SELL` (the encoding the checkpoint was actually trained
against) if that ever changes.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from app.strategy_engine.base_strategy import Position, PositionSide, Signal, SignalAction, Strategy
from app.strategy_engine.features import FEATURE_WINDOW, build_observation
from app.strategy_engine.registry import register_strategy

# Repo root, resolved from this file's own location rather than the
# process's cwd -- works whether the backend is launched from
# `backend/` (the documented convention) or from the repo root.
# .../backend/app/strategy_engine/strategies/rl_strategy.py -> parents:
# [0]=strategies [1]=strategy_engine [2]=app [3]=backend [4]=repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CHECKPOINTS_DIR = _REPO_ROOT / "ml" / "checkpoints"

# Must match ml/envs/trading_env.py's HOLD/BUY/SELL constants -- see
# module docstring for why this is a duplicated constant, not an
# import.
_HOLD, _BUY, _SELL = 0, 1, 2
_ACTION_TO_SIGNAL_ACTION = {_HOLD: SignalAction.HOLD, _BUY: SignalAction.BUY, _SELL: SignalAction.SELL}


class RLConfig(BaseModel):
    checkpoint_name: str = Field(
        ...,
        description=(
            "Base filename (no extension) of a checkpoint under ml/checkpoints/, e.g. "
            "'dqn_RELIANCE_NS_20260910T090649Z' for ml/checkpoints/dqn_RELIANCE_NS_20260910T090649Z.zip "
            "-- see the matching .json metadata sidecar for which symbol/interval it was trained on."
        ),
    )
    deterministic: bool = Field(True, description="Use the policy's greedy action instead of sampling one")


@register_strategy("rl")
class RLStrategy(Strategy):
    """Loads a stable-baselines3 DQN checkpoint once, lazily, on first
    use, and turns its per-bar action into the same BUY/SELL/HOLD
    `Signal` every other strategy emits. The already-long/already-flat
    guards mirror `MACrossoverStrategy`'s: a policy that outputs BUY
    while already long (or SELL while already flat) becomes a HOLD,
    not a redundant re-entry/exit.
    """

    def __init__(self, config: BaseModel | dict | None = None) -> None:
        super().__init__(config)
        # Loaded lazily (see _load_model) rather than in __init__, so
        # constructing an RLStrategy -- e.g. just to read config_schema()
        # for the Strategy Builder UI -- never requires stable-baselines3
        # to actually load a checkpoint off disk.
        self._model = None

    @classmethod
    def config_schema(cls) -> type[BaseModel]:
        return RLConfig

    def _checkpoint_path(self) -> Path:
        return DEFAULT_CHECKPOINTS_DIR / f"{self.config.checkpoint_name}.zip"

    def _load_model(self):
        # Imported lazily so importing this module -- and therefore
        # `app.strategy_engine.strategies`, imported at app startup
        # purely to populate the strategy registry -- never requires
        # stable-baselines3/torch to be importable unless an RLStrategy
        # is actually *used*. No other strategy in this package has a
        # dependency this heavy, and this one shouldn't force an import
        # cost onto all of them just by existing.
        from stable_baselines3 import DQN

        path = self._checkpoint_path()
        if not path.exists():
            raise FileNotFoundError(
                f"RL checkpoint not found: {path}. Train one in "
                "ml/notebooks/train_rl_agent.ipynb and drop the .zip (plus its .json "
                "metadata sidecar) into ml/checkpoints/ -- see CLAUDE.md's Phase 7 section."
            )
        return DQN.load(path)

    def generate_signal(self, df: pd.DataFrame, position: Position) -> Signal:
        # Same warm-up contract as every other strategy: not enough
        # history yet is HOLD, never a guess -- and checked *before*
        # touching the model, so a strategy configured with a checkpoint
        # that hasn't landed yet (or a symbol still warming up) doesn't
        # raise on every bar during that warm-up window.
        obs = build_observation(df, window=FEATURE_WINDOW)
        if obs is None:
            return Signal(action=SignalAction.HOLD, reason="insufficient warm-up data")

        if self._model is None:
            self._model = self._load_model()

        raw_action, _states = self._model.predict(obs, deterministic=self.config.deterministic)
        action = int(raw_action)

        if action not in _ACTION_TO_SIGNAL_ACTION:  # pragma: no cover - guarded by the env's Discrete(3) action space
            return Signal(action=SignalAction.HOLD, reason=f"unrecognized model action {action!r}")

        mapped = _ACTION_TO_SIGNAL_ACTION[action]

        if mapped is SignalAction.BUY and position.side != PositionSide.LONG:
            return Signal(action=SignalAction.BUY, confidence=1.0, reason="RL policy: go long")
        if mapped is SignalAction.SELL and position.side == PositionSide.LONG:
            return Signal(action=SignalAction.SELL, confidence=1.0, reason="RL policy: go flat")

        return Signal(action=SignalAction.HOLD, reason="RL policy: no position change")
