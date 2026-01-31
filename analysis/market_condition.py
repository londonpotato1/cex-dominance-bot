#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시황 자동 판단 모듈 (Phase 1).

업비트 24H 거래량 + BTC 변동률 기반 불장/망장 자동 판정.

판정 기준 (따리 펀더멘탈):
- 불장: 업비트 24H 거래량 10조+ 또는 BTC +5% 이상
- 보통: 업비트 5~10조, BTC -3% ~ +5%
- 망장: 업비트 5조 미만 또는 BTC -5% 이하

데이터 소스:
- 업비트: GET /v1/ticker (KRW 마켓 거래량 합산)
- Binance: GET /api/v3/ticker/24hr (BTC 변동률)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class MarketCondition(Enum):
    """시황 상태"""
    BULL = "bull"        # 불장 🔥
    NEUTRAL = "neutral"  # 보통 😐
    BEAR = "bear"        # 망장 ❄️


@dataclass
class MarketConditionResult:
    """시황 판단 결과"""
    condition: MarketCondition
    
    # 업비트 24H 거래량 (KRW)
    upbit_volume_24h_krw: Optional[float] = None
    upbit_volume_tier: str = "unknown"  # huge / high / normal / low
    
    # BTC 24H 변동률
    btc_price_usd: Optional[float] = None
    btc_change_24h_pct: Optional[float] = None
    btc_trend: str = "unknown"  # bullish / neutral / bearish
    
    # 점수 (-100 ~ +100)
    market_score: float = 0
    
    # 판단 근거
    reasons: list[str] = None
    
    # 타임스탬프
    timestamp: float = 0
    
    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []


# 업비트 거래량 기준 (KRW)
UPBIT_VOLUME_THRESHOLDS = {
    "huge": 15_000_000_000_000,    # 15조+ (초불장)
    "high": 10_000_000_000_000,    # 10조+ (불장)
    "normal": 5_000_000_000_000,   # 5조+ (보통)
    # 5조 미만 = low (망장)
}

# BTC 변동률 기준 (%)
BTC_CHANGE_THRESHOLDS = {
    "strong_bull": 5.0,    # +5% 이상 (강한 불장)
    "bull": 3.0,           # +3% 이상 (불장)
    "neutral_high": 0.0,   # 0% ~ +3% (중립 상방)
    "neutral_low": -3.0,   # -3% ~ 0% (중립 하방)
    "bear": -5.0,          # -5% 이하 (망장)
}


