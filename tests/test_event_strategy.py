"""Phase 7a: 이벤트 자동 전략 실행 테스트."""

import pytest
from datetime import datetime, timezone

from analysis.event_strategy import (
    EventStrategyExecutor,
    StrategyType,
    StrategyRecommendation,
    format_strategy_alert,
)
from collectors.notice_parser import (
    NoticeParseResult,
    EventSeverity,
    EventAction,
)


@pytest.fixture
def executor():
    """EventStrategyExecutor 인스턴스."""
    return EventStrategyExecutor(enable_auto_trade=False)


class TestWARNINGStrategy:
    """WARNING 이벤트 전략 테스트."""

    @pytest.mark.asyncio
    async def test_withdrawal_suspension_buy_opportunity(self, executor):
        """출금 중단 → 매수 기회."""
        notice = NoticeParseResult(
            symbols=["BTC"],
            listing_time=None,
            notice_type="warning",
            exchange="upbit",
            raw_title="[공지] 비트코인(BTC) 출금 중단 안내",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.TRADE,
        )

        result = await executor.process_event(notice)

        assert result is not None
        assert result.strategy_type == StrategyType.BUY_OPPORTUNITY
        assert result.recommended_action == "BUY"
        assert result.symbol == "BTC"
        assert result.risk_level == "medium"
        assert "프리미엄 상승" in result.reason

    @pytest.mark.asyncio
    async def test_deposit_suspension_monitor_only(self, executor):
        """입금 중단 → 모니터링만."""
        notice = NoticeParseResult(
            symbols=["ETH"],
            listing_time=None,
            notice_type="warning",
            exchange="bithumb",
            raw_title="[공지] 이더리움(ETH) 입금 중단 안내",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.MONITOR,
        )

        result = await executor.process_event(notice)

        assert result is not None
        assert result.strategy_type == StrategyType.NO_ACTION
        assert result.recommended_action == "MONITOR"
        assert "입금 중단" in result.reason


class TestHALTStrategy:
    """HALT 이벤트 전략 테스트."""

    @pytest.mark.asyncio
    async def test_trading_halt_monitor(self, executor):
        """거래 중단 → 재개 모니터링."""
        notice = NoticeParseResult(
            symbols=["LUNA"],
            listing_time=None,
            notice_type="halt",
            exchange="upbit",
            raw_title="[긴급] 루나(LUNA) 거래 일시 중단",
            event_severity=EventSeverity.HIGH,
            event_action=EventAction.MONITOR,
        )

        result = await executor.process_event(notice)

        assert result is not None
        assert result.strategy_type == StrategyType.MONITOR_RESUME
        assert result.recommended_action == "MONITOR"
        assert result.risk_level == "high"
        assert result.alert_sound is True  # 긴급 알림
        assert "재개 시 급변동" in result.reason


class TestMIGRATIONStrategy:
    """MIGRATION 이벤트 전략 테스트."""

    @pytest.mark.asyncio
    async def test_token_swap_opportunity(self, executor):
        """토큰 스왑 → 기회 감지."""
        notice = NoticeParseResult(
            symbols=["MATIC"],
            listing_time=None,
            notice_type="migration",
            exchange="bithumb",
            raw_title="[안내] 폴리곤(MATIC → POL) 토큰 전환",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.ALERT,
        )

        result = await executor.process_event(notice)

        assert result is not None
        assert result.strategy_type == StrategyType.SWAP_OPPORTUNITY
        assert result.recommended_action == "HOLD"
        assert result.risk_level == "low"
        assert result.expected_roi == 1.5
        assert "스왑 가능" in result.reason


class TestDEPEGStrategy:
    """DEPEG 이벤트 전략 테스트."""

    @pytest.mark.asyncio
    async def test_stablecoin_depeg_sell(self, executor):
        """스테이블코인 디페깅 → 청산."""
        notice = NoticeParseResult(
            symbols=["USDT"],
            listing_time=None,
            notice_type="depeg",
            exchange="upbit",
            raw_title="[긴급] USDT 가격 급락 안내",
            event_severity=EventSeverity.CRITICAL,
            event_action=EventAction.ALERT,
        )

        result = await executor.process_event(notice)

        assert result is not None
        assert result.strategy_type == StrategyType.SAFETY_CHECK
        assert result.recommended_action == "SELL"
        assert result.risk_level == "critical"
        assert result.alert_sound is True
        assert "즉시 청산" in result.reason

    @pytest.mark.asyncio
    async def test_altcoin_crash_buy_opportunity(self, executor):
        """알트코인 급락 → 저가 매수 (고위험)."""
        notice = NoticeParseResult(
            symbols=["XRP"],
            listing_time=None,
            notice_type="depeg",
            exchange="bithumb",
            raw_title="[긴급] 리플(XRP) 가격 급락",
            event_severity=EventSeverity.CRITICAL,
            event_action=EventAction.ALERT,
        )

        result = await executor.process_event(notice)

        assert result is not None
        assert result.strategy_type == StrategyType.BUY_OPPORTUNITY
        assert result.recommended_action == "BUY"
        assert result.risk_level == "high"
        assert result.stop_loss == -10.0
        assert result.take_profit == 5.0
        assert "저가 매수" in result.reason


