from fastapi import FastAPI

from app.api.candles import router as candles_router

app = FastAPI(title="QuantForge API", version="0.1.0")

app.include_router(candles_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
