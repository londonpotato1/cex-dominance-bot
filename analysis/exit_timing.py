"""매도 타이밍 엔진 (Phase 8 Week 8).

Exit Trigger 자동 판단:
  1. 프리미엄 Threshold: 목표 갭 도달 시 매도
  2. 시간 제한: 최대 보유 시간 초과 시 청산
  3. 볼륨 스파이크: 거래량 급증 시 매도 (덤핑 직전)
  4. 프리미엄 역전: 역프 발생 시 긴급 청산
  5. 트레일링 스톱: 고점 대비 하락 시 청산

연동:
  - scenario.py: ScenarioCard → Exit Trigger 조건
  - post_listing.py: 후따리 진입 후 Exit Trigger
  - spot_futures_gap.py: 갭 변화 추적

알림:
  - Telegram 알림 콜백
  - 레벨별 긴급도 (INFO, WARNING, CRITICAL)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional, Protocol

logger = logging.getLogger(__name__)


class ExitTriggerType(Enum):
    """Exit Trigger 유형."""
    PREMIUM_TARGET = "premium_target"       # 목표 프리미엄 도달
    PREMIUM_FLOOR = "premium_floor"         # 프리미엄 하한선 도달
    TIME_LIMIT = "time_limit"               # 시간 제한 초과
    VOLUME_SPIKE = "volume_spike"           # 거래량 급증
    PREMIUM_REVERSAL = "premium_reversal"   # 역프 발생
    TRAILING_STOP = "trailing_stop"         # 트레일링 스톱
    MANUAL = "manual"                       # 수동 청산


class ExitUrgency(Enum):
    """Exit 긴급도."""
    CRITICAL = "critical"   # 즉시 청산 필요
    HIGH = "high"           # 빠른 청산 권장
    MEDIUM = "medium"       # 청산 고려
    LOW = "low"             # 참고용


@dataclass
class ExitTrigger:
    """Exit Trigger 조건."""
    trigger_type: ExitTriggerType
    urgency: ExitUrgency
    triggered: bool = False
    trigger_value: float = 0.0           # 트리거 기준값
    current_value: float = 0.0           # 현재값
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ExitDecision:
    """Exit 결정."""
    should_exit: bool
    urgency: ExitUrgency
    primary_trigger: ExitTrigger | None
    all_triggers: list[ExitTrigger]

    # 추천
    recommended_action: str              # "SELL_MARKET", "SELL_LIMIT", "HOLD", "WATCH"
    recommended_price: float | None      # 추천 매도가
    expected_profit_pct: float           # 예상 수익률

    # 설명
    headline: str = ""
    factors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Position:
    """포지션 정보."""
    symbol: str
    exchange: str
    entry_time: datetime
    entry_price_krw: float
    entry_premium_pct: float
    quantity: float
    current_price_krw: float = 0.0
    current_premium_pct: float = 0.0
    peak_price_krw: float = 0.0
    peak_premium_pct: float = 0.0


@dataclass
class ExitConfig:
    """Exit 설정."""
    # 프리미엄 조건
    target_premium_pct: float = 8.0      # 목표 프리미엄 (%)
    floor_premium_pct: float = 2.0       # 프리미엄 하한 (%)
    reversal_threshold_pct: float = -1.0 # 역프 임계값 (%)

    # 시간 조건
    max_hold_minutes: int = 30           # 최대 보유 시간 (분)
    urgent_exit_minutes: int = 60        # 긴급 청산 시간 (분)

    # 볼륨 조건
    volume_spike_ratio: float = 3.0      # 거래량 급증 비율

    # 트레일링 스톱
    trailing_stop_pct: float = 30.0      # 고점 대비 하락률 (%)

    # 비용
    total_cost_pct: float = 1.5          # 총 비용 (수수료+슬리피지)


class ExitAlertCallback(Protocol):
    """Exit 알림 콜백."""
    async def __call__(self, decision: ExitDecision, position: Position) -> None:
        ...


class ExitTimingEngine:
    """매도 타이밍 엔진.

    포지션 상태를 모니터링하고 Exit Trigger 조건을 체크.

    사용법:
        engine = ExitTimingEngine(config=ExitConfig())
        decision = engine.evaluate(
            position=my_position,
            current_volume=current_5m_volume,
            avg_volume=avg_5m_volume,
        )
        if decision.should_exit:
            print(f"EXIT: {decision.headline}")
    """

    def __init__(
        self,
        config: ExitConfig | None = None,
        alert_callback: ExitAlertCallback | None = None,
    ) -> None:
        """
        Args:
            config: Exit 설정.
            alert_callback: 알림 콜백.
        """
        self._config = config or ExitConfig()
        self._alert_callback = alert_callback

    def evaluate(
        self,
        position: Position,
        current_volume: float = 0.0,
        avg_volume: float = 0.0,
        now: datetime | None = None,
    ) -> ExitDecision:
        """Exit 조건 평가.

        Args:
            position: 포지션 정보.
            current_volume: 현재 5분 거래량.
            avg_volume: 평균 5분 거래량.
            now: 현재 시간 (None이면 datetime.now()).

        Returns:
            ExitDecision.
        """
        if now is None:
            now = datetime.now()

        triggers: list[ExitTrigger] = []

        # 1. 프리미엄 목표 도달
        trigger = self._check_premium_target(position)
        triggers.append(trigger)

        # 2. 프리미엄 하한선
        trigger = self._check_premium_floor(position)
        triggers.append(trigger)

        # 3. 시간 제한
        trigger = self._check_time_limit(position, now)
        triggers.append(trigger)

        # 4. 볼륨 스파이크
        trigger = self._check_volume_spike(current_volume, avg_volume)
        triggers.append(trigger)

        # 5. 프리미엄 역전
        trigger = self._check_premium_reversal(position)
        triggers.append(trigger)

        # 6. 트레일링 스톱
        trigger = self._check_trailing_stop(position)
        triggers.append(trigger)

        # 트리거된 것들 필터
        triggered = [t for t in triggers if t.triggered]

        # 가장 긴급한 트리거 선택
        primary_trigger = None
        if triggered:
            triggered.sort(key=lambda t: (
                t.urgency == ExitUrgency.CRITICAL,
                t.urgency == ExitUrgency.HIGH,
                t.urgency == ExitUrgency.MEDIUM,
            ), reverse=True)
            primary_trigger = triggered[0]

        # Exit 결정
        should_exit = len(triggered) > 0
        urgency = primary_trigger.urgency if primary_trigger else ExitUrgency.LOW

        # 추천 행동 및 가격
        action, price = self._recommend_action(position, primary_trigger, urgency)

        # 예상 수익률
        expected_profit = self._calculate_expected_profit(position, price)

        # 설명 생성
        headline, factors, warnings = self._generate_explanation(
            position, triggered, should_exit, urgency, now,
        )

        return ExitDecision(
            should_exit=should_exit,
            urgency=urgency,
            primary_trigger=primary_trigger,
            all_triggers=triggers,
            recommended_action=action,
            recommended_price=price,
            expected_profit_pct=expected_profit,
            headline=headline,
            factors=factors,
            warnings=warnings,
        )

    def _check_premium_target(self, position: Position) -> ExitTrigger:
        """프리미엄 목표 도달 체크."""
        target = self._config.target_premium_pct
        current = position.current_premium_pct

        triggered = current >= target
        urgency = ExitUrgency.MEDIUM if triggered else ExitUrgency.LOW

        return ExitTrigger(
            trigger_type=ExitTriggerType.PREMIUM_TARGET,
            urgency=urgency,
            triggered=triggered,
            trigger_value=target,
            current_value=current,
            message=f"목표 프리미엄 도달: {current:.1f}% >= {target:.1f}%",
        )

    def _check_premium_floor(self, position: Position) -> ExitTrigger:
        """프리미엄 하한선 체크."""
        floor = self._config.floor_premium_pct
        current = position.current_premium_pct

        triggered = current <= floor
        urgency = ExitUrgency.HIGH if triggered else ExitUrgency.LOW

        return ExitTrigger(
            trigger_type=ExitTriggerType.PREMIUM_FLOOR,
            urgency=urgency,
            triggered=triggered,
            trigger_value=floor,
            current_value=current,
            message=f"프리미엄 하한 도달: {current:.1f}% <= {floor:.1f}%",
        )

    def _check_time_limit(self, position: Position, now: datetime) -> ExitTrigger:
        """시간 제한 체크."""
        max_minutes = self._config.max_hold_minutes
        elapsed = (now - position.entry_time).total_seconds() / 60

        triggered = elapsed >= max_minutes
        urgent = elapsed >= self._config.urgent_exit_minutes

        if urgent:
            urgency = ExitUrgency.CRITICAL
        elif triggered:
            urgency = ExitUrgency.HIGH
        else:
            urgency = ExitUrgency.LOW

        return ExitTrigger(
            trigger_type=ExitTriggerType.TIME_LIMIT,
            urgency=urgency,
            triggered=triggered,
            trigger_value=max_minutes,
            current_value=elapsed,
            message=f"보유 시간 초과: {elapsed:.0f}분 >= {max_minutes}분",
        )

    def _check_volume_spike(
        self, current_volume: float, avg_volume: float,
    ) -> ExitTrigger:
        """볼륨 스파이크 체크."""
        if avg_volume <= 0:
            return ExitTrigger(
                trigger_type=ExitTriggerType.VOLUME_SPIKE,
                urgency=ExitUrgency.LOW,
                triggered=False,
                message="거래량 데이터 없음",
            )

        ratio = current_volume / avg_volume
        threshold = self._config.volume_spike_ratio

        triggered = ratio >= threshold
        urgency = ExitUrgency.HIGH if triggered else ExitUrgency.LOW

        return ExitTrigger(
            trigger_type=ExitTriggerType.VOLUME_SPIKE,
            urgency=urgency,
            triggered=triggered,
            trigger_value=threshold,
            current_value=ratio,
            message=f"거래량 급증: {ratio:.1f}x >= {threshold:.1f}x",
        )

    def _check_premium_reversal(self, position: Position) -> ExitTrigger:
        """프리미엄 역전 (역프) 체크."""
        threshold = self._config.reversal_threshold_pct
        current = position.current_premium_pct

        triggered = current <= threshold
        urgency = ExitUrgency.CRITICAL if triggered else ExitUrgency.LOW

        return ExitTrigger(
            trigger_type=ExitTriggerType.PREMIUM_REVERSAL,
            urgency=urgency,
            triggered=triggered,
            trigger_value=threshold,
            current_value=current,
            message=f"역프리미엄 발생: {current:.1f}% <= {threshold:.1f}%",
        )

    def _check_trailing_stop(self, position: Position) -> ExitTrigger:
        """트레일링 스톱 체크."""
        threshold = self._config.trailing_stop_pct
        peak = position.peak_premium_pct
        current = position.current_premium_pct

        if peak <= 0:
            return ExitTrigger(
                trigger_type=ExitTriggerType.TRAILING_STOP,
                urgency=ExitUrgency.LOW,
                triggered=False,
                message="고점 데이터 없음",
            )

        drop_pct = ((peak - current) / peak) * 100
        triggered = drop_pct >= threshold

        urgency = ExitUrgency.HIGH if triggered else ExitUrgency.LOW

        return ExitTrigger(
            trigger_type=ExitTriggerType.TRAILING_STOP,
            urgency=urgency,
            triggered=triggered,
            trigger_value=threshold,
            current_value=drop_pct,
            message=f"트레일링 스톱: 고점 대비 -{drop_pct:.1f}% >= -{threshold:.1f}%",
        )

    def _recommend_action(
        self,
        position: Position,
        primary_trigger: ExitTrigger | None,
        urgency: ExitUrgency,
    ) -> tuple[str, float | None]:
        """추천 행동 및 가격."""
        if not primary_trigger:
            return "HOLD", None

        current_price = position.current_price_krw

        if urgency == ExitUrgency.CRITICAL:
            # 긴급: 시장가 매도
            return "SELL_MARKET", current_price * 0.995
        elif urgency == ExitUrgency.HIGH:
            # 높음: 현재가 근처 지정가
            return "SELL_LIMIT", current_price * 0.998
        elif urgency == ExitUrgency.MEDIUM:
            # 중간: 목표가 도달 시 매도
            return "SELL_LIMIT", current_price
        else:
            return "WATCH", None

    def _calculate_expected_profit(
        self, position: Position, exit_price: float | None,
    ) -> float:
        """예상 수익률 계산."""
        if exit_price is None or position.entry_price_krw <= 0:
            return 0.0

        gross_profit = ((exit_price - position.entry_price_krw) / position.entry_price_krw) * 100
        net_profit = gross_profit - self._config.total_cost_pct
        return net_profit

    def _generate_explanation(
        self,
        position: Position,
        triggered: list[ExitTrigger],
        should_exit: bool,
        urgency: ExitUrgency,
        now: datetime,
    ) -> tuple[str, list[str], list[str]]:
        """설명 생성."""
        factors = []
        warnings = []

        for trigger in triggered:
            if trigger.urgency == ExitUrgency.CRITICAL:
                factors.append(f"🚨 {trigger.message}")
            elif trigger.urgency == ExitUrgency.HIGH:
                factors.append(f"⚠️ {trigger.message}")
            else:
                factors.append(f"ℹ️ {trigger.message}")

        # 헤드라인
        if urgency == ExitUrgency.CRITICAL:
            headline = f"🚨 긴급 청산 필요: {position.symbol}"
        elif urgency == ExitUrgency.HIGH:
            headline = f"⚠️ 청산 권장: {position.symbol}"
        elif should_exit:
            headline = f"📊 청산 고려: {position.symbol}"
        else:
            headline = f"✅ 보유 유지: {position.symbol}"

        # 경고
        if position.current_premium_pct < 3:
            warnings.append(f"⚠️ 프리미엄 낮음: {position.current_premium_pct:.1f}%")

        elapsed = (now - position.entry_time).total_seconds() / 60
        if elapsed > 20:
            warnings.append(f"⏰ 장기 보유 중: {elapsed:.0f}분")

        return headline, factors, warnings

    async def evaluate_and_alert(
        self,
        position: Position,
        current_volume: float = 0.0,
        avg_volume: float = 0.0,
    ) -> ExitDecision:
        """평가 후 알림 전송."""
        decision = self.evaluate(position, current_volume, avg_volume)

        if self._alert_callback and decision.should_exit:
            await self._alert_callback(decision, position)

        return decision


def format_exit_alert(
    decision: ExitDecision,
    position: Position,
    now: datetime | None = None,
) -> str:
    """Exit 결정을 Telegram 메시지로 포맷."""
    if now is None:
        now = datetime.now()

    # 긴급도 이모지
    urgency_emoji = {
        ExitUrgency.CRITICAL: "🚨",
        ExitUrgency.HIGH: "⚠️",
        ExitUrgency.MEDIUM: "📊",
        ExitUrgency.LOW: "ℹ️",
    }
    emoji = urgency_emoji.get(decision.urgency, "❓")

    # 경과 시간
    elapsed = (now - position.entry_time).total_seconds() / 60

    lines = [
        f"{emoji} **Exit Signal: {position.symbol}@{position.exchange}**",
        "━━━━━━━━━━━━━━━",
        f"📈 진입: ₩{position.entry_price_krw:,.0f} ({position.entry_premium_pct:.1f}%)",
        f"📊 현재: ₩{position.current_price_krw:,.0f} ({position.current_premium_pct:.1f}%)",
        f"🏔️ 고점: ₩{position.peak_price_krw:,.0f} ({position.peak_premium_pct:.1f}%)",
        f"⏱️ 경과: {elapsed:.0f}분",
        "━━━━━━━━━━━━━━━",
    ]

    # 트리거 정보
    if decision.primary_trigger:
        lines.append(f"🎯 트리거: {decision.primary_trigger.trigger_type.value}")
        lines.append(f"📝 {decision.primary_trigger.message}")

    # 추천 행동
    lines.append("")
    lines.append(f"💡 추천: {decision.recommended_action}")
    if decision.recommended_price:
        lines.append(f"💰 추천가: ₩{decision.recommended_price:,.0f}")
    lines.append(f"📈 예상 수익: {decision.expected_profit_pct:+.1f}%")

    # 요인
    if decision.factors:
        lines.append("")
        lines.extend(decision.factors)

    # 경고
    if decision.warnings:
        lines.append("")
        lines.extend(decision.warnings)

    return "\n".join(lines)


# 편의 함수
def create_position_from_entry(
    symbol: str,
    exchange: str,
    entry_price_krw: float,
    entry_premium_pct: float,
    quantity: float,
    entry_time: datetime | None = None,
) -> Position:
    """진입 정보로 Position 생성."""
    if entry_time is None:
        entry_time = datetime.now()

    return Position(
        symbol=symbol,
        exchange=exchange,
        entry_time=entry_time,
        entry_price_krw=entry_price_krw,
        entry_premium_pct=entry_premium_pct,
        quantity=quantity,
        current_price_krw=entry_price_krw,
        current_premium_pct=entry_premium_pct,
        peak_price_krw=entry_price_krw,
        peak_premium_pct=entry_premium_pct,
    )


def update_position(
    position: Position,
    current_price_krw: float,
    current_premium_pct: float,
) -> Position:
    """Position 업데이트 (immutable)."""
    return Position(
        symbol=position.symbol,
        exchange=position.exchange,
        entry_time=position.entry_time,
        entry_price_krw=position.entry_price_krw,
        entry_premium_pct=position.entry_premium_pct,
        quantity=position.quantity,
        current_price_krw=current_price_krw,
        current_premium_pct=current_premium_pct,
        peak_price_krw=max(position.peak_price_krw, current_price_krw),
        peak_premium_pct=max(position.peak_premium_pct, current_premium_pct),
    )
