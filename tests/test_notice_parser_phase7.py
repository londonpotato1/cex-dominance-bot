"""Phase 7: 이벤트 아비트라지 패턴 테스트.

WARNING/HALT/MIGRATION/DEPEG 감지 및 심각도/조치 분류 검증.
"""

import pytest
from collectors.notice_parser import (
    BithumbNoticeParser,
    UpbitNoticeParser,
    EventSeverity,
    EventAction,
)


@pytest.fixture
def bithumb_parser():
    """BithumbNoticeParser 인스턴스."""
    return BithumbNoticeParser()


@pytest.fixture
def upbit_parser():
    """UpbitNoticeParser 인스턴스."""
    return UpbitNoticeParser()


class TestWARNINGDetection:
    """WARNING (출금 중단) 감지 테스트."""

    def test_withdrawal_suspension_bithumb(self, bithumb_parser):
        """빗썸 출금 중단 감지."""
        title = "[공지] 이더리움(ETH) 출금 중단 안내"
        result = bithumb_parser.parse(title)

        assert result.notice_type == "warning"
        assert result.event_severity == EventSeverity.MEDIUM
        assert result.event_action == EventAction.TRADE  # 출금 중단 = 매수 기회
        assert "ETH" in result.symbols

    def test_withdrawal_suspension_upbit(self, upbit_parser):
        """업비트 입출금 중단 감지."""
        title = "[공지] 비트코인(BTC) 입출금 일시 중단"
        content = "지갑 점검으로 2026-01-30 14:00부터 입출금이 중단됩니다."
        result = upbit_parser.parse(title, content)

        assert result.notice_type == "warning"
        assert result.event_action == EventAction.TRADE
        assert "BTC" in result.symbols
        assert "14:00" in result.listing_time

    def test_wallet_maintenance(self, bithumb_parser):
        """지갑 점검 감지."""
        title = "[안내] 솔라나(SOL) 지갑 점검 안내"
        result = bithumb_parser.parse(title)

        assert result.notice_type == "warning"
        assert result.event_severity == EventSeverity.MEDIUM
        # 출금이 아닌 점검 → MONITOR
        assert result.event_action == EventAction.MONITOR

    def test_deposit_suspension(self, upbit_parser):
        """입금 중단 감지."""
        # "입금 중단" 또는 "입출금 중단" 키워드 사용
        title = "[공지] 폴리곤(MATIC) 입금 중단 안내"
        result = upbit_parser.parse(title)

        assert result.notice_type == "warning"
        assert "MATIC" in result.symbols


class TestHALTDetection:
    """HALT (거래 중단) 감지 테스트."""

    def test_trading_halt_bithumb(self, bithumb_parser):
        """빗썸 거래 중단 감지."""
        title = "[긴급] 루나(LUNA) 거래 일시 중단"
        result = bithumb_parser.parse(title)

        assert result.notice_type == "halt"
        assert result.event_severity == EventSeverity.HIGH
        assert result.event_action == EventAction.MONITOR
        assert "LUNA" in result.symbols

    def test_trading_halt_upbit(self, upbit_parser):
        """업비트 매매 정지 감지."""
        title = "[긴급] 테라(UST) 매매 정지 안내"
        content = "이상 거래 감지로 즉시 거래가 중단되었습니다."
        result = upbit_parser.parse(title, content)

        assert result.notice_type == "halt"
        assert result.event_severity == EventSeverity.HIGH
        assert "UST" in result.symbols

    def test_trading_suspension(self, bithumb_parser):
        """거래 정지 감지."""
        title = "[공지] 샌드박스(SAND) 거래 정지"
        result = bithumb_parser.parse(title)

        assert result.notice_type == "halt"
        assert result.event_action == EventAction.MONITOR


class TestMIGRATIONDetection:
    """MIGRATION (마이그레이션) 감지 테스트."""

    def test_token_swap_bithumb(self, bithumb_parser):
        """빗썸 토큰 스왑 감지."""
        # 심볼 패턴이 "(MATIC)"를 감지하도록 제목 수정
        title = "[안내] 폴리곤(MATIC) 토큰 전환"
        content = "기존 MATIC 토큰이 POL로 1:1 스왑됩니다."
        result = bithumb_parser.parse(title, content)

        assert result.notice_type == "migration"
        assert result.event_severity == EventSeverity.MEDIUM
        assert result.event_action == EventAction.ALERT
        assert "MATIC" in result.symbols

    def test_chain_migration_upbit(self, upbit_parser):
        """업비트 체인 변경 감지."""
        title = "[안내] 칠리즈(CHZ) 체인 변경 안내"
        result = upbit_parser.parse(title)

        assert result.notice_type == "migration"
        assert result.event_action == EventAction.ALERT
        assert "CHZ" in result.symbols

    def test_contract_change(self, bithumb_parser):
        """컨트랙트 변경 감지."""
        title = "[중요] 유니스왑(UNI) 컨트랙트 변경"
        result = bithumb_parser.parse(title)

        assert result.notice_type == "migration"
        assert "UNI" in result.symbols


class TestDEPEGDetection:
    """DEPEG (디페깅) 감지 테스트."""

    def test_price_crash_bithumb(self, bithumb_parser):
        """빗썸 가격 급락 감지."""
        title = "[긴급] USDT 가격 급락 안내"
        content = "USDT 시세가 급락하여 거래 주의가 필요합니다."
        result = bithumb_parser.parse(title, content)

        assert result.notice_type == "depeg"
        assert result.event_severity == EventSeverity.CRITICAL
        assert result.event_action == EventAction.ALERT
        assert "USDT" in result.symbols

    def test_abnormal_trading_upbit(self, upbit_parser):
        """업비트 이상 거래 감지."""
        title = "[긴급] 테라(UST) 이상 체결 안내"
        result = upbit_parser.parse(title)

        assert result.notice_type == "depeg"
        assert result.event_severity == EventSeverity.CRITICAL
        assert "UST" in result.symbols

    def test_price_error(self, bithumb_parser):
        """시세 오류 감지."""
        title = "[공지] 비트코인(BTC) 시세 오류 안내"
        result = bithumb_parser.parse(title)

        assert result.notice_type == "depeg"
        assert result.event_action == EventAction.ALERT


