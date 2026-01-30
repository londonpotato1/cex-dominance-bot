"""공지 파서 테스트 (Phase 4)."""

import pytest
from collectors.notice_parser import (
    BithumbNoticeParser,
    NoticeParseResult,
)


@pytest.fixture
def bithumb_parser():
    """BithumbNoticeParser 인스턴스."""
    return BithumbNoticeParser()


class TestBithumbNoticeParser:
    """빗썸 공지 파서 테스트."""

    class TestListingDetection:
        """상장 공지 감지."""

        def test_detect_listing_market_add(self, bithumb_parser):
            """'마켓 추가' 감지."""
            title = "[마켓 추가] 비트코인(BTC) 원화 마켓 추가"
            assert bithumb_parser.is_listing_notice(title) is True

        def test_detect_listing_new_listing(self, bithumb_parser):
            """'신규 상장' 감지."""
            title = "[신규 상장] 솔라나(SOL) KRW 마켓 오픈 안내"
            assert bithumb_parser.is_listing_notice(title) is True

        def test_detect_listing_market_open(self, bithumb_parser):
            """'마켓 오픈' 감지."""
            title = "이더리움(ETH) 원화 마켓 오픈 안내"
            assert bithumb_parser.is_listing_notice(title) is True

        def test_ignore_non_listing(self, bithumb_parser):
            """비상장 공지 무시."""
            title = "[공지] 서버 점검 안내"
            assert bithumb_parser.is_listing_notice(title) is False

        def test_ignore_maintenance(self, bithumb_parser):
            """점검 공지 무시."""
            title = "[점검 안내] 지갑 점검 안내"
            assert bithumb_parser.is_listing_notice(title) is False

    class TestSymbolExtraction:
        """심볼 추출."""

        def test_extract_symbol_parentheses(self, bithumb_parser):
            """괄호 형식: (SENT)."""
            title = "[마켓 추가] 센티넬(SENT) 원화 마켓 추가"
            result = bithumb_parser.parse(title)

            assert result.notice_type == "listing"
            assert "SENT" in result.symbols

        def test_extract_symbol_slash(self, bithumb_parser):
            """슬래시 형식: SENT/KRW."""
            title = "[신규 상장] SENT/KRW 마켓 추가 안내"  # 상장 키워드 명시
            result = bithumb_parser.parse(title)

            assert result.notice_type == "listing"
            assert "SENT" in result.symbols

        def test_extract_symbol_underscore(self, bithumb_parser):
            """언더스코어 형식: ELSA_KRW."""
            title = "[마켓 추가] ELSA_KRW 마켓 신규 오픈"  # 상장 키워드 명시
            result = bithumb_parser.parse(title)

            assert result.notice_type == "listing"

            assert "ELSA" in result.symbols

        def test_extract_symbol_space(self, bithumb_parser):
            """공백 형식: XYZ 원화."""
            title = "[신규 상장] XYZ 원화 마켓 신규 상장"  # 상장 키워드 명시
            result = bithumb_parser.parse(title)

            assert result.notice_type == "listing"
            assert "XYZ" in result.symbols

        def test_extract_multiple_symbols(self, bithumb_parser):
            """복수 심볼 추출."""
            title = "[마켓 추가] 센티넬(SENT), 엘사(ELSA) 원화 마켓 추가"
            result = bithumb_parser.parse(title)

            assert "SENT" in result.symbols
            assert "ELSA" in result.symbols
            assert len(result.symbols) == 2

        def test_exclude_common_words(self, bithumb_parser):
            """일반 단어 제외."""
            title = "[신규 상장] NEW 코인(XYZ) KRW 마켓 오픈"
            result = bithumb_parser.parse(title)

            assert "XYZ" in result.symbols
            assert "NEW" not in result.symbols
            assert "KRW" not in result.symbols

        def test_exclude_usdt_btc_eth(self, bithumb_parser):
            """기축 통화 제외."""
            title = "[마켓 추가] 테스트(TEST) BTC/USDT 마켓 추가"
            result = bithumb_parser.parse(title)

            assert "TEST" in result.symbols
            assert "BTC" not in result.symbols
            assert "USDT" not in result.symbols

    class TestTimeExtraction:
        """상장 시간 추출."""

        def test_extract_time_colon(self, bithumb_parser):
            """콜론 시간: 14:00."""
            title = "상장 안내"
            content = "거래 시작 시간: 2024-01-15 14:00 KST"
            result = bithumb_parser.parse(title, content)

            assert result.listing_time is not None
            assert "14:00" in result.listing_time

        def test_extract_time_korean_pm(self, bithumb_parser):
            """한국어 오후 시간: 오후 2시 30분."""
            title = "상장 안내"
            content = "거래 시작 시간: 오후 2시 30분"
            result = bithumb_parser.parse(title, content)

            assert result.listing_time is not None
            assert "14:30" in result.listing_time

        def test_extract_time_korean_am(self, bithumb_parser):
            """한국어 오전 시간: 오전 11시."""
            title = "상장 안내"
            content = "거래 시작 시간: 오전 11시"
            result = bithumb_parser.parse(title, content)

            assert result.listing_time is not None
            assert "11:00" in result.listing_time

        def test_extract_time_from_title(self, bithumb_parser):
            """제목에서 시간 추출."""
            title = "[마켓 추가] 비트코인(BTC) 14:00 오픈"
            result = bithumb_parser.parse(title)

            assert result.listing_time is not None
            assert "14:00" in result.listing_time

        def test_no_time_found(self, bithumb_parser):
            """시간 미발견."""
            title = "[마켓 추가] 비트코인(BTC) 마켓 추가"
            result = bithumb_parser.parse(title)

            assert result.listing_time is None

    class TestNoticeParseResult:
        """NoticeParseResult 테스트."""

        def test_result_fields(self, bithumb_parser):
            """결과 필드 검증."""
            title = "[마켓 추가] 테스트(TEST) 원화 마켓 추가"
            result = bithumb_parser.parse(
                title,
                notice_id="12345",
                notice_url="https://bithumb.com/notice/12345",
            )

            assert result.exchange == "bithumb"
            assert result.notice_type == "listing"
            assert result.raw_title == title
            assert result.notice_id == "12345"
            assert result.notice_url == "https://bithumb.com/notice/12345"

        def test_symbol_property(self, bithumb_parser):
            """symbol 프로퍼티 (하위 호환)."""
            title = "[마켓 추가] 테스트(TEST) 원화 마켓 추가"
            result = bithumb_parser.parse(title)

            # symbol 프로퍼티는 첫 번째 심볼 반환
            assert result.symbol == "TEST"
            assert result.symbol == result.symbols[0]

        def test_unknown_notice_type(self, bithumb_parser):
            """비상장 공지 타입."""
            title = "[공지] 서버 점검 안내"
            result = bithumb_parser.parse(title)

            assert result.notice_type == "unknown"
            assert len(result.symbols) == 0
            assert result.symbol is None


