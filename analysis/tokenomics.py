"""토크노믹스 조회 (Phase 3).

CoinGecko API 경유 MC/FDV/유통량/가격 조회.
store/cache.py TTL 캐시를 사용하여 API rate limit 관리.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from store.cache import CoinGeckoCache

logger = logging.getLogger(__name__)


@dataclass
class TokenomicsData:
    """토크노믹스 데이터."""
    symbol: str
    market_cap_usd: Optional[float] = None
    fdv_usd: Optional[float] = None
    circulating_supply: Optional[float] = None
    total_supply: Optional[float] = None
    price_usd: Optional[float] = None


async def get_tokenomics(
    symbol: str,
    cache: CoinGeckoCache,
    coingecko_id: str | None = None,
) -> TokenomicsData | None:
    """토크노믹스 데이터 조회.

    Args:
        symbol: 토큰 심볼 (e.g., "BTC").
        cache: CoinGeckoCache 인스턴스.
        coingecko_id: CoinGecko 코인 ID. None이면 심볼로 검색.

    Returns:
        TokenomicsData 또는 조회 실패 시 None.
    """
    if not coingecko_id:
        # 심볼로 검색하여 coingecko_id 확보
        coingecko_id = await _resolve_coingecko_id(symbol, cache)
        if not coingecko_id:
            logger.debug("CoinGecko ID 조회 실패: %s", symbol)
            return None

    data = await cache.get_coin_data(coingecko_id)
    if not data:
        return None

    market_data = data.get("market_data", {})
    if not market_data:
        return TokenomicsData(symbol=symbol)

    return TokenomicsData(
        symbol=symbol,
        market_cap_usd=market_data.get("market_cap", {}).get("usd"),
        fdv_usd=market_data.get("fully_diluted_valuation", {}).get("usd"),
        circulating_supply=market_data.get("circulating_supply"),
        total_supply=market_data.get("total_supply"),
        price_usd=market_data.get("current_price", {}).get("usd"),
    )


async def _resolve_coingecko_id(
    symbol: str, cache: CoinGeckoCache
) -> str | None:
    """심볼에서 CoinGecko ID 추출.

    /coins/markets 엔드포인트로 상위 코인 목록에서 매칭 시도.
    """
    coins = await cache.get_coin_market_data(ids=None, per_page=250, page=1)
    if not coins:
        return None

    symbol_upper = symbol.upper()
    for coin in coins:
        if coin.get("symbol", "").upper() == symbol_upper:
            return coin.get("id")

    return None
