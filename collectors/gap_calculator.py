#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
갭 계산 서비스
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict
from collectors.exchange_service import PriceData


class GapCondition(Enum):
    """갭 상태"""
    PREMIUM = "premium"      # 선물 > 현물
    DISCOUNT = "discount"    # 선물 < 현물
    NEUTRAL = "neutral"      # 거의 같음


@dataclass
class GapResult:
    """갭 계산 결과 (현선갭)"""
    spot_exchange: str
    futures_exchange: str
    symbol: str
    spot_price: float
    futures_price: float
    gap_percent: float
    gap_absolute: float
    condition: GapCondition
    funding_rate: Optional[float] = None
    timestamp: float = 0
    spot_krw_price: Optional[float] = None  # 현물 원화 가격 (업비트/빗썸용)


@dataclass
class FuturesGapResult:
    """선선갭 계산 결과 (선물 vs 선물)"""
    exchange_a: str
    exchange_b: str
    symbol: str
    price_a: float
    price_b: float
    gap_percent: float
    gap_absolute: float
    condition: GapCondition
    funding_rate_a: Optional[float] = None
    funding_rate_b: Optional[float] = None
    funding_diff: Optional[float] = None  # 펀딩비 차이
    timestamp: float = 0
    next_funding_time_a: Optional[float] = None  # A 거래소 다음 펀딩 시간
    next_funding_time_b: Optional[float] = None  # B 거래소 다음 펀딩 시간


