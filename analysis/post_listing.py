"""후따리 분석기 (Phase 8 Week 7).

후따리 = 상장 후 2차 펌핑 기회

분석 요소:
  1. 초기 덤핑 후 반등 패턴
  2. 거래량 패턴 (고점 대비 감소 후 재증가)
  3. 프리미엄 수렴 후 재확대
  4. 시간 경과에 따른 기회 감소

진입 조건:
  - 상장 후 30분~2시간 경과
  - 초기 고점 대비 40%+ 하락
  - 거래량 고점 대비 70%+ 감소
  - 프리미엄 역전 없음 (아직 양수)

Exit 조건:
  - 프리미엄 재확대 (입장 대비 +50%)
  - 거래량 재급증 (2배 이상)
  - 최대 보유 시간 초과 (2시간)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class PostListingPhase(Enum):
    """상장 후 단계."""
    INITIAL_PUMP = "initial_pump"       # 0-10분: 초기 펌핑
    FIRST_DUMP = "first_dump"           # 10-30분: 첫 덤핑 (에어드랍 매도)
    CONSOLIDATION = "consolidation"     # 30분-2시간: 횡보/수렴
    SECOND_PUMP = "second_pump"         # 2차 펌핑 가능 구간
    FADE_OUT = "fade_out"               # 2시간+: 기회 감소


class PostListingSignal(Enum):
    """후따리 시그널."""
    STRONG_BUY = "strong_buy"           # 강력 매수 (모든 조건 충족)
    BUY = "buy"                         # 매수 (대부분 조건 충족)
    HOLD = "hold"                       # 관망 (조건 미충족)
    AVOID = "avoid"                     # 회피 (역프 또는 위험)


@dataclass
class PriceSnapshot:
    """가격 스냅샷."""
    timestamp: datetime
    price_krw: float
    price_usd: float
    premium_pct: float
    volume_5m_krw: float      # 5분 거래량


@dataclass
class PostListingMetrics:
    """후따리 분석 지표."""
    symbol: str
    exchange: str

    # 시간 정보
    listing_time: datetime
    current_time: datetime
    elapsed_minutes: float
    current_phase: PostListingPhase

    # 가격 정보
    initial_price_krw: float           # 상장 초기 가격
    peak_price_krw: float              # 최고가
    current_price_krw: float           # 현재가
    trough_price_krw: float            # 최저가 (덤핑 후)

    # 프리미엄
    initial_premium: float             # 초기 프리미엄 (%)
    peak_premium: float                # 최고 프리미엄 (%)
    current_premium: float             # 현재 프리미엄 (%)
    premium_from_peak: float           # 고점 대비 프리미엄 변화

    # 거래량
    peak_volume_5m: float              # 5분 최고 거래량
    current_volume_5m: float           # 현재 5분 거래량
    volume_ratio: float                # 거래량 비율 (현재/고점)

    # 하락폭
    drawdown_from_peak: float          # 고점 대비 하락률 (%)
    recovery_from_trough: float        # 저점 대비 회복률 (%)


@dataclass
class PostListingAnalysis:
    """후따리 분석 결과."""
    metrics: PostListingMetrics
    signal: PostListingSignal
    confidence: float                  # 신뢰도 (0.0 ~ 1.0)

    # 점수 세부
    time_score: float                  # 시간 점수 (30분-2시간이 최적)
    price_score: float                 # 가격 점수 (적정 하락 후)
    volume_score: float                # 거래량 점수 (감소 후)
    premium_score: float               # 프리미엄 점수 (아직 양수)

    # 추천
    entry_price_krw: Optional[float] = None    # 추천 진입가
    target_price_krw: Optional[float] = None   # 목표가
    stop_loss_krw: Optional[float] = None      # 손절가

    # 설명
    headline: str = ""
    factors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PostListingAnalyzer:
    """후따리 분석기.

    상장 후 2차 펌핑 기회를 분석.

    사용법:
        analyzer = PostListingAnalyzer()
        result = analyzer.analyze(
            symbol="XYZ",
            exchange="bithumb",
            listing_time=datetime(2026, 1, 30, 10, 0),
            snapshots=price_history,
        )
    """

    # 기본값 상수 (참조용 - 실제 값은 __init__에서 설정)
    _DEFAULT_OPTIMAL_TIME = (30, 120)
    _DEFAULT_MIN_DRAWDOWN = 30.0
    _DEFAULT_VOLUME_COOLDOWN = 0.3

    def __init__(
        self,
        optimal_time_range: tuple[int, int] = (30, 120),
        min_drawdown: float = 30.0,
        max_drawdown: float = 70.0,
        volume_cooldown: float = 0.3,
        min_premium: float = 0.0,
    ) -> None:
        """
        Args:
            optimal_time_range: 최적 진입 시간 범위 (분).
            min_drawdown: 최소 하락률 (%).
            max_drawdown: 최대 하락률 (과매도).
            volume_cooldown: 거래량 감소 기준.
            min_premium: 최소 프리미엄 (역프 방지).
        """
        self.OPTIMAL_TIME_MIN, self.OPTIMAL_TIME_MAX = optimal_time_range
        self.MIN_DRAWDOWN_PCT = min_drawdown
        self.MAX_DRAWDOWN_PCT = max_drawdown
        self.VOLUME_COOLDOWN_RATIO = volume_cooldown
        self.MIN_PREMIUM_PCT = min_premium

    def analyze(
        self,
        symbol: str,
        exchange: str,
        listing_time: datetime,
        snapshots: list[PriceSnapshot],
        current_time: Optional[datetime] = None,
    ) -> PostListingAnalysis:
        """후따리 분석 실행.

        Args:
            symbol: 토큰 심볼.
            exchange: 거래소 ID.
            listing_time: 상장 시간.
            snapshots: 가격 스냅샷 히스토리.
            current_time: 현재 시간 (None이면 now).

        Returns:
            PostListingAnalysis 결과.
        """
        if current_time is None:
            current_time = datetime.now()

        # 지표 계산
        metrics = self._calculate_metrics(
            symbol, exchange, listing_time, snapshots, current_time,
        )

        # 점수 계산
        time_score = self._score_time(metrics)
        price_score = self._score_price(metrics)
        volume_score = self._score_volume(metrics)
        premium_score = self._score_premium(metrics)

        # 종합 점수 (가중 평균)
        total_score = (
            time_score * 0.2 +
            price_score * 0.3 +
            volume_score * 0.2 +
            premium_score * 0.3
        )

        # 시그널 결정
        signal, confidence = self._determine_signal(
            total_score, metrics, time_score, price_score, volume_score, premium_score,
        )

        # 가격 추천
        entry_price, target_price, stop_loss = self._calculate_prices(
            metrics, signal,
        )

        # 설명 생성
        headline, factors, warnings = self._generate_explanation(
            metrics, signal, time_score, price_score, volume_score, premium_score,
        )

        return PostListingAnalysis(
            metrics=metrics,
            signal=signal,
            confidence=confidence,
            time_score=time_score,
            price_score=price_score,
            volume_score=volume_score,
            premium_score=premium_score,
            entry_price_krw=entry_price,
            target_price_krw=target_price,
            stop_loss_krw=stop_loss,
            headline=headline,
            factors=factors,
            warnings=warnings,
        )

    def _calculate_metrics(
        self,
        symbol: str,
        exchange: str,
        listing_time: datetime,
        snapshots: list[PriceSnapshot],
        current_time: datetime,
    ) -> PostListingMetrics:
        """지표 계산."""
        if not snapshots:
            # 빈 스냅샷 → 기본값
            return PostListingMetrics(
                symbol=symbol,
                exchange=exchange,
                listing_time=listing_time,
                current_time=current_time,
                elapsed_minutes=0,
                current_phase=PostListingPhase.INITIAL_PUMP,
                initial_price_krw=0,
                peak_price_krw=0,
                current_price_krw=0,
                trough_price_krw=0,
                initial_premium=0,
                peak_premium=0,
                current_premium=0,
                premium_from_peak=0,
                peak_volume_5m=0,
                current_volume_5m=0,
                volume_ratio=0,
                drawdown_from_peak=0,
                recovery_from_trough=0,
            )

        elapsed = (current_time - listing_time).total_seconds() / 60

        # 가격 통계
        prices = [s.price_krw for s in snapshots]
        premiums = [s.premium_pct for s in snapshots]
        volumes = [s.volume_5m_krw for s in snapshots]

        initial_price = prices[0] if prices else 0
        peak_price = max(prices) if prices else 0
        current_price = prices[-1] if prices else 0
        trough_price = min(prices) if prices else 0

        initial_premium = premiums[0] if premiums else 0
        peak_premium = max(premiums) if premiums else 0
        current_premium = premiums[-1] if premiums else 0

        peak_volume = max(volumes) if volumes else 0
        current_volume = volumes[-1] if volumes else 0

        # 비율 계산
        drawdown = ((peak_price - current_price) / peak_price * 100) if peak_price > 0 else 0
        recovery = ((current_price - trough_price) / trough_price * 100) if trough_price > 0 else 0
        volume_ratio = (current_volume / peak_volume) if peak_volume > 0 else 0
        premium_from_peak = current_premium - peak_premium

        # 단계 결정
        phase = self._determine_phase(elapsed)

        return PostListingMetrics(
            symbol=symbol,
            exchange=exchange,
            listing_time=listing_time,
            current_time=current_time,
            elapsed_minutes=elapsed,
            current_phase=phase,
            initial_price_krw=initial_price,
            peak_price_krw=peak_price,
            current_price_krw=current_price,
            trough_price_krw=trough_price,
            initial_premium=initial_premium,
            peak_premium=peak_premium,
            current_premium=current_premium,
            premium_from_peak=premium_from_peak,
            peak_volume_5m=peak_volume,
            current_volume_5m=current_volume,
            volume_ratio=volume_ratio,
            drawdown_from_peak=drawdown,
            recovery_from_trough=recovery,
        )

    def _determine_phase(self, elapsed_minutes: float) -> PostListingPhase:
        """현재 단계 결정."""
        if elapsed_minutes < 10:
            return PostListingPhase.INITIAL_PUMP
        elif elapsed_minutes < 30:
            return PostListingPhase.FIRST_DUMP
        elif elapsed_minutes < 120:
            return PostListingPhase.CONSOLIDATION
        elif elapsed_minutes < 180:
            return PostListingPhase.SECOND_PUMP
        else:
            return PostListingPhase.FADE_OUT

    def _score_time(self, metrics: PostListingMetrics) -> float:
        """시간 점수 계산 (0.0 ~ 1.0)."""
        elapsed = metrics.elapsed_minutes

        # 너무 이름 (< 30분): 점수 낮음
        if elapsed < self.OPTIMAL_TIME_MIN:
            return elapsed / self.OPTIMAL_TIME_MIN * 0.5

        # 최적 구간 (30분 ~ 2시간): 높은 점수
        if elapsed <= self.OPTIMAL_TIME_MAX:
            # 45분~90분이 최적
            if 45 <= elapsed <= 90:
                return 1.0
            elif elapsed < 45:
                return 0.7 + (elapsed - 30) / 15 * 0.3
            else:
                return 1.0 - (elapsed - 90) / 30 * 0.3

        # 늦음 (> 2시간): 점수 감소
        if elapsed <= 180:
            return 0.5 - (elapsed - 120) / 60 * 0.3

        return 0.2  # 3시간 이후

    def _score_price(self, metrics: PostListingMetrics) -> float:
        """가격 점수 계산."""
        drawdown = metrics.drawdown_from_peak

        # 아직 하락 안 함: 점수 낮음
        if drawdown < 20:
            return 0.2

        # 적정 하락 (30-50%): 높은 점수
        if 30 <= drawdown <= 50:
            return 1.0

        # 약간 하락 (20-30%): 중간
        if 20 <= drawdown < 30:
            return 0.5 + (drawdown - 20) / 10 * 0.5

        # 과매도 (50-70%): 위험하지만 기회
        if 50 < drawdown <= 70:
            return 0.8 - (drawdown - 50) / 20 * 0.3

        # 극단적 하락 (> 70%): 회피
        return 0.3

    def _score_volume(self, metrics: PostListingMetrics) -> float:
        """거래량 점수 계산."""
        ratio = metrics.volume_ratio

        # 거래량 충분히 감소: 좋음
        if ratio <= 0.2:
            return 1.0
        elif ratio <= 0.3:
            return 0.8
        elif ratio <= 0.5:
            return 0.5
        elif ratio <= 0.7:
            return 0.3
        else:
            # 거래량 아직 높음: 덤핑 진행 중
            return 0.1

    def _score_premium(self, metrics: PostListingMetrics) -> float:
        """프리미엄 점수 계산."""
        premium = metrics.current_premium

        # 역프: 회피
        if premium < 0:
            return 0.0

        # 프리미엄 거의 없음: 낮은 점수
        if premium < 2:
            return 0.2

        # 적정 프리미엄 (2-8%): 좋음
        if 2 <= premium <= 8:
            return 0.7 + (premium - 2) / 6 * 0.3

        # 높은 프리미엄 (> 8%): 매우 좋음
        return 1.0

    def _determine_signal(
        self,
        total_score: float,
        metrics: PostListingMetrics,
        time_score: float,
        price_score: float,
        volume_score: float,
        premium_score: float,
    ) -> tuple[PostListingSignal, float]:
        """시그널 결정."""
        # 역프면 무조건 AVOID
        if metrics.current_premium < 0:
            return PostListingSignal.AVOID, 0.9

        # 너무 이르거나 늦으면 HOLD
        if time_score < 0.3:
            return PostListingSignal.HOLD, 0.6

        # 점수 기반 결정
        if total_score >= 0.8:
            return PostListingSignal.STRONG_BUY, min(total_score, 0.95)
        elif total_score >= 0.6:
            return PostListingSignal.BUY, total_score
        elif total_score >= 0.4:
            return PostListingSignal.HOLD, 0.5
        else:
            return PostListingSignal.AVOID, 0.7

    def _calculate_prices(
        self,
        metrics: PostListingMetrics,
        signal: PostListingSignal,
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """가격 추천 계산."""
        if signal in (PostListingSignal.HOLD, PostListingSignal.AVOID):
            return None, None, None

        current = metrics.current_price_krw
        peak = metrics.peak_price_krw
        trough = metrics.trough_price_krw

        # 진입가: 현재가 또는 약간 아래
        entry_price = current * 0.98

        # 목표가: 고점의 60-70% 회복
        target_price = trough + (peak - trough) * 0.65

        # 손절가: 저점 아래 5%
        stop_loss = trough * 0.95

        return entry_price, target_price, stop_loss

    def _generate_explanation(
        self,
        metrics: PostListingMetrics,
        signal: PostListingSignal,
        time_score: float,
        price_score: float,
        volume_score: float,
        premium_score: float,
    ) -> tuple[str, list[str], list[str]]:
        """설명 생성."""
        factors = []
        warnings = []

        # 시간 요인
        if time_score >= 0.7:
            factors.append(f"✅ 최적 진입 시간대 ({metrics.elapsed_minutes:.0f}분 경과)")
        elif time_score >= 0.4:
            factors.append(f"⏰ 진입 가능 시간대 ({metrics.elapsed_minutes:.0f}분 경과)")
        else:
            warnings.append(f"⚠️ 시간 조건 미충족 ({metrics.elapsed_minutes:.0f}분)")

        # 가격 요인
        if price_score >= 0.7:
            factors.append(f"✅ 적정 하락 후 진입점 (고점 대비 -{metrics.drawdown_from_peak:.1f}%)")
        elif metrics.drawdown_from_peak < 20:
            warnings.append(f"⚠️ 아직 충분히 하락 안함 (-{metrics.drawdown_from_peak:.1f}%)")
        elif metrics.drawdown_from_peak > 60:
            warnings.append(f"⚠️ 과도한 하락 주의 (-{metrics.drawdown_from_peak:.1f}%)")

        # 거래량 요인
        if volume_score >= 0.7:
            factors.append(f"✅ 거래량 감소 (고점 대비 {metrics.volume_ratio*100:.0f}%)")
        else:
            warnings.append(f"⚠️ 거래량 아직 높음 ({metrics.volume_ratio*100:.0f}%)")

        # 프리미엄 요인
        if premium_score >= 0.7:
            factors.append(f"✅ 프리미엄 유지 ({metrics.current_premium:.1f}%)")
        elif metrics.current_premium < 0:
            warnings.append(f"🚨 역프리미엄 ({metrics.current_premium:.1f}%)")
        else:
            warnings.append(f"⚠️ 프리미엄 낮음 ({metrics.current_premium:.1f}%)")

        # 헤드라인
        if signal == PostListingSignal.STRONG_BUY:
            headline = f"🚀 후따리 강력 매수 시그널 ({metrics.symbol})"
        elif signal == PostListingSignal.BUY:
            headline = f"📈 후따리 매수 시그널 ({metrics.symbol})"
        elif signal == PostListingSignal.HOLD:
            headline = f"⏳ 후따리 관망 ({metrics.symbol})"
        else:
            headline = f"❌ 후따리 회피 ({metrics.symbol})"

        return headline, factors, warnings


def format_post_listing_alert(analysis: PostListingAnalysis) -> str:
    """후따리 분석 결과를 Telegram 메시지로 포맷."""
    m = analysis.metrics

    # 시그널 이모지
    signal_emoji = {
        PostListingSignal.STRONG_BUY: "🚀",
        PostListingSignal.BUY: "📈",
        PostListingSignal.HOLD: "⏳",
        PostListingSignal.AVOID: "❌",
    }
    emoji = signal_emoji.get(analysis.signal, "❓")

    # 점수 바
    def score_bar(score: float) -> str:
        filled = int(score * 5)
        return "█" * filled + "░" * (5 - filled)

    lines = [
        f"{emoji} **후따리 분석: {m.symbol}@{m.exchange}**",
        "━━━━━━━━━━━━━━━",
        f"⏱️ 경과: {m.elapsed_minutes:.0f}분 ({m.current_phase.value})",
        f"📉 하락: -{m.drawdown_from_peak:.1f}% (고점 대비)",
        f"📊 프리미엄: {m.current_premium:.1f}%",
        f"📈 거래량: {m.volume_ratio*100:.0f}% (고점 대비)",
        "━━━━━━━━━━━━━━━",
        f"⏰ 시간: {score_bar(analysis.time_score)} {analysis.time_score:.0%}",
        f"💰 가격: {score_bar(analysis.price_score)} {analysis.price_score:.0%}",
        f"📊 거래량: {score_bar(analysis.volume_score)} {analysis.volume_score:.0%}",
        f"📈 프리미엄: {score_bar(analysis.premium_score)} {analysis.premium_score:.0%}",
        "━━━━━━━━━━━━━━━",
        f"🎯 신뢰도: {analysis.confidence:.0%}",
    ]

    # 가격 추천
    if analysis.entry_price_krw:
        lines.extend([
            "",
            f"📍 진입가: ₩{analysis.entry_price_krw:,.0f}",
            f"🎯 목표가: ₩{analysis.target_price_krw:,.0f}",
            f"🛑 손절가: ₩{analysis.stop_loss_krw:,.0f}",
        ])

    # 요인
    if analysis.factors:
        lines.append("")
        lines.extend(analysis.factors)

    # 경고
    if analysis.warnings:
        lines.append("")
        lines.extend(analysis.warnings)

    return "\n".join(lines)
