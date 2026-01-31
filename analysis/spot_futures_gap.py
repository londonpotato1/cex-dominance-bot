#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""현선갭 조회 모듈 (gap_dashboard_v3 기반 통합).

상장 전 GO/NO-GO 판단에 필요한 현선갭 정보를 조회.
- 선물 존재 여부 확인
- 현선갭 계산
- 펀딩비 조회
- 헷지 가능성 판단

gap_dashboard_v3의 ExchangeService, GapCalculator를 경량화하여 통합.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, List, Any
from concurrent.futures import ThreadPoolExecutor

import aiohttp

logger = logging.getLogger(__name__)


class HedgeType(Enum):
    """헷지 가능성 유형"""
    CEX_FUTURES = "cex_futures"    # CEX 선물로 헷지 가능
    DEX_FUTURES = "dex_futures"    # DEX 선물만 가능 (Hyperliquid 등)
    NO_HEDGE = "no_hedge"          # 헷지 불가


@dataclass
class FuturesInfo:
    """선물 정보"""
    exchange: str
    symbol: str
    price: float
    funding_rate: Optional[float] = None
    next_funding_time: Optional[float] = None
    timestamp: float = 0


@dataclass
class SpotFuturesGapResult:
    """현선갭 분석 결과"""
    symbol: str
    
    # 선물 존재 여부
    has_cex_futures: bool = False
    has_dex_futures: bool = False
    
    # 최고 거래소 정보
    top_futures_exchange: Optional[str] = None
    top_futures_price: Optional[float] = None
    
    # 글로벌 현물 가격 (VWAP)
    global_spot_price: Optional[float] = None
    
    # 현선갭 (%)
    spot_futures_gap_pct: Optional[float] = None
    
    # 펀딩비 정보
    funding_rate: Optional[float] = None
    funding_rate_8h_pct: Optional[float] = None  # 연환산이 아닌 8시간 기준
    next_funding_time: Optional[float] = None
    
    # 헷지 판단
    hedge_type: HedgeType = HedgeType.NO_HEDGE
    hedge_difficulty: str = "unknown"  # easy / medium / hard / impossible
    
    # 상세 데이터
    futures_data: List[FuturesInfo] = None
    
    # 타임스탬프
    timestamp: float = 0
    
    def __post_init__(self):
        if self.futures_data is None:
            self.futures_data = []


# CEX 거래소 설정
CEX_FUTURES_EXCHANGES = {
    'binance': {
        'api_url': 'https://fapi.binance.com/fapi/v1/ticker/price',
        'funding_url': 'https://fapi.binance.com/fapi/v1/premiumIndex',
        'symbol_format': '{symbol}USDT',
    },
    'bybit': {
        'api_url': 'https://api.bybit.com/v5/market/tickers',
        'symbol_format': '{symbol}USDT',
    },
    'okx': {
        'api_url': 'https://www.okx.com/api/v5/market/ticker',
        'funding_url': 'https://www.okx.com/api/v5/public/funding-rate',
        'symbol_format': '{symbol}-USDT-SWAP',
    },
    'gate': {
        'api_url': 'https://api.gateio.ws/api/v4/futures/usdt/tickers',
        'symbol_format': '{symbol}_USDT',
    },
    'bitget': {
        'api_url': 'https://api.bitget.com/api/v2/mix/market/ticker',
        'symbol_format': '{symbol}USDT',
    },
}

# DEX 선물 거래소
DEX_FUTURES_EXCHANGES = {
    'hyperliquid': {
        'api_url': 'https://api.hyperliquid.xyz/info',
    },
}

# 현물 거래소 (글로벌 VWAP용)
SPOT_EXCHANGES = {
    'binance': {
        'api_url': 'https://api.binance.com/api/v3/ticker/price',
        'symbol_format': '{symbol}USDT',
    },
    'bybit': {
        'api_url': 'https://api.bybit.com/v5/market/tickers',
        'symbol_format': '{symbol}USDT',
    },
    'okx': {
        'api_url': 'https://www.okx.com/api/v5/market/ticker',
        'symbol_format': '{symbol}-USDT',
    },
}