class TestEdgeCases:
    """엣지 케이스."""

    def test_empty_title(self, bithumb_parser):
        """빈 제목."""
        result = bithumb_parser.parse("")
        assert result.notice_type == "unknown"

    def test_long_symbol(self, bithumb_parser):
        """긴 심볼 (10자)."""
        title = "[마켓 추가] 테스트코인(TESTCOINXX) 원화 마켓 추가"
        result = bithumb_parser.parse(title)

        assert "TESTCOINXX" in result.symbols

    def test_short_symbol(self, bithumb_parser):
        """짧은 심볼 (2자)."""
        title = "[마켓 추가] 오엠지(OM) 원화 마켓 추가"
        result = bithumb_parser.parse(title)

        assert "OM" in result.symbols

    def test_unicode_in_title(self, bithumb_parser):
        """유니코드 제목."""
        title = "[마켓 추가] 🚀 센티넬(SENT) 원화 마켓 추가 🎉"
        result = bithumb_parser.parse(title)

        assert "SENT" in result.symbols

    def test_duplicate_symbols(self, bithumb_parser):
        """중복 심볼 제거."""
        title = "[마켓 추가] 센티넬(SENT) SENT/KRW 마켓"
        result = bithumb_parser.parse(title)

        # 중복 제거 후 1개만
        assert result.symbols.count("SENT") == 1

    def test_content_symbols_added(self, bithumb_parser):
        """본문에서 추가 심볼 추출."""
        title = "[마켓 추가] 원화 마켓 추가"
        content = "다음 코인이 상장됩니다: 테스트(TEST), 샘플(SAMPLE)"
        result = bithumb_parser.parse(title, content)

        assert "TEST" in result.symbols
        assert "SAMPLE" in result.symbols


class TestRealWorldExamples:
    """실제 공지 예시 테스트."""

    def test_real_bithumb_listing_1(self, bithumb_parser):
        """실제 빗썸 상장 공지 1."""
        title = "[마켓 추가] 센티넬프로토콜(UPP) 원화 마켓 추가"
        result = bithumb_parser.parse(title)

        assert result.notice_type == "listing"
        assert "UPP" in result.symbols

    def test_real_bithumb_listing_2(self, bithumb_parser):
        """실제 빗썸 상장 공지 2."""
        title = "[신규 상장] 신규 코인 상장 예정 안내"
        content = "에어드랍(AIRDROP) 코인이 2024년 1월 15일 14:00에 상장됩니다."
        result = bithumb_parser.parse(title, content)

        assert result.notice_type == "listing"
        assert "AIRDROP" in result.symbols
        assert "14:00" in result.listing_time

    def test_real_bithumb_listing_3(self, bithumb_parser):
        """실제 빗썸 상장 공지 3 (다중 심볼)."""
        title = "[마켓 추가] 스텝(STEP), 러너(RUN) 원화 마켓 추가"
        result = bithumb_parser.parse(title)

        assert result.notice_type == "listing"
        assert "STEP" in result.symbols
        assert "RUN" in result.symbols


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
