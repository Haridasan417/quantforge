# QuantForge

No-code, AI-augmented algorithmic trading platform: live/historical charting, a
drag-and-drop visual strategy builder, backtesting with real quant metrics,
and a paper-trading execution pipeline.

Academic project (CSE-DS) — deliberately spans full-stack dev, data
engineering, ML/RL, quant finance, distributed systems, DB design, and
software architecture rather than staying in one lane.

> **Non-negotiable:** this system only ever *simulates* fills using
> live/historical market data. It never calls a broker's live
> order-placement endpoint, in any phase. See `CLAUDE.md`'s "Paper trading"
> section for details.

See [`CLAUDE.md`](./CLAUDE.md) for the full spec, stack, and conventions, and
[`docs/PROMPTS.md`](./docs/PROMPTS.md) for the phase-by-phase build plan this
project follows.

## Stack

Frontend: React + Vite + TypeScript + Tailwind, deployed to Vercel.
Backend: FastAPI (Python 3.11+), deployed to Oracle Cloud Free VM or Render.
DB: Postgres (Neon) via SQLAlchemy 2.0 (async) + Alembic. Queue: Redis
(Upstash). Market data: `yfinance` / `nsepy`. Backtesting: `backtrader`.
Broker data: Angel One SmartAPI (quote/LTP only). RL: `stable-baselines3` +
`gymnasium`, trained in Google Colab.

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
docs/PROMPTS.md              phase-by-phase build prompts
```

## Local setup

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in DATABASE_URL, REDIS_URL, SMARTAPI_*
alembic upgrade head    # once migrations exist (Phase 1+)
uvicorn app.main:app --reload
```

`GET /health` should return `{"status": "ok"}`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_BASE_URL, defaults to http://localhost:8000
npm run dev
```

Opens the app with the Dashboard, Chart, and Strategy Builder routes.

## Status

This project is being built phase by phase, per `docs/PROMPTS.md`. See
`CLAUDE.md`'s Phase Progress checklist for what's landed so far.
