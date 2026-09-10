from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.candles import router as candles_router
from app.config import settings

app = FastAPI(title="QuantForge API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(candles_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
