# QuantForge — Phase Build Prompts

**How to use this file:** save `CLAUDE.md` (its sibling) at your repo root — Claude Code reads it automatically every session, so you won't need to re-explain the project each time. Then, one phase at a time, paste that phase's prompt into Claude Code, let it work, walk through the Definition of Done yourself, and only then move to the next. Don't paste two phases in one go — each one assumes the previous phase's code already exists and builds on it.

**Before Phase 0:** `git` installed, a GitHub account (ideally with `gh` CLI authenticated — Claude Code will use it to create the repo directly; otherwise it'll just tell you the commands to run), Python 3.11+, Node 18+. You don't need Neon/Upstash/Angel One accounts until Phases 1, 1, and 6 respectively, or a Google account for Colab until Phase 7 — grab those keys shortly before each, not now.

---

## Phase 0 — Repo, Environment & Scaffolding

**Goal:** a running skeleton, in git, pushed to GitHub.

```text
We're starting QuantForge from scratch. Read CLAUDE.md first — it's the
persistent spec for this whole project, and you should keep it updated
as we go (especially the Phase Progress checklist at the bottom).

Set up the monorepo:
- Create frontend/, backend/, ml/, docs/ as described in CLAUDE.md.
- Backend: Python 3.11+ project in backend/, FastAPI app with a /health
  endpoint, requirements.txt with pinned versions (fastapi, uvicorn,
  sqlalchemy, alembic, asyncpg, pydantic). Initialize Alembic (migration
  scaffold only, no models yet) pointed at a DATABASE_URL env var.
- Frontend: Vite + React + TypeScript + Tailwind app in frontend/, with
  placeholder routes for Chart, Strategy Builder, and Dashboard, and an
  API client stub pointed at VITE_API_BASE_URL.
- Root: .gitignore (Python, Node, .env, ml/checkpoints/* with a
  .gitkeep so the folder itself is tracked). README.md with a short
  description and local setup steps for both halves. .env.example in
  backend/ and frontend/ listing every variable we'll eventually need —
  Neon DATABASE_URL, Upstash REDIS_URL, Angel One SMARTAPI_KEY and
  SMARTAPI_CLIENT_ID, etc. — even the ones later phases will use, so the
  shape is visible now.

Then: git init, first commit ("chore: initial project scaffolding"),
create the GitHub repo (gh repo create quantforge --private
--source=. --remote=origin if gh is authenticated; otherwise give me
the exact manual commands), and push to main.

Update the Phase 0 checkbox in CLAUDE.md before you finish.
```

**Definition of done:** `uvicorn app.main:app --reload` serves `/health` with a 200; `npm run dev` renders the shell with all three routes; the repo exists on GitHub with the initial commit.

---

## Phase 1 — Backend Core + Data Service

**Goal:** real market data flowing through a real schema.

```text
Phase 1: backend core models + Data Service.

Models (backend/app/models/, SQLAlchemy 2.0): Strategy (id, name, type,
config JSON, created_at), Trade (id, strategy_id, symbol, side, qty,
price, simulated bool, executed_at), PortfolioSnapshot (id, timestamp,
cash, holdings JSON, equity), RLCheckpoint (id, strategy_id, version,
trained_at, metrics JSON, file_path). Generate and apply the Alembic
migration against DATABASE_URL.

Data Service (backend/app/data_service/): fetch_candles(symbol,
interval, start, end) that tries yfinance first and falls back to
nsepy for NSE symbols yfinance can't resolve. Cache results (pick
Postgres table vs. Redis TTL cache — your call, note the choice in
CLAUDE.md) so repeat requests for the same range don't re-hit the
source. Add RSI/MACD/EMA helpers via pandas-ta.

API: GET /api/candles?symbol=&interval=&start=&end= returning OHLCV
plus requested indicators.

Write pytest tests for the data service (mock network calls) and for
the indicator math against a small known dataset.

Commit ("feat: backend core models + data service") and push. Update
CLAUDE.md's Phase 1 checkbox.
```

**Definition of done:** migration applies cleanly; `/api/candles` returns real data for a known NSE symbol (e.g. `RELIANCE.NS`) with a sane indicator value; tests pass.

---

## Phase 2 — Frontend Chart

**Goal:** the chart from the architecture diagram, actually rendering real data.

```text
Phase 2: charting frontend.

Install lightweight-charts. Build a Chart component that fetches
/api/candles and renders candlesticks, with RSI/MACD/EMA overlaid
(separate panes below the price pane for RSI/MACD makes sense — your
call). Add a symbol + interval picker above the chart. "Live" can mean
"refetch on an interval" for now — true push-based updates arrive once
the Trigger/Executor pipeline exists in Phase 6.

Wire this into the Dashboard route as the default view.

Commit ("feat: charting UI wired to data service") and push. Update
CLAUDE.md.
```

**Definition of done:** loading the frontend shows a real candlestick chart with at least one indicator overlay; switching symbol/interval updates it.

---

## Phase 3 — Strategy Engine Core

**Goal:** the interface everything else in the project will plug into — get this one right.

```text
Phase 3: Strategy Engine core. This is the piece the "pluggable
architecture" claim rests on, so nail the interface before adding more
strategies later.

backend/app/strategy_engine/base_strategy.py: an abstract Strategy
class with generate_signal(df: pd.DataFrame, position: Position) ->
Signal (Signal = enum BUY/SELL/HOLD, or a small dataclass if you want
confidence/size attached), plus a config_schema() classmethod
(Pydantic model) describing its tunable parameters.

backend/app/strategy_engine/registry.py: a @register_strategy("name")
decorator that adds a class to a module-level registry dict, plus a
list_strategies() helper.

Implement two concrete strategies in strategy_engine/strategies/:
MACrossoverStrategy (fast/slow MA crossover) and RSIThresholdStrategy
(buy below X, sell above Y), both registered via the decorator and
driven entirely by their config_schema.

API: GET /api/strategies returns the registered strategies with their
config schemas — the frontend will use this in Phase 4 to build
strategy config forms and node parameters.

Tests: run each strategy against a small synthetic OHLCV series with a
known crossover/threshold event and assert the signal fires on the
expected row.

Commit ("feat: strategy engine with pluggable registry") and push.
Update CLAUDE.md.
```

**Definition of done:** `/api/strategies` lists both strategies with correct schemas; tests pass; adding a third strategy later should touch nothing outside `strategy_engine/strategies/`.

---

## Phase 4 — Strategy Builder UI

**Goal:** the no-code promise, delivered.

```text
Phase 4: Strategy Builder UI.

Install reactflow. Build a canvas with two node types: ConditionNode
(indicator + comparator + threshold, e.g. "RSI < 30" — populate the
indicator list from what's available in the Strategy Engine) and
ActionNode (BUY/SELL). Support at least AND-chains of conditions into
one action.

Persist the graph: "Save Strategy" serializes nodes+edges to JSON and
POSTs to /api/strategies/custom.

Backend: a GraphStrategy class (same Strategy interface as Phase 3)
that takes the saved JSON and interprets it at generate_signal time —
walk the graph, evaluate conditions against the current row, fire the
connected action if satisfied. Register instances of it per saved
graph (dynamically, not via the class-level decorator, since these are
user-created at runtime) so they show up anywhere registered
strategies are listed — backtest and execution shouldn't need to know
this one came from the visual builder.

Commit ("feat: visual strategy builder + graph interpreter") and push.
Update CLAUDE.md.
```

**Definition of done:** build a simple 2-node strategy in the UI, save it, confirm it shows up alongside the built-in strategies, and that running it against sample data produces sane signals.

---

## Phase 5 — Backtesting Engine

**Goal:** real quant metrics, not a fake accuracy percentage.

```text
Phase 5: Backtesting Engine.

backend/app/backtest_engine/: takes any registered strategy (built-in
or custom graph) + symbol + date range and runs it through backtrader
— bridge Strategy.generate_signal into a backtrader.Strategy subclass
(or drive Cerebro manually, feeding it signals row by row; pick
whichever keeps the bridge thinnest). Compute Sharpe ratio, max
drawdown, and win rate from the backtrader results.

API: POST /api/backtest {strategy_id, symbol, start, end} ->
{sharpe, max_drawdown, win_rate, equity_curve, trades}.

Frontend: a results panel (Recharts for the equity curve) plus
buy/sell markers plotted on the Phase 2 price chart for the same run.

Commit ("feat: backtesting engine with backtrader integration") and
push. Update CLAUDE.md.
```

**Definition of done:** backtesting the MA crossover strategy on a real symbol returns believable Sharpe/drawdown/win-rate numbers and a rendering equity curve.

---

## Phase 6 — Risk Manager, Trigger & Executor

**Goal:** the paper-trading pipeline, end to end. This is the phase where the safety boundary actually matters — re-read CLAUDE.md's "Paper trading" section before starting.

```text
Phase 6: Risk Manager, Trigger & Executor.

Risk Manager (backend/app/risk_manager/): given a signal + current
portfolio state, apply stop-loss %, max position size, and max total
exposure rules (configurable via env or a settings table), returning
an approved/adjusted order or a rejection with reason.

Trigger service (backend/app/trigger_service/): for each symbol with
an active strategy, poll the latest price at a configurable interval,
only during NSE hours (9:15-15:30 IST, Mon-Fri), and push an
"evaluate {strategy_id, symbol}" event onto the Upstash Redis queue.
Write this as a function callable either by a long-running loop (for
an always-on deployment) or by a single external trigger hit (for a
cron/GitHub-Actions deployment) — see CLAUDE.md's free-tier note;
don't hard-code one or the other.

Executor service (backend/app/executor_service/): consumes queue
events, re-runs the strategy's generate_signal on fresh data, passes
the result through the Risk Manager, and — if approved — fetches the
current LTP from Angel One SmartAPI's quote/market-data endpoint ONLY,
simulates a fill at that price, writes the Trade row, and updates the
latest PortfolioSnapshot. Wrap the SmartAPI call behind a small
interface so it's mockable in tests. Do not call any order-placement
endpoint anywhere in this service.

Add an integration test that pushes a fake event through the queue and
asserts a simulated trade lands in the DB with correctly risk-adjusted
sizing.

Commit ("feat: risk manager + trigger/executor paper-trading
pipeline") and push. Update CLAUDE.md.
```

**Definition of done:** with a strategy active on a real symbol during market hours, a full cycle (trigger → queue → executor → simulated trade → portfolio update) runs end to end, and grepping the executor code confirms no live order-placement call exists.

---

## Phase 7 — ML/RL Strategy Plugin

**Goal:** the self-improving flagship strategy. This phase has a manual hand-off in the middle: Claude Code writes all the code and the training notebook, but the GPU training run itself happens in Google Colab, not here.

```text
Phase 7, part A: everything Claude Code can do without leaving this
session.

Feature engineering (backend/app/strategy_engine/features.py): one
function building the observation vector (normalized OHLCV window +
indicators), reused by backtesting, live inference, AND RL training
below — no separate feature logic for training vs. serving.

WalkForwardStrategy (same Strategy interface): periodically re-fits
simple strategy parameters on a rolling window and evaluates
out-of-sample on the next window. No GPU needed — implement and
register it now like any other strategy.

Custom environment (ml/envs/trading_env.py): a Gymnasium env wrapping
the feature function above — state = feature vector, action =
{BUY, SELL, HOLD} (discrete, for DQN) or a position delta (continuous,
for PPO — pick one and note the choice in CLAUDE.md), reward =
risk-adjusted return. Chronological split only (e.g. 70/15/15 by
time) — never shuffle.

Colab notebook (ml/notebooks/train_rl_agent.ipynb): installs
stable-baselines3 and gymnasium, mounts Google Drive, imports the env
from this repo (pick the simpler of "pip install -e a packaged ml/"
or "copy the env file into the Colab runtime" and say which), trains
PPO or DQN, evaluates on the held-out split, saves the checkpoint to
Drive, and prints clear instructions for downloading it.

Commit ("feat: RL env, walk-forward strategy, training notebook") and
push.

STOP HERE and hand off to me: I'll open the notebook in Colab, run it,
download the checkpoint, and drop it into ml/checkpoints/.
```

```text
Phase 7, part B: after I confirm the checkpoint is in ml/checkpoints/.

Build RLStrategy (same Strategy interface) that loads the checkpoint
and calls the SAME feature function from part A at inference time, so
there's no train/serve skew. Register it like any other strategy.

Commit ("feat: wire trained RL checkpoint into RLStrategy") and push.
Update CLAUDE.md's Phase 7 checkbox.
```

**Definition of done:** `WalkForwardStrategy` backtests with no manual steps; the notebook runs cleanly top-to-bottom in Colab and produces a checkpoint; after part B, `RLStrategy` produces signals from that checkpoint through the normal `/api/backtest` and live pipeline.

---

## Phase 8 — Dashboard

**Goal:** the P&L / trade log / equity curve view, live.

```text
Phase 8: Dashboard.

Build out the Dashboard route: P&L summary, a trade log table (from
Trade), the equity curve (from PortfolioSnapshot history, Recharts),
and Sharpe/max-drawdown/win-rate cards computed over the live
paper-trading history — not just backtest results.

Add a WebSocket endpoint that pushes an update whenever the Executor
(Phase 6) writes a new trade or portfolio snapshot, and have the
dashboard subscribe so P&L/trade log update live without a manual
refresh.

Commit ("feat: live dashboard with P&L, trade log, equity curve") and
push. Update CLAUDE.md.
```

**Definition of done:** triggering a simulated trade (manually or via the pipeline) shows up on the dashboard within a few seconds, no refresh needed.

---

## Phase 9 — Deployment & Polish

**Goal:** live URLs, and a project someone else can actually walk through.

```text
Phase 9: deployment and final polish.

Frontend: deploy to Vercel, VITE_API_BASE_URL pointed at the deployed
backend.

Backend: deploy to [Oracle Cloud Always-Free VM / Render — say which
we're using, per CLAUDE.md's free-tier note], with env vars for
DATABASE_URL, REDIS_URL, and the SmartAPI credentials. If
Trigger/Executor need a persistent loop, confirm the chosen platform
actually keeps a process alive; if not, switch to the scheduled-cron
variant from Phase 6 now.

Final pass: update README with the real architecture diagram, setup
instructions, and a short demo script (charting -> strategy builder ->
backtest -> paper-trading pipeline -> RL strategy, in that order).
Smoke-test the whole flow against the deployed URLs, not just
localhost.

Commit ("chore: deployment config + final polish"), push, and tag the
release (git tag v1.0 && git push --tags). Update CLAUDE.md — every
Phase Progress box should be checked now.
```

**Definition of done:** both deployed URLs work, the demo script runs against them end to end, and the repo has a `v1.0` tag.
