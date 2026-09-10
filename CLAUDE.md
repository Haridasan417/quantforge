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
| Backend | FastAPI (Python 3.12 — `pandas-ta` 0.4.x requires it) → Oracle Cloud Free VM or Render |
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

## Free-tier notes

- Render's free web services sleep on idle — bad for a service that needs to poll continuously. Either run Trigger/Executor as a persistent loop on an Oracle Cloud Always-Free VM, or replace the loop with a scheduled GitHub Action / external cron (e.g. cron-job.org) hitting a `/trigger/run-once` endpoint.
- Large RL checkpoints: use Git LFS, or keep only metadata (version, trained_at, metrics) in Postgres and the binary in Drive/release assets.

## Phase progress

*(check these off as phases land — update this file yourself at the end of each one)*

- [x] 0 — Repo, environment & scaffolding
- [x] 1 — Backend core + Data Service
- [ ] 2 — Frontend chart
- [ ] 3 — Strategy Engine core
- [ ] 4 — Strategy Builder UI
- [ ] 5 — Backtesting Engine
- [ ] 6 — Risk Manager, Trigger & Executor
- [ ] 7 — ML/RL strategy plugin
- [ ] 8 — Dashboard
- [ ] 9 — Deployment & polish
