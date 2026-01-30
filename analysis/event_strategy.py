"""이벤트 기반 자동 트레이딩 전략 (Phase 7a).

공지사항 이벤트 감지 시 자동으로 트레이딩 전략을 제안/실행.
- WARNING: 출금 중단 → 매수 기회
- HALT: 거래 중단 → 재개 모니터링
- MIGRATION: 마이그레이션 → 스왑 기회
- DEPEG: 디페깅 → 안전 마진 체크
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import logging

from collectors.notice_parser import NoticeParseResult, EventAction, EventSeverity


logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """전략 유형."""
    BUY_OPPORTUNITY = "buy_opportunity"      # 매수 기회
    MONITOR_RESUME = "monitor_resume"        # 재개 모니터링
    SWAP_OPPORTUNITY = "swap_opportunity"    # 스왑 기회
    SAFETY_CHECK = "safety_check"            # 안전성 체크
    NO_ACTION = "no_action"                  # 조치 불필요


@dataclass
class StrategyRecommendation:
    """전략 추천 결과."""
    strategy_type: StrategyType
    symbol: str
    exchange: str
    event_type: str                          # "warning", "halt", "migration", "depeg"
    severity: EventSeverity
    action: EventAction

    # 전략 파라미터
    recommended_action: str                  # "BUY", "SELL", "HOLD", "MONITOR"
    target_price: Optional[float] = None     # 목표 진입가
    stop_loss: Optional[float] = None        # 손절가
    take_profit: Optional[float] = None      # 익절가
    position_size: Optional[float] = None    # 포지션 크기

    # 리스크 관리
    risk_level: str = "medium"               # "low", "medium", "high", "critical"
    max_hold_time: Optional[int] = None      # 최대 보유 시간 (분)

    # 추가 정보
    reason: str = ""                         # 전략 사유
    expected_roi: Optional[float] = None     # 예상 수익률 (%)
    confidence: float = 0.5                  # 신뢰도 (0.0 ~ 1.0)

    # 알림 설정
    alert_telegram: bool = True              # 텔레그램 알림
    alert_sound: bool = False                # 소리 알림

    # 메타데이터
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_notice: Optional[NoticeParseResult] = None


class EventStrategyExecutor:
    """이벤트 기반 전략 실행기.

    공지사항 이벤트를 분석하여 적절한 트레이딩 전략을 제안.
    """

    def __init__(
        self,
        premium_calculator=None,
        cost_model=None,
        enable_auto_trade: bool = False,
    ):
        """
        Args:
            premium_calculator: PremiumCalculator 인스턴스 (프리미엄 계산)
            cost_model: CostModel 인스턴스 (비용 계산)
            enable_auto_trade: True면 자동 주문 실행, False면 추천만
        """
        self._premium = premium_calculator
        self._cost_model = cost_model
        self._enable_auto_trade = enable_auto_trade

        # 이벤트 히스토리 (메모리 캐시)
        self._event_history: list[StrategyRecommendation] = []
        self._max_history = 1000

    async def process_event(
        self, notice_result: NoticeParseResult
    ) -> Optional[StrategyRecommendation]:
        """이벤트 처리 및 전략 생성.

        Args:
            notice_result: 공지 파싱 결과

        Returns:
            StrategyRecommendation 또는 None (조치 불필요 시)
        """
        if notice_result.event_action == EventAction.NONE:
            logger.debug("[EventStrategy] 조치 불필요: %s", notice_result.notice_type)
            return None

        # 이벤트 유형별 전략 생성
        if notice_result.notice_type == "warning":
            return await self._handle_warning_event(notice_result)
        elif notice_result.notice_type == "halt":
            return await self._handle_halt_event(notice_result)
        elif notice_result.notice_type == "migration":
            return await self._handle_migration_event(notice_result)
        elif notice_result.notice_type == "depeg":
            return await self._handle_depeg_event(notice_result)
        else:
            logger.warning("[EventStrategy] 알 수 없는 이벤트: %s", notice_result.notice_type)
            return None

    async def _handle_warning_event(
        self, notice: NoticeParseResult
    ) -> Optional[StrategyRecommendation]:
        """WARNING 이벤트 처리 (출금 중단).

        출금 중단 → 프리미엄 상승 예상 → 매수 기회
        """
        if not notice.symbols:
            logger.warning("[EventStrategy] WARNING 이벤트지만 심볼 없음")
            return None

        symbol = notice.symbols[0]
        exchange = notice.exchange

        # "출금" 키워드 있으면 매수 기회
        if "출금" in notice.raw_title:
            recommendation = StrategyRecommendation(
                strategy_type=StrategyType.BUY_OPPORTUNITY,
                symbol=symbol,
                exchange=exchange,
                event_type="warning",
                severity=notice.event_severity,
                action=notice.event_action,
                recommended_action="BUY",
                risk_level="medium",
                max_hold_time=180,  # 3시간
                reason=f"출금 중단으로 {exchange} 프리미엄 상승 예상",
                expected_roi=2.5,  # 평균 2.5% 상승 기대
                confidence=0.7,
                alert_telegram=True,
                raw_notice=notice,
            )

            # 프리미엄 계산 가능하면 추가
            if self._premium:
                try:
                    premium_result = await self._premium.calculate_premium(
                        symbol=symbol, exchange=exchange
                    )
                    if premium_result:
                        recommendation.expected_roi = premium_result.premium_pct + 2.0
                        recommendation.confidence = 0.8
                except Exception as e:
                    logger.debug("[EventStrategy] 프리미엄 계산 실패: %s", e)

            self._add_to_history(recommendation)
            return recommendation

        # 입금 중단은 모니터링만
        else:
            recommendation = StrategyRecommendation(
                strategy_type=StrategyType.NO_ACTION,
                symbol=symbol,
                exchange=exchange,
                event_type="warning",
                severity=notice.event_severity,
                action=EventAction.MONITOR,
                recommended_action="MONITOR",
                risk_level="low",
                reason=f"{exchange} 입금 중단 안내 (출금은 정상)",
                confidence=0.5,
                alert_telegram=True,
                raw_notice=notice,
            )
            self._add_to_history(recommendation)
            return recommendation

    async def _handle_halt_event(
        self, notice: NoticeParseResult
    ) -> Optional[StrategyRecommendation]:
        """HALT 이벤트 처리 (거래 중단).

        거래 중단 → 재개 시 변동성 급증 → 모니터링
        """
        if not notice.symbols:
            return None

        symbol = notice.symbols[0]
        exchange = notice.exchange

        recommendation = StrategyRecommendation(
            strategy_type=StrategyType.MONITOR_RESUME,
            symbol=symbol,
            exchange=exchange,
            event_type="halt",
            severity=notice.event_severity,
            action=notice.event_action,
            recommended_action="MONITOR",
            risk_level="high",
            reason=f"{exchange} {symbol} 거래 중단. 재개 시 급변동 예상",
            expected_roi=None,  # 예측 불가
            confidence=0.6,
            alert_telegram=True,
            alert_sound=True,  # 긴급 알림
            raw_notice=notice,
        )

        self._add_to_history(recommendation)
        return recommendation

    async def _handle_migration_event(
        self, notice: NoticeParseResult
    ) -> Optional[StrategyRecommendation]:
        """MIGRATION 이벤트 처리 (마이그레이션/스왑).

        토큰 전환 → 구버전 할인 매수 → 신버전 스왑
        """
        if not notice.symbols:
            return None

        symbol = notice.symbols[0]
        exchange = notice.exchange

        recommendation = StrategyRecommendation(
            strategy_type=StrategyType.SWAP_OPPORTUNITY,
            symbol=symbol,
            exchange=exchange,
            event_type="migration",
            severity=notice.event_severity,
            action=notice.event_action,
            recommended_action="HOLD",  # 기존 보유자는 HOLD
            risk_level="low",
            reason=f"{symbol} 마이그레이션. 구버전 할인 매수 후 스왑 가능",
            expected_roi=1.5,  # 평균 1.5% 차익
            confidence=0.6,
            max_hold_time=10080,  # 7일
            alert_telegram=True,
            raw_notice=notice,
        )

        self._add_to_history(recommendation)
        return recommendation

    async def _handle_depeg_event(
        self, notice: NoticeParseResult
    ) -> Optional[StrategyRecommendation]:
        """DEPEG 이벤트 처리 (디페깅).

        가격 급락 → 안전성 체크 → 저가 매수 또는 회피
        """
        if not notice.symbols:
            return None

        symbol = notice.symbols[0]
        exchange = notice.exchange

        # 스테이블코인 디페깅은 매우 위험
        is_stablecoin = symbol in {"USDT", "USDC", "DAI", "BUSD", "UST"}

        if is_stablecoin:
            recommendation = StrategyRecommendation(
                strategy_type=StrategyType.SAFETY_CHECK,
                symbol=symbol,
                exchange=exchange,
                event_type="depeg",
                severity=EventSeverity.CRITICAL,
                action=EventAction.ALERT,
                recommended_action="SELL",  # 스테이블코인 디페깅은 청산
                risk_level="critical",
                reason=f"{symbol} 디페깅 감지. 즉시 청산 권장",
                expected_roi=-5.0,  # 손실 예상
                confidence=0.9,
                alert_telegram=True,
                alert_sound=True,
                raw_notice=notice,
            )
        else:
            # 일반 코인 급락은 매수 기회일 수도
            recommendation = StrategyRecommendation(
                strategy_type=StrategyType.BUY_OPPORTUNITY,
                symbol=symbol,
                exchange=exchange,
                event_type="depeg",
                severity=notice.event_severity,
                action=notice.event_action,
                recommended_action="BUY",  # 저가 매수
                risk_level="high",
                reason=f"{symbol} 가격 급락. 저가 매수 기회 (고위험)",
                expected_roi=5.0,  # 반등 시 5% 기대
                confidence=0.4,  # 낮은 신뢰도
                max_hold_time=60,  # 1시간
                stop_loss=-10.0,  # 10% 손절
                take_profit=5.0,   # 5% 익절
                alert_telegram=True,
                raw_notice=notice,
            )

        self._add_to_history(recommendation)
        return recommendation

    def _add_to_history(self, recommendation: StrategyRecommendation) -> None:
        """히스토리에 추가 (메모리 관리)."""
        self._event_history.append(recommendation)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

    def get_recent_events(self, limit: int = 10) -> list[StrategyRecommendation]:
        """최근 이벤트 조회."""
        return self._event_history[-limit:]

    def get_events_by_symbol(self, symbol: str) -> list[StrategyRecommendation]:
        """특정 심볼 이벤트 조회."""
        return [e for e in self._event_history if e.symbol == symbol]

    def clear_history(self) -> None:
        """히스토리 초기화."""
        self._event_history.clear()
        logger.info("[EventStrategy] 이벤트 히스토리 초기화")


def format_strategy_alert(recommendation: StrategyRecommendation) -> str:
    """전략 추천을 텔레그램 알림 형식으로 포맷.

    Args:
        recommendation: 전략 추천 결과

    Returns:
        포맷된 알림 메시지
    """
    severity_emoji = {
        EventSeverity.LOW: "ℹ️",
        EventSeverity.MEDIUM: "⚠️",
        EventSeverity.HIGH: "🔴",
        EventSeverity.CRITICAL: "🚨",
    }

    action_emoji = {
        "BUY": "💰",
        "SELL": "💸",
        "HOLD": "🤝",
        "MONITOR": "👀",
    }

    emoji = severity_emoji.get(recommendation.severity, "📌")
    action_icon = action_emoji.get(recommendation.recommended_action, "📊")

    lines = [
        f"{emoji} **이벤트 전략 알림**",
        f"━━━━━━━━━━━━━━━",
        f"{action_icon} **조치**: {recommendation.recommended_action}",
        f"🪙 **심볼**: {recommendation.symbol}",
        f"🏢 **거래소**: {recommendation.exchange}",
        f"📋 **이벤트**: {recommendation.event_type.upper()}",
        f"⚡ **심각도**: {recommendation.severity.value}",
        f"",
        f"💡 **사유**:",
        f"{recommendation.reason}",
    ]

    if recommendation.expected_roi is not None:
        lines.append(f"📈 **예상 수익**: {recommendation.expected_roi:+.1f}%")

    if recommendation.max_hold_time:
        hours = recommendation.max_hold_time // 60
        minutes = recommendation.max_hold_time % 60
        if hours > 0:
            lines.append(f"⏰ **최대 보유**: {hours}시간 {minutes}분")
        else:
            lines.append(f"⏰ **최대 보유**: {minutes}분")

    if recommendation.stop_loss:
        lines.append(f"🛑 **손절**: {recommendation.stop_loss:+.1f}%")

    if recommendation.take_profit:
        lines.append(f"🎯 **익절**: {recommendation.take_profit:+.1f}%")

    lines.extend([
        f"",
        f"🎲 **신뢰도**: {recommendation.confidence:.0%}",
        f"⚠️ **리스크**: {recommendation.risk_level}",
        f"━━━━━━━━━━━━━━━",
    ])

    return "\n".join(lines)
