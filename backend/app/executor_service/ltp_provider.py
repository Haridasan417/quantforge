"""The Executor's *only* window onto Angel One SmartAPI: a single
read-only `get_ltp(symbol) -> float` call. `SmartApiLTPProvider` wraps
`SmartConnect.ltpData(exchange, tradingsymbol, symboltoken)` — the
quote/market-data endpoint — and nothing else. This class has no method
that could place, modify, or cancel an order; per CLAUDE.md's
non-negotiable rule, QuantForge never calls a broker order-placement
endpoint anywhere, in any phase, for any reason.

`LTPProvider` is an ABC so the Executor's core logic (`process_event`)
never imports the SmartAPI SDK directly — tests (and the integration
test) inject `FakeLTPProvider` instead.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod


class LTPProviderError(RuntimeError):
    """Raised on a SmartAPI login/quote failure, or a symbol with no
    configured instrument token."""


class LTPProvider(ABC):
    @abstractmethod
    async def get_ltp(self, symbol: str) -> float:
        """Latest traded price for `symbol` (QuantForge's own symbol
        convention, e.g. "RELIANCE.NS")."""


class FakeLTPProvider(LTPProvider):
    """Test/mock double. `prices` maps QuantForge symbols to a fixed
    price; `default` (if set) is returned for any symbol not in the
    map, so a test can fix just the symbols it cares about."""

    def __init__(self, prices: dict[str, float] | None = None, default: float | None = None) -> None:
        self._prices = dict(prices or {})
        self._default = default

    async def get_ltp(self, symbol: str) -> float:
        if symbol in self._prices:
            return self._prices[symbol]
        if self._default is not None:
            return self._default
        raise LTPProviderError(f"FakeLTPProvider has no price configured for {symbol!r}")


class SmartApiLTPProvider(LTPProvider):
    """Real implementation, used in production (the loop/`__main__`
    deployment and `POST /trigger/run-once`).

    Angel One identifies instruments by a numeric "symboltoken", not by
    trading symbol alone — there's no generic symbol->token lookup here
    (that would need the NSE instrument master, out of scope for this
    phase per CLAUDE.md), so callers must supply `symbol_token_map`
    (QuantForge symbol -> Angel One symboltoken) for whatever symbols
    they've deployed strategies on.

    `SmartConnect` and its `ltpData` call are synchronous (the SDK has
    no async API), so `get_ltp` runs them in a worker thread rather than
    blocking the event loop — same pattern as `run_backtest` in
    `app.backtest_engine.runner`.
    """

    def __init__(self, symbol_token_map: dict[str, str] | None = None, exchange: str = "NSE") -> None:
        self._symbol_token_map = dict(symbol_token_map or {})
        self._exchange = exchange
        self._client = None  # lazily logged in on first use

    @staticmethod
    def _tradingsymbol(symbol: str) -> str:
        """QuantForge symbols are Yahoo-style ("RELIANCE.NS"); Angel
        One's equity trading symbols look like "RELIANCE-EQ"."""
        base = symbol.split(".")[0]
        return f"{base}-EQ"

    def _login(self):
        from SmartApi import SmartConnect  # imported lazily: heavy, network-touching SDK
        import pyotp

        from app.config import settings

        if not settings.smartapi_key or not settings.smartapi_client_id:
            raise LTPProviderError("SMARTAPI_KEY / SMARTAPI_CLIENT_ID are not configured")

        client = SmartConnect(api_key=settings.smartapi_key)
        totp = pyotp.TOTP(settings.smartapi_totp_secret).now()
        session = client.generateSession(settings.smartapi_client_id, settings.smartapi_password, totp)
        if not session or not session.get("status"):
            raise LTPProviderError(f"SmartAPI login failed: {session}")
        return client

    def _ensure_client(self):
        if self._client is None:
            self._client = self._login()
        return self._client

    def _fetch_ltp_sync(self, symbol: str) -> float:
        token = self._symbol_token_map.get(symbol)
        if token is None:
            raise LTPProviderError(f"No SmartAPI instrument token configured for {symbol!r}")

        client = self._ensure_client()
        tradingsymbol = self._tradingsymbol(symbol)
        response = client.ltpData(self._exchange, tradingsymbol, token)
        if not response or not response.get("status"):
            raise LTPProviderError(f"SmartAPI ltpData failed for {symbol!r}: {response}")
        try:
            return float(response["data"]["ltp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LTPProviderError(f"Unexpected SmartAPI ltpData response for {symbol!r}: {response}") from exc

    async def get_ltp(self, symbol: str) -> float:
        return await asyncio.to_thread(self._fetch_ltp_sync, symbol)
