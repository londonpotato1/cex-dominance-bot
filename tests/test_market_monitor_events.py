"""MarketMonitor Phase 7 이벤트 처리 통합 테스트."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from collectors.market_monitor import MarketMonitor
from collectors.notice_parser import NoticeParseResult, EventSeverity, EventAction
from analysis.event_strategy import EventStrategyExecutor, StrategyRecommendation
from analysis.gate import AlertLevel
from store.token_registry import TokenRegistry
from store.writer import DatabaseWriter


@pytest.fixture
def mock_writer():
    """DatabaseWriter mock."""
    writer = MagicMock(spec=DatabaseWriter)
    writer.enqueue_sync = MagicMock()
    return writer


@pytest.fixture
def mock_registry():
    """TokenRegistry mock."""
    return MagicMock(spec=TokenRegistry)


@pytest.fixture
def mock_alert():
    """TelegramAlert mock."""
    alert = AsyncMock()
    alert.send = AsyncMock()
    return alert


@pytest.fixture
def mock_event_strategy():
    """EventStrategyExecutor mock."""
    strategy = AsyncMock(spec=EventStrategyExecutor)
    strategy.process_event = AsyncMock()
    return strategy


@pytest.fixture
def market_monitor(mock_writer, mock_registry, mock_alert, mock_event_strategy):
    """MarketMonitor 인스턴스 (Phase 7 통합)."""
    return MarketMonitor(
        writer=mock_writer,
        token_registry=mock_registry,
        alert=mock_alert,
        event_strategy=mock_event_strategy,
        notice_polling=False,  # 테스트에서는 비활성화
    )


class TestNonListingEvents:
    """비상장 이벤트 (WARNING/HALT/MIGRATION/DEPEG) 테스트."""

    @pytest.mark.asyncio
    async def test_warning_event_triggers_strategy(
        self, market_monitor, mock_event_strategy, mock_alert
    ):
        """WARNING 이벤트 감지 시 전략 생성."""
        # WARNING 공지
        notice = NoticeParseResult(
            exchange="upbit",
            notice_type="warning",
            symbols=["BTC"],
            listing_time="",
            notice_url="https://upbit.com/notice/123",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.TRADE,
            event_details={},
        )

        # 전략 반환 설정
        strategy = StrategyRecommendation(
            symbol="BTC",
            exchange="upbit",
            event_type="warning",
            severity=EventSeverity.MEDIUM,
            recommended_action="BUY",
            reason="출금 중단으로 프리미엄 상승 예상",
            expected_roi=2.5,
            confidence=0.7,
            max_hold_time_hours=3,
            risk_level="medium",
            alert_sound=False,
        )
        mock_event_strategy.process_event.return_value = strategy

        # 콜백 실행
        await market_monitor._on_notice_listing(notice)

        # 전략 생성 호출 확인
        mock_event_strategy.process_event.assert_called_once_with(notice)

        # 알림 발송 확인
        mock_alert.send.assert_called_once()
        call_args = mock_alert.send.call_args
        assert call_args[0][0] == AlertLevel.MEDIUM  # severity에 따라
        assert "BTC" in call_args[0][1]
        assert "BUY" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_halt_event_critical_alert(
        self, market_monitor, mock_event_strategy, mock_alert
    ):
        """HALT 이벤트는 CRITICAL 알림."""
        notice = NoticeParseResult(
            exchange="bithumb",
            notice_type="halt",
            symbols=["LUNA"],
            listing_time="",
            notice_url="",
            event_severity=EventSeverity.HIGH,
            event_action=EventAction.MONITOR,
            event_details={},
        )

        strategy = StrategyRecommendation(
            symbol="LUNA",
            exchange="bithumb",
            event_type="halt",
            severity=EventSeverity.HIGH,
            recommended_action="MONITOR",
            reason="거래 중단, 재개 모니터링",
            expected_roi=0.0,
            confidence=0.5,
            max_hold_time_hours=0,
            risk_level="high",
            alert_sound=True,
        )
        mock_event_strategy.process_event.return_value = strategy

        await market_monitor._on_notice_listing(notice)

        # HIGH 레벨 알림
        call_args = mock_alert.send.call_args
        assert call_args[0][0] == AlertLevel.HIGH

    @pytest.mark.asyncio
    async def test_depeg_event(
        self, market_monitor, mock_event_strategy, mock_alert
    ):
        """DEPEG 이벤트 처리."""
        notice = NoticeParseResult(
            exchange="upbit",
            notice_type="depeg",
            symbols=["USDT"],
            listing_time="",
            notice_url="",
            event_severity=EventSeverity.CRITICAL,
            event_action=EventAction.ALERT,
            event_details={},
        )

        strategy = StrategyRecommendation(
            symbol="USDT",
            exchange="upbit",
            event_type="depeg",
            severity=EventSeverity.CRITICAL,
            recommended_action="SELL",
            reason="스테이블코인 디페깅 감지",
            expected_roi=-5.0,
            confidence=0.9,
            max_hold_time_hours=0,
            risk_level="critical",
            alert_sound=True,
        )
        mock_event_strategy.process_event.return_value = strategy

        await market_monitor._on_notice_listing(notice)

        # CRITICAL 레벨 알림
        call_args = mock_alert.send.call_args
        assert call_args[0][0] == AlertLevel.CRITICAL
        assert "USDT" in call_args[0][1]
        assert "SELL" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_migration_event(
        self, market_monitor, mock_event_strategy, mock_alert
    ):
        """MIGRATION 이벤트 처리."""
        notice = NoticeParseResult(
            exchange="bithumb",
            notice_type="migration",
            symbols=["MATIC"],
            listing_time="",
            notice_url="",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.ALERT,
            event_details={},
        )

        strategy = StrategyRecommendation(
            symbol="MATIC",
            exchange="bithumb",
            event_type="migration",
            severity=EventSeverity.MEDIUM,
            recommended_action="HOLD",
            reason="POL 전환, 1:1 스왑 대기",
            expected_roi=0.0,
            confidence=0.8,
            max_hold_time_hours=24,
            risk_level="medium",
            alert_sound=False,
        )
        mock_event_strategy.process_event.return_value = strategy

        await market_monitor._on_notice_listing(notice)

        # MEDIUM 레벨 알림
        call_args = mock_alert.send.call_args
        assert call_args[0][0] == AlertLevel.MEDIUM

    @pytest.mark.asyncio
    async def test_no_action_event(
        self, market_monitor, mock_event_strategy, mock_alert
    ):
        """조치 불필요 이벤트 (strategy None 반환)."""
        notice = NoticeParseResult(
            exchange="upbit",
            notice_type="warning",
            symbols=["BTC"],
            listing_time="",
            notice_url="",
            event_severity=EventSeverity.LOW,
            event_action=EventAction.NONE,
            event_details={},
        )

        # None 반환 (조치 불필요)
        mock_event_strategy.process_event.return_value = None

        await market_monitor._on_notice_listing(notice)

        # 알림 발송 안됨
        mock_alert.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_event_strategy_warning(
        self, mock_writer, mock_registry, mock_alert
    ):
        """EventStrategy 미설정 시 경고 로그."""
        monitor = MarketMonitor(
            writer=mock_writer,
            token_registry=mock_registry,
            alert=mock_alert,
            event_strategy=None,  # 미설정
            notice_polling=False,
        )

        notice = NoticeParseResult(
            exchange="upbit",
            notice_type="warning",
            symbols=["BTC"],
            listing_time="",
            notice_url="",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.TRADE,
            event_details={},
        )

        # 예외 발생하지 않아야 함 (경고 로그만)
        await monitor._on_notice_listing(notice)

        # 알림 발송 안됨
        mock_alert.send.assert_not_called()


class TestListingEvents:
    """기존 상장 이벤트 동작 유지 확인."""

    @pytest.mark.asyncio
    async def test_listing_event_skips_event_handler(
        self, market_monitor, mock_event_strategy
    ):
        """LISTING 이벤트는 기존 로직 사용."""
        notice = NoticeParseResult(
            exchange="upbit",
            notice_type="listing",
            symbols=["SENT"],
            listing_time="2026-01-30 14:00",
            notice_url="",
            event_severity=EventSeverity.LOW,
            event_action=EventAction.TRADE,
            event_details={},
        )

        # Gate checker 없으면 즉시 종료
        market_monitor._gate_checker = None

        await market_monitor._on_notice_listing(notice)

        # EventStrategy 호출 안됨
        mock_event_strategy.process_event.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
