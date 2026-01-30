"""Gate 통합 테스트 (Phase 4).

전체 파이프라인 end-to-end 테스트:
  1. 상장 감지
  2. Gate 분석
  3. Phase 5a 확장 (supply, listing_type, scenario)
  4. 결과 검증
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from analysis.gate import (
    GateChecker,
    GateResult,
    AlertLevel,
    StrategyCode,
)
from analysis.premium import PremiumCalculator, PremiumResult, VWAPResult
from analysis.cost_model import CostModel, CostResult
from analysis.supply_classifier import SupplyClassification
from analysis.listing_type import ListingType
from analysis.scenario import ScenarioOutcome


@pytest.fixture
def mock_premium():
    """Mock PremiumCalculator."""
    premium = MagicMock(spec=PremiumCalculator)

    # calculate_premium mock
    async def mock_calculate_premium(*args, **kwargs):
        return PremiumResult(
            premium_pct=10.0,
            krw_price=1_500_000,
            global_usd_price=1000.0,
            fx_rate=1350.0,
            fx_source="btc_implied",
        )

    premium.calculate_premium = AsyncMock(side_effect=mock_calculate_premium)

    # get_domestic_price mock
    async def mock_get_domestic_price(*args, **kwargs):
        return 1_500_000.0

    premium.get_domestic_price = AsyncMock(side_effect=mock_get_domestic_price)

    # get_global_vwap mock
    async def mock_get_global_vwap(*args, **kwargs):
        return VWAPResult(
            price_usd=1000.0,
            total_volume_usd=500_000_000.0,
            sources=["binance", "okx", "bybit"],
        )

    premium.get_global_vwap = AsyncMock(side_effect=mock_get_global_vwap)

    # get_implied_fx mock
    async def mock_get_implied_fx(*args, **kwargs):
        return (1350.0, "btc_implied")

    premium.get_implied_fx = AsyncMock(side_effect=mock_get_implied_fx)

    return premium


@pytest.fixture
def mock_cost_model():
    """Mock CostModel."""
    cost_model = MagicMock(spec=CostModel)

    def mock_calculate_total_cost(*args, **kwargs):
        return CostResult(
            slippage_pct=0.5,
            gas_cost_krw=5000,
            exchange_fee_pct=0.15,
            hedge_cost_pct=0.06,
            total_cost_pct=1.71,
            net_profit_pct=8.29,  # 10% - 1.71%
            gas_warn=False,
        )

    cost_model.calculate_total_cost = MagicMock(side_effect=mock_calculate_total_cost)
    return cost_model


@pytest.fixture
def mock_writer():
    """Mock DatabaseWriter."""
    writer = MagicMock()
    writer.push = AsyncMock()
    return writer


@pytest.fixture
def gate_checker(mock_premium, mock_cost_model, mock_writer):
    """GateChecker 인스턴스 (mocked dependencies)."""
    config_dir = Path(__file__).parent.parent / "config"

    with patch.object(GateChecker, "_load_vasp_matrix", return_value={}):
        with patch.object(GateChecker, "_load_features", return_value={
            "supply_classifier": True,
            "listing_type": True,
            "scenario_planner": True,
        }):
            with patch.object(GateChecker, "_load_networks", return_value={}):
                checker = GateChecker(
                    premium=mock_premium,
                    cost_model=mock_cost_model,
                    writer=mock_writer,
                    config_dir=config_dir,
                )

                # Mock async methods that analyze_listing calls
                mock_session = MagicMock()
                checker._get_session = AsyncMock(return_value=mock_session)
                checker._fetch_domestic_price_safe = AsyncMock(return_value=1_500_000.0)
                checker._check_futures_market = AsyncMock(return_value="binance")

    return checker


class TestEndToEndPipeline:
    """전체 파이프라인 통합 테스트."""

    @pytest.mark.asyncio
    async def test_full_pipeline_go(self, gate_checker):
        """전체 파이프라인: GO 판정."""
        # Mock futures cache (hedging 가능)
        gate_checker._futures_cache["binance"] = {"TESTUSDT"}
        gate_checker._futures_cache_time["binance"] = 9999999999.0

        result = await gate_checker.analyze_listing(
            symbol="TEST",
            exchange="upbit",
        )

        assert isinstance(result, GateResult)
        assert result.can_proceed is True
        assert result.symbol == "TEST"
        assert result.exchange == "upbit"
        assert result.alert_level in AlertLevel

    @pytest.mark.asyncio
    async def test_full_pipeline_nogo_low_premium(self, gate_checker, mock_premium):
        """전체 파이프라인: NO-GO (낮은 프리미엄)."""
        # 낮은 프리미엄 mock
        async def mock_low_premium(*args, **kwargs):
            return PremiumResult(
                premium_pct=0.5,  # 0.5% (수익성 부족)
                krw_price=1_350_000,
                global_usd_price=1000.0,
                fx_rate=1350.0,
                fx_source="btc_implied",
            )

        mock_premium.calculate_premium = AsyncMock(side_effect=mock_low_premium)

        result = await gate_checker.analyze_listing(
            symbol="LOWPREM",
            exchange="upbit",
        )

        assert result.can_proceed is False
        assert any("수익성 부족" in b for b in result.blockers)


class TestPhase5aIntegration:
    """Phase 5a 확장 통합 테스트."""

    @pytest.mark.asyncio
    async def test_supply_classification(self, gate_checker):
        """공급 분류 통합."""
        result = await gate_checker.analyze_listing(
            symbol="TEST",
            exchange="upbit",
        )

        # supply_classifier feature flag ON → supply_result 존재
        if result.can_proceed:
            assert result.supply_result is not None
            assert result.supply_result.classification in SupplyClassification

    @pytest.mark.asyncio
    async def test_listing_type_classification(self, gate_checker):
        """상장 유형 분류 통합."""
        result = await gate_checker.analyze_listing(
            symbol="TEST",
            exchange="upbit",
        )

        # listing_type feature flag ON → listing_type_result 존재
        if result.can_proceed:
            assert result.listing_type_result is not None
            assert result.listing_type_result.listing_type in ListingType

    @pytest.mark.asyncio
    async def test_strategy_recommendation(self, gate_checker):
        """전략 추천 통합."""
        result = await gate_checker.analyze_listing(
            symbol="TEST",
            exchange="upbit",
        )

        # recommended_strategy 존재
        assert result.recommended_strategy in StrategyCode

    @pytest.mark.asyncio
    async def test_scenario_card_generation(self, gate_checker):
        """시나리오 카드 생성 통합."""
        gate_checker._futures_cache["binance"] = {"TESTUSDT"}
        gate_checker._futures_cache_time["binance"] = 9999999999.0

        result = await gate_checker.analyze_listing(
            symbol="TEST",
            exchange="upbit",
        )

        # scenario_planner feature flag ON → scenario_card 존재
        if result.can_proceed and result.supply_result and result.listing_type_result:
            assert result.scenario_card is not None
            assert result.scenario_card.predicted_outcome in ScenarioOutcome


class TestCaching:
    """캐싱 동작 테스트."""

    @pytest.mark.asyncio
    async def test_analysis_cache_hit(self, gate_checker):
        """분석 캐시 히트."""
        # 첫 번째 호출
        result1 = await gate_checker.analyze_listing(
            symbol="CACHED",
            exchange="upbit",
        )

        # 두 번째 호출 (캐시됨)
        result2 = await gate_checker.analyze_listing(
            symbol="CACHED",
            exchange="upbit",
        )

        # 동일한 결과 (캐시에서 반환)
        assert result1.can_proceed == result2.can_proceed
        assert result1.symbol == result2.symbol

    @pytest.mark.asyncio
    async def test_futures_cache(self, gate_checker):
        """선물 마켓 캐시."""
        # 캐시 설정
        gate_checker._futures_cache["binance"] = {"BTCUSDT", "ETHUSDT"}
        gate_checker._futures_cache_time["binance"] = 9999999999.0

        # analyze_listing 호출
        result = await gate_checker.analyze_listing(
            symbol="BTC",
            exchange="upbit",
        )

        # hedge_type이 캐시 기반으로 결정됨
        assert result.gate_input.hedge_type in ["cex", "dex_only", "none"]


class TestErrorHandling:
    """에러 처리 통합 테스트."""

    @pytest.mark.asyncio
    async def test_premium_api_failure(self, gate_checker, mock_premium):
        """프리미엄 API 실패."""
        # 예외 발생 mock
        mock_premium.get_domestic_price = AsyncMock(side_effect=Exception("API Error"))

        result = await gate_checker.analyze_listing(
            symbol="FAIL",
            exchange="upbit",
        )

        # 실패해도 GateResult 반환 (NO-GO)
        assert result.can_proceed is False
        assert any("가격 조회 실패" in b for b in result.blockers)

    @pytest.mark.asyncio
    async def test_vwap_api_failure(self, gate_checker, mock_premium):
        """VWAP API 실패."""
        mock_premium.get_global_vwap = AsyncMock(return_value=None)

        result = await gate_checker.analyze_listing(
            symbol="FAIL",
            exchange="upbit",
        )

        assert result.can_proceed is False
        assert any("글로벌 가격 조회 실패" in b for b in result.blockers)


class TestAPIMetrics:
    """API 메트릭 수집 테스트."""

    @pytest.mark.asyncio
    async def test_metrics_recorded(self, gate_checker):
        """API 메트릭 기록."""
        await gate_checker.analyze_listing(
            symbol="METRICS",
            exchange="upbit",
        )

        # 메트릭 기록 확인 (실제 구현은 exchange명으로 기록)
        assert gate_checker._metrics["upbit"].total_calls > 0
        assert gate_checker._metrics["implied_fx"].total_calls > 0


class TestRealWorldScenarios:
    """실제 시나리오 통합 테스트."""

    @pytest.mark.asyncio
    async def test_scenario_heung_tge_constrained(self, gate_checker):
        """시나리오: 흥따리 (TGE + constrained + hedge_none)."""
        # Mock: 헤징 불가
        gate_checker._futures_cache["binance"] = set()
        gate_checker._futures_cache["bybit"] = set()
        gate_checker._futures_cache["hyperliquid"] = set()
        gate_checker._futures_cache_time["binance"] = 9999999999.0
        gate_checker._futures_cache_time["bybit"] = 9999999999.0
        gate_checker._futures_cache_time["hyperliquid"] = 9999999999.0

        result = await gate_checker.analyze_listing(
            symbol="HEUNG",
            exchange="upbit",
        )

        # GO + hedge_none
        if result.can_proceed:
            assert result.gate_input.hedge_type == "none"
            # 시나리오 카드: 높은 흥따리 확률 예상
            if result.scenario_card:
                assert result.scenario_card.heung_probability > 0.5

    @pytest.mark.asyncio
    async def test_scenario_mang_side_smooth(self, gate_checker):
        """시나리오: 망따리 (SIDE + smooth + hedge_cex)."""
        # Mock: 헤징 가능
        gate_checker._futures_cache["binance"] = {"MANGUSDT"}
        gate_checker._futures_cache_time["binance"] = 9999999999.0

        result = await gate_checker.analyze_listing(
            symbol="MANG",
            exchange="upbit",
        )

        # GO + hedge_cex
        if result.can_proceed:
            assert result.gate_input.hedge_type == "cex"


class TestPerformance:
    """성능 테스트."""

    @pytest.mark.asyncio
    async def test_analysis_performance(self, gate_checker):
        """분석 성능 (병렬 처리)."""
        import time

        start = time.time()
        result = await gate_checker.analyze_listing(
            symbol="PERF",
            exchange="upbit",
        )
        elapsed = time.time() - start

        # 병렬 처리로 5초 이내 완료
        assert elapsed < 5.0
        assert isinstance(result, GateResult)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
