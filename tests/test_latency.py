"""Phase 4.2 알림 속도 측정 테스트."""

import asyncio
import time
import pytest

from metrics.latency import LatencyTracker


class TestLatencyTracker:
    """LatencyTracker 단위 테스트."""

    def test_mark_detect(self):
        """감지 시점 기록 테스트."""
        tracker = LatencyTracker(symbol="BTC", exchange="upbit")
        assert tracker.detect_ts is None
        
        tracker.mark_detect()
        assert tracker.detect_ts is not None
        assert tracker.detect_ts > 0

    def test_mark_analyze(self):
        """분석 시작/종료 시점 기록 테스트."""
        tracker = LatencyTracker(symbol="BTC", exchange="upbit")
        
        tracker.mark_analyze_start()
        time.sleep(0.01)  # 10ms 대기
        tracker.mark_analyze_end()
        
        assert tracker.analyze_start_ts is not None
        assert tracker.analyze_end_ts is not None
        assert tracker.analyze_end_ts > tracker.analyze_start_ts

    def test_analyze_duration_ms(self):
        """분석 소요 시간 계산 테스트."""
        tracker = LatencyTracker(symbol="BTC", exchange="upbit")
        
        tracker.mark_analyze_start()
        time.sleep(0.05)  # 50ms 대기
        tracker.mark_analyze_end()
        
        duration = tracker.analyze_duration_ms
        assert duration is not None
        assert duration >= 40  # 최소 40ms 이상
        assert duration < 200  # 최대 200ms 미만

    def test_detect_to_alert_ms(self):
        """감지 → 알림 전체 시간 계산 테스트."""
        tracker = LatencyTracker(symbol="ETH", exchange="bithumb")
        
        tracker.mark_detect()
        time.sleep(0.02)  # 20ms
        tracker.mark_analyze_start()
        time.sleep(0.03)  # 30ms
        tracker.mark_analyze_end()
        time.sleep(0.01)  # 10ms
        tracker.mark_alert_sent()
        
        total = tracker.detect_to_alert_ms
        assert total is not None
        assert total >= 50  # 최소 50ms 이상

    def test_format_summary_ms(self):
        """요약 문자열 (밀리초) 테스트."""
        tracker = LatencyTracker(symbol="BTC", exchange="upbit")
        
        tracker.mark_detect()
        tracker.mark_analyze_start()
        time.sleep(0.05)  # 50ms
        tracker.mark_analyze_end()
        tracker.mark_alert_sent()
        
        summary = tracker.format_summary()
        assert "⚡" in summary
        assert "감지→알림" in summary
        assert "분석" in summary
        assert "ms" in summary

    def test_format_summary_seconds(self):
        """요약 문자열 (초 단위) 테스트."""
        tracker = LatencyTracker(symbol="BTC", exchange="upbit")
        
        # 수동으로 타임스탬프 설정 (1.5초 지연 시뮬레이션)
        tracker.detect_ts = 0
        tracker.alert_sent_ts = 1.5
        tracker.analyze_start_ts = 0.1
        tracker.analyze_end_ts = 0.3
        
        summary = tracker.format_summary()
        assert "1.5s" in summary  # 초 단위로 표시

    def test_set_result(self):
        """결과 설정 테스트."""
        tracker = LatencyTracker(symbol="BTC", exchange="upbit")
        
        tracker.set_result("CRITICAL", True)
        assert tracker.alert_level == "CRITICAL"
        assert tracker.can_proceed is True

    def test_none_durations(self):
        """타임스탬프 미설정 시 None 반환 테스트."""
        tracker = LatencyTracker(symbol="BTC", exchange="upbit")
        
        assert tracker.detect_to_alert_ms is None
        assert tracker.analyze_duration_ms is None
        assert tracker.total_duration_ms is None

    def test_format_summary_empty(self):
        """타임스탬프 없을 때 빈 문자열 반환."""
        tracker = LatencyTracker(symbol="BTC", exchange="upbit")
        assert tracker.format_summary() == ""


class TestLatencyTrackerChaining:
    """LatencyTracker 메서드 체이닝 테스트."""

    def test_method_chaining(self):
        """메서드 체이닝 지원 테스트."""
        tracker = (
            LatencyTracker(symbol="BTC", exchange="upbit")
            .mark_detect()
            .mark_analyze_start()
            .mark_analyze_end()
            .set_result("HIGH", False)
            .mark_alert_sent()
        )
        
        assert tracker.detect_ts is not None
        assert tracker.alert_sent_ts is not None
        assert tracker.alert_level == "HIGH"
        assert tracker.can_proceed is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
