"""알림 속도 측정 모듈 (Phase 4.2).

상장 감지 → 분석 → 알림 전송까지의 지연 시간을 측정하고 기록.

타임스탬프 포인트:
- detect_ts: 상장/이벤트 감지 시점
- analyze_start_ts: Gate 분석 시작
- analyze_end_ts: Gate 분석 완료
- alert_sent_ts: 알림 전송 완료

Writer Queue 경유 (Single Writer 원칙).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from store.writer import DatabaseWriter

logger = logging.getLogger(__name__)

# DB INSERT SQL
_INSERT_LATENCY_SQL = """\
INSERT INTO alert_latency_log (
    timestamp, symbol, exchange, event_type,
    detect_ts, analyze_start_ts, analyze_end_ts, alert_sent_ts,
    detect_to_alert_ms, analyze_duration_ms, total_duration_ms,
    alert_level, can_proceed
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


@dataclass
class LatencyTracker:
    """알림 속도 측정 트래커.
    
    사용법:
        tracker = LatencyTracker(symbol="BTC", exchange="upbit")
        tracker.mark_detect()  # 감지 시점
        tracker.mark_analyze_start()  # 분석 시작
        # ... Gate 분석 ...
        tracker.mark_analyze_end()  # 분석 완료
        # ... 알림 전송 ...
        tracker.mark_alert_sent()  # 알림 전송 완료
        await tracker.save(writer)  # DB 저장
    """
    
    symbol: str
    exchange: str
    event_type: str = "listing"  # "listing" | "event" | "notice"
    
    # 타임스탬프 (monotonic, 초 단위)
    detect_ts: float | None = None
    analyze_start_ts: float | None = None
    analyze_end_ts: float | None = None
    alert_sent_ts: float | None = None
    
    # 메타데이터
    alert_level: str | None = None
    can_proceed: bool | None = None
    
    def mark_detect(self) -> "LatencyTracker":
        """감지 시점 기록."""
        self.detect_ts = time.monotonic()
        return self
    
    def mark_analyze_start(self) -> "LatencyTracker":
        """분석 시작 시점 기록."""
        self.analyze_start_ts = time.monotonic()
        return self
    
    def mark_analyze_end(self) -> "LatencyTracker":
        """분석 완료 시점 기록."""
        self.analyze_end_ts = time.monotonic()
        return self
    
    def mark_alert_sent(self) -> "LatencyTracker":
        """알림 전송 완료 시점 기록."""
        self.alert_sent_ts = time.monotonic()
        return self
    
    def set_result(
        self, alert_level: str, can_proceed: bool
    ) -> "LatencyTracker":
        """분석 결과 설정."""
        self.alert_level = alert_level
        self.can_proceed = can_proceed
        return self
    
    @property
    def detect_to_alert_ms(self) -> float | None:
        """감지 → 알림 전송 시간 (밀리초)."""
        if self.detect_ts is None or self.alert_sent_ts is None:
            return None
        return (self.alert_sent_ts - self.detect_ts) * 1000
    
    @property
    def analyze_duration_ms(self) -> float | None:
        """분석 소요 시간 (밀리초)."""
        if self.analyze_start_ts is None or self.analyze_end_ts is None:
            return None
        return (self.analyze_end_ts - self.analyze_start_ts) * 1000
    
    @property
    def total_duration_ms(self) -> float | None:
        """전체 소요 시간 (밀리초) - detect_to_alert와 동일."""
        return self.detect_to_alert_ms
    
    def format_summary(self) -> str:
        """지연 시간 요약 문자열.
        
        Returns:
            "⚡ 감지→알림: 1.2s | 분석: 234ms"
        """
        parts = []
        
        if self.detect_to_alert_ms is not None:
            if self.detect_to_alert_ms >= 1000:
                parts.append(f"감지→알림: {self.detect_to_alert_ms/1000:.1f}s")
            else:
                parts.append(f"감지→알림: {self.detect_to_alert_ms:.0f}ms")
        
        if self.analyze_duration_ms is not None:
            parts.append(f"분석: {self.analyze_duration_ms:.0f}ms")
        
        if not parts:
            return ""
        
        return "⚡ " + " | ".join(parts)
    
    async def save(self, writer: "DatabaseWriter") -> None:
        """DB에 지연 시간 기록.
        
        Args:
            writer: DatabaseWriter (Queue 경유).
        """
        params = (
            time.time(),  # 현재 Unix timestamp
            self.symbol,
            self.exchange,
            self.event_type,
            self.detect_ts,
            self.analyze_start_ts,
            self.analyze_end_ts,
            self.alert_sent_ts,
            self.detect_to_alert_ms,
            self.analyze_duration_ms,
            self.total_duration_ms,
            self.alert_level,
            1 if self.can_proceed else 0 if self.can_proceed is not None else None,
        )
        
        await writer.enqueue(_INSERT_LATENCY_SQL, params, priority="normal")
        
        logger.info(
            "[Latency] %s@%s: %s (분석: %.0fms)",
            self.symbol,
            self.exchange,
            self.format_summary(),
            self.analyze_duration_ms or 0,
        )


async def get_latency_stats(
    read_conn,
    hours: int = 24,
) -> dict:
    """최근 N시간 알림 속도 통계 조회.
    
    Args:
        read_conn: 읽기 전용 DB 커넥션.
        hours: 조회 기간 (시간).
        
    Returns:
        {
            "count": 총 건수,
            "avg_detect_to_alert_ms": 평균 감지→알림 시간,
            "avg_analyze_ms": 평균 분석 시간,
            "min_detect_to_alert_ms": 최소,
            "max_detect_to_alert_ms": 최대,
            "p90_detect_to_alert_ms": 90퍼센타일,
        }
    """
    cutoff = time.time() - (hours * 3600)
    
    query = """
        SELECT 
            COUNT(*) as count,
            AVG(detect_to_alert_ms) as avg_detect_to_alert_ms,
            AVG(analyze_duration_ms) as avg_analyze_ms,
            MIN(detect_to_alert_ms) as min_detect_to_alert_ms,
            MAX(detect_to_alert_ms) as max_detect_to_alert_ms
        FROM alert_latency_log
        WHERE timestamp > ?
    """
    
    try:
        row = read_conn.execute(query, (cutoff,)).fetchone()
        
        # P90 계산 (별도 쿼리)
        p90_query = """
            SELECT detect_to_alert_ms
            FROM alert_latency_log
            WHERE timestamp > ? AND detect_to_alert_ms IS NOT NULL
            ORDER BY detect_to_alert_ms
            LIMIT 1
            OFFSET (
                SELECT CAST(COUNT(*) * 0.9 AS INTEGER)
                FROM alert_latency_log
                WHERE timestamp > ? AND detect_to_alert_ms IS NOT NULL
            )
        """
        p90_row = read_conn.execute(p90_query, (cutoff, cutoff)).fetchone()
        
        return {
            "count": row["count"] or 0,
            "avg_detect_to_alert_ms": row["avg_detect_to_alert_ms"],
            "avg_analyze_ms": row["avg_analyze_ms"],
            "min_detect_to_alert_ms": row["min_detect_to_alert_ms"],
            "max_detect_to_alert_ms": row["max_detect_to_alert_ms"],
            "p90_detect_to_alert_ms": p90_row[0] if p90_row else None,
        }
    except Exception as e:
        logger.warning("[Latency] 통계 조회 실패: %s", e)
        return {
            "count": 0,
            "avg_detect_to_alert_ms": None,
            "avg_analyze_ms": None,
            "min_detect_to_alert_ms": None,
            "max_detect_to_alert_ms": None,
            "p90_detect_to_alert_ms": None,
        }