class MarketConditionAnalyzer:
    """시황 자동 판단기"""
    
    def __init__(self, timeout: float = 10.0):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def analyze(self) -> MarketConditionResult:
        """시황 자동 분석 (메인 함수)
        
        Returns:
            MarketConditionResult
        """
        result = MarketConditionResult(
            condition=MarketCondition.NEUTRAL,
            timestamp=time.time()
        )
        
        # 병렬 데이터 조회
        tasks = [
            self._fetch_upbit_volume(),
            self._fetch_btc_change(),
        ]
        
        try:
            upbit_data, btc_data = await asyncio.gather(
                *tasks, return_exceptions=True
            )
        except Exception as e:
            logger.error(f"[MarketCondition] 데이터 조회 실패: {e}")
            return result
        
        # 업비트 거래량 처리
        upbit_score = 0
        if isinstance(upbit_data, dict):
            volume = upbit_data.get("total_volume_krw", 0)
            result.upbit_volume_24h_krw = volume
            
            if volume >= UPBIT_VOLUME_THRESHOLDS["huge"]:
                result.upbit_volume_tier = "huge"
                upbit_score = 40
                result.reasons.append(f"🔥 업비트 24H {volume/1e12:.1f}조 (초불장)")
            elif volume >= UPBIT_VOLUME_THRESHOLDS["high"]:
                result.upbit_volume_tier = "high"
                upbit_score = 25
                result.reasons.append(f"📈 업비트 24H {volume/1e12:.1f}조 (불장)")
            elif volume >= UPBIT_VOLUME_THRESHOLDS["normal"]:
                result.upbit_volume_tier = "normal"
                upbit_score = 0
                result.reasons.append(f"📊 업비트 24H {volume/1e12:.1f}조 (보통)")
            else:
                result.upbit_volume_tier = "low"
                upbit_score = -25
                result.reasons.append(f"📉 업비트 24H {volume/1e12:.1f}조 (저조)")
        else:
            logger.warning(f"[MarketCondition] 업비트 조회 실패: {upbit_data}")
            result.reasons.append("⚠️ 업비트 거래량 조회 실패")
        
        # BTC 변동률 처리
        btc_score = 0
        if isinstance(btc_data, dict):
            result.btc_price_usd = btc_data.get("price_usd")
            change = btc_data.get("change_24h_pct", 0)
            result.btc_change_24h_pct = change
            
            if change >= BTC_CHANGE_THRESHOLDS["strong_bull"]:
                result.btc_trend = "strong_bullish"
                btc_score = 40
                result.reasons.append(f"🚀 BTC {change:+.1f}% (강한 상승)")
            elif change >= BTC_CHANGE_THRESHOLDS["bull"]:
                result.btc_trend = "bullish"
                btc_score = 20
                result.reasons.append(f"📈 BTC {change:+.1f}% (상승)")
            elif change >= BTC_CHANGE_THRESHOLDS["neutral_high"]:
                result.btc_trend = "neutral"
                btc_score = 5
                result.reasons.append(f"➡️ BTC {change:+.1f}% (횡보)")
            elif change >= BTC_CHANGE_THRESHOLDS["neutral_low"]:
                result.btc_trend = "neutral"
                btc_score = -5
                result.reasons.append(f"➡️ BTC {change:+.1f}% (소폭 하락)")
            elif change >= BTC_CHANGE_THRESHOLDS["bear"]:
                result.btc_trend = "bearish"
                btc_score = -20
                result.reasons.append(f"📉 BTC {change:+.1f}% (하락)")
            else:
                result.btc_trend = "strong_bearish"
                btc_score = -40
                result.reasons.append(f"💀 BTC {change:+.1f}% (급락)")
        else:
            logger.warning(f"[MarketCondition] BTC 조회 실패: {btc_data}")
            result.reasons.append("⚠️ BTC 변동률 조회 실패")
        
        # 총점 계산 및 시황 판정
        total_score = upbit_score + btc_score
        result.market_score = total_score
        
        if total_score >= 30:
            result.condition = MarketCondition.BULL
        elif total_score <= -30:
            result.condition = MarketCondition.BEAR
        else:
            result.condition = MarketCondition.NEUTRAL
        
        logger.info(
            "[MarketCondition] %s (score: %d, upbit: %s, btc: %s)",
            result.condition.value, total_score,
            result.upbit_volume_tier, result.btc_trend
        )
        
        return result
    
    async def _fetch_upbit_volume(self) -> dict:
        """업비트 24H 총 거래량 조회
        
        Returns:
            {"total_volume_krw": float, "market_count": int}
        """
        session = await self._get_session()
        
        try:
            # 1. KRW 마켓 목록 조회
            markets_url = "https://api.upbit.com/v1/market/all"
            async with session.get(markets_url) as resp:
                if resp.status != 200:
                    return {"error": f"markets API {resp.status}"}
                markets_data = await resp.json()
            
            # KRW 마켓만 필터
            krw_markets = [
                m["market"] for m in markets_data 
                if m["market"].startswith("KRW-")
            ]
            
            if not krw_markets:
                return {"error": "No KRW markets"}
            
            # 2. 티커 조회 (최대 100개씩)
            total_volume = 0.0
            batch_size = 100
            
            for i in range(0, len(krw_markets), batch_size):
                batch = krw_markets[i:i + batch_size]
                markets_param = ",".join(batch)
                
                ticker_url = f"https://api.upbit.com/v1/ticker?markets={markets_param}"
                async with session.get(ticker_url) as resp:
                    if resp.status != 200:
                        continue
                    tickers = await resp.json()
                
                # 거래대금 합산 (acc_trade_price_24h)
                for ticker in tickers:
                    volume = ticker.get("acc_trade_price_24h", 0)
                    if volume:
                        total_volume += float(volume)
                
                # Rate limit 회피
                await asyncio.sleep(0.1)
            
            return {
                "total_volume_krw": total_volume,
                "market_count": len(krw_markets)
            }
        
        except Exception as e:
            logger.error(f"[MarketCondition] 업비트 조회 오류: {e}")
            return {"error": str(e)}
    
    async def _fetch_btc_change(self) -> dict:
        """BTC 24H 변동률 조회 (Binance)
        
        Returns:
            {"price_usd": float, "change_24h_pct": float}
        """
        session = await self._get_session()
        
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            params = {"symbol": "BTCUSDT"}
            
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return {"error": f"Binance API {resp.status}"}
                data = await resp.json()
            
            price = float(data.get("lastPrice", 0))
            change_pct = float(data.get("priceChangePercent", 0))
            
            return {
                "price_usd": price,
                "change_24h_pct": change_pct
            }
        
        except Exception as e:
            logger.error(f"[MarketCondition] BTC 조회 오류: {e}")
            return {"error": str(e)}


