"""프리미엄 계산기 테스트 (Phase 4)."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import aiohttp

from analysis.premium import (
    PremiumCalculator,
    PremiumResult,
    VWAPResult,
    _get_fallback_fx,
)

# 테스트용 fallback 값
_HARDCODED_FX = _get_fallback_fx()


@pytest.fixture
def mock_writer():
    """Mock DatabaseWriter."""
    return MagicMock()


@pytest.fixture
def premium_calculator(mock_writer):
    """PremiumCalculator 인스턴스."""
    return PremiumCalculator(writer=mock_writer)


class TestPremiumCalculation:
    """프리미엄 퍼센트 계산 테스트."""

    @pytest.mark.asyncio
    async def test_positive_premium(self, premium_calculator):
        """양의 프리미엄 (김프)."""
        result = await premium_calculator.calculate_premium(
            krw_price=1_500_000,       # 150만원
            global_usd_price=1000.0,   # $1,000
            fx_rate=1350.0,            # 1,350원/달러
            fx_source="btc_implied",
        )

        # 예상 프리미엄: (1,500,000 / 1,350,000) - 1 = 0.1111 = 11.11%
        assert result.premium_pct > 0
        assert abs(result.premium_pct - 11.11) < 0.1

    @pytest.mark.asyncio
    async def test_negative_premium(self, premium_calculator):
        """음의 프리미엄 (역프)."""
        result = await premium_calculator.calculate_premium(
            krw_price=1_200_000,       # 120만원
            global_usd_price=1000.0,   # $1,000
            fx_rate=1350.0,            # 1,350원/달러
            fx_source="btc_implied",
        )

        # 예상 프리미엄: (1,200,000 / 1,350,000) - 1 = -0.1111 = -11.11%
        assert result.premium_pct < 0

    @pytest.mark.asyncio
    async def test_zero_premium(self, premium_calculator):
        """0% 프리미엄 (글로벌 = 국내)."""
        result = await premium_calculator.calculate_premium(
            krw_price=1_350_000,       # 135만원
            global_usd_price=1000.0,   # $1,000
            fx_rate=1350.0,            # 1,350원/달러
            fx_source="btc_implied",
        )

        # 예상 프리미엄: (1,350,000 / 1,350,000) - 1 = 0%
        assert abs(result.premium_pct) < 0.01

    @pytest.mark.asyncio
    async def test_premium_result_fields(self, premium_calculator):
        """PremiumResult 필드 검증."""
        result = await premium_calculator.calculate_premium(
            krw_price=1_500_000,
            global_usd_price=1000.0,
            fx_rate=1350.0,
            fx_source="btc_implied",
        )

        assert isinstance(result, PremiumResult)
        assert result.krw_price == 1_500_000
        assert result.global_usd_price == 1000.0
        assert result.fx_rate == 1350.0
        assert result.fx_source == "btc_implied"


class TestFXFallbackChain:
    """FX 5단계 폴백 체인 테스트."""

    @pytest.mark.asyncio
    async def test_fx_btc_implied_success(self, premium_calculator):
        """1단계: BTC Implied FX 성공."""
        # Mock the internal method
        with patch.object(
            premium_calculator, "_try_btc_implied",
            new_callable=AsyncMock,
            return_value=(1400.0, "btc_implied"),
        ):
            async with aiohttp.ClientSession() as session:
                fx_rate, fx_source = await premium_calculator.get_implied_fx(session)

        assert fx_rate == 1400.0
        assert fx_source == "btc_implied"

    @pytest.mark.asyncio
    async def test_fx_fallback_to_eth(self, premium_calculator):
        """2단계: ETH Implied FX 폴백."""
        with patch.object(
            premium_calculator, "_try_btc_implied",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with patch.object(
                premium_calculator, "_try_eth_implied",
                new_callable=AsyncMock,
                return_value=(1380.0, "eth_implied"),
            ):
                async with aiohttp.ClientSession() as session:
                    fx_rate, fx_source = await premium_calculator.get_implied_fx(session)

        assert fx_rate == 1380.0
        assert fx_source == "eth_implied"

    @pytest.mark.asyncio
    async def test_fx_fallback_to_usdt(self, premium_calculator):
        """3단계: USDT/KRW 직접 폴백."""
        with patch.object(
            premium_calculator, "_try_btc_implied",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with patch.object(
                premium_calculator, "_try_eth_implied",
                new_callable=AsyncMock,
                return_value=None,
            ):
                with patch.object(
                    premium_calculator, "_try_usdt_krw",
                    new_callable=AsyncMock,
                    return_value=(1360.0, "usdt_krw"),
                ):
                    async with aiohttp.ClientSession() as session:
                        fx_rate, fx_source = await premium_calculator.get_implied_fx(session)

        assert fx_rate == 1360.0
        assert fx_source == "usdt_krw"

    @pytest.mark.asyncio
    async def test_fx_fallback_to_hardcoded(self, premium_calculator):
        """5단계: 하드코딩 기본값 폴백."""
        # 모든 폴백 실패
        with patch.object(
            premium_calculator, "_try_btc_implied",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with patch.object(
                premium_calculator, "_try_eth_implied",
                new_callable=AsyncMock,
                return_value=None,
            ):
                with patch.object(
                    premium_calculator, "_try_usdt_krw",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    # 캐시도 없음
                    premium_calculator._fx_cache = None

                    async with aiohttp.ClientSession() as session:
                        fx_rate, fx_source = await premium_calculator.get_implied_fx(session)

        assert fx_rate == _HARDCODED_FX
        assert fx_source == "hardcoded_fallback"


class TestFXCache:
    """FX 캐시 테스트."""

    @pytest.mark.asyncio
    async def test_fx_cache_used(self, premium_calculator):
        """캐시된 FX 사용."""
        import time

        # 캐시 설정 (5분 이내)
        premium_calculator._fx_cache = (1400.0, "btc_implied", time.time() - 60)

        with patch.object(
            premium_calculator, "_try_btc_implied",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with patch.object(
                premium_calculator, "_try_eth_implied",
                new_callable=AsyncMock,
                return_value=None,
            ):
                with patch.object(
                    premium_calculator, "_try_usdt_krw",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    async with aiohttp.ClientSession() as session:
                        fx_rate, fx_source = await premium_calculator.get_implied_fx(session)

        # 캐시 사용됨 (원본 소스 유지)
        assert fx_rate == 1400.0
        assert fx_source == "btc_implied"

    @pytest.mark.asyncio
    async def test_fx_cache_expired(self, premium_calculator):
        """만료된 캐시 무시."""
        import time

        # 만료된 캐시 (5분 초과)
        premium_calculator._fx_cache = (1400.0, "btc_implied", time.time() - 400)

        with patch.object(
            premium_calculator, "_try_btc_implied",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with patch.object(
                premium_calculator, "_try_eth_implied",
                new_callable=AsyncMock,
                return_value=None,
            ):
                with patch.object(
                    premium_calculator, "_try_usdt_krw",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    async with aiohttp.ClientSession() as session:
                        fx_rate, fx_source = await premium_calculator.get_implied_fx(session)

        # 하드코딩 기본값으로 폴백
        assert fx_rate == _HARDCODED_FX
        assert fx_source == "hardcoded_fallback"


class TestVWAPResult:
    """VWAPResult 테스트."""

    def test_vwap_result_fields(self):
        """VWAPResult 필드 검증."""
        vwap = VWAPResult(
            price_usd=100_000.0,
            total_volume_usd=500_000_000.0,
            sources=["binance", "okx", "bybit"],
        )

        assert vwap.price_usd == 100_000.0
        assert vwap.total_volume_usd == 500_000_000.0
        assert len(vwap.sources) == 3


class TestEdgeCases:
    """엣지 케이스 테스트."""

    @pytest.mark.asyncio
    async def test_zero_global_price(self, premium_calculator):
        """글로벌 가격 0 처리."""
        # 0으로 나누기 방지 확인
        result = await premium_calculator.calculate_premium(
            krw_price=1_500_000,
            global_usd_price=0.0,  # 0
            fx_rate=1350.0,
            fx_source="btc_implied",
        )

        # 0으로 나누기 시 적절한 처리 (inf 또는 0)
        assert result.premium_pct == 0 or result.premium_pct == float("inf")

    @pytest.mark.asyncio
    async def test_zero_fx_rate(self, premium_calculator):
        """FX 환율 0 처리."""
        result = await premium_calculator.calculate_premium(
            krw_price=1_500_000,
            global_usd_price=1000.0,
            fx_rate=0.0,  # 0
            fx_source="error",
        )

        # 0으로 나누기 시 적절한 처리
        assert result.premium_pct == 0 or result.premium_pct == float("inf")

    @pytest.mark.asyncio
    async def test_very_high_premium(self, premium_calculator):
        """극단적 프리미엄 (100%+)."""
        result = await premium_calculator.calculate_premium(
            krw_price=3_000_000,       # 300만원
            global_usd_price=1000.0,   # $1,000
            fx_rate=1350.0,            # 1,350원/달러
            fx_source="btc_implied",
        )

        # 예상 프리미엄: (3,000,000 / 1,350,000) - 1 = 122.22%
        assert result.premium_pct > 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
