"""MM 조작 감지 엔진 (Phase 9 Week 9-10).

감지 패턴:
  1. 워시 트레이딩 (자전 거래): 비정상적 거래량 패턴
  2. 스푸핑/레이어링: 대량 호가 후 취소
  3. 덤핑 패턴: 급격한 매도 압력
  4. 펌프 앤 덤프: 급등 후 급락

사용법:
    detector = MMManipulationDetector()
    result = detector.analyze_trading_pattern(trades, orderbook)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


# =============================================================================
# Enums & Types
# =============================================================================


class ManipulationType(str, Enum):
    """조작 유형."""
    WASH_TRADING = "wash_trading"
    SPOOFING = "spoofing"
    LAYERING = "layering"
    PUMP_AND_DUMP = "pump_and_dump"
    AGGRESSIVE_DUMPING = "aggressive_dumping"
    FRONT_RUNNING = "front_running"
    UNKNOWN = "unknown"


class AlertSeverity(str, Enum):
    """경고 심각도."""
    CRITICAL = "critical"  # 즉시 회피
    HIGH = "high"          # 주의 필요
    MEDIUM = "medium"      # 모니터링
    LOW = "low"            # 참고


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Trade:
    """개별 거래 데이터."""
    timestamp: datetime
    price: float
    amount: float
    side: str  # "buy" or "sell"
    trade_id: Optional[str] = None


@dataclass
class OrderBookLevel:
    """호가창 레벨."""
    price: float
    amount: float


@dataclass
class OrderBook:
    """호가창 스냅샷."""
    timestamp: datetime
    bids: list[OrderBookLevel] = field(default_factory=list)  # 매수 (내림차순)
    asks: list[OrderBookLevel] = field(default_factory=list)  # 매도 (오름차순)


@dataclass
class ManipulationAlert:
    """조작 의심 경고."""
    manipulation_type: ManipulationType
    severity: AlertSeverity
    confidence: float  # 0.0 ~ 1.0
    description: str
    evidence: dict = field(default_factory=dict)
    detected_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "type": self.manipulation_type.value,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "description": self.description,
            "evidence": self.evidence,
            "detected_at": self.detected_at.isoformat(),
        }


@dataclass
class ManipulationAnalysis:
    """조작 분석 결과."""
    symbol: str
    mm_name: Optional[str]
    alerts: list[ManipulationAlert] = field(default_factory=list)
    overall_risk_score: float = 0.0  # 0-10
    is_safe: bool = True
    analyzed_at: datetime = field(default_factory=datetime.now)

    @property
    def highest_severity(self) -> Optional[AlertSeverity]:
        """가장 높은 심각도 반환."""
        if not self.alerts:
            return None
        severity_order = [AlertSeverity.CRITICAL, AlertSeverity.HIGH,
                         AlertSeverity.MEDIUM, AlertSeverity.LOW]
        for sev in severity_order:
            if any(a.severity == sev for a in self.alerts):
                return sev
        return None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "mm_name": self.mm_name,
            "alerts": [a.to_dict() for a in self.alerts],
            "overall_risk_score": self.overall_risk_score,
            "is_safe": self.is_safe,
            "highest_severity": self.highest_severity.value if self.highest_severity else None,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


# =============================================================================
# MM Manipulation Detector
# =============================================================================


class MMManipulationDetector:
    """MM 조작 감지 엔진.

    거래 패턴과 호가창 분석을 통해 조작 가능성 감지.
    """

    # 워시 트레이딩 감지 임계값
    WASH_TRADE_VOLUME_SPIKE_RATIO = 5.0  # 평균 대비 5배 이상
    WASH_TRADE_PRICE_STABILITY = 0.1     # 가격 변동 0.1% 미만
    WASH_TRADE_TIME_WINDOW_SEC = 60      # 1분 내 집중

    # 스푸핑/레이어링 감지 임계값
    SPOOF_ORDER_SIZE_RATIO = 10.0        # 평균 대비 10배 이상 주문
    SPOOF_CANCEL_RATIO = 0.9             # 90% 이상 취소율

    # 펌프 앤 덤프 감지 임계값
    PUMP_PRICE_INCREASE = 20.0           # 20% 이상 급등
    DUMP_PRICE_DECREASE = 15.0           # 15% 이상 급락
    PUMP_DUMP_TIME_WINDOW_MIN = 30       # 30분 내

    # 덤핑 감지 임계값
    DUMP_SELL_RATIO = 0.8                # 매도 비율 80% 이상
    DUMP_VOLUME_SPIKE = 3.0              # 평균 대비 3배 이상

    def __init__(
        self,
        mm_classifier: Optional["MMClassifier"] = None,  # type: ignore
    ) -> None:
        self._mm_classifier = mm_classifier

    def analyze(
        self,
        symbol: str,
        trades: list[Trade],
        orderbook: Optional[OrderBook] = None,
        mm_name: Optional[str] = None,
    ) -> ManipulationAnalysis:
        """종합 조작 분석.

        Args:
            symbol: 심볼
            trades: 최근 거래 리스트
            orderbook: 현재 호가창 (선택)
            mm_name: 알려진 MM 이름 (선택)

        Returns:
            ManipulationAnalysis
        """
        alerts: list[ManipulationAlert] = []

        # 1. MM 블랙리스트 체크
        if mm_name:
            mm_alert = self._check_mm_blacklist(mm_name)
            if mm_alert:
                alerts.append(mm_alert)

        # 2. 거래 패턴 분석
        if trades:
            # 워시 트레이딩 감지
            wash_alert = self._detect_wash_trading(trades)
            if wash_alert:
                alerts.append(wash_alert)

            # 펌프 앤 덤프 감지
            pnd_alert = self._detect_pump_and_dump(trades)
            if pnd_alert:
                alerts.append(pnd_alert)

            # 공격적 덤핑 감지
            dump_alert = self._detect_aggressive_dumping(trades)
            if dump_alert:
                alerts.append(dump_alert)

        # 3. 호가창 분석 (있으면)
        if orderbook:
            spoof_alert = self._detect_spoofing(orderbook, trades)
            if spoof_alert:
                alerts.append(spoof_alert)

        # 종합 점수 계산
        overall_risk = self._calculate_overall_risk(alerts, mm_name)
        is_safe = overall_risk < 5.0 and not any(
            a.severity in [AlertSeverity.CRITICAL, AlertSeverity.HIGH]
            for a in alerts
        )

        return ManipulationAnalysis(
            symbol=symbol,
            mm_name=mm_name,
            alerts=alerts,
            overall_risk_score=overall_risk,
            is_safe=is_safe,
            analyzed_at=datetime.now(),
        )

    def _check_mm_blacklist(self, mm_name: str) -> Optional[ManipulationAlert]:
        """MM 블랙리스트 체크."""
        if not self._mm_classifier:
            return None

        from collectors.vc_mm_collector import MMInfo
        mm_info: Optional[MMInfo] = self._mm_classifier.get_mm_info(mm_name)
        if not mm_info:
            return None

        # 조작 플래그 있으면 경고
        if mm_info.manipulation_flags:
            severity = AlertSeverity.HIGH
            if mm_info.risk_score >= 8.0:
                severity = AlertSeverity.CRITICAL
            elif mm_info.risk_score >= 6.0:
                severity = AlertSeverity.HIGH
            elif mm_info.risk_score >= 4.0:
                severity = AlertSeverity.MEDIUM

            return ManipulationAlert(
                manipulation_type=ManipulationType.UNKNOWN,
                severity=severity,
                confidence=0.9,
                description=f"MM '{mm_name}' has known manipulation history",
                evidence={
                    "mm_name": mm_name,
                    "risk_score": mm_info.risk_score,
                    "flags": mm_info.manipulation_flags,
                },
            )

        # 높은 리스크 스코어도 경고
        if mm_info.risk_score >= 6.0:
            return ManipulationAlert(
                manipulation_type=ManipulationType.UNKNOWN,
                severity=AlertSeverity.MEDIUM,
                confidence=0.7,
                description=f"MM '{mm_name}' has elevated risk score: {mm_info.risk_score}",
                evidence={
                    "mm_name": mm_name,
                    "risk_score": mm_info.risk_score,
                },
            )

        return None

    def _detect_wash_trading(self, trades: list[Trade]) -> Optional[ManipulationAlert]:
        """워시 트레이딩 감지.

        특징:
          - 짧은 시간 내 대량 거래
          - 가격 변동 거의 없음
          - 매수/매도 균형 (자전 거래)
        """
        if len(trades) < 10:
            return None

        # 시간 범위 체크
        time_window = timedelta(seconds=self.WASH_TRADE_TIME_WINDOW_SEC)
        recent_trades = [
            t for t in trades
            if (datetime.now() - t.timestamp) <= time_window
        ]

        if len(recent_trades) < 5:
            return None

        # 거래량 분석
        total_volume = sum(t.amount for t in recent_trades)
        avg_volume_per_trade = total_volume / len(recent_trades)

        # 전체 평균과 비교
        all_volume = sum(t.amount for t in trades)
        overall_avg = all_volume / len(trades) if trades else 0

        volume_spike_ratio = avg_volume_per_trade / overall_avg if overall_avg > 0 else 0

        # 가격 변동 분석
        prices = [t.price for t in recent_trades]
        if not prices:
            return None

        price_range = (max(prices) - min(prices)) / min(prices) * 100 if min(prices) > 0 else 0

        # 매수/매도 비율
        buy_volume = sum(t.amount for t in recent_trades if t.side == "buy")
        sell_volume = sum(t.amount for t in recent_trades if t.side == "sell")
        total_recent = buy_volume + sell_volume
        buy_ratio = buy_volume / total_recent if total_recent > 0 else 0.5

        # 워시 트레이딩 조건 체크
        is_wash = (
            volume_spike_ratio >= self.WASH_TRADE_VOLUME_SPIKE_RATIO
            and price_range <= self.WASH_TRADE_PRICE_STABILITY
            and 0.4 <= buy_ratio <= 0.6  # 매수/매도 균형
        )

        if is_wash:
            confidence = min(0.9, 0.5 + (volume_spike_ratio / 20))
            return ManipulationAlert(
                manipulation_type=ManipulationType.WASH_TRADING,
                severity=AlertSeverity.HIGH,
                confidence=confidence,
                description="Suspected wash trading: high volume with minimal price movement",
                evidence={
                    "volume_spike_ratio": round(volume_spike_ratio, 2),
                    "price_range_pct": round(price_range, 4),
                    "buy_sell_ratio": round(buy_ratio, 2),
                    "trade_count": len(recent_trades),
                },
            )

        return None

    def _detect_pump_and_dump(self, trades: list[Trade]) -> Optional[ManipulationAlert]:
        """펌프 앤 덤프 감지.

        특징:
          - 급격한 가격 상승 (펌프)
          - 이후 급격한 하락 (덤프)
          - 짧은 시간 내 발생
        """
        if len(trades) < 20:
            return None

        # 시간순 정렬
        sorted_trades = sorted(trades, key=lambda t: t.timestamp)

        # 시간 윈도우 내 거래
        time_window = timedelta(minutes=self.PUMP_DUMP_TIME_WINDOW_MIN)
        cutoff_time = datetime.now() - time_window
        window_trades = [t for t in sorted_trades if t.timestamp >= cutoff_time]

        if len(window_trades) < 10:
            return None

        prices = [t.price for t in window_trades]
        min_price = min(prices)
        max_price = max(prices)
        current_price = prices[-1]

        # 최저점 → 최고점 변화율
        pump_pct = ((max_price - min_price) / min_price * 100) if min_price > 0 else 0

        # 최고점 → 현재가 변화율
        dump_pct = ((max_price - current_price) / max_price * 100) if max_price > 0 else 0

        is_pump_dump = (
            pump_pct >= self.PUMP_PRICE_INCREASE
            and dump_pct >= self.DUMP_PRICE_DECREASE
        )

        if is_pump_dump:
            confidence = min(0.9, 0.5 + (pump_pct + dump_pct) / 100)
            return ManipulationAlert(
                manipulation_type=ManipulationType.PUMP_AND_DUMP,
                severity=AlertSeverity.CRITICAL,
                confidence=confidence,
                description=f"Pump and dump pattern: +{pump_pct:.1f}% then -{dump_pct:.1f}%",
                evidence={
                    "pump_pct": round(pump_pct, 2),
                    "dump_pct": round(dump_pct, 2),
                    "min_price": min_price,
                    "max_price": max_price,
                    "current_price": current_price,
                    "time_window_min": self.PUMP_DUMP_TIME_WINDOW_MIN,
                },
            )

        return None

    def _detect_aggressive_dumping(self, trades: list[Trade]) -> Optional[ManipulationAlert]:
        """공격적 덤핑 감지.

        특징:
          - 매도 비율 매우 높음
          - 거래량 급증
          - 가격 하락 동반
        """
        if len(trades) < 10:
            return None

        # 최근 거래
        recent_trades = trades[-50:] if len(trades) >= 50 else trades

        # 매도 비율
        sell_volume = sum(t.amount for t in recent_trades if t.side == "sell")
        total_volume = sum(t.amount for t in recent_trades)
        sell_ratio = sell_volume / total_volume if total_volume > 0 else 0

        # 거래량 스파이크
        avg_volume_per_trade = total_volume / len(recent_trades)
        overall_avg = sum(t.amount for t in trades) / len(trades)
        volume_spike = avg_volume_per_trade / overall_avg if overall_avg > 0 else 0

        # 가격 하락
        prices = [t.price for t in recent_trades]
        if len(prices) >= 2:
            price_change = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] > 0 else 0
        else:
            price_change = 0

        is_dumping = (
            sell_ratio >= self.DUMP_SELL_RATIO
            and volume_spike >= self.DUMP_VOLUME_SPIKE
            and price_change < -5.0  # 5% 이상 하락
        )

        if is_dumping:
            confidence = min(0.85, 0.4 + sell_ratio / 2)
            return ManipulationAlert(
                manipulation_type=ManipulationType.AGGRESSIVE_DUMPING,
                severity=AlertSeverity.HIGH,
                confidence=confidence,
                description=f"Aggressive dumping: {sell_ratio*100:.1f}% sells with {price_change:.1f}% drop",
                evidence={
                    "sell_ratio": round(sell_ratio, 2),
                    "volume_spike": round(volume_spike, 2),
                    "price_change_pct": round(price_change, 2),
                },
            )

        return None

    def _detect_spoofing(
        self,
        orderbook: OrderBook,
        trades: list[Trade],
    ) -> Optional[ManipulationAlert]:
        """스푸핑/레이어링 감지.

        특징:
          - 대량 주문 후 취소
          - 가격 움직임 유도 후 반대쪽에서 체결

        Note:
            실시간 주문 취소 데이터 없이는 정확도 제한됨.
            호가 크기 vs 체결량 비교로 간접 추정.
            실제 스푸핑 확인을 위해서는 주문 취소 이벤트 스트림 필요.
        """
        if not orderbook.bids or not orderbook.asks:
            return None

        # 평균 호가 크기 계산
        all_levels = orderbook.bids + orderbook.asks
        avg_size = sum(l.amount for l in all_levels) / len(all_levels) if all_levels else 0

        # 비정상적으로 큰 호가 찾기
        large_bids = [b for b in orderbook.bids if b.amount >= avg_size * self.SPOOF_ORDER_SIZE_RATIO]
        large_asks = [a for a in orderbook.asks if a.amount >= avg_size * self.SPOOF_ORDER_SIZE_RATIO]

        if large_bids or large_asks:
            # 실제 체결과 비교 (대형 호가가 체결되지 않으면 스푸핑 의심)
            recent_trades = trades[-20:] if len(trades) >= 20 else trades
            avg_trade_size = sum(t.amount for t in recent_trades) / len(recent_trades) if recent_trades else 0

            # 호가 대비 실제 체결이 현저히 작으면 스푸핑 의심
            if avg_size > 0 and avg_trade_size < avg_size * 0.3:
                total_large = len(large_bids) + len(large_asks)
                confidence = min(0.8, 0.3 + total_large * 0.1)

                return ManipulationAlert(
                    manipulation_type=ManipulationType.SPOOFING,
                    severity=AlertSeverity.MEDIUM,
                    confidence=confidence,
                    description=f"Possible spoofing: {total_large} large orders with low execution",
                    evidence={
                        "large_bid_count": len(large_bids),
                        "large_ask_count": len(large_asks),
                        "avg_order_size": round(avg_size, 4),
                        "avg_trade_size": round(avg_trade_size, 4),
                    },
                )

        return None

    def _calculate_overall_risk(
        self,
        alerts: list[ManipulationAlert],
        mm_name: Optional[str],
    ) -> float:
        """종합 리스크 스코어 계산.

        Returns:
            0-10 스코어
        """
        if not alerts:
            # MM 리스크만 고려
            if mm_name and self._mm_classifier:
                return self._mm_classifier.get_risk_score(mm_name)
            return 0.0

        # 경고별 점수
        severity_scores = {
            AlertSeverity.CRITICAL: 8.0,
            AlertSeverity.HIGH: 6.0,
            AlertSeverity.MEDIUM: 4.0,
            AlertSeverity.LOW: 2.0,
        }

        # 가중 평균 계산
        total_score = 0.0
        for alert in alerts:
            base_score = severity_scores.get(alert.severity, 2.0)
            total_score += base_score * alert.confidence

        # MM 리스크 추가
        if mm_name and self._mm_classifier:
            mm_risk = self._mm_classifier.get_risk_score(mm_name)
            total_score = (total_score + mm_risk) / 2

        return min(10.0, total_score)


# =============================================================================
# 편의 함수
# =============================================================================


def format_manipulation_alert(analysis: ManipulationAnalysis) -> str:
    """조작 분석 결과 텍스트 포맷."""
    if analysis.is_safe and not analysis.alerts:
        return f"✅ {analysis.symbol}: 조작 의심 없음 (리스크: {analysis.overall_risk_score:.1f}/10)"

    emoji_map = {
        AlertSeverity.CRITICAL: "🚨",
        AlertSeverity.HIGH: "⚠️",
        AlertSeverity.MEDIUM: "⚡",
        AlertSeverity.LOW: "📌",
    }

    lines = [
        f"🔍 **{analysis.symbol} 조작 분석**",
        "━━━━━━━━━━━━━━━",
        f"📊 종합 리스크: {analysis.overall_risk_score:.1f}/10",
        f"🔒 안전 여부: {'✅ 안전' if analysis.is_safe else '❌ 주의'}",
    ]

    if analysis.mm_name:
        lines.append(f"🏦 MM: {analysis.mm_name}")

    if analysis.alerts:
        lines.append("")
        lines.append("**경고:**")
        for alert in analysis.alerts:
            emoji = emoji_map.get(alert.severity, "📌")
            lines.append(f"  {emoji} [{alert.severity.value}] {alert.description}")

    return "\n".join(lines)