class GapCalculator:
    """갭 계산기"""

    NEUTRAL_THRESHOLD = 0.1  # 0.1% 이하면 중립

    @staticmethod
    def calculate(
        spot_price: float,
        futures_price: float,
        spot_exchange: str = "",
        futures_exchange: str = "",
        symbol: str = "",
        funding_rate: Optional[float] = None,
        spot_krw_price: Optional[float] = None
    ) -> Optional[GapResult]:
        """
        갭 계산

        갭 공식: (선물가격 - 현물가격) / 현물가격 * 100

        - 양수: 선물이 더 비쌈 (Premium)
        - 음수: 선물이 더 쌈 (Discount)
        """
        if spot_price <= 0 or futures_price <= 0:
            return None

        gap_absolute = futures_price - spot_price
        gap_percent = (gap_absolute / spot_price) * 100

        # 상태 판단
        if abs(gap_percent) < GapCalculator.NEUTRAL_THRESHOLD:
            condition = GapCondition.NEUTRAL
        elif gap_percent > 0:
            condition = GapCondition.PREMIUM
        else:
            condition = GapCondition.DISCOUNT

        import time
        return GapResult(
            spot_exchange=spot_exchange,
            futures_exchange=futures_exchange,
            symbol=symbol,
            spot_price=spot_price,
            futures_price=futures_price,
            gap_percent=gap_percent,
            gap_absolute=gap_absolute,
            condition=condition,
            funding_rate=funding_rate,
            timestamp=time.time(),
            spot_krw_price=spot_krw_price
        )

    @staticmethod
    def calculate_all_gaps(
        prices: Dict[str, Dict[str, PriceData]],
        symbol: str,
        allowed_spot: Optional[List[str]] = None,
        allowed_futures: Optional[List[str]] = None
    ) -> List[GapResult]:
        """모든 거래소 조합의 갭 계산

        Args:
            prices: 가격 데이터
            symbol: 심볼
            allowed_spot: 허용된 현물 거래소 (None이면 모든 거래소)
            allowed_futures: 허용된 선물 거래소 (None이면 모든 거래소)
        """
        results = []

        spot_prices = prices.get('spot', {})
        futures_prices = prices.get('futures', {})

        # 허용된 거래소만 필터링
        if allowed_spot is not None:
            spot_prices = {k: v for k, v in spot_prices.items() if k in allowed_spot}
        if allowed_futures is not None:
            futures_prices = {k: v for k, v in futures_prices.items() if k in allowed_futures}

        for futures_ex, futures_data in futures_prices.items():
            for spot_ex, spot_data in spot_prices.items():
                result = GapCalculator.calculate(
                    spot_price=spot_data.price,
                    futures_price=futures_data.price,
                    spot_exchange=spot_ex,
                    futures_exchange=futures_ex,
                    symbol=symbol,
                    funding_rate=futures_data.funding_rate,
                    spot_krw_price=spot_data.krw_price
                )
                if result:
                    results.append(result)

        # 갭 크기 순으로 정렬 (절대값 기준 내림차순)
        results.sort(key=lambda x: abs(x.gap_percent), reverse=True)

        return results

    @staticmethod
    def get_color_for_gap(gap_percent: float) -> str:
        """갭에 따른 색상 반환"""
        if abs(gap_percent) < GapCalculator.NEUTRAL_THRESHOLD:
            return "#8892a0"  # 중립 (회색)
        elif gap_percent > 0:
            return "#00d4aa"  # 프리미엄 (민트)
        else:
            return "#ff6b6b"  # 디스카운트 (빨강)

    @staticmethod
    def get_best_opportunities(
        results: List[GapResult],
        min_gap: float = 0.3,
        limit: int = 5
    ) -> List[GapResult]:
        """최적의 기회 필터링"""
        filtered = [r for r in results if abs(r.gap_percent) >= min_gap]
        return filtered[:limit]

    @staticmethod
    def calculate_futures_gap(
        price_a: float,
        price_b: float,
        exchange_a: str = "",
        exchange_b: str = "",
        symbol: str = "",
        funding_rate_a: Optional[float] = None,
        funding_rate_b: Optional[float] = None,
        next_funding_time_a: Optional[float] = None,
        next_funding_time_b: Optional[float] = None
    ) -> Optional[FuturesGapResult]:
        """
        선선갭 계산 (선물 vs 선물)

        갭 공식: (거래소B_가격 - 거래소A_가격) / 거래소A_가격 * 100

        - 양수: 거래소B가 더 비쌈
        - 음수: 거래소B가 더 쌈
        """
        if price_a <= 0 or price_b <= 0:
            return None

        gap_absolute = price_b - price_a
        gap_percent = (gap_absolute / price_a) * 100

        # 상태 판단
        if abs(gap_percent) < GapCalculator.NEUTRAL_THRESHOLD:
            condition = GapCondition.NEUTRAL
        elif gap_percent > 0:
            condition = GapCondition.PREMIUM
        else:
            condition = GapCondition.DISCOUNT

        # 펀딩비 차이 계산
        funding_diff = None
        if funding_rate_a is not None and funding_rate_b is not None:
            funding_diff = funding_rate_b - funding_rate_a

        import time
        return FuturesGapResult(
            exchange_a=exchange_a,
            exchange_b=exchange_b,
            symbol=symbol,
            price_a=price_a,
            price_b=price_b,
            gap_percent=gap_percent,
            gap_absolute=gap_absolute,
            condition=condition,
            funding_rate_a=funding_rate_a,
            funding_rate_b=funding_rate_b,
            funding_diff=funding_diff,
            timestamp=time.time(),
            next_funding_time_a=next_funding_time_a,
            next_funding_time_b=next_funding_time_b
        )

    @staticmethod
    def calculate_all_futures_gaps(
        prices: Dict[str, Dict[str, PriceData]],
        symbol: str,
        allowed_exchanges: Optional[List[str]] = None
    ) -> List[FuturesGapResult]:
        """모든 선물 거래소 조합의 선선갭 계산

        Args:
            prices: 가격 데이터
            symbol: 심볼
            allowed_exchanges: 허용된 거래소 목록 (None이면 모든 거래소)
        """
        results = []
        futures_prices = prices.get('futures', {})

        # 허용된 거래소만 필터링
        if allowed_exchanges is not None:
            futures_prices = {k: v for k, v in futures_prices.items() if k in allowed_exchanges}

        # 모든 거래소 조합 (A vs B, A != B)
        exchanges = list(futures_prices.keys())
        for i, ex_a in enumerate(exchanges):
            for ex_b in exchanges[i+1:]:
                data_a = futures_prices[ex_a]
                data_b = futures_prices[ex_b]

                # A -> B 방향
                result = GapCalculator.calculate_futures_gap(
                    price_a=data_a.price,
                    price_b=data_b.price,
                    exchange_a=ex_a,
                    exchange_b=ex_b,
                    symbol=symbol,
                    funding_rate_a=data_a.funding_rate,
                    funding_rate_b=data_b.funding_rate,
                    next_funding_time_a=data_a.next_funding_time,
                    next_funding_time_b=data_b.next_funding_time
                )
                if result:
                    results.append(result)

                # B -> A 방향 (역방향)
                result_rev = GapCalculator.calculate_futures_gap(
                    price_a=data_b.price,
                    price_b=data_a.price,
                    exchange_a=ex_b,
                    exchange_b=ex_a,
                    symbol=symbol,
                    funding_rate_a=data_b.funding_rate,
                    funding_rate_b=data_a.funding_rate,
                    next_funding_time_a=data_b.next_funding_time,
                    next_funding_time_b=data_a.next_funding_time
                )
                if result_rev:
                    results.append(result_rev)

        # 갭 크기 순으로 정렬 (절대값 기준 내림차순)
        results.sort(key=lambda x: abs(x.gap_percent), reverse=True)

        return results

    @staticmethod
    def get_best_futures_opportunities(
        results: List[FuturesGapResult],
        min_gap: float = 0.2,
        limit: int = 5
    ) -> List[FuturesGapResult]:
        """최적의 선선갭 기회 필터링"""
        filtered = [r for r in results if abs(r.gap_percent) >= min_gap]
        return filtered[:limit]


# 싱글톤 인스턴스
gap_calculator = GapCalculator()
