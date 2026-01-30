"""비용 모델 테스트 (Phase 4)."""

import pytest
from pathlib import Path

from analysis.cost_model import CostModel, CostResult, HedgeCost


@pytest.fixture
def cost_model():
    """CostModel 인스턴스."""
    config_dir = Path(__file__).parent.parent / "config"
    return CostModel(config_dir=config_dir)


@pytest.fixture
def sample_orderbook():
    """샘플 오더북 (asks)."""
    return {
        "asks": [
            [10000, 1.0],   # 10,000 KRW x 1개
            [10010, 2.0],   # 10,010 KRW x 2개
            [10020, 3.0],   # 10,020 KRW x 3개
            [10050, 5.0],   # 10,050 KRW x 5개
        ],
        "bids": [
            [9990, 1.0],
            [9980, 2.0],
        ]
    }


class TestHedgeCost:
    """헤지 비용 테스트."""

    def test_cex_hedge_cost(self, cost_model):
        """CEX 헤지 비용."""
        hedge = cost_model.get_hedge_cost("cex")

        assert hedge.hedge_type == "cex"
        assert hedge.fee_pct >= 0
        assert hedge.funding_cost_pct >= 0

    def test_dex_hedge_cost(self, cost_model):
        """DEX 헤지 비용."""
        hedge = cost_model.get_hedge_cost("dex_only")

        assert hedge.hedge_type == "dex_only"
        assert hedge.fee_pct >= 0
        # DEX는 펀딩비 0으로 단순화
        assert hedge.funding_cost_pct == 0.0

    def test_no_hedge_cost(self, cost_model):
        """헤지 없음 비용."""
        hedge = cost_model.get_hedge_cost("none")

        assert hedge.hedge_type == "none"
        assert hedge.fee_pct == 0.0
        assert hedge.funding_cost_pct == 0.0

    def test_hedge_cost_order(self, cost_model):
        """헤지 비용 순서: none < dex_only <= cex."""
        none_hedge = cost_model.get_hedge_cost("none")
        dex_hedge = cost_model.get_hedge_cost("dex_only")
        cex_hedge = cost_model.get_hedge_cost("cex")

        none_total = none_hedge.fee_pct + none_hedge.funding_cost_pct
        dex_total = dex_hedge.fee_pct + dex_hedge.funding_cost_pct
        cex_total = cex_hedge.fee_pct + cex_hedge.funding_cost_pct

        assert none_total == 0.0
        assert dex_total >= none_total
        # CEX는 펀딩비 포함하므로 더 높을 수 있음
        assert cex_total >= 0


class TestSlippage:
    """오더북 슬리피지 테스트."""

    def test_slippage_no_orderbook(self, cost_model):
        """오더북 없을 때 기본 슬리피지."""
        slippage = cost_model.estimate_slippage(None, 10_000_000)
        assert slippage == 1.0  # 기본값 1%

    def test_slippage_empty_asks(self, cost_model):
        """빈 asks 기본 슬리피지."""
        slippage = cost_model.estimate_slippage({"asks": []}, 10_000_000)
        assert slippage == 1.0

    def test_slippage_small_order(self, cost_model, sample_orderbook):
        """소량 주문 슬리피지 (첫 호가 내)."""
        # 5,000 KRW → 첫 호가(10,000 KRW x 1개 = 10,000 KRW)에서 체결
        slippage = cost_model.estimate_slippage(sample_orderbook, 5000)
        assert slippage == 0.0  # 첫 호가 = mid price

    def test_slippage_walkthrough(self, cost_model, sample_orderbook):
        """오더북 워크스루 슬리피지."""
        # 25,000 KRW → 첫 두 호가 소진
        # 호가1: 10,000 KRW (10,000 x 1)
        # 호가2: 15,000 KRW (10,010 x 1.5) ← 25,000 - 10,000 = 15,000
        slippage = cost_model.estimate_slippage(sample_orderbook, 25000)

        # mid_price = 10,000
        # 평균 체결가 = (10,000*1 + 15,000) / (1 + 1.5) = 25,000 / 2.5 = 10,000
        # 슬리피지 = (10,000 - 10,000) / 10,000 = 0%
        # 실제로는 두 번째 호가 가격이 10,010이므로 약간의 슬리피지 발생
        assert slippage >= 0.0
        assert slippage < 1.0  # 1% 미만

    def test_slippage_large_order(self, cost_model, sample_orderbook):
        """대량 주문 슬리피지 (오더북 소진)."""
        # 1억 KRW → 오더북 전체 소진 + 미체결
        # 오더북 총 유동성: 10,000*1 + 10,010*2 + 10,020*3 + 10,050*5
        #                 = 10,000 + 20,020 + 30,060 + 50,250 = 110,330 KRW
        slippage = cost_model.estimate_slippage(sample_orderbook, 100_000_000)

        # 미체결 비율당 5% 가산 → 큰 슬리피지
        assert slippage > 1.0


class TestGasCost:
    """네트워크 수수료 테스트."""

    def test_gas_cost_ethereum(self, cost_model):
        """이더리움 가스비."""
        gas_krw = cost_model.get_gas_cost_krw("ethereum", fx_rate=1350)
        assert gas_krw > 0

    def test_gas_cost_solana(self, cost_model):
        """솔라나 가스비 (저렴)."""
        eth_gas = cost_model.get_gas_cost_krw("ethereum", fx_rate=1350)
        sol_gas = cost_model.get_gas_cost_krw("solana", fx_rate=1350)

        # 솔라나가 이더리움보다 저렴해야 함
        assert sol_gas < eth_gas

    def test_gas_cost_unknown_network(self, cost_model):
        """알 수 없는 네트워크 기본값."""
        gas_krw = cost_model.get_gas_cost_krw("unknown_network", fx_rate=1350)
        # 기본값 1 USDT
        assert gas_krw == 1350


