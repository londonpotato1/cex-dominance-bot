"""Reference Price Fetcher - Phase 7 Quick Win #3.

6-stage fallback chain for global reference prices.
Solves the TGE listing problem: new tokens don't have futures contracts yet.

Fallback Chain:
  1. Binance futures (highest confidence: 0.95)
  2. Bybit futures (high confidence: 0.90)
  3. Binance spot (medium confidence: 0.75)
  4. OKX spot (medium confidence: 0.70)
  5. CoinGecko API (low confidence: 0.50)
  6. Fail with error

Confidence Scoring:
  - Futures > Spot (더 깊은 유동성)
  - Binance > others (거래량 최고)
  - CoinGecko: 최후 수단 (여러 거래소 집계)

Gate Decision Integration:
  - confidence < 0.8 → premium threshold 상향 조정
  - confidence < 0.6 → WATCH_ONLY 권장
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# HTTP 타임아웃
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)


class ReferenceSource(Enum):
    """참조 가격 소스."""
    BINANCE_FUTURES = "binance_futures"
    BYBIT_FUTURES = "bybit_futures"
    BINANCE_SPOT = "binance_spot"
    OKX_SPOT = "okx_spot"
    COINGECKO = "coingecko"
    UNKNOWN = "unknown"


@dataclass
class ReferencePrice:
    """참조 가격 결과."""
    symbol: str
    price_usd: float
    source: ReferenceSource
    confidence: float  # 0.0 ~ 1.0
    volume_24h_usd: Optional[float] = None


class ReferencePriceFetcher:
    """Reference price fetcher with 6-stage fallback chain.

    사용법:
        fetcher = ReferencePriceFetcher()
        ref = await fetcher.get_reference_price("BTC")
        if ref:
            print(f"Price: ${ref.price_usd}, Confidence: {ref.confidence}")
    """

    # 소스별 신뢰도 (confidence)
    _CONFIDENCE_MAP = {
        ReferenceSource.BINANCE_FUTURES: 0.95,
        ReferenceSource.BYBIT_FUTURES: 0.90,
        ReferenceSource.BINANCE_SPOT: 0.75,
        ReferenceSource.OKX_SPOT: 0.70,
        ReferenceSource.COINGECKO: 0.50,
    }

    def __init__(self, coingecko_api_key: str | None = None) -> None:
        """
        Args:
            coingecko_api_key: CoinGecko API 키 (optional, Pro plan).
        """
        self._coingecko_key = coingecko_api_key

    async def get_reference_price(
        self,
        symbol: str,
        session: aiohttp.ClientSession | None = None,
    ) -> ReferencePrice | None:
        """Reference price 6단계 폴백 체인.

        Args:
            symbol: 토큰 심볼 (e.g., "BTC", "ETH").
            session: aiohttp 세션 (없으면 생성).

        Returns:
            ReferencePrice 또는 모든 폴백 실패 시 None.
        """
        own_session = session is None
        if own_session:
            session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)

        try:
            # 1단계: Binance Futures
            ref = await self._try_binance_futures(symbol, session)
            if ref:
                return ref

            # 2단계: Bybit Futures
            ref = await self._try_bybit_futures(symbol, session)
            if ref:
                return ref

            # 3단계: Binance Spot
            ref = await self._try_binance_spot(symbol, session)
            if ref:
                return ref

            # 4단계: OKX Spot
            ref = await self._try_okx_spot(symbol, session)
            if ref:
                return ref

            # 5단계: CoinGecko
            ref = await self._try_coingecko(symbol, session)
            if ref:
                return ref

            # 6단계: 모든 폴백 실패
            logger.error(
                "[RefPrice] 모든 폴백 실패: %s (6단계 시도 완료)", symbol
            )
            return None

        finally:
            if own_session and session:
                await session.close()

    # -------------------------------------------------------------------------
    # 1단계: Binance Futures (USDT-M)
    # -------------------------------------------------------------------------

    async def _try_binance_futures(
        self, symbol: str, session: aiohttp.ClientSession,
    ) -> ReferencePrice | None:
        """Binance USDT-M 선물 가격 조회."""
        try:
            url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
            pair = f"{symbol}USDT"

            async with session.get(url, params={"symbol": pair}) as resp:
                if resp.status != 200:
                    logger.debug("[RefPrice] Binance Futures 실패: %s (HTTP %d)", pair, resp.status)
                    return None

                data = await resp.json()
                price = float(data.get("lastPrice", 0))
                volume = float(data.get("quoteVolume", 0))  # USDT volume

                if price <= 0:
                    return None

                logger.info(
                    "[RefPrice] %s → Binance Futures: $%.2f (vol: $%.0f, conf: %.2f)",
                    symbol, price, volume, self._CONFIDENCE_MAP[ReferenceSource.BINANCE_FUTURES],
                )

                return ReferencePrice(
                    symbol=symbol,
                    price_usd=price,
                    source=ReferenceSource.BINANCE_FUTURES,
                    confidence=self._CONFIDENCE_MAP[ReferenceSource.BINANCE_FUTURES],
                    volume_24h_usd=volume,
                )

        except Exception as e:
            logger.debug("[RefPrice] Binance Futures 에러 (%s): %s", symbol, e)
        return None

    # -------------------------------------------------------------------------
    # 2단계: Bybit Futures (Linear)
    # -------------------------------------------------------------------------

    async def _try_bybit_futures(
        self, symbol: str, session: aiohttp.ClientSession,
    ) -> ReferencePrice | None:
        """Bybit Linear 선물 가격 조회."""
        try:
            url = "https://api.bybit.com/v5/market/tickers"
            pair = f"{symbol}USDT"

            async with session.get(
                url, params={"category": "linear", "symbol": pair}
            ) as resp:
                if resp.status != 200:
                    logger.debug("[RefPrice] Bybit Futures 실패: %s (HTTP %d)", pair, resp.status)
                    return None

                data = await resp.json()
                result = data.get("result", {})
                tickers = result.get("list", [])

                if not tickers:
                    return None

                t = tickers[0]
                price = float(t.get("lastPrice", 0))
                volume = float(t.get("turnover24h", 0))  # USD volume

                if price <= 0:
                    return None

                logger.info(
                    "[RefPrice] %s → Bybit Futures: $%.2f (vol: $%.0f, conf: %.2f)",
                    symbol, price, volume, self._CONFIDENCE_MAP[ReferenceSource.BYBIT_FUTURES],
                )

                return ReferencePrice(
                    symbol=symbol,
                    price_usd=price,
                    source=ReferenceSource.BYBIT_FUTURES,
                    confidence=self._CONFIDENCE_MAP[ReferenceSource.BYBIT_FUTURES],
                    volume_24h_usd=volume,
                )

        except Exception as e:
            logger.debug("[RefPrice] Bybit Futures 에러 (%s): %s", symbol, e)
        return None

    # -------------------------------------------------------------------------
    # 3단계: Binance Spot
    # -------------------------------------------------------------------------

    async def _try_binance_spot(
        self, symbol: str, session: aiohttp.ClientSession,
    ) -> ReferencePrice | None:
        """Binance 현물 가격 조회."""
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            pair = f"{symbol}USDT"

            async with session.get(url, params={"symbol": pair}) as resp:
                if resp.status != 200:
                    logger.debug("[RefPrice] Binance Spot 실패: %s (HTTP %d)", pair, resp.status)
                    return None

                data = await resp.json()
                price = float(data.get("lastPrice", 0))
                volume = float(data.get("quoteVolume", 0))  # USDT volume

                if price <= 0:
                    return None

                logger.info(
                    "[RefPrice] %s → Binance Spot: $%.2f (vol: $%.0f, conf: %.2f)",
                    symbol, price, volume, self._CONFIDENCE_MAP[ReferenceSource.BINANCE_SPOT],
                )

                return ReferencePrice(
                    symbol=symbol,
                    price_usd=price,
                    source=ReferenceSource.BINANCE_SPOT,
                    confidence=self._CONFIDENCE_MAP[ReferenceSource.BINANCE_SPOT],
                    volume_24h_usd=volume,
                )

        except Exception as e:
            logger.debug("[RefPrice] Binance Spot 에러 (%s): %s", symbol, e)
        return None

    # -------------------------------------------------------------------------
    # 4단계: OKX Spot
    # -------------------------------------------------------------------------

    async def _try_okx_spot(
        self, symbol: str, session: aiohttp.ClientSession,
    ) -> ReferencePrice | None:
        """OKX 현물 가격 조회."""
        try:
            url = "https://www.okx.com/api/v5/market/ticker"
            pair = f"{symbol}-USDT"

            async with session.get(url, params={"instId": pair}) as resp:
                if resp.status != 200:
                    logger.debug("[RefPrice] OKX Spot 실패: %s (HTTP %d)", pair, resp.status)
                    return None

                data = await resp.json()
                tickers = data.get("data", [])

                if not tickers:
                    return None

                t = tickers[0]
                price = float(t.get("last", 0))
                vol24h = float(t.get("vol24h", 0))  # base volume
                volume_usd = vol24h * price

                if price <= 0:
                    return None

                logger.info(
                    "[RefPrice] %s → OKX Spot: $%.2f (vol: $%.0f, conf: %.2f)",
                    symbol, price, volume_usd, self._CONFIDENCE_MAP[ReferenceSource.OKX_SPOT],
                )

                return ReferencePrice(
                    symbol=symbol,
                    price_usd=price,
                    source=ReferenceSource.OKX_SPOT,
                    confidence=self._CONFIDENCE_MAP[ReferenceSource.OKX_SPOT],
                    volume_24h_usd=volume_usd,
                )

        except Exception as e:
            logger.debug("[RefPrice] OKX Spot 에러 (%s): %s", symbol, e)
        return None

    # -------------------------------------------------------------------------
    # 5단계: CoinGecko (집계 가격)
    # -------------------------------------------------------------------------

    async def _try_coingecko(
        self, symbol: str, session: aiohttp.ClientSession,
    ) -> ReferencePrice | None:
        """CoinGecko 집계 가격 조회 (최후 수단).

        주의: CoinGecko는 여러 거래소 평균이므로 신뢰도 낮음.
        """
        try:
            # 심볼 → CoinGecko ID 매핑 (간단한 경우만)
            coingecko_id = _symbol_to_coingecko_id(symbol)
            if not coingecko_id:
                logger.debug("[RefPrice] CoinGecko ID 매핑 실패: %s", symbol)
                return None

            # CoinGecko API: /simple/price
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": coingecko_id,
                "vs_currencies": "usd",
                "include_24hr_vol": "true",
            }

            # API 키가 있으면 헤더 추가 (Pro plan)
            headers = {}
            if self._coingecko_key:
                headers["x-cg-pro-api-key"] = self._coingecko_key

            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    logger.debug("[RefPrice] CoinGecko 실패: %s (HTTP %d)", coingecko_id, resp.status)
                    return None

                data = await resp.json()
                coin_data = data.get(coingecko_id, {})

                price = coin_data.get("usd")
                volume = coin_data.get("usd_24h_vol")

                if not price or price <= 0:
                    return None

                logger.warning(
                    "[RefPrice] %s → CoinGecko: $%.2f (vol: $%.0f, conf: %.2f) — 저신뢰도 참조",
                    symbol, price, volume or 0, self._CONFIDENCE_MAP[ReferenceSource.COINGECKO],
                )

                return ReferencePrice(
                    symbol=symbol,
                    price_usd=price,
                    source=ReferenceSource.COINGECKO,
                    confidence=self._CONFIDENCE_MAP[ReferenceSource.COINGECKO],
                    volume_24h_usd=volume,
                )

        except Exception as e:
            logger.debug("[RefPrice] CoinGecko 에러 (%s): %s", symbol, e)
        return None


# -----------------------------------------------------------------------------
# 헬퍼 함수
# -----------------------------------------------------------------------------


def _symbol_to_coingecko_id(symbol: str) -> str | None:
    """심볼 → CoinGecko ID 매핑 (간단한 경우만).

    완전한 매핑은 CoinGecko /coins/list API 필요.
    """
    # 주요 코인만 매핑 (TGE 신규 코인은 자동 매핑 어려움)
    mapping = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "BNB": "binancecoin",
        "SOL": "solana",
        "XRP": "ripple",
        "ADA": "cardano",
        "AVAX": "avalanche-2",
        "MATIC": "matic-network",
        "DOT": "polkadot",
        "LINK": "chainlink",
        "UNI": "uniswap",
        "ATOM": "cosmos",
        "ARB": "arbitrum",
        "OP": "optimism",
        "STRK": "starknet",
        "BLUR": "blur",
        "ACE": "fusionist",
        "XAI": "xai-blockchain",
        "MOCA": "moca-network",
        "PORTAL": "portal",
    }
    return mapping.get(symbol.upper())


def get_confidence_emoji(confidence: float) -> str:
    """Confidence 이모지 반환."""
    if confidence >= 0.9:
        return "🟢"  # 높음
    elif confidence >= 0.7:
        return "🟡"  # 보통
    elif confidence >= 0.5:
        return "🟠"  # 낮음
    else:
        return "🔴"  # 매우 낮음


def format_reference_price(ref: ReferencePrice) -> str:
    """Reference price 포맷 (로그/UI용)."""
    emoji = get_confidence_emoji(ref.confidence)
    vol_str = f"${ref.volume_24h_usd:,.0f}" if ref.volume_24h_usd else "N/A"
    return (
        f"{emoji} {ref.symbol} Reference Price\n"
        f"  • Source: {ref.source.value}\n"
        f"  • Price: ${ref.price_usd:,.2f}\n"
        f"  • Confidence: {ref.confidence:.2f}\n"
        f"  • 24h Volume: {vol_str}"
    )
