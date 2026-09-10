# QuantForge

No-code, AI-augmented algorithmic trading platform: live/historical charting, a drag-and-drop visual strategy builder, backtesting with real quant metrics, and a paper-trading execution pipeline. Academic project (CSE-DS) — deliberately spans full-stack dev, data engineering, ML/RL, quant finance, distributed systems, DB design, and software architecture rather than staying in one lane.

**Non-negotiable rule:** this system only ever *simulates* fills using live/historical market data. Never call a broker's live order-placement endpoint, for any reason, in any phase. See "Paper trading" below — re-read it before touching `executor_service/`.

## Stack

| Layer | Choice |
|---|---|
| Frontend | React + Vite + TypeScript + Tailwind → Vercel |
| Charting | TradingView `lightweight-charts` |
| Strategy builder | React Flow |
| Dashboard charts | Recharts |
| Backend | FastAPI (Python 3.12 — `pandas-ta` 0.4.x requires it) → Render (free web service) |
| Scheduled Trigger/Executor | GitHub Actions cron → `POST /trigger/run-once` (see "Deployment", Phase 9) |
| DB / migrations | Postgres (Neon) via SQLAlchemy 2.0 (async) + Alembic |
| Queue | Redis (Upstash) |
| Market data | `yfinance` primary, `nsepy` fallback for NSE symbols |
| Indicators | `pandas-ta` (RSI, MACD, EMA) |
| Backtesting | `backtrader` |
| Broker | Angel One SmartAPI — **quote/LTP endpoints only** |
| RL | `stable-baselines3` + `gymnasium`, trained in Google Colab |

## Layout

```
frontend/                  React app (chart, strategy builder, dashboard)
backend/app/
  api/                      FastAPI routers
  data_service/             candle fetch + cache
  strategy_engine/          base_strategy.py, registry.py, strategies/, features.py
  backtest_engine/          backtrader wrapper
  risk_manager/
  trigger_service/
  executor_service/
  models/  schemas/         SQLAlchemy / Pydantic
ml/
  envs/                      Gymnasium trading env
  notebooks/                 Colab training notebooks
  checkpoints/                trained model artifacts
docs/PROMPTS.md              phase-by-phase build prompts (the playbook this file's sibling)
```

## Commands

```
cd backend && uvicorn app.main:app --reload      # run API
cd backend && pytest                              # run tests
cd backend && alembic upgrade head                 # apply migrations
cd frontend && npm run dev                         # run UI
```

## Conventions

