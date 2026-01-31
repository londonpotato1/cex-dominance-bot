"""역프 아비트라지 전략 모듈.

역프(국내 < 해외) 상황에서의 전략:
- 일반 따리: 해외 매수 → 국내 매도 ❌ (손실)
- 역따리: 국내 매수 → 해외 매도 ✅ (수익)
         + 해외 선물 숏으로 가격 변동 헷징

사용 케이스:
1. 역프 발생 시 반대 방향 아비트라지
2. 국내 현물 + 해외 선물 숏 조합
3. 캐리 트레이드 (펀딩비 수익)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class ArbitrageDirection(Enum):
    """아비트라지 방향."""
    NORMAL = "normal"       # 해외 → 국내 (김프)
    REVERSE = "reverse"     # 국내 → 해외 (역프)
    NEUTRAL = "neutral"     # 중립 (기회 없음)


@dataclass
class ReverseArbOpportunity:
    """역프 아비트라지 기회."""
    symbol: str
    direction: ArbitrageDirection
    
    # 가격 정보
    kr_price: float         # 국내 현물가 (USD 환산)
    global_price: float     # 해외 현물가 (USD)
    futures_price: float    # 해외 선물가 (USD)
    
    # 프리미엄
    spot_premium: float     # 현물 프리미엄 (%) - 양수면 김프, 음수면 역프
    futures_gap: float      # 현선갭 (%) - 선물 vs 해외현물
    
    # 전략 수익
    strategy: str           # 추천 전략
    expected_profit: float  # 예상 수익 (%)
    hedge_cost: float       # 헷징 비용 (%) - 펀딩비 등
    net_profit: float       # 순 수익 (%)
    
    # 리스크
    risk_level: str         # LOW / MEDIUM / HIGH
    risk_factors: list[str]
    
    # 추천
    recommendation: str     # 추천 행동
    recommendation_emoji: str
    
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


def analyze_reverse_arb(
    symbol: str,
    kr_spot_price: float,
    global_spot_price: float,
    futures_price: float,
    funding_rate: float = 0.0,
    fee_percent: float = 0.2,  # 거래 수수료
    transfer_fee_percent: float = 0.05,  # 전송 수수료
) -> ReverseArbOpportunity:
    """역프 아비트라지 기회 분석.
    
    Args:
        symbol: 심볼
        kr_spot_price: 국내 현물가 (USD 환산)
        global_spot_price: 해외 현물가 (USD)
        futures_price: 해외 선물가 (USD)
        funding_rate: 현재 펀딩비 (%, 8시간당)
        fee_percent: 거래 수수료 (%)
        transfer_fee_percent: 전송 수수료 (%)
    
    Returns:
        ReverseArbOpportunity
    """
    # 프리미엄 계산
    spot_premium = (kr_spot_price - global_spot_price) / global_spot_price * 100
    futures_gap = (futures_price - global_spot_price) / global_spot_price * 100
    
    # 방향 판단
    if spot_premium > 1.0:
        direction = ArbitrageDirection.NORMAL  # 김프 → 일반 따리
    elif spot_premium < -1.0:
        direction = ArbitrageDirection.REVERSE  # 역프 → 역따리
    else:
        direction = ArbitrageDirection.NEUTRAL  # 중립
    
    # 전략 및 수익 계산
    if direction == ArbitrageDirection.NORMAL:
        # 일반 따리: 해외 매수 → 국내 매도
        strategy = "해외 현물 매수 → 국내 현물 매도"
        expected_profit = spot_premium
        hedge_cost = abs(futures_gap) if futures_gap < 0 else 0  # 선물 프리미엄이면 헷징 비용
        
    elif direction == ArbitrageDirection.REVERSE:
        # 역따리: 국내 매수 → 해외 매도 + 선물 숏 헷징
        strategy = "국내 현물 매수 → 해외 현물 매도 (+ 선물 숏 헷징)"
        expected_profit = abs(spot_premium)  # 역프 크기
        
        # 헷징 비용 = 현선갭 + 펀딩비 (숏 포지션)
        # 펀딩비가 양수면 숏이 받음 (수익), 음수면 숏이 지급 (비용)
        funding_daily = funding_rate * 3  # 하루 3번
        hedge_cost = futures_gap - funding_daily  # 선물이 비싸면 + 숏 진입 시 비용
        
    else:
        # 중립
        strategy = "대기 (기회 없음)"
        expected_profit = abs(spot_premium)
        hedge_cost = 0
    
    # 총 비용
    total_fee = fee_percent * 2 + transfer_fee_percent  # 매수 + 매도 + 전송
    
    # 순 수익
    net_profit = expected_profit - total_fee - max(0, hedge_cost)
    
    # 리스크 평가
    risk_factors = []
    
    if abs(spot_premium) < 2:
        risk_factors.append("프리미엄 낮음")
    
    if direction == ArbitrageDirection.REVERSE:
        risk_factors.append("역방향 전략 (복잡)")
        if funding_rate < -0.01:  # 음수 펀딩비
            risk_factors.append("숏 펀딩비 부담")
    
    if futures_gap > 5:
        risk_factors.append("현선갭 높음 (헷징 비용)")
    
    # 리스크 레벨
    if len(risk_factors) >= 3:
        risk_level = "HIGH"
    elif len(risk_factors) >= 1:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"
    
    # 추천
    if direction == ArbitrageDirection.NORMAL:
        if net_profit > 2:
            recommendation = "강력 추천"
            recommendation_emoji = "🟢🟢"
        elif net_profit > 0.5:
            recommendation = "추천"
            recommendation_emoji = "🟢"
        else:
            recommendation = "주의 필요"
            recommendation_emoji = "🟡"
            
    elif direction == ArbitrageDirection.REVERSE:
        if net_profit > 2:
            recommendation = "역따리 기회!"
            recommendation_emoji = "🔄🟢"
        elif net_profit > 0.5:
            recommendation = "역따리 고려"
            recommendation_emoji = "🔄"
        else:
            recommendation = "리스크 높음"
            recommendation_emoji = "⚠️"
    else:
        recommendation = "대기"
        recommendation_emoji = "⏸️"
    
    return ReverseArbOpportunity(
        symbol=symbol,
        direction=direction,
        kr_price=kr_spot_price,
        global_price=global_spot_price,
        futures_price=futures_price,
        spot_premium=spot_premium,
        futures_gap=futures_gap,
        strategy=strategy,
        expected_profit=expected_profit,
        hedge_cost=hedge_cost,
        net_profit=net_profit,
        risk_level=risk_level,
        risk_factors=risk_factors,
        recommendation=recommendation,
        recommendation_emoji=recommendation_emoji,
    )


def format_reverse_arb_report(opp: ReverseArbOpportunity) -> str:
    """역프 아비트라지 리포트 포맷."""
    
    if opp.direction == ArbitrageDirection.NORMAL:
        direction_text = "김프 (일반 따리)"
        direction_emoji = "📈"
    elif opp.direction == ArbitrageDirection.REVERSE:
        direction_text = "역프 (역따리 기회)"
        direction_emoji = "📉🔄"
    else:
        direction_text = "중립"
        direction_emoji = "➖"
    
    lines = [
        f"{opp.recommendation_emoji} {opp.symbol} 분석",
        f"",
        f"📊 상황: {direction_emoji} {direction_text}",
        f"├── 현물 프리미엄: {opp.spot_premium:+.2f}%",
        f"├── 현선갭: {opp.futures_gap:+.2f}%",
        f"",
        f"💡 추천 전략:",
        f"   {opp.strategy}",
        f"",
        f"💰 예상 수익:",
        f"├── 기대 수익: {opp.expected_profit:+.2f}%",
        f"├── 헷징 비용: {opp.hedge_cost:+.2f}%",
        f"└── 순 수익: {opp.net_profit:+.2f}%",
        f"",
        f"⚠️ 리스크: {opp.risk_level}",
    ]
    
    if opp.risk_factors:
        for factor in opp.risk_factors:
            lines.append(f"   • {factor}")
    
    lines.append(f"")
    lines.append(f"📝 결론: {opp.recommendation}")
    
    return "\n".join(lines)


def get_strategy_recommendation(spot_premium: float, futures_gap: float, funding_rate: float = 0) -> dict:
    """간단한 전략 추천 (UI용).
    
    Returns:
        {
            'direction': 'normal' | 'reverse' | 'neutral',
            'emoji': '🟢' | '🔄' | '🔴',
            'text': '추천 텍스트',
            'detail': '상세 설명'
        }
    """
    if spot_premium > 1.0:
        # 김프 상황
        if spot_premium > 5:
            return {
                'direction': 'normal',
                'emoji': '🟢🟢',
                'text': '강력 GO',
                'detail': f'김프 {spot_premium:+.1f}% - 해외 매수 → 국내 매도'
            }
        elif spot_premium > 2:
            return {
                'direction': 'normal',
                'emoji': '🟢',
                'text': 'GO',
                'detail': f'김프 {spot_premium:+.1f}% - 일반 따리'
            }
        else:
            return {
                'direction': 'normal',
                'emoji': '🟡',
                'text': 'CAUTION',
                'detail': f'김프 {spot_premium:+.1f}% - 소액만'
            }
            
    elif spot_premium < -1.0:
        # 역프 상황
        reverse_profit = abs(spot_premium)
        
        if reverse_profit > 3:
            return {
                'direction': 'reverse',
                'emoji': '🔄🟢',
                'text': '역따리 GO',
                'detail': f'역프 {spot_premium:+.1f}% - 국내 매수 → 해외 매도 + 숏 헷징'
            }
        elif reverse_profit > 1.5:
            return {
                'direction': 'reverse',
                'emoji': '🔄',
                'text': '역따리 가능',
                'detail': f'역프 {spot_premium:+.1f}% - 헷징 비용 고려 필요'
            }
        else:
            return {
                'direction': 'reverse',
                'emoji': '⚠️',
                'text': '역프 주의',
                'detail': f'역프 {spot_premium:+.1f}% - 수익 낮음, 대기 권장'
            }
    else:
        # 중립
        return {
            'direction': 'neutral',
            'emoji': '➖',
            'text': '중립',
            'detail': f'프리미엄 {spot_premium:+.1f}% - 기회 대기'
        }


# 테스트
if __name__ == "__main__":
    # 김프 상황 테스트
    print("=== 김프 상황 ===")
    opp1 = analyze_reverse_arb(
        symbol="BTC",
        kr_spot_price=105000,  # 국내 $105,000
        global_spot_price=100000,  # 해외 $100,000
        futures_price=100500,  # 선물 $100,500
        funding_rate=0.01,
    )
    print(format_reverse_arb_report(opp1))
    
    print("\n" + "="*50 + "\n")
    
    # 역프 상황 테스트
    print("=== 역프 상황 ===")
    opp2 = analyze_reverse_arb(
        symbol="ETH",
        kr_spot_price=3300,  # 국내 $3,300
        global_spot_price=3400,  # 해외 $3,400
        futures_price=3420,  # 선물 $3,420
        funding_rate=0.005,
    )
    print(format_reverse_arb_report(opp2))