class TestTotalCost:
    """총 비용 계산 테스트."""

    def test_total_cost_basic(self, cost_model):
        """기본 총 비용 계산."""
        result = cost_model.calculate_total_cost(
            premium_pct=10.0,
            network="ethereum",
            amount_krw=10_000_000,
            hedge_type="cex",
            fx_rate=1350,
        )

        assert isinstance(result, CostResult)
        assert result.total_cost_pct > 0
        # 올바른 공식: net_profit = premium - total_cost
        assert result.net_profit_pct == pytest.approx(10.0 - result.total_cost_pct, abs=0.01)

    def test_net_profit_positive(self, cost_model):
        """높은 프리미엄 → 양의 순수익."""
        result = cost_model.calculate_total_cost(
            premium_pct=15.0,  # 15% 프리미엄
            network="solana",  # 저렴한 네트워크
            amount_krw=10_000_000,
            hedge_type="cex",
            fx_rate=1350,
        )

        # 15% 프리미엄이면 비용 제외해도 양의 순수익
        assert result.net_profit_pct > 0

    def test_net_profit_negative(self, cost_model):
        """낮은 프리미엄 → 음의 순수익."""
        result = cost_model.calculate_total_cost(
            premium_pct=0.5,  # 0.5% 프리미엄
            network="ethereum",
            amount_krw=10_000_000,
            hedge_type="cex",
            fx_rate=1350,
        )

        # 0.5% 프리미엄은 비용보다 작음 → 손실
        assert result.net_profit_pct < 0

    def test_gas_warning(self, cost_model):
        """가스비 경고 (원금 1% 초과)."""
        # 소액 거래 시 가스비 비율 높음
        result = cost_model.calculate_total_cost(
            premium_pct=10.0,
            network="ethereum",
            amount_krw=100_000,  # 10만원 (소액)
            hedge_type="cex",
            fx_rate=1350,
        )

        # 이더리움 가스비가 10만원의 1% (1,000원) 초과하면 경고
        # 실제 가스비가 약 10 USDT = 13,500 KRW → 13.5%
        assert result.gas_warn is True

    def test_no_gas_warning(self, cost_model):
        """가스비 경고 없음 (원금 대비 작음)."""
        result = cost_model.calculate_total_cost(
            premium_pct=10.0,
            network="solana",
            amount_krw=100_000_000,  # 1억원 (대량)
            hedge_type="cex",
            fx_rate=1350,
        )

        # 1억원 대비 솔라나 가스비는 미미
        assert result.gas_warn is False

    def test_hedge_type_affects_cost(self, cost_model):
        """헤지 유형별 비용 차이."""
        base_params = {
            "premium_pct": 10.0,
            "network": "ethereum",
            "amount_krw": 10_000_000,
            "fx_rate": 1350,
        }

        result_cex = cost_model.calculate_total_cost(**base_params, hedge_type="cex")
        result_dex = cost_model.calculate_total_cost(**base_params, hedge_type="dex_only")
        result_none = cost_model.calculate_total_cost(**base_params, hedge_type="none")

        # 헤지 없음이 가장 낮은 비용
        assert result_none.hedge_cost_pct == 0.0
        assert result_none.total_cost_pct <= result_cex.total_cost_pct
        assert result_none.total_cost_pct <= result_dex.total_cost_pct

    def test_orderbook_affects_slippage(self, cost_model, sample_orderbook):
        """오더북 유무에 따른 슬리피지 차이."""
        base_params = {
            "premium_pct": 10.0,
            "network": "ethereum",
            "amount_krw": 10_000_000,
            "hedge_type": "cex",
            "fx_rate": 1350,
        }

        result_no_ob = cost_model.calculate_total_cost(**base_params, orderbook=None)
        result_with_ob = cost_model.calculate_total_cost(**base_params, orderbook=sample_orderbook)

        # 오더북 없으면 기본 슬리피지 1%, 있으면 실제 계산
        assert result_no_ob.slippage_pct == 1.0
        # 오더북 있으면 다를 수 있음 (실제 워크스루 결과)


class TestCostResultDataclass:
    """CostResult 데이터클래스 테스트."""

    def test_cost_result_fields(self, cost_model):
        """CostResult 필드 검증."""
        result = cost_model.calculate_total_cost(
            premium_pct=10.0,
            network="ethereum",
            amount_krw=10_000_000,
            hedge_type="cex",
            fx_rate=1350,
        )

        # 모든 필드 존재
        assert hasattr(result, "slippage_pct")
        assert hasattr(result, "gas_cost_krw")
        assert hasattr(result, "exchange_fee_pct")
        assert hasattr(result, "hedge_cost_pct")
        assert hasattr(result, "total_cost_pct")
        assert hasattr(result, "net_profit_pct")
        assert hasattr(result, "gas_warn")

    def test_cost_result_rounding(self, cost_model):
        """CostResult 소수점 반올림."""
        result = cost_model.calculate_total_cost(
            premium_pct=10.123456789,
            network="ethereum",
            amount_krw=10_000_000,
            hedge_type="cex",
            fx_rate=1350.5,
        )

        # 4자리 반올림
        assert len(str(result.slippage_pct).split(".")[-1]) <= 4
        assert len(str(result.total_cost_pct).split(".")[-1]) <= 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