- Every strategy — rule-based, walk-forward, RL, or a saved visual graph from the builder — implements `Strategy.generate_signal(df, position) -> Signal` and registers via `@register_strategy("name")`. Backtest, live execution, and the builder UI all go through this one interface; nothing outside `strategy_engine/` should need to know which kind it's talking to.
- One feature-engineering function computes the observation/indicator vector for backtesting, live inference, and RL training. Never let train-time and serve-time features drift apart.
- Commits: Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`). Push to `main` at the end of each phase.
- Secrets are never committed. `.env.example` documents every variable; real values live in `.env` (gitignored) or the deploy platform's secret store.
- Trigger/Executor only act during NSE hours (9:15–15:30 IST, Mon–Fri) — check this before polling, not just before a fill.
- The API and the frontend run on different origins in dev (Vite on 5173, uvicorn on 8000), so `CORSMiddleware` is configured from `CORS_ORIGINS` in `app/config.py` — add the deployed frontend URL there in Phase 9.

## Paper trading

Angel One's SmartAPI has no broker-side sandbox, so "paper trading" is simulated *inside* QuantForge, not by talking to a demo brokerage account:

- SmartAPI is used only to read live LTP / quote data.
- The Executor computes a simulated fill (at LTP, optionally with slippage modeling) and writes it to `trades` itself.
- Live order-placement calls are out of scope for this entire project. If a phase prompt ever seems to point that direction, that's a bug in the prompt, not a green light.

## Data Service caching

`GET /api/candles` caches the raw OHLCV response (not the indicator-augmented
one) in a Postgres table, `candle_cache`, keyed on the exact
`(symbol, interval, start, end)` request — a repeat request for that same
range is served from Postgres without re-hitting yfinance/nsepy; a different
or overlapping range is treated as a miss and re-fetched. Indicators
(RSI/MACD/EMA) are computed fresh on every request from the cached raw bars,
since that's cheap and keeps the cached payload reusable across different
`indicators=` query values.

Chose Postgres over a Redis (Upstash) TTL cache for this because: historical
bars don't change once their range is in the past, so there's nothing that
needs to expire (a TTL is the wrong tool); and Neon is already provisioned
for the ORM models, so this doesn't pull in a second datastore a phase early
— Redis/Upstash arrives in Phase 6 for the Trigger→Executor queue, which is
what it's actually needed for.

## Charting ("live" for now)

The Chart route and Dashboard's default view both render `CandleChart`
(`frontend/src/components/CandleChart.tsx`): a `lightweight-charts` v5 chart
with three panes — price candlesticks + EMA overlay (pane 0), RSI (pane 1),
MACD histogram/line/signal (pane 2) — fed by `GET /api/candles`. "Live"
currently means polling that endpoint on a timer (`POLL_INTERVAL_MS`, 15s);
this gets replaced by a real push once the Trigger/Executor pipeline (Phase
6) and the Dashboard's WebSocket (Phase 8) exist — search for `POLL_INTERVAL_MS`
when that phase lands.

## Strategy Engine

`backend/app/strategy_engine/`: every strategy — rule-based (Phase 3),
a saved visual graph from the builder (Phase 4), or an RL policy (Phase
7) — implements the abstract `Strategy` class (`base_strategy.py`):
`generate_signal(df, position) -> Signal` plus a `config_schema()`
classmethod returning a Pydantic model. `Signal` is a small dataclass
(`action: BUY/SELL/HOLD`, plus optional `confidence`/`size`/`reason`) so
simple strategies can ignore the extra fields while RL/walk-forward
strategies can use them later without an interface change. `Position`
is QuantForge's own minimal holding abstraction (`side`/`qty`/
`avg_price`) — not backtrader's — so a strategy can tell "am I already
in this trade" without reaching into portfolio bookkeeping.

Strategies self-register via `@register_strategy("name")`
(`registry.py`) at import time; `strategy_engine/strategies/__init__.py`
imports every concrete strategy module purely for that side effect, and
`list_strategies()` / `get_strategy()` read the registry. `GET
/api/strategies` returns each registered strategy's name, docstring,
and `config_schema().model_json_schema()` — the Strategy Builder
(Phase 4) renders config forms and node parameters straight from that
JSON Schema, so adding a new strategy never needs matching frontend
code.

Two built-ins ship in `strategy_engine/strategies/`: `MACrossoverStrategy`
(fast/slow MA crossover) and `RSIThresholdStrategy` (buy below X, sell
above Y, reusing `data_service.indicators.rsi` rather than
recomputing). While building `RSIThresholdStrategy`'s tests, found that
`pandas-ta`'s DataFrame accessor (`df.ta.rsi()` / `.ema()` / `.macd()`)
falls back to silently returning the *original* input df (not `None`,
not an empty Series) when there isn't enough data for the requested
length — `data_service/indicators.py`'s `rsi()`/`ema()`/`macd()` now
detect that fallback and normalize it to a properly-shaped all-NaN
Series/DataFrame instead, so warm-up windows behave the same
(`pd.isna(...)`-checkable) everywhere these functions are used,
including `/api/candles`.

## Strategy Builder + GraphStrategy

`frontend/src/routes/StrategyBuilder.tsx`: a React Flow canvas with two
node types (`components/strategy-builder/ConditionNode.tsx`,
`ActionNode.tsx`). A ConditionNode is indicator + comparator +
threshold (e.g. "RSI < 30"); its indicator dropdown and per-indicator
params (e.g. RSI's `length`) are populated from `GET
/api/strategies/indicators`, not hard-coded — the same
`data_service.indicators` implementations the backend actually
evaluates against, so the UI can't drift out of sync with what it can
compute. An ActionNode is just BUY/SELL. Wiring one or more
ConditionNodes into one ActionNode is an AND-chain: every condition
feeding that action must hold for it to fire — enforced by
`isValidConnection` only allowing condition→action edges, and by the
backend interpreter treating multiple incoming edges as AND, never OR.
"Save Strategy" strips the UI-only parts of each node's `data` (the
indicator catalog, onChange callbacks) down to the plain
id/type/position/data shape the backend expects, and POSTs it to
`POST /api/strategies/custom`.

`backend/app/strategy_engine/graph_strategy.py`: `GraphStrategy`
implements the same `Strategy` interface as any built-in, but
interprets a saved graph at `generate_signal` time instead of running
fixed logic — walk the graph, evaluate every ConditionNode wired into
each ActionNode against the current row, fire that action if they're
all true (and the position makes it a sensible action: don't BUY if
already long, don't SELL if flat). Unlike `MACrossoverStrategy`/
`RSIThresholdStrategy`, it's never `@register_strategy`-decorated —
one graph strategy exists per *saved graph*, each with its own
nodes/edges, not a fixed set of class-level parameters. Instead,
`POST /api/strategies/custom` builds one `GraphStrategy` instance per
saved row and calls the registry's new
`register_strategy_instance(f"graph:{id}", instance)` — a separate
instance registry alongside the existing class registry
(`list_strategy_instances()`/`get_strategy_instance()` in
`registry.py`) — so it shows up in `GET /api/strategies` (and will be
resolvable by name for the backtest engine and executor) exactly like
a built-in, without either needing to know it came from the visual
builder. The instance registry lives in process memory, so
`app/main.py`'s lifespan handler re-registers every saved `type="graph"`
row from Postgres on startup — otherwise a saved strategy would
silently vanish the moment the API process restarted.

A save is validated (`GraphStrategy.validate_graph()`) before it's
persisted — unknown indicator, bad comparator, a dangling edge, an
action node nothing feeds into, no action node at all — so a broken
graph gets a 422 with a real reason immediately, not a mysterious
failure discovered later inside a backtest. `api/client.ts`'s `request()`
was extended to surface a FastAPI error body's `detail` as
`ApiError.message` (previously just "POST ... failed: 422") specifically
so this validation message reaches the Strategy Builder's error banner
verbatim.

## Backtesting Engine

`backend/app/backtest_engine/`: runs any registered `Strategy` (a
built-in class or a saved `graph:<id>` — resolved the same way for
both, see below) through `backtrader` over historical OHLCV, and
reduces the result to the metrics/series `POST /api/backtest` returns.

`bridge.py`'s `StrategyBridge(bt.Strategy)` is the thin adapter the
phase brief called for: backtrader owns bar iteration, order
execution, and cash/position bookkeeping; every bar, it hands
`strategy.generate_signal` the exact OHLCV slice seen so far
(`full_df.iloc[:len(self)]` — can't include a future row by
construction, since `len(self)` is backtrader's own running bar count)
and places a `buy()`/`close()` based on the returned `Signal`, mirroring
every strategy's own already-established convention (BUY only when not
long, SELL/close only when long). Its `params` tuple names the strategy
instance `qf_strategy`, not `strategy` — backtrader's own
`Cerebro.addstrategy(strategy, *args, **kwargs)` already has a
positional parameter called `strategy`, and the collision isn't
obvious until you hit "got multiple values for argument 'strategy'".

`runner.py`'s `run_backtest(strategy, df)` sets up `Cerebro` with fixed,
documented defaults (₹100,000 starting cash, 0.1% commission per fill,
`PercentSizer` at 95% of cash per BUY, whole-share sizing via
`retint=True`) rather than exposing a pile of new tunable parameters —
this phase runs a strategy "as-is" over history, it isn't a portfolio
simulator with its own config surface. Sharpe (`bt.analyzers.SharpeRatio`,
annualized), max drawdown (`bt.analyzers.DrawDown`, returned as a
fraction of equity, not a percentage), and win rate (closed-trade
won/total from `bt.analyzers.TradeAnalyzer`, `0.0` rather than a
division error when nothing's closed yet) are read from backtrader's
own analyzers rather than recomputed by hand. A strategy that never
trades makes Sharpe `None` (zero-variance returns), which is passed
through as `null` rather than coerced to `0.0` — "never traded" and "a
real Sharpe of zero" are different things and the frontend can tell
them apart.

`resolve.py`'s `resolve_strategy(strategy_id, config=None)` is the one
place that knows built-ins (instantiated fresh, with `config` validated
against that class's `config_schema()` — see Phase 7 part B below for
why a per-request override was added) and saved graphs
(already-configured instances from the Phase 4 instance registry, where
`config` is ignored — a graph's config lives on its own saved row) need
different lookups; backtest and, later, execution (Phase 6) both call
this instead of duplicating the built-in-vs-graph branch.

`POST /api/backtest` (`api/backtest.py`) fetches OHLCV through the same
`get_candles_cached` path `/api/candles` uses (so a symbol/range a user
already charted is already warm in the cache), then runs
`run_backtest` — synchronous and CPU-bound, since backtrader has no
async API — via `asyncio.to_thread` so a long backtest doesn't block
the event loop out from under other requests. The request body adds an
optional `interval` (default `"1d"`) beyond the phase brief's literal
`{strategy_id, symbol, start, end}` — there was no other way to say
what bar size to backtest on.

Frontend: `routes/Backtest.tsx` — a strategy/symbol/date-range form,
a metrics grid, `components/backtest/EquityCurveChart.tsx` (Recharts)
for the equity curve, and the Phase 2 `CandleChart` reused for the
same run's buy/sell markers. `CandleChart` gained three optional props
for this: `markers` (drawn via `lightweight-charts` v5's
`createSeriesMarkers` plugin — v5 replaced v4's `series.setMarkers()`
with a separate marker-plugin API), `initialSymbol`/`initialInterval`,
and `fixedRange` (a fixed historical window instead of "now minus
`rangeFor(interval)`" — also switches off the live-polling timer,
since re-polling "now" makes no sense while looking at one specific
backtest run's fixed date range). The Backtest page mounts it with
`key={runCount}` so a new run remounts it cleanly with the new
range/markers rather than fighting stale internal state.

## Risk Manager, Trigger & Executor

Three packages implement the paper-trading pipeline end to end: Trigger
finds work, the Redis queue hands it off, Executor does the work and
asks Risk Manager for permission first.

**Risk Manager** (`app/risk_manager/manager.py`) is a stateless
`RiskManager.evaluate(signal, symbol, reference_price, position,
portfolio) -> RiskDecision`, applying three configurable rules —
`stop_loss_pct` (default 5%), `max_position_size_pct` (default 20% of
equity per symbol), `max_total_exposure_pct` (default 60% of equity
across all symbols) — sourced from `app/config.py`'s `Settings` (env
vars `STOP_LOSS_PCT`/`MAX_POSITION_SIZE_PCT`/`MAX_TOTAL_EXPOSURE_PCT`,
see `.env.example`) unless a caller passes its own
`RiskManagerSettings`. A protective stop-loss check runs first and can
force a SELL regardless of what the strategy's own signal says this
bar; otherwise HOLD is a no-op, SELL is approved only when actually
long, and BUY is sized to `min(max_position_size_pct × equity,
remaining exposure budget, available cash)`, floored to a whole share
count. `RiskDecision.order` is `None` on rejection — the reason string
is always populated, on approval or not, so the Executor/tests can log
or assert on *why*.

**The queue** (`app/queue.py`) is one Redis list
(`quantforge:trigger-events`), FIFO via RPUSH/LPOP — no consumer
groups or ack/retry. That's deliberate: strategies are re-evaluated on
a timer (or a single cron hit), not edge-triggered, so a dropped event
just waits for the next Trigger cycle to re-evaluate the same
strategy/symbol; there's nothing here that needs at-least-once
delivery guarantees. `push_event`/`pop_event`/`queue_length` all accept
an injectable `client=` so tests use `fakeredis` instead of a real
Redis connection.

**Deployments, not just strategies.** `strategies` gained `symbol`
(nullable) and `is_active` (default `False`) columns (migration
`2a5bbc3df14a`) — a *deployment* is a `strategies` row with both set.
`POST /api/strategies/activate` (`app/api/strategies.py`) is what
creates/updates one: given `{strategy_id, symbol, is_active, config?}`,
a saved graph (`"graph:<id>"`) has its row updated in place (it already
exists from `POST /api/strategies/custom`); a built-in (e.g.
`"ma_crossover"`) is find-or-created keyed on `(type, symbol)`, so the
same built-in can be deployed on multiple symbols as separate rows, and
re-activating the same pair updates rather than duplicates. Without
this endpoint the Trigger service's query
(`is_active=True AND symbol IS NOT NULL`) would have nothing to ever
find.

**Trigger** (`app/trigger_service/trigger.py`): `is_market_open()`
gates everything on NSE hours (9:15–15:30 IST, Mon–Fri, no holiday
calendar yet). `run_trigger_once(db, force=False, client=None)` is the
one deployment-agnostic core — it queries every active deployment and
pushes one `{strategy_id, symbol}` event per row (`strategy_id` here is
always the deployment's integer `strategies.id`, *not* the string
registry name used elsewhere in the API — built-ins have no row at all
until deployed, so the registry name alone isn't enough to identify
*which* deployment). `force=True` bypasses the NSE-hours gate, for
tests and for a manual/demo hit outside market hours.

**Executor** (`app/executor_service/executor.py`):
`resolve_deployed_strategy(db, strategy_row_id)` turns that integer id
into the DB row plus a runnable `Strategy` instance built from *that
row's own config* (unlike `backtest_engine.resolve_strategy`, which
uses class defaults for built-ins — each deployment may have been
activated with different parameters). `process_event` then: fetches
180 days of fresh OHLCV via `get_candles_cached` (same cached path
`/api/candles`/backtest use — this always misses the cache since the
window's `end` is `datetime.now()` every call, which is correct here:
the brief calls for *fresh* data, not cached-as-of-activation data),
derives `Position` from the single latest `PortfolioSnapshot.holdings`
entry for that symbol (account-wide, no per-strategy book — see below),
calls `strategy.generate_signal`, and passes the result through
`RiskManager.evaluate` using the **candle close** as the reference
price. Only if that's approved does it fetch the real LTP and write the
`Trade` (at the LTP, not the reference close) plus an updated
`PortfolioSnapshot` — fetching LTP only after approval avoids a wasted
SmartAPI call when the answer was always going to be "no trade".

**Position/portfolio state** is derived, not stored per-strategy:
there's one account-wide `PortfolioSnapshot.holdings` JSONB dict
(`{symbol: {qty, avg_price}}`), read from the latest row and rewritten
after every fill. This means every active deployment shares one paper
cash balance — deliberate, since `PortfolioSnapshot` has no
`strategy_id` column and adding per-strategy books would mean solving
capital allocation across strategies, out of scope here. A BUY merges
into any existing holding at a qty-weighted average cost (defensive:
the Risk Manager already blocks a second BUY while long, so this
should only ever create a fresh entry in practice); a SELL always
closes the position outright, since the Risk Manager only ever approves
selling the full held quantity.

**SmartAPI, read-only.** `app/executor_service/ltp_provider.py` defines
`LTPProvider` (ABC: `get_ltp(symbol) -> float`) so `process_event` never
imports the SmartAPI SDK directly. `SmartApiLTPProvider` wraps
`SmartConnect.ltpData(exchange, tradingsymbol, symboltoken)` — the
quote endpoint, run via `asyncio.to_thread` since the SDK is
synchronous — and has no method that could place, modify, or cancel an
order, by construction. Angel One identifies instruments by a numeric
symboltoken, not by trading symbol alone; there's no NSE
instrument-master lookup built (out of scope for this phase), so
`SmartApiLTPProvider(symbol_token_map=...)` must be handed a QuantForge
symbol → symboltoken mapping for whatever's actually deployed before it
can fetch anything real. `FakeLTPProvider(prices={...})` is what every
test uses instead.

**Loop vs. single-hit, not hard-coded.** `run_trigger_once` and
`run_executor_once` are the deployment-agnostic cores; nothing in
`trigger_service`/`executor_service` assumes one deployment shape over
the other:
- **Always-on** (an Oracle Cloud Always-Free VM): `python -m
  app.trigger_service` and `python -m app.executor_service` each run a
  loop (`run_trigger_loop`/`run_executor_loop`) polling every
  `TRIGGER_POLL_SECONDS`/`EXECUTOR_POLL_SECONDS` (default 60s each) as
  two persistent processes.
- **Single-hit** (Render free tier, which sleeps on idle — see below):
  `POST /trigger/run-once` (`app/api/trigger.py`, deliberately *not*
  under the `/api` prefix — this exact path is what the note below
  names) runs one Trigger poll immediately followed by one Executor
  drain, synchronously, in a single request. A scheduled GitHub Action
  or external cron (e.g. cron-job.org) hits this on a schedule instead
  of a loop ever running. `?force=true` bypasses the NSE-hours gate for
  manual/demo hits.

**Testing.** Risk Manager and Trigger are pure/DB-free unit tests
(fixed `RiskManagerSettings`, a fake `AsyncSession` stub, `fakeredis`
for the queue). Executor's unit tests monkeypatch
`resolve_deployed_strategy`/`get_candles_cached` and use
`FakeLTPProvider`, same convention. The one exception to "DB-free" is
`tests/test_executor_integration.py`: it pushes a fake event through a
`fakeredis` queue and runs the real `run_executor_once` against a real
Postgres connection (whatever `DATABASE_URL` points at — skips
gracefully if unreachable), asserting a `Trade` row lands with
correctly risk-adjusted `qty` (not just "a trade exists"), then deletes
every row it created in a `finally` block, FK-safe (trades before their
strategy row) — this is what actually exercises `Trade`/
`PortfolioSnapshot`'s FK constraints, JSONB columns, and `Numeric`
precision, which a fake session can't meaningfully verify. Async tests
run via `pytest-asyncio` (`asyncio_mode = auto` in `pytest.ini`, added
this phase).

## Feature Engineering, Walk-Forward Strategy & RL Environment (Phase 7 part A)

**One feature function, everywhere.** `app/strategy_engine/features.py`
is the single implementation of "the model-facing state": `build_features(df)`
turns raw OHLCV into five scale-free per-bar columns (`ret`, `high_low_range`,
`rsi` rescaled to 0-1, `ema_dist`, `macd_hist` — each already a
percent/ratio/bounded oscillator, so no separate normalization/scaler
step, and nothing that needs fitting on training data and staying in
sync with inference); `observation_at(features_df, index, window=FEATURE_WINDOW)`
flattens `FEATURE_WINDOW` (20) trailing bars into one `OBSERVATION_SIZE`
(100) vector, returning `None` — never zeros — when there isn't a full,
fully-warmed-up window yet, so "no data" can never look like a real
market state to a model. `build_observation(df)` is the convenience
wrapper a per-bar caller (backtest/live inference) uses; `ml/envs/trading_env.py`
calls `build_features`/`observation_at` directly instead, since an RL
episode needs one observation per timestep and recomputing every
indicator from scratch each step would be wasteful. `RLStrategy`
(Phase 7 part B, once a checkpoint exists) will call `build_observation`
too — same function, so train-time and serve-time state can't drift
apart.

**WalkForwardStrategy** (`app/strategy_engine/strategies/walk_forward.py`,
registered as `"walk_forward"`) needs no GPU/training: it's an
MA-crossover strategy whose `(fast, slow)` periods are re-derived on
every call via a small grid search (`_best_params`/`_mechanical_return`)
over `config.fast_candidates`/`slow_candidates`, scored on the
`train_window` bars ending `test_window` bars *before* the live bar —
so the fit is always evaluated on data it wasn't chosen using, and the
gap (`test_window`) is what actually makes this "walk-forward" rather
than just "in-sample-optimized". Once fit, it trades the winning pair's
crossover on the current bar exactly like `MACrossoverStrategy` does.

**RL Environment** (`ml/envs/trading_env.py`): `TradingEnv` wraps
`features.py` in a `gymnasium.Env`, one episode per full pass through
whatever OHLCV slice it's constructed with.
- **Action space: `Discrete(3)` (HOLD/BUY/SELL), trained with DQN** —
  chosen over a continuous position-delta + PPO because it mirrors the
  project's existing `SignalAction` vocabulary and long/flat-only
  position model (`PositionSide` has no short anywhere the Risk Manager
  or Executor act on), so a trained policy's action maps straight onto
  a `Signal` without a translation layer once Phase 7 part B builds
  `RLStrategy`.
- **Reward: risk-adjusted (Sharpe-shaped) return** — realized next-bar
  return (the fill happens "now", the return is realized going into the
  next bar) minus a transaction-cost penalty on position changes,
  divided by a trailing realized-volatility estimate, so the policy is
  rewarded for consistent risk-adjusted gains rather than raw
  return-chasing.
- **`chronological_split(df, train_frac, val_frac)`**: contiguous,
  time-ordered train/val/test slices — never shuffled, since shuffling
  a time series before a split leaks the future into training.
- Verified with gymnasium's own `check_env` plus a full-episode rollout
  and a transaction-cost regression test (`ml/tests/test_trading_env.py`,
  run via `cd ml && pytest` — `ml/pytest.ini` puts both `ml/` and
  `../backend` on `sys.path`, the same two directories the Colab
  notebook adds).

**Training notebook** (`ml/notebooks/train_rl_agent.ipynb`): git-clones
this repo and adds `backend/`/`ml/` to `sys.path` rather than
`pip install -e` — the repo isn't packaged (no `setup.py`/`pyproject.toml`,
and doesn't need one for a project this size), so cloning + `sys.path`
is the simpler of the two options the phase brief asked to choose
between. It installs the *full* `backend/requirements.txt` (not a
hand-curated subset) because merely importing `app.strategy_engine.features`
transitively imports `app.data_service`'s package `__init__.py`, which
pulls in sqlalchemy/yfinance/nsepy regardless — simplest to just match
what the backend service itself installs rather than maintain a second,
partial dependency list that could drift out of sync. Data comes from
the backend's own `fetch_candles` (same yfinance/nsepy code
`/api/candles` uses), split chronologically 70/15/15, trained with
`stable_baselines3.DQN`, evaluated on val *and* held-out test via
`evaluate_policy` plus a plain cumulative-return readout, then saved to
Google Drive as a checkpoint `.zip` *plus* a JSON metadata sidecar
(symbol, date range, timesteps, eval metrics) — per the free-tier note
below, only that small metadata is meant to live long-term in the
repo/DB; the binary stays in Drive (or Git LFS/a release asset if it
ever needs to be committed).

**Part A stops here, by design** (per the phase brief): the notebook
must be run interactively in Colab (GPU/long-running training, a human
watching the loss curve) — Claude Code cannot execute it from this
session. Phase 7 part B (loading a downloaded checkpoint into a live
`RLStrategy` for backtest/execution) is unblocked once a `.zip`/`.json`
pair lands in `ml/checkpoints/`.

**Post-part-A fix:** the notebook's install cell originally ran
`pip install -r backend/requirements.txt` in full inside Colab. In
practice this triggered two separate numpy-downgrade conflicts against
Colab's preinstalled numpy>=2 stack (torch/jax/opencv/etc.): first
`nsepy` (unmaintained, and never actually imported by anything this
notebook touches — it's a lazy fallback inside `data_service/sources.py`,
only reached if the yfinance fetch fails), then `stable-baselines3==2.4.0`
itself, which pins `numpy<2.0`. Fixed by (1) replacing the install cell
with a minimal curated list (`pandas-ta`, `sqlalchemy`, `yfinance`,
`pydantic`, `pydantic-settings`, pinned to the same versions as
`backend/requirements.txt`) instead of the full requirements file, and
(2) bumping `stable-baselines3` to `2.5.0` (relaxed to `numpy<3.0`) in
both `ml/requirements.txt` and `backend/requirements.txt` — see those
files' comments. Neither change touches Colab's own numpy/pandas.

## RLStrategy (Phase 7 part B)

`backend/app/strategy_engine/strategies/rl_strategy.py`, registered as
`"rl"`: loads a stable-baselines3 `DQN` checkpoint (`ml/checkpoints/<checkpoint_name>.zip`,
configured via `RLConfig.checkpoint_name` — no default, since which
checkpoint to run is never a sensible thing to guess) and calls the
*same* `build_observation` feature function part A's `TradingEnv`
trains against, so there's no train/serve skew. The model is loaded
lazily on first `generate_signal` call, not in `__init__`, so just
constructing an `RLStrategy` (e.g. to read `config_schema()` for the
Strategy Builder UI) never touches disk or requires a checkpoint to
exist yet; a missing checkpoint raises a clear `FileNotFoundError`
naming the expected path and pointing at the notebook, rather than a
bare stable-baselines3 stack trace.

Warm-up is checked *before* the model is touched at all: `build_observation`
returning `None` (not enough history yet) is a `HOLD`, same contract as
every other strategy, and means a deployment configured with a
checkpoint that hasn't landed yet doesn't raise on every bar during
that warm-up window — only once real inference is actually attempted.
The model's raw action (0=HOLD/1=BUY/2=SELL) is mapped through the same
already-long/already-flat guard `MACrossoverStrategy` uses (BUY only
fires while flat, SELL only fires while long), so a policy re-asserting
BUY every bar while already long is a `HOLD`, not a repeated re-entry.

**Why this module doesn't import `ml/envs/trading_env.py`:** this
project's dependency direction is `ml/` → `backend/` (the training env
and notebook import backend code), never the reverse — `ml/` is a
training-time/Colab-only concern, not part of what ships as the
backend service. The action encoding (`0=HOLD, 1=BUY, 2=SELL`) is
therefore duplicated as a small module-level constant in
`rl_strategy.py` rather than imported; a comment on it flags that it
must stay in sync with `ml/envs/trading_env.py`'s `HOLD`/`BUY`/`SELL`
if that encoding ever changes, since it's the encoding whatever
checkpoint gets loaded was actually trained against.

**Why stable-baselines3/gymnasium are imported lazily inside
`_load_model`, not at module level:** `strategy_engine/strategies/__init__.py`
imports every strategy module purely to run its `@register_strategy`
decorator at app startup — every other built-in strategy has no heavy
dependency, and `RLStrategy` shouldn't force a torch import cost onto
the whole registry just by existing, only when an `RLStrategy` is
actually invoked.

**Testing** (`backend/tests/test_rl_strategy.py`): `ml/checkpoints/*.zip`
is gitignored (trained artifacts, not source — see `.gitignore`) and
never present in CI, so the tests train their own tiny, fast DQN
checkpoint in a `module`-scoped fixture against a minimal synthetic
Gymnasium env matching `RLStrategy`'s expected observation/action
shapes (`Box(OBSERVATION_SIZE,)`/`Discrete(3)`) — not
`ml/envs/trading_env.py`, consistent with this module never importing
`ml/` — just enough to exercise a real save/load round trip. Position-
aware signal gating (BUY-while-long, SELL-while-flat, HOLD) is tested
by monkeypatching the *loaded* model's `.predict` to force a specific
action, isolating the gating logic from what the tiny (untrained-to-any-
real-skill) policy actually happens to output.

**Follow-up fix: per-request config in `/api/backtest`.** Manually
exercising `RLStrategy` through `POST /api/backtest` after landing the
above surfaced a real gap: `backtest_engine/resolve.py`'s
`resolve_strategy` instantiated every built-in with `cls()` — no
config — because every built-in before this one had sane defaults for
every field. `RLConfig.checkpoint_name` doesn't (there's no sensible
default for "which checkpoint to run"), so backtesting `"rl"` with no
override raised a `pydantic.ValidationError` `resolve_strategy` had no
way to be given a value to avoid. Fixed by threading an optional
`config: dict | None` through `resolve_strategy` → `BacktestRequest`
(new field) → `POST /api/backtest`, and catching `ValidationError` in
the endpoint as a 422 (a bad per-request config is a client error, not
a server crash) — same pattern `POST /api/strategies/activate` already
used for its own built-in config validation. This generalizes past
RLStrategy: any built-in's params can now be overridden per backtest
request, not just at `/activate` time. `resolve_strategy` ignores
`config` for a saved graph (`"graph:<id>"`), unchanged.

## Dashboard (Phase 8)

Live P&L, a trade log, an equity curve, and Sharpe/max-drawdown/win-rate —
all computed over the **real paper-trading history the Executor has
actually written**, not a backtest replay. Two new pieces make that live:
`app/dashboard/` (query + metrics), and a Redis pub/sub channel the
Executor publishes to and a new WebSocket endpoint forwards.

**Live metrics, not backtrader.** There's no strategy to replay against
live history — the equity curve and fills already *are* the ground truth
— so `app/dashboard/metrics.py` computes Sharpe/max-drawdown/win-rate with
plain Python instead of spinning up a `Cerebro` run. It deliberately
mirrors `backtest_engine/runner.py`'s conventions so the two are
comparable at a glance: Sharpe is annualized (`TRADING_DAYS_PER_YEAR =
252`) and `None` (not `0.0`) when there are fewer than 3 data points or
the returns have zero variance — same "never traded" vs "a real zero"
distinction backtrader's own analyzer makes; max drawdown is a
running-peak-based fraction of equity, not a percentage; win rate pairs
each symbol's BUYs/SELLs FIFO in chronological order, mirroring the
Executor's own position rule that a SELL always closes the whole
position. `app/dashboard/queries.py` separates `fetch_all_trades`
(ascending, full history — needed for correct FIFO win-rate pairing) from
`fetch_recent_trades` (descending, capped at `limit`, for the trade log
table) and `fetch_portfolio_history` (every `PortfolioSnapshot`, for the
equity curve). `GET /api/dashboard/overview` returns the P&L summary +
metrics + equity curve in one call; `GET /api/dashboard/trades?limit=200`
serves the trade log separately so the table can page independently of
the summary cards later.

**Live push: Redis pub/sub, separate from the Trigger→Executor queue.**
The existing `quantforge:trigger-events` list (Phase 6) is a work queue —
FIFO, one consumer, no fan-out. Telling a WebSocket "something changed"
needs the opposite shape: fan-out to every connected browser, no
persistence, fire-and-forget. `app/queue.py` adds a second primitive for
that: `DASHBOARD_UPDATES_CHANNEL` and `publish_update(event, client=)`
(PUBLISH, matching the existing `client=` injectable-Redis convention).
`executor_service/executor.py`'s `process_event` calls it right after
committing a trade + snapshot, wrapped in try/except — a Redis publish
failure must never lose or roll back a trade that already happened, so
it's logged and swallowed, not raised. This has to be pub/sub rather than
an in-process event (e.g. an `asyncio.Event` or a Python callback) because
Executor and the FastAPI process serving the WebSocket are two different
OS processes in the always-on deployment mode (see "Loop vs. single-hit"
above) — pub/sub is the one mechanism that works identically whether
Executor runs as its own persistent loop process or in-process via
`POST /trigger/run-once`.

`GET /api/ws/dashboard` (`app/api/dashboard.py`) subscribes to that
channel and forwards every message verbatim to the browser. It runs two
concurrent tasks — one forwarding pubsub messages, one watching for the
client to disconnect — via `asyncio.wait(..., return_when=FIRST_COMPLETED)`,
so a client that closes the socket doesn't leave the forwarding task
blocked forever on `pubsub` reads; both tasks are cancelled and the
pubsub connection unsubscribed/closed in a `finally`.

**Frontend: the WebSocket is a "something changed" signal, not incremental
state.** `routes/Dashboard.tsx` could parse each pushed event and patch
P&L/Sharpe/etc. in place, but that means duplicating
`app/dashboard/metrics.py`'s math in TypeScript and keeping the two in
sync forever. Instead every WS message (auto-reconnecting every 3s on
drop) just triggers a full re-fetch of `GET /api/dashboard/overview` +
`GET /api/dashboard/trades` — the backend stays the single source of
truth for every number on the page, and the extra round trip is
unnoticeable since fills land at most a few times a minute (Trigger/
Executor's own poll interval). `MetricCard` (previously a private
component inside `Backtest.tsx`) was promoted to
`components/MetricCard.tsx` so Backtest and Dashboard share one
implementation instead of two copies drifting apart.

**Testing.** `test_dashboard_metrics.py` covers the pure-Python
Sharpe/drawdown/win-rate functions directly (11 tests: empty history,
zero-variance Sharpe, known-value drawdown, FIFO/out-of-order win-rate
pairing). `test_api_dashboard.py` covers the two REST endpoints plus the
WebSocket — the WebSocket tests use hand-rolled `_FakePubSub`/`_FakeRedis`
doubles rather than real `fakeredis`, because two separately-constructed
`fakeredis.aioredis.FakeRedis()` instances were confirmed (via a hung
test) not to share pub/sub state with each other, which real fakeredis
would need across `TestClient`'s background thread. `test_executor_service.py`
gained a test that the publish actually fires with the right payload shape
(real single shared `fakeredis` instance, `pubsub.listen()`) and a test
that a broken Redis publish doesn't stop the trade from committing.

## Deployment (Phase 9)

**Backend: Render, not an Oracle Cloud VM — chosen for this project.** Both
modes were implemented as of Phase 6 (see "Loop vs. single-hit" above), and
CLAUDE.md's Phase 6 section left the choice open; Phase 9 settles it in
favor of Render + a scheduled GitHub Action, because it needs no cloud VM
to provision, SSH into, or keep patched — the whole backend deploy is `git
push` plus a Render dashboard form. The tradeoff is Render's free tier
sleeping after ~15 minutes idle, which is exactly why Trigger/Executor
can't run as the persistent-loop processes an always-on VM would host —
see the next point.

**Scheduled Trigger/Executor: `.github/workflows/trigger-poll.yml`.** A
GitHub Actions cron job POSTs to `/trigger/run-once` every 5 minutes across
a window that generously covers NSE hours (03:00-09:55 UTC = before
9:15-15:30 IST, Mon-Fri) rather than trying to match the exact open/close
minute — cron can't start a schedule at `:45` anyway, and the endpoint
itself already gates on `is_market_open()`, so a hit outside real market
hours is just a fast no-op (`market_open: false` in the response), not a
wasted trade cycle. The workflow reads the deployed backend's URL from a
repository secret (`QUANTFORGE_API_URL`) rather than a hard-coded value, so
redeploying to a different Render URL is a one-line secret update, not a
code change; `workflow_dispatch` with a `force` input lets you trigger an
off-hours run on demand (Actions tab → "Trigger poll" → Run workflow) for
testing/demos without waiting for market hours.

**Frontend: Vercel, with `frontend/vercel.json`'s SPA rewrite.** React
Router (`BrowserRouter`) means routes like `/chart` and `/backtest` only
exist client-side — without a rewrite, Vercel's static host 404s on a
direct load or refresh of anything but `/`, since there's no file at that
path. `vercel.json`'s single rewrite rule (`/(.*)` → `/index.html`) fixes
that by always serving the SPA shell and letting React Router take it from
there.

**CORS is a live env var, not a code change.** `app/config.py`'s
`cors_origins` (env `CORS_ORIGINS`) already existed from earlier phases
specifically for this moment — the deployed Vercel URL is added to it on
Render once known, no redeploy-the-code-to-fix-CORS cycle needed.

**`backend/render.yaml`** documents the exact build/start commands and the
env var *names* (not values — `sync: false` on every one, since none of
them belong in git) for a reproducible/Blueprint deploy; the manual
dashboard flow in README.md's "Deployment" section uses the same commands
and doesn't require this file to exist, so either path works.

See README.md's "Deployment" section for the exact step-by-step (Render →
Vercel → GitHub secret, in that order — Vercel's `VITE_API_BASE_URL` and
Render's `CORS_ORIGINS` are each other's dependency, so one pass through
both is needed either way) and "Demo script" for a guided walkthrough of
the deployed app.

## Free-tier notes

- Render's free web services sleep on idle — this project's answer for Trigger/Executor is the scheduled GitHub Action above, not an always-on VM; see "Deployment" for why. An Oracle Cloud Always-Free VM running `python -m app.trigger_service` / `python -m app.executor_service` as persistent loops remains a documented, implemented alternative if you'd rather not depend on a scheduled hit (README.md's "Deployment" section covers both).
- Large RL checkpoints: use Git LFS, or keep only metadata (version, trained_at, metrics) in Postgres and the binary in Drive/release assets.

## Phase progress

*(check these off as phases land — update this file yourself at the end of each one)*

- [x] 0 — Repo, environment & scaffolding
- [x] 1 — Backend core + Data Service
- [x] 2 — Frontend chart
- [x] 3 — Strategy Engine core
- [x] 4 — Strategy Builder UI
- [x] 5 — Backtesting Engine
- [x] 6 — Risk Manager, Trigger & Executor
- [x] 7 — ML/RL strategy plugin
- [x] 8 — Dashboard
- [x] 9 — Deployment & polish
