"""Premium Velocity Tracker - Phase 7 Quick Win #5.

실시간 프리미엄 변화율 추적 및 알림.

기능:
  - 1m/5m/15m 프리미엄 변화율 계산
  - 급격한 프리미엄 붕괴 감지 (>2% in 1min)
  - 급격한 프리미엄 확대 감지 (갭 확대)
  - Telegram 알림 통합

사용처:
  - collectors/market_monitor.py: 상장 직후 모니터링
  - collectors/aggregator.py: 실시간 프리미엄 추적
  - alerts/telegram.py: 자동 알림 발송

알림 조건:
  - 프리미엄 붕괴: 1분간 -2% 이상 하락
  - 프리미엄 급등: 1분간 +3% 이상 상승
  - 갭 수렴: 15분간 프리미엄 50% 이상 감소
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from alerts.telegram import TelegramAlert

logger = logging.getLogger(__name__)


class VelocityAlertType(Enum):
    """Velocity 알림 유형."""
    COLLAPSE = "collapse"      # 급락 (망따리 시그널)
    SURGE = "surge"            # 급등 (흥따리 강화)
    CONVERGENCE = "convergence"  # 갭 수렴 (청산 타이밍)
    STABLE = "stable"          # 안정 (정보성)


@dataclass
class PremiumSnapshot:
    """프리미엄 스냅샷."""
    timestamp: float
    premium_pct: float
    krw_price: float
    global_price: float


@dataclass
class VelocityResult:
    """Velocity 계산 결과."""
    symbol: str
    exchange: str
    current_premium: float

    # 변화율 (%p, percentage point)
    velocity_1m: Optional[float] = None  # 1분간 변화
    velocity_5m: Optional[float] = None  # 5분간 변화
    velocity_15m: Optional[float] = None  # 15분간 변화

    # 알림 판정
    alert_type: Optional[VelocityAlertType] = None
    alert_reason: str = ""

    # 메타데이터
    sample_count: int = 0  # 현재 샘플 개수
    tracking_duration_sec: float = 0.0  # 추적 시작 후 경과 시간


class PremiumVelocityTracker:
    """프리미엄 변화율 추적기.

    실시간으로 프리미엄 변화를 추적하고 급격한 변동 감지.

    사용법:
        tracker = PremiumVelocityTracker(
            symbol="BTC",
            exchange="upbit",
            alert=telegram_alert,
        )

        # 실시간 프리미엄 업데이트
        tracker.add_snapshot(premium_pct, krw_price, global_price)

        # Velocity 계산
        result = tracker.calculate_velocity()
        if result.alert_type:
            print(f"Alert: {result.alert_reason}")
    """

    # 알림 임계값
    _COLLAPSE_THRESHOLD_1M = -2.0  # 1분간 -2%p 이상 하락
    _SURGE_THRESHOLD_1M = 3.0      # 1분간 +3%p 이상 상승
    _CONVERGENCE_THRESHOLD_15M = 0.5  # 15분간 50% 이상 감소

    def __init__(
        self,
        symbol: str,
        exchange: str,
        alert: Optional[TelegramAlert] = None,
        window_size: int = 900,  # 15분 = 900초
    ) -> None:
        """
        Args:
            symbol: 토큰 심볼.
            exchange: 거래소.
            alert: Telegram 알림 (optional).
            window_size: 추적 윈도우 크기 (초).
        """
        self._symbol = symbol
        self._exchange = exchange
        self._alert = alert
        self._window_size = window_size

        # 스냅샷 히스토리 (시간 순 deque)
        self._snapshots: Deque[PremiumSnapshot] = deque()

        # 추적 시작 시각
        self._start_time = time.time()

        # 알림 발송 throttle (같은 타입 알림 60초 쿨다운)
        self._last_alert_time: dict[VelocityAlertType, float] = {}

    def add_snapshot(
        self,
        premium_pct: float,
        krw_price: float,
        global_price: float,
    ) -> None:
        """프리미엄 스냅샷 추가.

        Args:
            premium_pct: 현재 프리미엄 (%).
            krw_price: 국내 가격 (KRW).
            global_price: 글로벌 가격 (USD).
        """
        snapshot = PremiumSnapshot(
            timestamp=time.time(),
            premium_pct=premium_pct,
            krw_price=krw_price,
            global_price=global_price,
        )
        self._snapshots.append(snapshot)

        # 오래된 스냅샷 제거 (window_size 초과)
        cutoff = time.time() - self._window_size
        while self._snapshots and self._snapshots[0].timestamp < cutoff:
            self._snapshots.popleft()

        logger.debug(
            "[Velocity] %s@%s 스냅샷 추가: premium=%.2f%%, samples=%d",
            self._symbol, self._exchange, premium_pct, len(self._snapshots),
        )

    def calculate_velocity(self) -> VelocityResult:
        """Velocity 계산 및 알림 판정.

        Returns:
            VelocityResult.
        """
        if not self._snapshots:
            return VelocityResult(
                symbol=self._symbol,
                exchange=self._exchange,
                current_premium=0.0,
                alert_reason="스냅샷 없음",
            )

        current = self._snapshots[-1]
        current_time = current.timestamp

        # 1m/5m/15m 이전 스냅샷 찾기
        snap_1m = self._find_snapshot_at(current_time - 60)
        snap_5m = self._find_snapshot_at(current_time - 300)
        snap_15m = self._find_snapshot_at(current_time - 900)

        # 변화율 계산 (percentage point)
        velocity_1m = None
        velocity_5m = None
        velocity_15m = None

        if snap_1m:
            velocity_1m = current.premium_pct - snap_1m.premium_pct
        if snap_5m:
            velocity_5m = current.premium_pct - snap_5m.premium_pct
        if snap_15m:
            velocity_15m = current.premium_pct - snap_15m.premium_pct

        # 알림 판정
        alert_type = None
        alert_reason = ""

        if velocity_1m is not None:
            # 급락 감지
            if velocity_1m <= self._COLLAPSE_THRESHOLD_1M:
                alert_type = VelocityAlertType.COLLAPSE
                alert_reason = (
                    f"1분간 {velocity_1m:+.2f}%p 급락 "
                    f"({snap_1m.premium_pct:.2f}% → {current.premium_pct:.2f}%)"
                )

            # 급등 감지
            elif velocity_1m >= self._SURGE_THRESHOLD_1M:
                alert_type = VelocityAlertType.SURGE
                alert_reason = (
                    f"1분간 {velocity_1m:+.2f}%p 급등 "
                    f"({snap_1m.premium_pct:.2f}% → {current.premium_pct:.2f}%)"
                )

        # 갭 수렴 감지 (15분)
        if velocity_15m is not None and snap_15m.premium_pct > 5.0:
            convergence_ratio = abs(velocity_15m) / snap_15m.premium_pct
            if convergence_ratio >= self._CONVERGENCE_THRESHOLD_15M:
                alert_type = VelocityAlertType.CONVERGENCE
                alert_reason = (
                    f"15분간 프리미엄 {convergence_ratio*100:.0f}% 수렴 "
                    f"({snap_15m.premium_pct:.2f}% → {current.premium_pct:.2f}%)"
                )

        result = VelocityResult(
            symbol=self._symbol,
            exchange=self._exchange,
            current_premium=current.premium_pct,
            velocity_1m=velocity_1m,
            velocity_5m=velocity_5m,
            velocity_15m=velocity_15m,
            alert_type=alert_type,
            alert_reason=alert_reason,
            sample_count=len(self._snapshots),
            tracking_duration_sec=current_time - self._start_time,
        )

        logger.debug(
            "[Velocity] %s@%s → 1m: %s, 5m: %s, 15m: %s",
            self._symbol, self._exchange,
            f"{velocity_1m:+.2f}%p" if velocity_1m is not None else "N/A",
            f"{velocity_5m:+.2f}%p" if velocity_5m is not None else "N/A",
            f"{velocity_15m:+.2f}%p" if velocity_15m is not None else "N/A",
        )

        return result

    async def check_and_alert(self) -> Optional[VelocityResult]:
        """Velocity 계산 및 조건 충족 시 텔레그램 알림 발송.

        Returns:
            알림 발송한 경우 VelocityResult, 아니면 None.
        """
        result = self.calculate_velocity()

        if not result.alert_type or not self._alert:
            return None

        # Throttle: 같은 타입 알림 60초 쿨다운
        now = time.time()
        last_alert = self._last_alert_time.get(result.alert_type, 0.0)
        if now - last_alert < 60:
            logger.debug(
                "[Velocity] 알림 throttle: %s (쿨다운 중)",
                result.alert_type.value,
            )
            return None

        # 알림 발송
        alert_msg = format_velocity_alert(result)
        alert_level = self._get_alert_level(result.alert_type)

        await self._alert.send(
            alert_level,
            alert_msg,
            key=f"velocity:{self._symbol}:{result.alert_type.value}",
        )

        self._last_alert_time[result.alert_type] = now
        logger.info(
            "[Velocity] 알림 발송: %s@%s → %s",
            self._symbol, self._exchange, result.alert_type.value,
        )

        return result

    def _find_snapshot_at(self, target_time: float) -> Optional[PremiumSnapshot]:
        """특정 시각에 가장 가까운 스냅샷 찾기 (±10초 허용).

        Args:
            target_time: 목표 시각 (unix timestamp).

        Returns:
            가장 가까운 스냅샷 또는 None.
        """
        tolerance = 10.0  # 10초 허용

        closest = None
        min_diff = float("inf")

        for snap in self._snapshots:
            diff = abs(snap.timestamp - target_time)
            if diff <= tolerance and diff < min_diff:
                closest = snap
                min_diff = diff

        return closest

    def _get_alert_level(self, alert_type: VelocityAlertType) -> str:
        """알림 타입별 레벨 반환.

        Returns:
            "CRITICAL", "HIGH", "MEDIUM", "LOW" 중 하나.
        """
        level_map = {
            VelocityAlertType.COLLAPSE: "HIGH",     # 급락 → 즉시 알림
            VelocityAlertType.SURGE: "MEDIUM",      # 급등 → 주의 알림
            VelocityAlertType.CONVERGENCE: "LOW",   # 수렴 → 정보성 알림
            VelocityAlertType.STABLE: "INFO",       # 안정 → 로그만
        }
        return level_map.get(alert_type, "LOW")


def format_velocity_alert(result: VelocityResult) -> str:
    """Velocity 알림 메시지 포맷.

    Args:
        result: VelocityResult.

    Returns:
        포맷된 메시지 (Markdown).
    """
    emoji_map = {
        VelocityAlertType.COLLAPSE: "💀",
        VelocityAlertType.SURGE: "🚀",
        VelocityAlertType.CONVERGENCE: "📉",
        VelocityAlertType.STABLE: "✅",
    }

    emoji = emoji_map.get(result.alert_type, "📊")

    lines = [
        f"{emoji} Premium Velocity Alert",
        f"━━━━━━━━━━━━━━━",
        f"*{result.symbol}@{result.exchange.upper()}*",
        f"",
        f"현재 프리미엄: {result.current_premium:+.2f}%",
        f"",
    ]

    # 변화율 표시
    if result.velocity_1m is not None:
        lines.append(f"📊 1m: {result.velocity_1m:+.2f}%p")
    if result.velocity_5m is not None:
        lines.append(f"📊 5m: {result.velocity_5m:+.2f}%p")
    if result.velocity_15m is not None:
        lines.append(f"📊 15m: {result.velocity_15m:+.2f}%p")

    lines.extend([
        f"",
        f"⚠️ {result.alert_reason}",
        f"━━━━━━━━━━━━━━━",
    ])

    return "\n".join(lines)
