#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
갭 계산 서비스

기능:
- 현선갭 계산 (현물 vs 선물)
- 선선갭 계산 (선물 vs 선물)
- 오더북 기반 프리미엄 계산 (실제 체결 가능 가격)
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict
from collectors.exchange_service import PriceData, OrderbookData


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


@dataclass
class OrderbookGapResult:
    """오더북 기반 프리미엄 계산 결과 (실제 체결 가능 가격)
    
    일반 GapResult와 달리 특정 금액에 대한 가중평균 체결가 기반
    슬리피지가 반영된 실제 프리미엄 표시
    """
    buy_exchange: str       # 매수 거래소 (해외)
    sell_exchange: str      # 매도 거래소 (국내)
    symbol: str
    amount_usd: float       # 분석 기준 금액
    buy_price: float        # 매수 가중평균가 (Ask 소진)
    sell_price: float       # 매도 가중평균가 (Bid 소진)
    premium_percent: float  # 프리미엄 (%)
    premium_absolute: float # 프리미엄 (절대값)
    condition: GapCondition
    # 슬리피지 정보
    buy_slippage: float     # 매수 슬리피지 (%) - mid price 대비
    sell_slippage: float    # 매도 슬리피지 (%) - mid price 대비
    total_slippage: float   # 총 슬리피지 (%)
    # 손익 정보
    net_premium: float      # 순 프리미엄 (슬리피지 차감)
    estimated_pnl_usd: float # 예상 손익 (USD)
    # 오더북 상세
    buy_depth_usd: float    # 매수측 호가 깊이 (USD)
    sell_depth_usd: float   # 매도측 호가 깊이 (USD)
    buy_spread: float       # 매수 거래소 스프레드 (%)
    sell_spread: float      # 매도 거래소 스프레드 (%)
    timestamp: float = 0
    
    @property
    def is_executable(self) -> bool:
        """실행 가능 여부 (호가 깊이 충분)"""
        return self.buy_depth_usd >= self.amount_usd and self.sell_depth_usd >= self.amount_usd
    
    @property
    def quality_score(self) -> int:
        """품질 점수 (0-100)
        
        - 프리미엄 높을수록 +
        - 슬리피지 낮을수록 +
        - 호가 깊이 깊을수록 +
        """
        score = 50  # 기본
        
        # 프리미엄 점수 (0-30)
        if self.net_premium > 5:
            score += 30
        elif self.net_premium > 3:
            score += 20
        elif self.net_premium > 1:
            score += 10
        elif self.net_premium > 0:
            score += 5
        elif self.net_premium < -1:
            score -= 20
        
        # 슬리피지 점수 (0-20)
        if self.total_slippage < 0.1:
            score += 20
        elif self.total_slippage < 0.3:
            score += 15
        elif self.total_slippage < 0.5:
            score += 10
        elif self.total_slippage > 1:
            score -= 10
        
        # 호가 깊이 점수 (0-20)
        depth_ratio = min(self.buy_depth_usd, self.sell_depth_usd) / self.amount_usd
        if depth_ratio > 10:
            score += 20
        elif depth_ratio > 5:
            score += 15
        elif depth_ratio > 2:
            score += 10
        elif depth_ratio < 1:
            score -= 10
        
        return max(0, min(100, score))


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

    # =========================================================================
    # 오더북 기반 프리미엄 계산 (실제 체결 가능 가격)
    # =========================================================================

    @staticmethod
    def calculate_orderbook_gap(
        buy_orderbook: OrderbookData,
        sell_orderbook: OrderbookData,
        amount_usd: float = 10000,
        symbol: str = ""
    ) -> Optional[OrderbookGapResult]:
        """오더북 기반 프리미엄 계산
        
        해외에서 매수 (Ask 소진) → 국내에서 매도 (Bid 소진)
        
        Args:
            buy_orderbook: 매수 거래소 오더북 (해외)
            sell_orderbook: 매도 거래소 오더북 (국내)
            amount_usd: 거래 금액 (USD)
            symbol: 심볼
            
        Returns:
            OrderbookGapResult 또는 None
        """
        if not buy_orderbook or not sell_orderbook:
            return None
        
        # 매수 가중평균가 (Ask 소진)
        buy_price = buy_orderbook.get_executable_buy_price(amount_usd)
        if not buy_price:
            return None
        
        # 매도 가중평균가 (Bid 소진)
        sell_price = sell_orderbook.get_executable_sell_price(amount_usd)
        if not sell_price:
            return None
        
        # 프리미엄 계산
        premium_absolute = sell_price - buy_price
        premium_percent = (premium_absolute / buy_price) * 100
        
        # 상태 판단
        if abs(premium_percent) < GapCalculator.NEUTRAL_THRESHOLD:
            condition = GapCondition.NEUTRAL
        elif premium_percent > 0:
            condition = GapCondition.PREMIUM
        else:
            condition = GapCondition.DISCOUNT
        
        # 슬리피지 계산 (mid price 대비)
        buy_mid = buy_orderbook.mid_price or buy_price
        sell_mid = sell_orderbook.mid_price or sell_price
        
        buy_slippage = ((buy_price - buy_mid) / buy_mid) * 100 if buy_mid > 0 else 0
        sell_slippage = ((sell_mid - sell_price) / sell_mid) * 100 if sell_mid > 0 else 0
        total_slippage = buy_slippage + sell_slippage
        
        # 순 프리미엄 (슬리피지 차감)
        net_premium = premium_percent - total_slippage
        
        # 예상 손익
        estimated_pnl_usd = amount_usd * (net_premium / 100)
        
        # 호가 깊이 계산
        buy_depth = sum(p * q for p, q in buy_orderbook.asks[:20]) if buy_orderbook.asks else 0
        sell_depth = sum(p * q for p, q in sell_orderbook.bids[:20]) if sell_orderbook.bids else 0
        
        import time
        return OrderbookGapResult(
            buy_exchange=buy_orderbook.exchange,
            sell_exchange=sell_orderbook.exchange,
            symbol=symbol or buy_orderbook.symbol,
            amount_usd=amount_usd,
            buy_price=buy_price,
            sell_price=sell_price,
            premium_percent=premium_percent,
            premium_absolute=premium_absolute,
            condition=condition,
            buy_slippage=buy_slippage,
            sell_slippage=sell_slippage,
            total_slippage=total_slippage,
            net_premium=net_premium,
            estimated_pnl_usd=estimated_pnl_usd,
            buy_depth_usd=buy_depth,
            sell_depth_usd=sell_depth,
            buy_spread=buy_orderbook.spread_percent or 0,
            sell_spread=sell_orderbook.spread_percent or 0,
            timestamp=time.time()
        )

    @staticmethod
    def calculate_all_orderbook_gaps(
        orderbooks: Dict[str, Dict[str, OrderbookData]],
        symbol: str,
        amount_usd: float = 10000,
        buy_exchanges: Optional[List[str]] = None,
        sell_exchanges: Optional[List[str]] = None
    ) -> List[OrderbookGapResult]:
        """모든 거래소 조합의 오더북 기반 프리미엄 계산
        
        Args:
            orderbooks: {'spot': {exchange: OrderbookData}, 'futures': {...}}
            symbol: 심볼
            amount_usd: 거래 금액
            buy_exchanges: 매수 거래소 목록 (해외, 기본: 모든 비-KRW 거래소)
            sell_exchanges: 매도 거래소 목록 (국내, 기본: upbit, bithumb)
            
        Returns:
            OrderbookGapResult 리스트 (프리미엄 순 정렬)
        """
        results = []
        spot_orderbooks = orderbooks.get('spot', {})
        
        # 기본값: 국내 = upbit, bithumb / 해외 = 나머지
        if sell_exchanges is None:
            sell_exchanges = ['upbit', 'bithumb']
        if buy_exchanges is None:
            buy_exchanges = [ex for ex in spot_orderbooks.keys() if ex not in sell_exchanges]
        
        for buy_ex in buy_exchanges:
            buy_ob = spot_orderbooks.get(buy_ex)
            if not buy_ob:
                continue
                
            for sell_ex in sell_exchanges:
                sell_ob = spot_orderbooks.get(sell_ex)
                if not sell_ob:
                    continue
                
                result = GapCalculator.calculate_orderbook_gap(
                    buy_orderbook=buy_ob,
                    sell_orderbook=sell_ob,
                    amount_usd=amount_usd,
                    symbol=symbol
                )
                if result:
                    results.append(result)
        
        # 순 프리미엄 순으로 정렬 (내림차순)
        results.sort(key=lambda x: x.net_premium, reverse=True)
        
        return results

    @staticmethod
    def get_best_orderbook_opportunities(
        results: List[OrderbookGapResult],
        min_net_premium: float = 0.5,
        limit: int = 5
    ) -> List[OrderbookGapResult]:
        """최적의 오더북 기회 필터링
        
        Args:
            results: OrderbookGapResult 리스트
            min_net_premium: 최소 순 프리미엄 (%)
            limit: 최대 결과 수
        """
        filtered = [r for r in results if r.net_premium >= min_net_premium and r.is_executable]
        return filtered[:limit]


# 싱글톤 인스턴스
gap_calculator = GapCalculator()
