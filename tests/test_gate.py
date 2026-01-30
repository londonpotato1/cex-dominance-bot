"""Gate 판정기 테스트 (Phase 4)."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from analysis.gate import (
    GateChecker,
    GateInput,
    GateResult,
    AlertLevel,
    StrategyCode,
)
from analysis.cost_model import CostModel, CostResult


@pytest.fixture
def cost_result_profitable():
    """수익성 있는 CostResult."""
    return CostResult(
        slippage_pct=0.5,
        gas_cost_krw=5000,
        exchange_fee_pct=0.15,
        hedge_cost_pct=0.06,
        total_cost_pct=1.71,
        net_profit_pct=8.29,  # 10% - 1.71%
        gas_warn=False,
    )


@pytest.fixture
def cost_result_unprofitable():
    """수익성 없는 CostResult."""
    return CostResult(
        slippage_pct=1.0,
        gas_cost_krw=15000,
        exchange_fee_pct=0.15,
        hedge_cost_pct=0.06,
        total_cost_pct=3.21,
        net_profit_pct=-1.21,  # 2% - 3.21%
        gas_warn=True,
    )


@pytest.fixture
def gate_input_go(cost_result_profitable):
    """GO 판정용 GateInput."""
    return GateInput(
        symbol="TEST",
        exchange="upbit",
        premium_pct=10.0,
        cost_result=cost_result_profitable,
        deposit_open=True,
        withdrawal_open=True,
        transfer_time_min=5.0,
        global_volume_usd=500_000,
        fx_source="btc_implied",
        hedge_type="cex",
        network="ethereum",
        top_exchange="binance",
    )


@pytest.fixture
def gate_input_nogo_deposit(cost_result_profitable):
    """NO-GO (입금 차단) GateInput."""
    return GateInput(
        symbol="TEST",
        exchange="upbit",
        premium_pct=10.0,
        cost_result=cost_result_profitable,
        deposit_open=False,  # 입금 차단
        withdrawal_open=True,
        transfer_time_min=5.0,
        global_volume_usd=500_000,
        fx_source="btc_implied",
        hedge_type="cex",
        network="ethereum",
        top_exchange="binance",
    )


@pytest.fixture
def gate_input_nogo_profit(cost_result_unprofitable):
    """NO-GO (수익성 부족) GateInput."""
    return GateInput(
        symbol="TEST",
        exchange="upbit",
        premium_pct=2.0,
        cost_result=cost_result_unprofitable,
        deposit_open=True,
        withdrawal_open=True,
        transfer_time_min=5.0,
        global_volume_usd=500_000,
        fx_source="btc_implied",
        hedge_type="cex",
        network="ethereum",
        top_exchange="binance",
    )


@pytest.fixture
def mock_gate_checker():
    """Mock GateChecker (외부 의존성 제거)."""
    # Mock dependencies
    mock_premium = MagicMock()
    mock_cost_model = MagicMock(spec=CostModel)
    mock_writer = MagicMock()

    config_dir = Path(__file__).parent.parent / "config"

    with patch.object(GateChecker, "_load_vasp_matrix", return_value={}):
        with patch.object(GateChecker, "_load_features", return_value={"supply_classifier": False, "listing_type": False}):
            with patch.object(GateChecker, "_load_networks", return_value={}):
                checker = GateChecker(
                    premium=mock_premium,
                    cost_model=mock_cost_model,
                    writer=mock_writer,
                    config_dir=config_dir,
                )
    return checker


class TestHardBlockers:
    """Hard Blocker 테스트."""

    def test_go_all_conditions_met(self, mock_gate_checker, gate_input_go):
        """모든 조건 충족 → GO."""
        result = mock_gate_checker.check_hard_blockers(gate_input_go)

        assert result.can_proceed is True
        assert len(result.blockers) == 0

    def test_nogo_deposit_closed(self, mock_gate_checker, gate_input_nogo_deposit):
        """입금 차단 → NO-GO."""
        result = mock_gate_checker.check_hard_blockers(gate_input_nogo_deposit)

        assert result.can_proceed is False
        assert any("입금 차단" in b for b in result.blockers)

    def test_nogo_withdrawal_closed(self, mock_gate_checker, cost_result_profitable):
        """출금 차단 → NO-GO."""
        gate_input = GateInput(
            symbol="TEST",
            exchange="upbit",
            premium_pct=10.0,
            cost_result=cost_result_profitable,
            deposit_open=True,
            withdrawal_open=False,  # 출금 차단
            transfer_time_min=5.0,
            global_volume_usd=500_000,
            fx_source="btc_implied",
            hedge_type="cex",
            network="ethereum",
            top_exchange="binance",
        )

        result = mock_gate_checker.check_hard_blockers(gate_input)

        assert result.can_proceed is False
        assert any("출금 차단" in b for b in result.blockers)

    def test_nogo_unprofitable(self, mock_gate_checker, gate_input_nogo_profit):
        """수익성 부족 → NO-GO."""
        result = mock_gate_checker.check_hard_blockers(gate_input_nogo_profit)

        assert result.can_proceed is False
        assert any("수익성 부족" in b for b in result.blockers)

    def test_nogo_transfer_time_exceeded(self, mock_gate_checker, cost_result_profitable):
        """전송 시간 초과 → NO-GO."""
        gate_input = GateInput(
            symbol="TEST",
            exchange="upbit",
            premium_pct=10.0,
            cost_result=cost_result_profitable,
            deposit_open=True,
            withdrawal_open=True,
            transfer_time_min=45.0,  # 30분 초과
            global_volume_usd=500_000,
            fx_source="btc_implied",
            hedge_type="cex",
            network="ethereum",
            top_exchange="binance",
        )

        result = mock_gate_checker.check_hard_blockers(gate_input)

        assert result.can_proceed is False
        assert any("전송 시간 초과" in b for b in result.blockers)

    def test_multiple_blockers(self, mock_gate_checker, cost_result_unprofitable):
        """복수 blocker."""
        gate_input = GateInput(
            symbol="TEST",
            exchange="upbit",
            premium_pct=2.0,
            cost_result=cost_result_unprofitable,
            deposit_open=False,  # 입금 차단
            withdrawal_open=False,  # 출금 차단
            transfer_time_min=45.0,  # 전송 시간 초과
            global_volume_usd=500_000,
            fx_source="btc_implied",
            hedge_type="cex",
            network="ethereum",
            top_exchange="binance",
        )

        result = mock_gate_checker.check_hard_blockers(gate_input)

        assert result.can_proceed is False
        assert len(result.blockers) >= 3  # 최소 3개 blocker


class TestWarnings:
    """Warning 테스트."""

    def test_warning_low_liquidity(self, mock_gate_checker, cost_result_profitable):
        """유동성 부족 경고."""
        gate_input = GateInput(
            symbol="TEST",
            exchange="upbit",
            premium_pct=10.0,
            cost_result=cost_result_profitable,
            deposit_open=True,
            withdrawal_open=True,
            transfer_time_min=5.0,
            global_volume_usd=50_000,  # $100K 미만
            fx_source="btc_implied",
            hedge_type="cex",
            network="ethereum",
            top_exchange="binance",
        )

        result = mock_gate_checker.check_hard_blockers(gate_input)

        # GO지만 경고 있음
        assert result.can_proceed is True
        assert any("유동성 부족" in w for w in result.warnings)

    def test_warning_gas_high(self, mock_gate_checker, cost_result_unprofitable):
        """가스비 경고."""
        # gas_warn=True인 CostResult
        gate_input = GateInput(
            symbol="TEST",
            exchange="upbit",
            premium_pct=10.0,  # 수익성은 있도록 조정
            cost_result=CostResult(
                slippage_pct=0.5,
                gas_cost_krw=15000,
                exchange_fee_pct=0.15,
                hedge_cost_pct=0.06,
                total_cost_pct=1.71,
                net_profit_pct=8.29,
                gas_warn=True,  # 가스비 경고
            ),
            deposit_open=True,
            withdrawal_open=True,
            transfer_time_min=5.0,
            global_volume_usd=500_000,
            fx_source="btc_implied",
            hedge_type="cex",
            network="ethereum",
            top_exchange="binance",
        )

        result = mock_gate_checker.check_hard_blockers(gate_input)

        assert result.can_proceed is True
        assert any("가스비 경고" in w for w in result.warnings)

    def test_warning_dex_only(self, mock_gate_checker, cost_result_profitable):
        """DEX-only 헤징 경고."""
        gate_input = GateInput(
            symbol="TEST",
            exchange="upbit",
            premium_pct=10.0,
            cost_result=cost_result_profitable,
            deposit_open=True,
            withdrawal_open=True,
            transfer_time_min=5.0,
            global_volume_usd=500_000,
            fx_source="btc_implied",
            hedge_type="dex_only",  # DEX-only
            network="ethereum",
            top_exchange="binance",
        )

        result = mock_gate_checker.check_hard_blockers(gate_input)

        assert result.can_proceed is True
        assert any("DEX-only" in w for w in result.warnings)


class TestAlertLevel:
    """AlertLevel 테스트."""

    def test_alert_critical(self, mock_gate_checker, gate_input_go):
        """GO + 신뢰 FX + 행동 가능 → CRITICAL."""
        result = mock_gate_checker.check_hard_blockers(gate_input_go)

        # CRITICAL 조건: GO + trusted_fx + actionable + no warnings
        assert result.can_proceed is True
        assert result.alert_level in (AlertLevel.CRITICAL, AlertLevel.HIGH)

    def test_alert_high_nogo(self, mock_gate_checker, gate_input_nogo_deposit):
        """NO-GO → HIGH."""
        result = mock_gate_checker.check_hard_blockers(gate_input_nogo_deposit)

        assert result.can_proceed is False
        assert result.alert_level == AlertLevel.HIGH


class TestGateResult:
    """GateResult 데이터클래스 테스트."""

    def test_gate_result_fields(self, mock_gate_checker, gate_input_go):
        """GateResult 필드 검증."""
        result = mock_gate_checker.check_hard_blockers(gate_input_go)

        assert hasattr(result, "can_proceed")
        assert hasattr(result, "blockers")
        assert hasattr(result, "warnings")
        assert hasattr(result, "alert_level")
        assert hasattr(result, "gate_input")
        assert hasattr(result, "symbol")
        assert hasattr(result, "exchange")

    def test_gate_result_symbol_exchange(self, mock_gate_checker, gate_input_go):
        """GateResult에 symbol/exchange 보존."""
        result = mock_gate_checker.check_hard_blockers(gate_input_go)

        assert result.symbol == "TEST"
        assert result.exchange == "upbit"


class TestFXWatchOnly:
    """FX hardcoded → WATCH_ONLY 테스트."""

    def test_fx_hardcoded_blocker(self, mock_gate_checker, cost_result_profitable):
        """FX hardcoded → blocker 추가."""
        gate_input = GateInput(
            symbol="TEST",
            exchange="upbit",
            premium_pct=10.0,
            cost_result=cost_result_profitable,
            deposit_open=True,
            withdrawal_open=True,
            transfer_time_min=5.0,
            global_volume_usd=500_000,
            fx_source="hardcoded_fallback",  # 하드코딩 FX
            hedge_type="cex",
            network="ethereum",
            top_exchange="binance",
        )

        result = mock_gate_checker.check_hard_blockers(gate_input)

        # FX hardcoded는 blocker로 추가됨
        assert any("FX" in b or "WATCH_ONLY" in b for b in result.blockers)


class TestEdgeCases:
    """엣지 케이스 테스트."""

    def test_zero_premium(self, mock_gate_checker):
        """0% 프리미엄."""
        gate_input = GateInput(
            symbol="TEST",
            exchange="upbit",
            premium_pct=0.0,
            cost_result=CostResult(
                slippage_pct=0.5,
                gas_cost_krw=5000,
                exchange_fee_pct=0.15,
                hedge_cost_pct=0.06,
                total_cost_pct=0.71,
                net_profit_pct=-0.71,  # 0% - 0.71%
                gas_warn=False,
            ),
            deposit_open=True,
            withdrawal_open=True,
            transfer_time_min=5.0,
            global_volume_usd=500_000,
            fx_source="btc_implied",
            hedge_type="cex",
            network="ethereum",
            top_exchange="binance",
        )

        result = mock_gate_checker.check_hard_blockers(gate_input)

        # 수익성 부족 → NO-GO
        assert result.can_proceed is False
        assert any("수익성 부족" in b for b in result.blockers)

    def test_negative_premium(self, mock_gate_checker):
        """음수 프리미엄 (역프)."""
        gate_input = GateInput(
            symbol="TEST",
            exchange="upbit",
            premium_pct=-5.0,
            cost_result=CostResult(
                slippage_pct=0.5,
                gas_cost_krw=5000,
                exchange_fee_pct=0.15,
                hedge_cost_pct=0.06,
                total_cost_pct=0.71,
                net_profit_pct=-5.71,  # -5% - 0.71%
                gas_warn=False,
            ),
            deposit_open=True,
            withdrawal_open=True,
            transfer_time_min=5.0,
            global_volume_usd=500_000,
            fx_source="btc_implied",
            hedge_type="cex",
            network="ethereum",
            top_exchange="binance",
        )

        result = mock_gate_checker.check_hard_blockers(gate_input)

        # 역프 → NO-GO
        assert result.can_proceed is False

    def test_exact_threshold_transfer_time(self, mock_gate_checker, cost_result_profitable):
        """정확히 30분 전송 시간."""
        gate_input = GateInput(
            symbol="TEST",
            exchange="upbit",
            premium_pct=10.0,
            cost_result=cost_result_profitable,
            deposit_open=True,
            withdrawal_open=True,
            transfer_time_min=30.0,  # 정확히 30분
            global_volume_usd=500_000,
            fx_source="btc_implied",
            hedge_type="cex",
            network="ethereum",
            top_exchange="binance",
        )

        result = mock_gate_checker.check_hard_blockers(gate_input)

        # 30분은 초과가 아님 → GO
        assert result.can_proceed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