# 편의 함수
async def get_market_condition() -> MarketConditionResult:
    """시황 조회 (편의 함수)"""
    analyzer = MarketConditionAnalyzer()
    try:
        return await analyzer.analyze()
    finally:
        await analyzer.close()


def get_market_condition_sync() -> MarketConditionResult:
    """시황 조회 (동기 버전)"""
    return asyncio.run(get_market_condition())


def format_market_condition(result: MarketConditionResult) -> str:
    """시황 결과 포맷팅 (텔레그램용)"""
    emoji_map = {
        MarketCondition.BULL: "🔥",
        MarketCondition.NEUTRAL: "😐",
        MarketCondition.BEAR: "❄️",
    }
    
    label_map = {
        MarketCondition.BULL: "불장",
        MarketCondition.NEUTRAL: "보통",
        MarketCondition.BEAR: "망장",
    }
    
    emoji = emoji_map.get(result.condition, "❓")
    label = label_map.get(result.condition, "알수없음")
    
    lines = [
        f"{emoji} **시황: {label}** (점수: {result.market_score:+.0f})",
        "",
    ]
    
    if result.upbit_volume_24h_krw:
        vol_str = f"{result.upbit_volume_24h_krw / 1e12:.1f}조원"
        lines.append(f"📊 업비트 24H: {vol_str}")
    
    if result.btc_price_usd and result.btc_change_24h_pct is not None:
        lines.append(f"₿ BTC: ${result.btc_price_usd:,.0f} ({result.btc_change_24h_pct:+.1f}%)")
    
    if result.reasons:
        lines.append("")
        for reason in result.reasons:
            lines.append(f"  {reason}")
    
    return "\n".join(lines)


# 테스트용
if __name__ == "__main__":
    async def main():
        print("=== 시황 자동 판단 테스트 ===\n")
        
        result = await get_market_condition()
        
        print(f"판정: {result.condition.value}")
        print(f"점수: {result.market_score}")
        print(f"업비트 거래량: {result.upbit_volume_24h_krw}")
        print(f"업비트 티어: {result.upbit_volume_tier}")
        print(f"BTC 가격: ${result.btc_price_usd:,.0f}" if result.btc_price_usd else "BTC: N/A")
        print(f"BTC 변동: {result.btc_change_24h_pct:+.2f}%" if result.btc_change_24h_pct else "BTC 변동: N/A")
        
        print(f"\n--- 판단 근거 ---")
        for reason in result.reasons:
            print(f"  {reason}")
        
        print(f"\n--- 텔레그램 포맷 ---")
        print(format_market_condition(result))
    
    asyncio.run(main())
