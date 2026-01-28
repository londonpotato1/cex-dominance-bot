"""김치 프리미엄 계산 (Phase 3).

5단계 FX 폴백 체인:
  1. BTC Implied FX (BTC_Upbit_KRW / BTC_Binance_USDT)
  2. ETH Implied FX
  3. USDT/KRW 직접 환율 (Upbit)
  4. 캐시된 FX값 (5분 이내)
  5. 하드코딩 기본값 (1350.0) + CRITICAL

글로벌 VWAP: Binance + OKX + Bybit REST ticker → 거래량 가중 평균.
모든 가격은 REST API on-demand 호출 (DB 미사용).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import aiohttp
import yaml

if TYPE_CHECKING:
    from store.writer import DatabaseWriter

logger = logging.getLogger(__name__)

# FX 하드코딩 기본값 (최후 폴백)
_HARDCODED_FX = 1350.0

# FX 캐시 유효 시간 (초)
_FX_CACHE_TTL = 300.0  # 5분

# HTTP 타임아웃
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)

# FX 스냅샷 INSERT SQL
_FX_SNAPSHOT_SQL = (
    "INSERT INTO fx_snapshots (timestamp, fx_rate, source, btc_krw, btc_usd) "
    "VALUES (?, ?, ?, ?, ?)"
)


@dataclass
class PremiumResult:
    """프리미엄 계산 결과."""
    premium_pct: float          # 프리미엄 퍼센트 (e.g., 5.2 = 5.2%)
    krw_price: float            # 국내 원화 가격
    global_usd_price: float     # 글로벌 USD 가격
    fx_rate: float              # 사용된 FX 환율
    fx_source: str              # FX 소스 ('btc_implied', 'eth_implied', ...)


@dataclass
class VWAPResult:
    """글로벌 VWAP 결과."""
    price_usd: float            # 가중 평균 가격
    total_volume_usd: float     # 총 거래량 (USD)
    sources: list[str]          # 참여 거래소 목록


class PremiumCalculator:
    """김치 프리미엄 계산기.

    - FX 환율: 5단계 폴백 체인
    - 글로벌 가격: 3개 거래소 VWAP
    - FX 스냅샷: DB 저장 (Writer Queue 경유)
    """

    def __init__(
        self,
        writer: DatabaseWriter,
        config_dir: str | Path | None = None,
    ) -> None:
        self._writer = writer
        self._fx_cache: Optional[tuple[float, str, float]] = None  # (rate, source, timestamp)

        # 거래소 API 설정 로드
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        config_path = Path(config_dir) / "exchanges.yaml"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                self._exchange_config = yaml.safe_load(f) or {}
        else:
            logger.warning("exchanges.yaml 미발견, 기본값 사용")
            self._exchange_config = {}

    async def get_implied_fx(
        self, session: aiohttp.ClientSession | None = None,
    ) -> tuple[float, str]:
        """내재 FX 환율 조회 (5단계 폴백).

        Returns:
            (fx_rate, source) 튜플.
        """
        own_session = session is None
        if own_session:
            session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)

        try:
            # 1단계: BTC Implied FX
            fx = await self._try_btc_implied(session)
            if fx:
                return fx

            # 2단계: ETH Implied FX
            fx = await self._try_eth_implied(session)
            if fx:
                return fx

            # 3단계: USDT/KRW 직접
            fx = await self._try_usdt_krw(session)
            if fx:
                return fx

            # 4단계: 캐시된 FX값 (5분 이내) — 원본 소스 유지
            if self._fx_cache:
                rate, source, ts = self._fx_cache
                age = time.time() - ts
                if age < _FX_CACHE_TTL:
                    logger.info("FX 캐시 사용: %.2f (%s, age=%.0fs)", rate, source, age)
                    return rate, source

            # 5단계: 하드코딩 기본값
            logger.critical(
                "FX 모든 폴백 실패! 하드코딩 기본값 사용: %.2f", _HARDCODED_FX,
            )
            return _HARDCODED_FX, "hardcoded_fallback"

        finally:
            if own_session and session:
                await session.close()

    async def calculate_premium(
        self,
        krw_price: float,
        global_usd_price: float,
        fx_rate: float,
        fx_source: str = "unknown",
    ) -> PremiumResult:
        """프리미엄 퍼센트 계산.

        Args:
            krw_price: 국내 KRW 가격.
            global_usd_price: 글로벌 USD 가격.
            fx_rate: FX 환율.
            fx_source: FX 환율 출처 (e.g., "btc_implied").

        Returns:
            PremiumResult.
        """
        if global_usd_price <= 0 or fx_rate <= 0:
            return PremiumResult(
                premium_pct=0.0,
                krw_price=krw_price,
                global_usd_price=global_usd_price,
                fx_rate=fx_rate,
                fx_source=fx_source,
            )

        global_krw_equivalent = global_usd_price * fx_rate
        premium_pct = ((krw_price - global_krw_equivalent) / global_krw_equivalent) * 100.0

        return PremiumResult(
            premium_pct=premium_pct,
            krw_price=krw_price,
            global_usd_price=global_usd_price,
            fx_rate=fx_rate,
            fx_source=fx_source,
        )

    async def get_global_vwap(
        self,
        symbol: str,
        session: aiohttp.ClientSession | None = None,
    ) -> VWAPResult | None:
        """글로벌 3거래소 VWAP (거래량 가중 평균).

        Binance + OKX + Bybit REST ticker → 거래량 기준 가중 평균.

        Args:
            symbol: 토큰 심볼 (e.g., "BTC", "ETH").
            session: aiohttp 세션 (없으면 생성).

        Returns:
            VWAPResult 또는 모든 거래소 실패 시 None.
        """
        own_session = session is None
        if own_session:
            session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)

        try:
            # 병렬 요청
            results = await _fetch_global_tickers(symbol, session)

            if not results:
                logger.warning("글로벌 VWAP 실패: 모든 거래소 응답 없음 (%s)", symbol)
                return None

            # 거래량 가중 평균
            total_volume = sum(r[1] for r in results)
            if total_volume <= 0:
                # 거래량 없으면 단순 평균
                avg_price = sum(r[0] for r in results) / len(results)
                return VWAPResult(
                    price_usd=avg_price,
                    total_volume_usd=0.0,
                    sources=[r[2] for r in results],
                )

            vwap = sum(r[0] * r[1] for r in results) / total_volume
            return VWAPResult(
                price_usd=vwap,
                total_volume_usd=total_volume,
                sources=[r[2] for r in results],
            )

        finally:
            if own_session and session:
                await session.close()

    async def save_fx_snapshot(
        self, fx_rate: float, source: str,
        btc_krw: float | None = None, btc_usd: float | None = None,
    ) -> None:
        """FX 스냅샷 DB 저장 (Writer Queue 경유)."""
        await self._writer.enqueue(
            _FX_SNAPSHOT_SQL,
            (time.time(), fx_rate, source, btc_krw, btc_usd),
        )

    # ------------------------------------------------------------------
    # FX 폴백 단계별 구현
    # ------------------------------------------------------------------

    async def _try_btc_implied(
        self, session: aiohttp.ClientSession,
    ) -> tuple[float, str] | None:
        """1단계: BTC Implied FX = BTC_KRW(Upbit) / BTC_USD(Binance)."""
        try:
            btc_krw = await _fetch_upbit_price("KRW-BTC", session)
            btc_usd = await _fetch_binance_price("BTCUSDT", session)

            if btc_krw and btc_usd and btc_usd > 0:
                fx = btc_krw / btc_usd
                self._fx_cache = (fx, "btc_implied", time.time())
                await self.save_fx_snapshot(fx, "btc_implied", btc_krw, btc_usd)
                logger.debug("BTC Implied FX: %.2f (BTC_KRW=%.0f, BTC_USD=%.2f)", fx, btc_krw, btc_usd)
                return fx, "btc_implied"
        except Exception as e:
            logger.debug("BTC Implied FX 실패: %s", e)
        return None

    async def _try_eth_implied(
        self, session: aiohttp.ClientSession,
    ) -> tuple[float, str] | None:
        """2단계: ETH Implied FX = ETH_KRW(Upbit) / ETH_USD(Binance)."""
        try:
            eth_krw = await _fetch_upbit_price("KRW-ETH", session)
            eth_usd = await _fetch_binance_price("ETHUSDT", session)

            if eth_krw and eth_usd and eth_usd > 0:
                fx = eth_krw / eth_usd
                self._fx_cache = (fx, "eth_implied", time.time())
                await self.save_fx_snapshot(fx, "eth_implied")
                logger.debug("ETH Implied FX: %.2f", fx)
                return fx, "eth_implied"
        except Exception as e:
            logger.debug("ETH Implied FX 실패: %s", e)
        return None

    async def _try_usdt_krw(
        self, session: aiohttp.ClientSession,
    ) -> tuple[float, str] | None:
        """3단계: USDT/KRW 직접 환율 (Upbit)."""
        try:
            usdt_krw = await _fetch_upbit_price("KRW-USDT", session)
            if usdt_krw and usdt_krw > 0:
                self._fx_cache = (usdt_krw, "usdt_krw_direct", time.time())
                await self.save_fx_snapshot(usdt_krw, "usdt_krw_direct")
                logger.debug("USDT/KRW 직접: %.2f", usdt_krw)
                return usdt_krw, "usdt_krw_direct"
        except Exception as e:
            logger.debug("USDT/KRW 직접 조회 실패: %s", e)
        return None


# ------------------------------------------------------------------
# REST API 헬퍼 함수 (모듈 레벨)
# ------------------------------------------------------------------

async def _fetch_upbit_price(
    market: str, session: aiohttp.ClientSession
) -> float | None:
    """Upbit REST ticker로 현재가 조회.

    Args:
        market: 마켓 코드 (e.g., "KRW-BTC").
        session: aiohttp 세션.

    Returns:
        현재 거래가 또는 None.
    """
    url = "https://api.upbit.com/v1/ticker"
    try:
        async with session.get(url, params={"markets": market}) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if data and len(data) > 0:
                return float(data[0].get("trade_price", 0))
    except Exception as e:
        logger.debug("Upbit 가격 조회 실패 (%s): %s", market, e)
    return None


async def _fetch_binance_price(
    symbol: str, session: aiohttp.ClientSession
) -> float | None:
    """Binance REST ticker로 현재가 조회.

    Args:
        symbol: 심볼 (e.g., "BTCUSDT").
        session: aiohttp 세션.

    Returns:
        현재 가격 또는 None.
    """
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        async with session.get(url, params={"symbol": symbol}) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return float(data.get("lastPrice", 0))
    except Exception as e:
        logger.debug("Binance 가격 조회 실패 (%s): %s", symbol, e)
    return None


async def _fetch_global_tickers(
    symbol: str, session: aiohttp.ClientSession,
) -> list[tuple[float, float, str]]:
    """글로벌 3거래소 ticker 병렬 조회.

    Returns:
        [(price, volume_usd, exchange_name), ...] — 성공한 거래소만.
    """

    async def _binance() -> tuple[float, float, str] | None:
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            async with session.get(url, params={"symbol": f"{symbol}USDT"}) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                price = float(data.get("lastPrice", 0))
                volume = float(data.get("quoteVolume", 0))  # USDT volume
                if price > 0:
                    return price, volume, "binance"
        except Exception as e:
            logger.debug("Binance ticker 실패 (%s): %s", symbol, e)
        return None

    async def _okx() -> tuple[float, float, str] | None:
        try:
            url = "https://www.okx.com/api/v5/market/ticker"
            async with session.get(url, params={"instId": f"{symbol}-USDT"}) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                tickers = data.get("data", [])
                if tickers:
                    t = tickers[0]
                    price = float(t.get("last", 0))
                    vol24h = float(t.get("vol24h", 0))      # base volume
                    volume_usd = vol24h * price
                    if price > 0:
                        return price, volume_usd, "okx"
        except Exception as e:
            logger.debug("OKX ticker 실패 (%s): %s", symbol, e)
        return None

    async def _bybit() -> tuple[float, float, str] | None:
        try:
            url = "https://api.bybit.com/v5/market/tickers"
            async with session.get(
                url, params={"category": "spot", "symbol": f"{symbol}USDT"}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                tickers = data.get("result", {}).get("list", [])
                if tickers:
                    t = tickers[0]
                    price = float(t.get("lastPrice", 0))
                    turnover = float(t.get("turnover24h", 0))  # USD volume
                    if price > 0:
                        return price, turnover, "bybit"
        except Exception as e:
            logger.debug("Bybit ticker 실패 (%s): %s", symbol, e)
        return None

    tasks = [_binance(), _okx(), _bybit()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid = []
    for r in results:
        if isinstance(r, tuple):
            valid.append(r)
    return valid
