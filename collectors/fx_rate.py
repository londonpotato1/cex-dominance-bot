"""다중 환율 소스 서비스.

5개 소스에서 환율 조회 후 가중 평균 계산:
- Tier 1: 업비트/빗썸 USDT/KRW (직접)
- Tier 2: BTC/ETH Implied (암시적)
- Tier 3: 외부 API (Fallback)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class FxRate:
    """단일 환율 정보."""
    rate: float                 # 환율 (KRW per USD)
    source: str                 # 소스명
    source_type: str            # "direct" | "implied" | "external"
    confidence: float           # 신뢰도 (0-1)
    timestamp: datetime = field(default_factory=datetime.now)
    raw_data: dict = field(default_factory=dict)

    @property
    def confidence_label(self) -> str:
        """신뢰도 라벨."""
        if self.confidence >= 0.95:
            return "EXCELLENT"
        elif self.confidence >= 0.85:
            return "GOOD"
        elif self.confidence >= 0.70:
            return "FAIR"
        else:
            return "POOR"
    
    @property
    def confidence_stars(self) -> str:
        """신뢰도 별표."""
        stars = int(self.confidence * 5)
        return "⭐" * stars


@dataclass
class FxRateResult:
    """환율 조회 결과 (다중 소스 통합)."""
    best_rate: float            # 최적 환율
    best_source: str            # 최적 소스
    confidence: float           # 종합 신뢰도
    
    all_rates: list[FxRate] = field(default_factory=list)
    spread: float = 0.0         # 소스 간 스프레드 (%)
    
    # 암시적 환율 (참고용)
    btc_implied: Optional[float] = None
    eth_implied: Optional[float] = None
    implied_premium: float = 0.0  # 정프 (%)
    
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def is_reliable(self) -> bool:
        """신뢰 가능 여부."""
        return self.confidence >= 0.85 and self.spread < 1.0
    
    @property
    def confidence_label(self) -> str:
        """신뢰도 라벨."""
        if self.confidence >= 0.95:
            return "EXCELLENT"
        elif self.confidence >= 0.85:
            return "GOOD"
        elif self.confidence >= 0.70:
            return "FAIR"
        else:
            return "POOR"


# 소스별 가중치
SOURCE_WEIGHTS = {
    'upbit_direct': 1.0,
    'bithumb_direct': 0.95,
    'btc_implied': 0.7,    # 김프 포함 가능성
    'eth_implied': 0.65,
    'external_api': 0.5,
    'fallback': 0.3,
}

# 캐시
_cache: dict = {}
_cache_ttl = 30  # 30초


async def _get_upbit_direct() -> Optional[FxRate]:
    """업비트 USDT/KRW 직접 조회."""
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.upbit.com/v1/ticker?markets=KRW-USDT"
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and len(data) > 0:
                        rate = float(data[0].get('trade_price', 0))
                        if rate > 0:
                            return FxRate(
                                rate=rate,
                                source='upbit_direct',
                                source_type='direct',
                                confidence=1.0,
                                raw_data=data[0],
                            )
    except Exception as e:
        logger.warning(f"업비트 환율 조회 실패: {e}")
    return None


async def _get_bithumb_direct() -> Optional[FxRate]:
    """빗썸 USDT/KRW 직접 조회."""
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.bithumb.com/public/ticker/USDT_KRW"
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('status') == '0000':
                        rate = float(data.get('data', {}).get('closing_price', 0))
                        if rate > 0:
                            return FxRate(
                                rate=rate,
                                source='bithumb_direct',
                                source_type='direct',
                                confidence=0.95,
                                raw_data=data.get('data', {}),
                            )
    except Exception as e:
        logger.warning(f"빗썸 환율 조회 실패: {e}")
    return None


async def _get_btc_implied() -> Optional[FxRate]:
    """BTC 암시적 환율 (업비트 BTC/KRW ÷ 바이낸스 BTC/USDT)."""
    try:
        async with aiohttp.ClientSession() as session:
            # 업비트 BTC/KRW
            upbit_url = "https://api.upbit.com/v1/ticker?markets=KRW-BTC"
            async with session.get(upbit_url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                upbit_data = await resp.json()
                upbit_btc = float(upbit_data[0].get('trade_price', 0))
            
            # 바이낸스 BTC/USDT
            binance_url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
            async with session.get(binance_url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                binance_data = await resp.json()
                binance_btc = float(binance_data.get('price', 0))
            
            if upbit_btc > 0 and binance_btc > 0:
                rate = upbit_btc / binance_btc
                return FxRate(
                    rate=rate,
                    source='btc_implied',
                    source_type='implied',
                    confidence=0.8,
                    raw_data={'upbit_btc': upbit_btc, 'binance_btc': binance_btc},
                )
    except Exception as e:
        logger.warning(f"BTC 암시적 환율 실패: {e}")
    return None


async def _get_eth_implied() -> Optional[FxRate]:
    """ETH 암시적 환율 (업비트 ETH/KRW ÷ 바이낸스 ETH/USDT)."""
    try:
        async with aiohttp.ClientSession() as session:
            # 업비트 ETH/KRW
            upbit_url = "https://api.upbit.com/v1/ticker?markets=KRW-ETH"
            async with session.get(upbit_url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                upbit_data = await resp.json()
                upbit_eth = float(upbit_data[0].get('trade_price', 0))
            
            # 바이낸스 ETH/USDT
            binance_url = "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT"
            async with session.get(binance_url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                binance_data = await resp.json()
                binance_eth = float(binance_data.get('price', 0))
            
            if upbit_eth > 0 and binance_eth > 0:
                rate = upbit_eth / binance_eth
                return FxRate(
                    rate=rate,
                    source='eth_implied',
                    source_type='implied',
                    confidence=0.75,
                    raw_data={'upbit_eth': upbit_eth, 'binance_eth': binance_eth},
                )
    except Exception as e:
        logger.warning(f"ETH 암시적 환율 실패: {e}")
    return None


async def _get_external_api() -> Optional[FxRate]:
    """외부 API 환율 (ExchangeRate-API)."""
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.exchangerate-api.com/v4/latest/USD"
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rate = data.get('rates', {}).get('KRW')
                    if rate:
                        return FxRate(
                            rate=float(rate),
                            source='external_api',
                            source_type='external',
                            confidence=0.6,
                            raw_data=data,
                        )
    except Exception as e:
        logger.warning(f"외부 API 환율 실패: {e}")
    return None


def _get_fallback() -> FxRate:
    """Fallback 환율."""
    return FxRate(
        rate=1450.0,
        source='fallback',
        source_type='fallback',
        confidence=0.3,
        raw_data={'note': 'hardcoded fallback'},
    )


async def get_best_rate(use_cache: bool = True) -> FxRateResult:
    """최적 환율 조회 (다중 소스 통합).
    
    Args:
        use_cache: 캐시 사용 여부
        
    Returns:
        FxRateResult
    """
    global _cache
    
    # 캐시 확인
    if use_cache and 'result' in _cache:
        if time.time() - _cache.get('timestamp', 0) < _cache_ttl:
            return _cache['result']
    
    # 모든 소스 병렬 조회
    tasks = [
        _get_upbit_direct(),
        _get_bithumb_direct(),
        _get_btc_implied(),
        _get_eth_implied(),
        _get_external_api(),
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 유효한 결과만 필터링
    valid_rates = [r for r in results if isinstance(r, FxRate)]
    
    if not valid_rates:
        # Fallback 사용
        fallback = _get_fallback()
        return FxRateResult(
            best_rate=fallback.rate,
            best_source=fallback.source,
            confidence=fallback.confidence,
            all_rates=[fallback],
        )
    
    # 가중 평균 계산
    weighted_sum = 0.0
    weight_sum = 0.0
    
    for rate in valid_rates:
        weight = SOURCE_WEIGHTS.get(rate.source, 0.5)
        adjusted_weight = weight * rate.confidence
        weighted_sum += rate.rate * adjusted_weight
        weight_sum += adjusted_weight
    
    best_rate = weighted_sum / weight_sum if weight_sum > 0 else 1450.0
    
    # 스프레드 계산 (직접 소스만)
    direct_rates = [r.rate for r in valid_rates if r.source_type == 'direct']
    if len(direct_rates) >= 2:
        spread = (max(direct_rates) - min(direct_rates)) / min(direct_rates) * 100
    else:
        spread = 0.0
    
    # 신뢰도 계산
    direct_count = sum(1 for r in valid_rates if r.source_type == 'direct')
    confidence = min(1.0, 0.5 + direct_count * 0.25)
    
    # 가장 신뢰도 높은 소스
    best_source = max(valid_rates, key=lambda r: r.confidence).source
    
    # 암시적 환율 (정프 계산용)
    btc_implied = next((r.rate for r in valid_rates if 'btc' in r.source), None)
    eth_implied = next((r.rate for r in valid_rates if 'eth' in r.source), None)
    
    # 정프 계산 (암시적 vs 직접)
    implied_premium = 0.0
    direct_rate = next((r.rate for r in valid_rates if r.source_type == 'direct'), None)
    if btc_implied and direct_rate:
        implied_premium = (btc_implied - direct_rate) / direct_rate * 100
    
    result = FxRateResult(
        best_rate=best_rate,
        best_source=best_source,
        confidence=confidence,
        all_rates=valid_rates,
        spread=spread,
        btc_implied=btc_implied,
        eth_implied=eth_implied,
        implied_premium=implied_premium,
    )
    
    # 캐시 저장
    _cache['result'] = result
    _cache['timestamp'] = time.time()
    
    return result


def get_rate_sync() -> tuple[float, str, float]:
    """동기식 환율 조회 (간단한 사용).
    
    Returns:
        (환율, 소스, 신뢰도)
    """
    try:
        result = asyncio.run(get_best_rate())
        return (result.best_rate, result.best_source, result.confidence)
    except Exception:
        return (1450.0, 'fallback', 0.3)


def format_fx_report(result: FxRateResult) -> str:
    """환율 리포트 포맷."""
    lines = [
        f"환율: {result.best_rate:,.1f} KRW/USD",
        f"소스: {result.best_source}",
        f"신뢰도: {result.confidence_label} ({result.confidence:.0%})",
    ]
    
    if result.spread > 0:
        lines.append(f"스프레드: {result.spread:.2f}%")
    
    if result.implied_premium != 0:
        prem_sign = "+" if result.implied_premium > 0 else ""
        lines.append(f"정프: {prem_sign}{result.implied_premium:.2f}%")
    
    return "\n".join(lines)


# 테스트
if __name__ == "__main__":
    async def test():
        print("Testing FX Rate Service...")
        result = await get_best_rate()
        print(format_fx_report(result))
        print(f"\nAll rates: {len(result.all_rates)}")
        for r in result.all_rates:
            print(f"  {r.source}: {r.rate:,.1f} ({r.confidence_label})")
    
    asyncio.run(test())
