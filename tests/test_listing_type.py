"""상장 유형 분류기 테스트 (Phase 4)."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from analysis.listing_type import (
    ListingType,
    ListingTypeClassifier,
    ListingTypeResult,
)


@pytest.fixture
def classifier():
    """ListingTypeClassifier 인스턴스."""
    return ListingTypeClassifier()


@pytest.fixture
def mock_registry():
    """Mock TokenRegistry."""
    registry = MagicMock()
    # 기본: 국내 경쟁 거래소 없음
    registry.get_domestic_listings = AsyncMock(return_value=[])
    return registry


class TestTGEClassification:
    """TGE (Token Generation Event) 분류."""

    @pytest.mark.asyncio
    async def test_tge_no_top_exchange(self, classifier):
        """top_exchange 없음 → TGE."""
        result = await classifier.classify(
            symbol="NEWCOIN",
            exchange="upbit",
            top_exchange="",  # 글로벌 주요 거래소 없음
            first_listed_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        assert result.listing_type == ListingType.TGE
        assert result.confidence >= 0.6

    @pytest.mark.asyncio
    async def test_tge_recent_listing(self, classifier):
        """최근 생성 (7일 이내) → TGE."""
        result = await classifier.classify(
            symbol="NEWCOIN",
            exchange="upbit",
            top_exchange="",
            first_listed_at=datetime.now(timezone.utc) - timedelta(days=3),
        )

        assert result.listing_type == ListingType.TGE
        assert result.confidence >= 0.85  # 시간 정보 있으면 높은 신뢰도

    @pytest.mark.asyncio
    async def test_tge_no_time_info(self, classifier):
        """시간 정보 없음 → 낮은 신뢰도."""
        result = await classifier.classify(
            symbol="NEWCOIN",
            exchange="upbit",
            top_exchange="",
            first_listed_at=None,
        )

        assert result.listing_type == ListingType.TGE
        assert result.confidence < 0.7  # 시간 정보 없으면 낮은 신뢰도

    @pytest.mark.asyncio
    async def test_not_tge_old_token(self, classifier):
        """오래된 토큰 → TGE 아님."""
        result = await classifier.classify(
            symbol="OLDCOIN",
            exchange="upbit",
            top_exchange="binance",  # 글로벌 거래소 있음
            first_listed_at=datetime.now(timezone.utc) - timedelta(days=100),
        )

        # TGE가 아니고 DIRECT
        assert result.listing_type != ListingType.TGE


class TestSIDEClassification:
    """SIDE (옆상장) 분류."""

    @pytest.mark.asyncio
    async def test_side_bithumb_competitor(self, classifier, mock_registry):
        """빗썸이 먼저 상장 → SIDE."""
        classifier_with_registry = ListingTypeClassifier(registry=mock_registry)

        # _is_listed_on_exchange를 mock하여 bithumb에 상장됨을 반환
        async def mock_is_listed(symbol, exchange, session=None):
            return exchange == "bithumb"

        classifier_with_registry._is_listed_on_exchange = AsyncMock(side_effect=mock_is_listed)

        result = await classifier_with_registry.classify(
            symbol="TEST",
            exchange="upbit",
            top_exchange="binance",
        )

        assert result.listing_type == ListingType.SIDE
        assert result.domestic_competitor == "bithumb"

    @pytest.mark.asyncio
    async def test_side_upbit_competitor(self, classifier, mock_registry):
        """업비트가 먼저 상장 → SIDE."""
        classifier_with_registry = ListingTypeClassifier(registry=mock_registry)

        # _is_listed_on_exchange를 mock하여 upbit에 상장됨을 반환
        async def mock_is_listed(symbol, exchange, session=None):
            return exchange == "upbit"

        classifier_with_registry._is_listed_on_exchange = AsyncMock(side_effect=mock_is_listed)

        result = await classifier_with_registry.classify(
            symbol="TEST",
            exchange="bithumb",
            top_exchange="binance",
        )

        assert result.listing_type == ListingType.SIDE
        assert result.domestic_competitor == "upbit"

    @pytest.mark.asyncio
    async def test_side_priority_over_direct(self, classifier, mock_registry):
        """SIDE가 DIRECT보다 우선."""
        classifier_with_registry = ListingTypeClassifier(registry=mock_registry)

        # _is_listed_on_exchange를 mock하여 bithumb에 상장됨을 반환
        async def mock_is_listed(symbol, exchange, session=None):
            return exchange == "bithumb"

        classifier_with_registry._is_listed_on_exchange = AsyncMock(side_effect=mock_is_listed)

        result = await classifier_with_registry.classify(
            symbol="TEST",
            exchange="upbit",
            top_exchange="binance",  # 해외 거래소도 있음
        )

        # DIRECT가 아니라 SIDE로 분류
        assert result.listing_type == ListingType.SIDE


class TestDIRECTClassification:
    """DIRECT (직상장) 분류."""

    @pytest.mark.asyncio
    async def test_direct_with_top_exchange(self, classifier):
        """해외 거래소 있음 + 국내 경쟁 없음 → DIRECT."""
        result = await classifier.classify(
            symbol="TEST",
            exchange="upbit",
            top_exchange="binance",
        )

        assert result.listing_type == ListingType.DIRECT
        assert result.top_exchange == "binance"

    @pytest.mark.asyncio
    async def test_direct_confidence(self, classifier):
        """DIRECT 신뢰도."""
        result = await classifier.classify(
            symbol="TEST",
            exchange="upbit",
            top_exchange="okx",
        )

        assert result.listing_type == ListingType.DIRECT
        assert result.confidence >= 0.7


class TestUNKNOWNClassification:
    """UNKNOWN 분류."""

    @pytest.mark.asyncio
    async def test_unknown_no_data(self, classifier):
        """데이터 부족 → UNKNOWN."""
        result = await classifier.classify(
            symbol="MYSTERY",
            exchange="upbit",
            top_exchange="",  # 글로벌 거래소 없음
            first_listed_at=datetime.now(timezone.utc) - timedelta(days=100),  # 오래됨
        )

        # 오래됐는데 top_exchange 없음 → 애매함
        # TGE도 아니고 DIRECT도 아님 → UNKNOWN 가능
        assert result.listing_type in (ListingType.UNKNOWN, ListingType.TGE)


class TestClassificationPriority:
    """분류 우선순위 테스트."""

    @pytest.mark.asyncio
    async def test_priority_side_over_tge(self, classifier, mock_registry):
        """SIDE > TGE 우선순위."""
        classifier_with_registry = ListingTypeClassifier(registry=mock_registry)

        # _is_listed_on_exchange를 mock하여 bithumb에 상장됨을 반환
        async def mock_is_listed(symbol, exchange, session=None):
            return exchange == "bithumb"

        classifier_with_registry._is_listed_on_exchange = AsyncMock(side_effect=mock_is_listed)

        result = await classifier_with_registry.classify(
            symbol="TEST",
            exchange="upbit",
            top_exchange="",  # TGE 조건
            first_listed_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        # 국내 경쟁 거래소 있으면 SIDE (TGE 아님)
        assert result.listing_type == ListingType.SIDE

    @pytest.mark.asyncio
    async def test_priority_side_over_direct(self, classifier, mock_registry):
        """SIDE > DIRECT 우선순위."""
        classifier_with_registry = ListingTypeClassifier(registry=mock_registry)

        # _is_listed_on_exchange를 mock하여 upbit에 상장됨을 반환
        async def mock_is_listed(symbol, exchange, session=None):
            return exchange == "upbit"

        classifier_with_registry._is_listed_on_exchange = AsyncMock(side_effect=mock_is_listed)

        result = await classifier_with_registry.classify(
            symbol="TEST",
            exchange="bithumb",
            top_exchange="binance",  # DIRECT 조건
        )

        # 국내 경쟁 거래소 있으면 SIDE (DIRECT 아님)
        assert result.listing_type == ListingType.SIDE


class TestListingTypeResult:
    """ListingTypeResult 테스트."""

    @pytest.mark.asyncio
    async def test_result_fields(self, classifier):
        """ListingTypeResult 필드 검증."""
        result = await classifier.classify(
            symbol="TEST",
            exchange="upbit",
            top_exchange="binance",
        )

        assert hasattr(result, "listing_type")
        assert hasattr(result, "confidence")
        assert hasattr(result, "top_exchange")
        assert hasattr(result, "first_listed_at")
        assert hasattr(result, "domestic_competitor")
        assert hasattr(result, "reason")

    @pytest.mark.asyncio
    async def test_result_reason(self, classifier):
        """분류 사유 기록."""
        result = await classifier.classify(
            symbol="TEST",
            exchange="upbit",
            top_exchange="binance",
        )

        # 사유 문자열 존재
        assert len(result.reason) > 0


class TestEdgeCases:
    """엣지 케이스."""

    @pytest.mark.asyncio
    async def test_empty_symbol(self, classifier):
        """빈 심볼."""
        result = await classifier.classify(
            symbol="",
            exchange="upbit",
            top_exchange="binance",
        )

        # 빈 심볼도 처리 가능 (UNKNOWN 가능)
        assert result.listing_type in ListingType

    @pytest.mark.asyncio
    async def test_unknown_exchange(self, classifier):
        """알 수 없는 거래소."""
        result = await classifier.classify(
            symbol="TEST",
            exchange="unknown_exchange",
            top_exchange="binance",
        )

        # 알 수 없는 거래소도 처리
        assert result.listing_type in ListingType

    @pytest.mark.asyncio
    async def test_same_exchange_as_top(self, classifier):
        """상장 거래소와 top_exchange 동일."""
        result = await classifier.classify(
            symbol="TEST",
            exchange="binance",  # top과 동일
            top_exchange="binance",
        )

        # 동일해도 처리 가능
        assert result.listing_type in ListingType

    @pytest.mark.asyncio
    async def test_future_listing_time(self, classifier):
        """미래 상장 시각 (예약 상장)."""
        result = await classifier.classify(
            symbol="FUTURE",
            exchange="upbit",
            top_exchange="",
            first_listed_at=datetime.now(timezone.utc) + timedelta(days=1),
        )

        # 미래 시각도 처리 (TGE로 간주 가능)
        assert result.listing_type in ListingType


class TestConfidence:
    """신뢰도 테스트."""

    @pytest.mark.asyncio
    async def test_high_confidence_side(self, classifier, mock_registry):
        """SIDE 높은 신뢰도."""
        classifier_with_registry = ListingTypeClassifier(registry=mock_registry)

        # _is_listed_on_exchange를 mock하여 bithumb에 상장됨을 반환
        async def mock_is_listed(symbol, exchange, session=None):
            return exchange == "bithumb"

        classifier_with_registry._is_listed_on_exchange = AsyncMock(side_effect=mock_is_listed)

        result = await classifier_with_registry.classify(
            symbol="TEST",
            exchange="upbit",
            top_exchange="binance",
        )

        # SIDE는 신뢰도 0.95
        assert result.confidence >= 0.95

    @pytest.mark.asyncio
    async def test_medium_confidence_tge(self, classifier):
        """TGE 중간 신뢰도 (시간 정보 있음)."""
        result = await classifier.classify(
            symbol="TEST",
            exchange="upbit",
            top_exchange="",
            first_listed_at=datetime.now(timezone.utc) - timedelta(days=2),
        )

        # TGE + 시간 정보 = 0.85
        assert result.confidence >= 0.85

    @pytest.mark.asyncio
    async def test_low_confidence_unknown(self, classifier):
        """UNKNOWN 낮은 신뢰도."""
        result = await classifier.classify(
            symbol="TEST",
            exchange="upbit",
            top_exchange="",  # 정보 부족
            first_listed_at=datetime.now(timezone.utc) - timedelta(days=365),  # 오래됨
        )

        # UNKNOWN 또는 낮은 신뢰도
        if result.listing_type == ListingType.UNKNOWN:
            assert result.confidence <= 0.5


class TestRealWorldScenarios:
    """실제 시나리오 테스트."""

    @pytest.mark.asyncio
    async def test_scenario_new_token_tge(self, classifier):
        """시나리오: 세계 최초 상장."""
        result = await classifier.classify(
            symbol="NEWTOKEN",
            exchange="upbit",
            top_exchange="",
            first_listed_at=datetime.now(timezone.utc) - timedelta(hours=12),
        )

        assert result.listing_type == ListingType.TGE

    @pytest.mark.asyncio
    async def test_scenario_binance_listed_direct(self, classifier):
        """시나리오: 바이낸스 기존 상장 → 업비트 신규."""
        result = await classifier.classify(
            symbol="BTCUSDT",
            exchange="upbit",
            top_exchange="binance",
            first_listed_at=datetime(2017, 7, 1, tzinfo=timezone.utc),  # 오래됨
        )

        assert result.listing_type == ListingType.DIRECT

    @pytest.mark.asyncio
    async def test_scenario_upbit_then_bithumb_side(self, classifier, mock_registry):
        """시나리오: 업비트 먼저, 빗썸 나중 (옆상장)."""
        classifier_with_registry = ListingTypeClassifier(registry=mock_registry)

        # _is_listed_on_exchange를 mock하여 upbit에 상장됨을 반환
        async def mock_is_listed(symbol, exchange, session=None):
            return exchange == "upbit"

        classifier_with_registry._is_listed_on_exchange = AsyncMock(side_effect=mock_is_listed)

        result = await classifier_with_registry.classify(
            symbol="XYZ",
            exchange="bithumb",
            top_exchange="binance",
        )

        assert result.listing_type == ListingType.SIDE
        assert result.domestic_competitor == "upbit"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
