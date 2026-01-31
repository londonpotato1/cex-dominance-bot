"""펀딩비 수집기 (Binance/Bybit).

선물 포지션 쏠림을 파악하기 위한 펀딩비 데이터 수집.
- 양수 펀딩비: 롱 포지션 과다 (롱이 숏에 지불)
- 음수 펀딩비: 숏 포지션 과다 (숏이 롱에 지불)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Binance Futures API
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
BYBIT_FUNDING_URL = "https://api.bybit.com/v5/market/tickers"


@dataclass
class FundingRate:
    """펀딩비 정보."""
    symbol: str
    exchange: str
    funding_rate: float  # 펀딩비 (0.01 = 1%)
    next_funding_time: Optional[datetime]
    mark_price: float
    index_price: float
    timestamp: datetime
    
    @property
    def funding_rate_pct(self) -> float:
        """펀딩비 퍼센트."""
        return self.funding_rate * 100
    
    @property
    def position_bias(self) -> str:
        """포지션 쏠림 방향."""
        if self.funding_rate > 0.0005:  # 0.05% 이상
            return "long_heavy"  # 롱 과다
        elif self.funding_rate < -0.0005:
            return "short_heavy"  # 숏 과다
        return "neutral"


async def fetch_binance_funding(symbol: str = "BTCUSDT") -> Optional[FundingRate]:
    """바이낸스 펀딩비 조회."""
    try:
        async with aiohttp.ClientSession() as session:
            params = {"symbol": symbol}
            async with session.get(BINANCE_FUNDING_URL, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return FundingRate(
                        symbol=data["symbol"],
                        exchange="binance",
                        funding_rate=float(data["lastFundingRate"]),
                        next_funding_time=datetime.fromtimestamp(data["nextFundingTime"] / 1000),
                        mark_price=float(data["markPrice"]),
                        index_price=float(data["indexPrice"]),
                        timestamp=datetime.now(),
                    )
    except Exception as e:
        logger.warning(f"Binance 펀딩비 조회 실패: {e}")
    return None


async def fetch_bybit_funding(symbol: str = "BTCUSDT") -> Optional[FundingRate]:
    """바이빗 펀딩비 조회."""
    try:
        async with aiohttp.ClientSession() as session:
            params = {"category": "linear", "symbol": symbol}
            async with session.get(BYBIT_FUNDING_URL, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data["result"]["list"]:
                        item = data["result"]["list"][0]
                        return FundingRate(
                            symbol=item["symbol"],
                            exchange="bybit",
                            funding_rate=float(item.get("fundingRate", 0)),
                            next_funding_time=datetime.fromtimestamp(int(item.get("nextFundingTime", 0)) / 1000) if item.get("nextFundingTime") else None,
                            mark_price=float(item["markPrice"]),
                            index_price=float(item["indexPrice"]),
                            timestamp=datetime.now(),
                        )
    except Exception as e:
        logger.warning(f"Bybit 펀딩비 조회 실패: {e}")
    return None


async def get_funding_rates(symbols: list[str] = None) -> dict[str, FundingRate]:
    """여러 심볼의 펀딩비 조회."""
    if symbols is None:
        symbols = ["BTCUSDT", "ETHUSDT"]
    
    results = {}
    for symbol in symbols:
        # 바이낸스 우선
        rate = await fetch_binance_funding(symbol)
        if rate:
            results[symbol] = rate
        else:
            # 바이빗 대체
            rate = await fetch_bybit_funding(symbol)
            if rate:
                results[symbol] = rate
    
    return results


def get_funding_summary(rates: dict[str, FundingRate]) -> dict:
    """펀딩비 요약."""
    if not rates:
        return {"status": "no_data"}
    
    avg_rate = sum(r.funding_rate for r in rates.values()) / len(rates)
    
    return {
        "status": "ok",
        "avg_funding_rate_pct": avg_rate * 100,
        "position_bias": "long_heavy" if avg_rate > 0.0005 else "short_heavy" if avg_rate < -0.0005 else "neutral",
        "symbols": {s: {"rate_pct": r.funding_rate_pct, "bias": r.position_bias} for s, r in rates.items()},
    }


# 테스트
if __name__ == "__main__":
    async def test():
        rates = await get_funding_rates(["BTCUSDT", "ETHUSDT"])
        for symbol, rate in rates.items():
            print(f"{symbol}: {rate.funding_rate_pct:.4f}% ({rate.position_bias})")
        
        summary = get_funding_summary(rates)
        print(f"\n요약: {summary}")
    
    asyncio.run(test())