class SpotFuturesGapAnalyzer:
    """현선갭 분석기"""
    
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
    
    async def analyze(self, symbol: str) -> SpotFuturesGapResult:
        """심볼의 현선갭 분석 (메인 함수)
        
        Args:
            symbol: 토큰 심볼 (예: "BTC", "SENT")
            
        Returns:
            SpotFuturesGapResult: 분석 결과
        """
        symbol = symbol.upper()
        result = SpotFuturesGapResult(symbol=symbol, timestamp=time.time())
        
        # 병렬로 데이터 조회
        tasks = [
            self._fetch_cex_futures(symbol),
            self._fetch_dex_futures(symbol),
            self._fetch_global_spot(symbol),
        ]
        
        try:
            cex_futures, dex_futures, spot_price = await asyncio.gather(
                *tasks, return_exceptions=True
            )
        except Exception as e:
            logger.error(f"[SpotFuturesGap] 분석 실패 ({symbol}): {e}")
            return result
        
        # CEX 선물 처리
        if isinstance(cex_futures, list) and cex_futures:
            result.has_cex_futures = True
            result.futures_data.extend(cex_futures)
            
            # 최고 거래량/유동성 거래소 선택 (일단 바이낸스 우선)
            for f in cex_futures:
                if f.exchange == 'binance':
                    result.top_futures_exchange = f.exchange
                    result.top_futures_price = f.price
                    result.funding_rate = f.funding_rate
                    result.next_funding_time = f.next_funding_time
                    break
            
            if not result.top_futures_exchange and cex_futures:
                f = cex_futures[0]
                result.top_futures_exchange = f.exchange
                result.top_futures_price = f.price
                result.funding_rate = f.funding_rate
                result.next_funding_time = f.next_funding_time
        
        # DEX 선물 처리
        if isinstance(dex_futures, list) and dex_futures:
            result.has_dex_futures = True
            result.futures_data.extend(dex_futures)
            
            # CEX 선물이 없으면 DEX 사용
            if not result.has_cex_futures:
                f = dex_futures[0]
                result.top_futures_exchange = f.exchange
                result.top_futures_price = f.price
                result.funding_rate = f.funding_rate
        
        # 글로벌 현물 가격
        if isinstance(spot_price, float) and spot_price > 0:
            result.global_spot_price = spot_price
        
        # 현선갭 계산
        if result.top_futures_price and result.global_spot_price:
            gap = (result.top_futures_price - result.global_spot_price) / result.global_spot_price * 100
            result.spot_futures_gap_pct = round(gap, 4)
        
        # 펀딩비 8시간 환산
        if result.funding_rate is not None:
            result.funding_rate_8h_pct = round(result.funding_rate * 100, 4)
        
        # 헷지 가능성 판단
        result.hedge_type, result.hedge_difficulty = self._determine_hedge(result)
        
        return result
    
    def _determine_hedge(
        self, result: SpotFuturesGapResult
    ) -> tuple[HedgeType, str]:
        """헷지 가능성 판단
        
        Returns:
            (hedge_type, hedge_difficulty)
        """
        if result.has_cex_futures:
            # CEX 선물 존재
            gap = abs(result.spot_futures_gap_pct or 0)
            
            if gap < 0.5:
                return HedgeType.CEX_FUTURES, "easy"
            elif gap < 2.0:
                return HedgeType.CEX_FUTURES, "medium"
            else:
                return HedgeType.CEX_FUTURES, "hard"
        
        elif result.has_dex_futures:
            # DEX 선물만 존재
            return HedgeType.DEX_FUTURES, "hard"
        
        else:
            # 선물 없음
            return HedgeType.NO_HEDGE, "impossible"
    
    async def _fetch_cex_futures(self, symbol: str) -> List[FuturesInfo]:
        """CEX 선물 가격 조회"""
        results = []
        session = await self._get_session()
        
        tasks = []
        for exchange, config in CEX_FUTURES_EXCHANGES.items():
            tasks.append(self._fetch_single_cex_futures(session, exchange, symbol, config))
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for resp in responses:
            if isinstance(resp, FuturesInfo):
                results.append(resp)
        
        return results
    
    async def _fetch_single_cex_futures(
        self, 
        session: aiohttp.ClientSession,
        exchange: str, 
        symbol: str, 
        config: dict
    ) -> Optional[FuturesInfo]:
        """단일 CEX 선물 가격 조회"""
        try:
            formatted_symbol = config['symbol_format'].format(symbol=symbol)
            
            if exchange == 'binance':
                # 가격 + 펀딩비 한번에
                url = config['funding_url']
                async with session.get(url, params={'symbol': formatted_symbol}) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    
                    return FuturesInfo(
                        exchange=exchange,
                        symbol=symbol,
                        price=float(data.get('markPrice', 0)),
                        funding_rate=float(data.get('lastFundingRate', 0)),
                        next_funding_time=data.get('nextFundingTime', 0) / 1000 if data.get('nextFundingTime') else None,
                        timestamp=time.time()
                    )
            
            elif exchange == 'bybit':
                url = config['api_url']
                async with session.get(url, params={'category': 'linear', 'symbol': formatted_symbol}) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    
                    if data.get('retCode') != 0:
                        return None
                    
                    items = data.get('result', {}).get('list', [])
                    if not items:
                        return None
                    
                    item = items[0]
                    return FuturesInfo(
                        exchange=exchange,
                        symbol=symbol,
                        price=float(item.get('lastPrice', 0)),
                        funding_rate=float(item.get('fundingRate', 0)) if item.get('fundingRate') else None,
                        next_funding_time=int(item.get('nextFundingTime', 0)) / 1000 if item.get('nextFundingTime') else None,
                        timestamp=time.time()
                    )
            
            elif exchange == 'okx':
                # 가격 조회
                url = config['api_url']
                async with session.get(url, params={'instId': formatted_symbol}) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    
                    if data.get('code') != '0':
                        return None
                    
                    items = data.get('data', [])
                    if not items:
                        return None
                    
                    price = float(items[0].get('last', 0))
                
                # 펀딩비 조회
                funding_rate = None
                next_funding = None
                try:
                    funding_url = config['funding_url']
                    async with session.get(funding_url, params={'instId': formatted_symbol}) as resp:
                        if resp.status == 200:
                            fdata = await resp.json()
                            if fdata.get('code') == '0' and fdata.get('data'):
                                funding_rate = float(fdata['data'][0].get('fundingRate', 0))
                                next_funding = int(fdata['data'][0].get('nextFundingTime', 0)) / 1000
                except:
                    pass
                
                return FuturesInfo(
                    exchange=exchange,
                    symbol=symbol,
                    price=price,
                    funding_rate=funding_rate,
                    next_funding_time=next_funding,
                    timestamp=time.time()
                )
            
            elif exchange == 'gate':
                url = f"{config['api_url']}"
                async with session.get(url, params={'contract': formatted_symbol}) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    
                    if not data:
                        return None
                    
                    item = data[0] if isinstance(data, list) else data
                    return FuturesInfo(
                        exchange=exchange,
                        symbol=symbol,
                        price=float(item.get('last', 0)),
                        funding_rate=float(item.get('funding_rate', 0)) if item.get('funding_rate') else None,
                        timestamp=time.time()
                    )
            
            elif exchange == 'bitget':
                url = config['api_url']
                async with session.get(url, params={'symbol': formatted_symbol, 'productType': 'USDT-FUTURES'}) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    
                    if data.get('code') != '00000':
                        return None
                    
                    item = data.get('data', {})
                    return FuturesInfo(
                        exchange=exchange,
                        symbol=symbol,
                        price=float(item.get('lastPr', 0)),
                        funding_rate=float(item.get('fundingRate', 0)) if item.get('fundingRate') else None,
                        timestamp=time.time()
                    )
        
        except Exception as e:
            logger.debug(f"[SpotFuturesGap] {exchange} 선물 조회 실패 ({symbol}): {e}")
        
        return None
    
    async def _fetch_dex_futures(self, symbol: str) -> List[FuturesInfo]:
        """DEX 선물 가격 조회 (Hyperliquid)"""
        results = []
        session = await self._get_session()
        
        try:
            # Hyperliquid
            url = DEX_FUTURES_EXCHANGES['hyperliquid']['api_url']
            async with session.post(url, json={'type': 'allMids'}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price_str = data.get(symbol)
                    if price_str:
                        results.append(FuturesInfo(
                            exchange='hyperliquid',
                            symbol=symbol,
                            price=float(price_str),
                            timestamp=time.time()
                        ))
        except Exception as e:
            logger.debug(f"[SpotFuturesGap] Hyperliquid 조회 실패 ({symbol}): {e}")
        
        return results
    
    async def _fetch_global_spot(self, symbol: str) -> Optional[float]:
        """글로벌 현물 가격 조회 (VWAP 대신 바이낸스 우선)"""
        session = await self._get_session()
        
        # 바이낸스 우선
        try:
            url = SPOT_EXCHANGES['binance']['api_url']
            formatted = f"{symbol}USDT"
            async with session.get(url, params={'symbol': formatted}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data.get('price', 0))
        except:
            pass
        
        # 바이비트 폴백
        try:
            url = SPOT_EXCHANGES['bybit']['api_url']
            formatted = f"{symbol}USDT"
            async with session.get(url, params={'category': 'spot', 'symbol': formatted}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get('result', {}).get('list', [])
                    if items:
                        return float(items[0].get('lastPrice', 0))
        except:
            pass
        
        return None


# 편의 함수
async def get_spot_futures_gap(symbol: str) -> SpotFuturesGapResult:
    """현선갭 조회 (편의 함수)
    
    Args:
        symbol: 토큰 심볼
        
    Returns:
        SpotFuturesGapResult
    """
    analyzer = SpotFuturesGapAnalyzer()
    try:
        return await analyzer.analyze(symbol)
    finally:
        await analyzer.close()


def get_spot_futures_gap_sync(symbol: str) -> SpotFuturesGapResult:
    """현선갭 조회 (동기 버전)"""
    return asyncio.run(get_spot_futures_gap(symbol))


# 테스트용
if __name__ == "__main__":
    import sys
    
    async def main():
        symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC"
        result = await get_spot_futures_gap(symbol)
        
        print(f"\n=== {symbol} Spot-Futures Gap ===")
        print(f"CEX Futures: {'YES' if result.has_cex_futures else 'NO'}")
        print(f"DEX Futures: {'YES' if result.has_dex_futures else 'NO'}")
        print(f"Top Exchange: {result.top_futures_exchange}")
        print(f"Futures Price: ${result.top_futures_price:,.4f}" if result.top_futures_price else "Futures Price: N/A")
        print(f"Spot Price: ${result.global_spot_price:,.4f}" if result.global_spot_price else "Spot Price: N/A")
        print(f"Gap: {result.spot_futures_gap_pct:+.4f}%" if result.spot_futures_gap_pct is not None else "Gap: N/A")
        print(f"Funding (8h): {result.funding_rate_8h_pct:+.4f}%" if result.funding_rate_8h_pct is not None else "Funding: N/A")
        print(f"Hedge Type: {result.hedge_type.value}")
        print(f"Hedge Difficulty: {result.hedge_difficulty}")
    
    asyncio.run(main())