class TestEventHistory:
    """이벤트 히스토리 테스트."""

    @pytest.mark.asyncio
    async def test_add_to_history(self, executor):
        """히스토리 추가."""
        notice = NoticeParseResult(
            symbols=["BTC"],
            listing_time=None,
            notice_type="warning",
            exchange="upbit",
            raw_title="[공지] 비트코인(BTC) 출금 중단",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.TRADE,
        )

        await executor.process_event(notice)

        history = executor.get_recent_events(limit=10)
        assert len(history) == 1
        assert history[0].symbol == "BTC"

    @pytest.mark.asyncio
    async def test_get_events_by_symbol(self, executor):
        """심볼별 이벤트 조회."""
        # BTC 이벤트 2개 추가
        notice1 = NoticeParseResult(
            symbols=["BTC"],
            notice_type="warning",
            exchange="upbit",
            raw_title="BTC 출금 중단",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.TRADE,
        )
        notice2 = NoticeParseResult(
            symbols=["BTC"],
            notice_type="halt",
            exchange="bithumb",
            raw_title="BTC 거래 중단",
            event_severity=EventSeverity.HIGH,
            event_action=EventAction.MONITOR,
        )

        # ETH 이벤트 1개 추가
        notice3 = NoticeParseResult(
            symbols=["ETH"],
            notice_type="warning",
            exchange="upbit",
            raw_title="ETH 출금 중단",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.TRADE,
        )

        await executor.process_event(notice1)
        await executor.process_event(notice2)
        await executor.process_event(notice3)

        btc_events = executor.get_events_by_symbol("BTC")
        eth_events = executor.get_events_by_symbol("ETH")

        assert len(btc_events) == 2
        assert len(eth_events) == 1

    @pytest.mark.asyncio
    async def test_clear_history(self, executor):
        """히스토리 초기화."""
        notice = NoticeParseResult(
            symbols=["BTC"],
            notice_type="warning",
            exchange="upbit",
            raw_title="BTC 출금 중단",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.TRADE,
        )

        await executor.process_event(notice)
        assert len(executor.get_recent_events()) == 1

        executor.clear_history()
        assert len(executor.get_recent_events()) == 0


class TestStrategyAlert:
    """전략 알림 포맷 테스트."""

    def test_format_buy_opportunity_alert(self):
        """매수 기회 알림 포맷."""
        recommendation = StrategyRecommendation(
            strategy_type=StrategyType.BUY_OPPORTUNITY,
            symbol="BTC",
            exchange="upbit",
            event_type="warning",
            severity=EventSeverity.MEDIUM,
            action=EventAction.TRADE,
            recommended_action="BUY",
            reason="출금 중단으로 프리미엄 상승 예상",
            expected_roi=2.5,
            confidence=0.7,
            risk_level="medium",
            max_hold_time=180,
        )

        alert = format_strategy_alert(recommendation)

        assert "이벤트 전략 알림" in alert
        assert "BUY" in alert
        assert "BTC" in alert
        assert "upbit" in alert
        assert "출금 중단" in alert
        assert "2.5%" in alert or "+2.5%" in alert
        assert "70%" in alert
        assert "3시간" in alert

    def test_format_critical_alert(self):
        """긴급 알림 포맷 (디페깅)."""
        recommendation = StrategyRecommendation(
            strategy_type=StrategyType.SAFETY_CHECK,
            symbol="USDT",
            exchange="upbit",
            event_type="depeg",
            severity=EventSeverity.CRITICAL,
            action=EventAction.ALERT,
            recommended_action="SELL",
            reason="USDT 디페깅 감지. 즉시 청산 권장",
            expected_roi=-5.0,
            confidence=0.9,
            risk_level="critical",
            stop_loss=-10.0,
        )

        alert = format_strategy_alert(recommendation)

        assert "🚨" in alert  # CRITICAL 이모지
        assert "SELL" in alert
        assert "USDT" in alert
        assert "즉시 청산" in alert
        assert "critical" in alert


class TestNoActionEvents:
    """조치 불필요 이벤트 테스트."""

    @pytest.mark.asyncio
    async def test_no_action_event_returns_none(self, executor):
        """NONE action 이벤트는 None 반환."""
        notice = NoticeParseResult(
            symbols=["BTC"],
            notice_type="unknown",
            exchange="upbit",
            raw_title="[공지] 서버 점검 안내",
            event_severity=EventSeverity.LOW,
            event_action=EventAction.NONE,
        )

        result = await executor.process_event(notice)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_symbols_returns_none(self, executor):
        """심볼 없는 이벤트는 None 반환."""
        notice = NoticeParseResult(
            symbols=[],
            notice_type="warning",
            exchange="upbit",
            raw_title="[공지] 시스템 점검",
            event_severity=EventSeverity.MEDIUM,
            event_action=EventAction.MONITOR,
        )

        result = await executor.process_event(notice)

        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