class TestEventPriority:
    """이벤트 우선순위 테스트."""

    def test_halt_over_warning(self, bithumb_parser):
        """HALT > WARNING 우선순위."""
        title = "[긴급] 이더리움(ETH) 거래 중단 및 출금 제한"
        result = bithumb_parser.parse(title)

        # 거래 중단(HALT)이 출금 제한(WARNING)보다 우선
        assert result.notice_type == "halt"
        assert result.event_severity == EventSeverity.HIGH

    def test_warning_over_listing(self, upbit_parser):
        """WARNING > LISTING 우선순위."""
        title = "[공지] 폴카닷(DOT) 신규 상장 및 입출금 중단"
        result = upbit_parser.parse(title)

        # 입출금 중단(WARNING)이 신규 상장(LISTING)보다 우선
        assert result.notice_type == "warning"
        assert result.event_action == EventAction.TRADE

    def test_depeg_over_migration(self, bithumb_parser):
        """DEPEG > MIGRATION 우선순위 (Phase 7 수정)."""
        title = "[긴급] USDT 가격 급락 및 스왑 안내"
        result = bithumb_parser.parse(title)

        # Phase 7 수정: 가격 급락(DEPEG)이 스왑(MIGRATION)보다 우선
        assert result.notice_type == "depeg"
        assert result.event_severity == EventSeverity.CRITICAL
        # Phase 7 수정: USDT도 심볼 추출 가능
        assert "USDT" in result.symbols


class TestEventDetails:
    """이벤트 상세 정보 테스트."""

    def test_event_details_fields(self, bithumb_parser):
        """event_details 필드 존재 확인."""
        title = "[공지] 센티넬(SENT) 출금 중단 안내"
        content = "2026-01-30 14:00부터 출금이 중단됩니다."
        result = bithumb_parser.parse(title, content)

        assert isinstance(result.event_details, dict)
        assert "has_time" in result.event_details
        assert "symbol_count" in result.event_details
        assert result.event_details["has_time"] is True
        assert result.event_details["symbol_count"] == 1

    def test_multiple_symbols_in_event(self, upbit_parser):
        """복수 심볼 이벤트."""
        title = "[공지] 비트코인(BTC), 이더리움(ETH) 출금 중단"
        result = upbit_parser.parse(title)

        assert result.notice_type == "warning"
        assert result.event_details["symbol_count"] == 2
        assert "BTC" in result.symbols
        assert "ETH" in result.symbols


class TestBackwardCompatibility:
    """하위 호환성 테스트."""

    def test_listing_still_works(self, bithumb_parser):
        """기존 상장 감지 동작 유지."""
        title = "[마켓 추가] 센티넬(SENT) 원화 마켓 추가"
        result = bithumb_parser.parse(title)

        assert result.notice_type == "listing"
        assert result.event_severity == EventSeverity.LOW
        assert result.event_action == EventAction.TRADE
        assert "SENT" in result.symbols

    def test_unknown_notice(self, upbit_parser):
        """알 수 없는 공지 처리."""
        title = "[공지] 서버 점검 안내"
        result = upbit_parser.parse(title)

        assert result.notice_type == "unknown"
        assert result.event_severity == EventSeverity.LOW
        assert result.event_action == EventAction.NONE

    def test_symbol_property_works(self, bithumb_parser):
        """symbol 프로퍼티 (하위 호환)."""
        title = "[공지] 비트코인(BTC) 출금 중단"
        result = bithumb_parser.parse(title)

        # symbols[0]과 symbol이 동일
        assert result.symbol == "BTC"
        assert result.symbol == result.symbols[0]


class TestRealWorldScenarios:
    """실제 시나리오 테스트."""

    def test_luna_crash_scenario(self, upbit_parser):
        """실제 사례: LUNA 폭락."""
        title = "[긴급] 루나(LUNA) 거래 일시 중단 안내"
        content = "이상 체결 감지로 거래가 즉시 중단되었습니다."
        result = upbit_parser.parse(title, content)

        assert result.notice_type == "halt"
        assert result.event_severity == EventSeverity.HIGH
        assert "LUNA" in result.symbols

    def test_matic_migration_scenario(self, bithumb_parser):
        """실제 사례: MATIC → POL 전환."""
        title = "[안내] 폴리곤(MATIC) POL 토큰 전환"
        content = "2024-09-04부터 MATIC이 POL로 1:1 스왑됩니다."
        result = bithumb_parser.parse(title, content)

        assert result.notice_type == "migration"
        assert result.event_action == EventAction.ALERT
        assert "MATIC" in result.symbols or "POL" in result.symbols

    def test_eth_withdrawal_suspension(self, upbit_parser):
        """실제 사례: ETH 출금 중단."""
        title = "[공지] 이더리움(ETH) 네트워크 점검에 따른 입출금 중단"
        content = "2026-01-30 14:00부터 약 2시간 동안 ETH 입출금이 중단됩니다."
        result = upbit_parser.parse(title, content)

        assert result.notice_type == "warning"
        assert result.event_action == EventAction.TRADE
        assert "ETH" in result.symbols
        assert "14:00" in result.listing_time


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
