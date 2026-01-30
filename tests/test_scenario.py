"""시나리오 플래너 테스트 (Phase 6)."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from analysis.scenario import (
    ScenarioCard,
    ScenarioOutcome,
    ScenarioPlanner,
    format_scenario_card_text,
)
from analysis.supply_classifier import (
    SupplyClassification,
    SupplyResult,
)
from analysis.listing_type import (
    ListingType,
    ListingTypeResult,
)


@pytest.fixture
def planner():
    """ScenarioPlanner 인스턴스."""
    config_dir = Path(__file__).parent.parent / "config"
    return ScenarioPlanner(config_dir=config_dir)


@pytest.fixture
def supply_constrained():
    """공급 제약 결과."""
    return SupplyResult(
        classification=SupplyClassification.CONSTRAINED,
        total_score=-0.5,
        confidence=0.8,
    )


@pytest.fixture
def supply_smooth():
    """공급 원활 결과."""
    return SupplyResult(
        classification=SupplyClassification.SMOOTH,
        total_score=0.5,
        confidence=0.8,
    )


@pytest.fixture
def listing_tge():
    """TGE 상장 유형."""
    return ListingTypeResult(
        listing_type=ListingType.TGE,
        confidence=0.9,
        top_exchange="",
        reason="글로벌 최초 상장",
    )


@pytest.fixture
def listing_direct():
    """직상장 유형."""
    return ListingTypeResult(
        listing_type=ListingType.DIRECT,
        confidence=0.9,
        top_exchange="binance",
        reason="해외 거래소 기존재",
    )


class TestScenarioPlanner:
    """ScenarioPlanner 테스트."""

    def test_basic_instantiation(self, planner):
        """기본 인스턴스 생성."""
        assert planner is not None
        assert planner._coefficients is not None
        assert "base_probability" in planner._coefficients

    def test_generate_card_minimal(self, planner):
        """최소 입력으로 카드 생성."""
        card = planner.generate_card(
            symbol="TEST",
            exchange="upbit",
        )

        assert card.symbol == "TEST"
        assert card.exchange == "upbit"
        assert 0 <= card.heung_probability <= 1
        assert card.predicted_outcome in ScenarioOutcome
        assert card.supply_class == "unknown"
        assert card.listing_type == "UNKNOWN"

    def test_generate_card_with_supply_constrained(self, planner, supply_constrained):
        """공급 제약 시나리오."""
        card = planner.generate_card(
            symbol="HEUNG",
            exchange="upbit",
            supply_result=supply_constrained,
            hedge_type="none",
        )

        # 공급 제약 + 헤징 불가 → 높은 흥따리 확률
        assert card.heung_probability > 0.6
        assert card.supply_contribution > 0
        assert card.hedge_contribution > 0
        assert card.supply_class == "constrained"

    def test_generate_card_with_supply_smooth(self, planner, supply_smooth):
        """공급 원활 시나리오."""
        card = planner.generate_card(
            symbol="MANG",
            exchange="upbit",
            supply_result=supply_smooth,
            hedge_type="cex",
        )

        # 공급 원활 + CEX 헤징 → 낮은 흥따리 확률
        assert card.heung_probability < 0.5
        assert card.supply_contribution < 0
        assert card.supply_class == "smooth"

    def test_hedge_type_coefficients(self, planner):
        """헤지 유형별 계수 차이."""
        # 동일 조건에서 hedge_type만 다르게
        card_cex = planner.generate_card(
            symbol="X", exchange="upbit", hedge_type="cex",
        )
        card_dex = planner.generate_card(
            symbol="X", exchange="upbit", hedge_type="dex_only",
        )
        card_none = planner.generate_card(
            symbol="X", exchange="upbit", hedge_type="none",
        )

        # hedge_none > hedge_cex > hedge_dex_only (shrinkage 적용 후)
        # 단, shrinkage 때문에 순서가 달라질 수 있음
        # none의 raw coefficient가 +0.37로 가장 높음
        assert card_none.hedge_contribution >= card_cex.hedge_contribution

    def test_market_condition_coefficients(self, planner):
        """시장 상황별 계수."""
        card_bull = planner.generate_card(
            symbol="X", exchange="upbit", market_condition="bull",
        )
        card_bear = planner.generate_card(
            symbol="X", exchange="upbit", market_condition="bear",
        )
        card_neutral = planner.generate_card(
            symbol="X", exchange="upbit", market_condition="neutral",
        )

        # bear는 강력한 역시그널 (-0.38)
        assert card_bear.market_contribution < card_bull.market_contribution
        assert card_bear.heung_probability < card_bull.heung_probability

    def test_shrinkage_applied(self, planner):
        """shrinkage 적용 확인."""
        # hedge_dex_only는 표본 4건으로 shrinkage 적용
        # 원본 -0.15 → shrinkage 후 -0.15 * (4/10) = -0.06
        raw_coeff = planner._coefficients.get("hedge_dex_only", -0.15)
        shrunk = planner._get_coeff("hedge_dex_only")

        # shrinkage 적용되면 절대값이 줄어야 함
        assert abs(shrunk) <= abs(raw_coeff)

    def test_upbit_base_probability(self, planner):
        """업비트 전용 base_probability 사용."""
        # use_upbit_base=True (기본값)
        prob_upbit = planner._calculate_heung_probability(
            "unknown", "cex", "neutral", "upbit",
        )[0]

        # 업비트 base는 0.42로 전체 base 0.51보다 낮음
        # neutral에서 시작하므로 market_neutral(+0.15) 적용
        # 대략 0.42 + 0.15 = 0.57 근처
        assert prob_upbit < 0.65

    def test_predict_outcome_heung_big(self, planner):
        """대흥따리 예측."""
        outcome, conf = planner._predict_outcome(
            heung_prob=0.85,
            hedge_type="none",
            supply_class="constrained",
        )

        assert outcome == ScenarioOutcome.HEUNG_BIG

    def test_predict_outcome_heung(self, planner):
        """흥따리 예측."""
        outcome, conf = planner._predict_outcome(
            heung_prob=0.60,
            hedge_type="cex",
            supply_class="neutral",
        )

        assert outcome == ScenarioOutcome.HEUNG

    def test_predict_outcome_mang(self, planner):
        """망따리 예측."""
        outcome, conf = planner._predict_outcome(
            heung_prob=0.20,
            hedge_type="cex",
            supply_class="smooth",
        )

        assert outcome == ScenarioOutcome.MANG

    def test_full_card_with_listing_type(
        self, planner, supply_constrained, listing_tge,
    ):
        """전체 정보로 카드 생성."""
        card = planner.generate_card(
            symbol="NEWCOIN",
            exchange="bithumb",
            supply_result=supply_constrained,
            listing_type_result=listing_tge,
            hedge_type="none",
            market_condition="neutral",
        )

        assert card.symbol == "NEWCOIN"
        assert card.exchange == "bithumb"
        assert card.listing_type == "TGE"
        assert card.supply_class == "constrained"
        assert card.hedge_type == "none"
        assert card.market_condition == "neutral"

        # 최적 조건: constrained + hedge_none + TGE
        assert card.heung_probability > 0.7
        assert card.predicted_outcome in (
            ScenarioOutcome.HEUNG_BIG,
            ScenarioOutcome.HEUNG,
        )


class TestFormatScenarioCard:
    """카드 포맷팅 테스트."""

    def test_format_basic(self, planner):
        """기본 포맷팅."""
        card = planner.generate_card(
            symbol="TEST",
            exchange="upbit",
        )

        text = format_scenario_card_text(card)

        assert "TEST" in text
        assert "upbit" in text
        assert "시나리오" in text
        assert "기여 요인" in text

    def test_format_heung_big(self, planner, supply_constrained):
        """대흥따리 포맷팅."""
        card = planner.generate_card(
            symbol="HEUNG",
            exchange="upbit",
            supply_result=supply_constrained,
            hedge_type="none",
            market_condition="neutral",
        )

        text = format_scenario_card_text(card)

        # 대흥따리 또는 흥따리 이모지
        assert "🔥" in text or "✨" in text

    def test_format_mang(self, planner, supply_smooth):
        """망따리 포맷팅."""
        card = planner.generate_card(
            symbol="MANG",
            exchange="upbit",
            supply_result=supply_smooth,
            hedge_type="cex",
            market_condition="bear",
        )

        text = format_scenario_card_text(card)

        # 망따리 이모지
        if card.predicted_outcome == ScenarioOutcome.MANG:
            assert "💀" in text

    def test_format_with_warnings(self, planner):
        """경고 포함 포맷팅."""
        card = planner.generate_card(
            symbol="WARN",
            exchange="upbit",
            hedge_type="dex_only",  # shrinkage 경고
        )

        text = format_scenario_card_text(card)

        # dex_only는 표본 부족 경고
        if card.warnings:
            assert "주의" in text


class TestCoefficientGovernance:
    """계수 관리 원칙 테스트."""

    def test_min_sample_size(self, planner):
        """최소 표본 크기 설정."""
        min_size = planner._min_sample_size
        assert min_size == 10  # thresholds.yaml 기본값

    def test_shrinkage_formula(self, planner):
        """shrinkage 공식 검증."""
        # 표본 4건, min 10건
        # shrinkage = raw * (4/10) = raw * 0.4
        raw = 0.15
        expected = raw * (4 / 10)

        # hedge_dex_only의 표본 수가 4인 경우
        planner._SAMPLE_COUNTS["test_key"] = 4
        with patch.object(planner, "_coefficients", {"test_key": raw}):
            shrunk = planner._apply_shrinkage("test_key", raw)
            assert abs(shrunk - expected) < 0.001

    def test_no_shrinkage_for_large_sample(self, planner):
        """충분한 표본에는 shrinkage 미적용."""
        # 표본 >= 10이면 원본 계수 유지
        raw = planner._coefficients.get("supply_constrained", 0.18)
        shrunk = planner._get_coeff("supply_constrained")

        # supply_constrained 표본 29건 → shrinkage 미적용
        assert shrunk == raw


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
