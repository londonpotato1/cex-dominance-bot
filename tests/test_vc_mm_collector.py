"""VC/MM 수집기 테스트 (Phase 7 Week 3).

테스트 범위:
  - VCTierClassifier: 정확한 매칭, 부분 매칭, classify_all
  - VCMMCollector: 수동 DB fallback, 알 수 없는 심볼 처리
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 테스트 대상 모듈
from collectors.vc_mm_collector import (
    VCTierClassifier,
    VCMMCollector,
    ProjectVCInfo,
    VCFundingRound,
    collect_vc_info,
    format_vc_info_text,
)


# =============================================================================
# VCTierClassifier 테스트
# =============================================================================


class TestVCTierClassifier:
    """VCTierClassifier 단위 테스트."""

    @pytest.fixture
    def classifier(self):
        """기본 분류기 (YAML 없이 하드코딩 fallback 사용)."""
        # 존재하지 않는 경로로 생성 → 하드코딩 fallback 사용
        return VCTierClassifier(config_path=Path("/nonexistent/path.yaml"))

    def test_exact_match_tier1(self, classifier):
        """Tier 1 VC 정확한 매칭."""
        assert classifier.classify("Binance Labs") == 1
        assert classifier.classify("a16z") == 1
        assert classifier.classify("Paradigm") == 1
        assert classifier.classify("Polychain Capital") == 1
        assert classifier.classify("Coinbase Ventures") == 1

    def test_exact_match_tier2(self, classifier):
        """Tier 2 VC 정확한 매칭."""
        assert classifier.classify("Hashed") == 2
        assert classifier.classify("Galaxy Digital") == 2
        assert classifier.classify("Blockchain Capital") == 2

    def test_unknown_vc_returns_tier3(self, classifier):
        """알 수 없는 VC는 Tier 3 반환."""
        assert classifier.classify("Unknown VC Fund") == 3
        assert classifier.classify("Random Investor") == 3
        assert classifier.classify("") == 3

    def test_partial_match_tier1(self, classifier):
        """Tier 1 부분 매칭 (a16z Crypto → a16z)."""
        assert classifier.classify("a16z Crypto") == 1
        assert classifier.classify("Polychain Capital Partners") == 1
        assert classifier.classify("binance labs") == 1  # 대소문자 무시

    def test_partial_match_tier2(self, classifier):
        """Tier 2 부분 매칭."""
        assert classifier.classify("Hashed Ventures") == 2
        assert classifier.classify("IOSG Ventures Fund") == 2

    def test_classify_all(self, classifier):
        """투자자 리스트 티어별 분류."""
        investors = [
            "Binance Labs",      # Tier 1
            "a16z",              # Tier 1
            "Hashed",            # Tier 2
            "Galaxy Digital",    # Tier 2
            "Unknown Fund",      # Tier 3
            "Random VC",         # Tier 3
        ]
        tier1, tier2, tier3 = classifier.classify_all(investors)

        assert "Binance Labs" in tier1
        assert "a16z" in tier1
        assert len(tier1) == 2

        assert "Hashed" in tier2
        assert "Galaxy Digital" in tier2
        assert len(tier2) == 2

        assert "Unknown Fund" in tier3
        assert "Random VC" in tier3
        assert len(tier3) == 2

    def test_classify_all_empty_list(self, classifier):
        """빈 리스트 처리."""
        tier1, tier2, tier3 = classifier.classify_all([])
        assert tier1 == []
        assert tier2 == []
        assert tier3 == []

    def test_classify_all_all_tier1(self, classifier):
        """모두 Tier 1인 경우."""
        investors = ["Binance Labs", "a16z", "Paradigm"]
        tier1, tier2, tier3 = classifier.classify_all(investors)
        assert len(tier1) == 3
        assert len(tier2) == 0
        assert len(tier3) == 0


# =============================================================================
# VCMMCollector 테스트
# =============================================================================


class TestVCMMCollector:
    """VCMMCollector 단위 테스트."""

    @pytest.fixture
    def collector(self, tmp_path):
        """테스트용 수집기 (임시 디렉토리 사용)."""
        # 임시 vc_tiers.yaml 생성
        vc_tiers_path = tmp_path / "vc_tiers.yaml"
        vc_tiers_path.write_text("""
tier1:
  - name: "Binance Labs"
    avg_listing_roi: 85.3
    portfolio_size: 200
tier2:
  - name: "Hashed"
    avg_listing_roi: 45.2
    portfolio_size: 100
""")

        # 임시 manual_vc_db.yaml 생성
        manual_db_path = tmp_path / "manual_vc_db.yaml"
        manual_db_path.write_text("""
projects:
  SENT:
    name: "Session Token"
    investors:
      - "Binance Labs"
      - "Polychain Capital"
    funding_rounds:
      - type: "Seed"
        amount_usd: 5000000
        date: "2023-06"
        investors: ["Binance Labs"]
        lead: "Binance Labs"
    mm_confirmed: true
    mm_name: "Wintermute"
    mm_risk_score: 2.0
""")

        return VCMMCollector(config_dir=tmp_path, client=MagicMock())

    @pytest.mark.asyncio
    async def test_manual_db_fallback(self, collector):
        """수동 DB에서 정보 로드 테스트."""
        info = await collector.collect("SENT")

        assert info.symbol == "SENT"
        assert info.project_name == "Session Token"
        assert info.data_source == "manual"
        assert info.confidence >= 0.9
        assert "Binance Labs" in info.tier1_investors
        assert info.mm_confirmed is True
        assert info.mm_name == "Wintermute"
        assert info.mm_risk_score == 2.0
        assert info.has_tier1_vc is True

    @pytest.mark.asyncio
    async def test_unknown_symbol_returns_empty(self, collector):
        """알 수 없는 심볼은 unknown 데이터 반환."""
        # CoinGecko mock도 실패하도록 설정
        collector._client.get = AsyncMock(return_value=None)

        info = await collector.collect("UNKNOWN_SYMBOL_XYZ")

        assert info.symbol == "UNKNOWN_SYMBOL_XYZ"
        assert info.data_source == "unknown"
        assert info.confidence == 0.0
        assert len(info.tier1_investors) == 0

    @pytest.mark.asyncio
    async def test_funding_rounds_parsed(self, collector):
        """펀딩 라운드 파싱 테스트."""
        info = await collector.collect("SENT")

        assert len(info.funding_rounds) == 1
        round_info = info.funding_rounds[0]
        assert round_info.round_type == "Seed"
        assert round_info.amount_usd == 5000000
        assert round_info.lead_investor == "Binance Labs"

    @pytest.mark.asyncio
    async def test_total_funding_calculation(self, collector):
        """총 펀딩 금액 계산 테스트."""
        info = await collector.collect("SENT")
        assert info.total_funding_usd == 5000000

    @pytest.mark.asyncio
    async def test_vc_risk_level_calculation(self, collector):
        """VC 리스크 레벨 계산 테스트."""
        info = await collector.collect("SENT")
        # Tier 1 VC 있음 + MM 리스크 2.0 → "low"
        assert info.vc_risk_level == "low"

    @pytest.mark.asyncio
    async def test_case_insensitive_symbol(self, collector):
        """대소문자 구분 없이 심볼 조회."""
        info_upper = await collector.collect("SENT")
        info_lower = await collector.collect("sent")

        # 둘 다 동일한 결과 (대문자로 변환됨)
        assert info_upper.symbol == "SENT"
        assert info_lower.symbol == "SENT"


# =============================================================================
# 헬퍼 함수 테스트
# =============================================================================


class TestHelperFunctions:
    """헬퍼 함수 테스트."""

    def test_format_vc_info_text(self):
        """VC 정보 텍스트 포맷 테스트."""
        info = ProjectVCInfo(
            symbol="TEST",
            project_name="Test Project",
            total_funding_usd=10000000,
            tier1_investors=["Binance Labs", "a16z"],
            tier2_investors=["Hashed"],
            tier3_investors=[],
            mm_confirmed=True,
            mm_name="Wintermute",
            mm_risk_score=2.0,
            data_source="manual",
            confidence=0.9,
            vc_risk_level="low",
        )

        text = format_vc_info_text(info)

        assert "TEST" in text
        assert "Binance Labs" in text
        assert "a16z" in text
        assert "Hashed" in text
        assert "Wintermute" in text
        assert "low" in text.upper() or "LOW" in text

    def test_format_vc_info_text_no_funding(self):
        """펀딩 정보 없는 경우."""
        info = ProjectVCInfo(
            symbol="TEST",
            project_name="Test Project",
            total_funding_usd=0,
            data_source="unknown",
            confidence=0.0,
            vc_risk_level="unknown",
        )

        text = format_vc_info_text(info)
        assert "TEST" in text
        # 펀딩 0이면 펀딩 라인 없음
        assert "$0" not in text or "총 펀딩" not in text


# =============================================================================
# 통합 테스트 (실제 YAML 파일 사용)
# =============================================================================


class TestIntegration:
    """실제 YAML 파일을 사용한 통합 테스트."""

    @pytest.fixture
    def real_classifier(self):
        """실제 vc_tiers.yaml 사용하는 분류기."""
        config_path = Path(__file__).parent.parent / "data" / "vc_mm_info" / "vc_tiers.yaml"
        if not config_path.exists():
            pytest.skip("vc_tiers.yaml not found")
        return VCTierClassifier(config_path=config_path)

    def test_real_yaml_loaded(self, real_classifier):
        """실제 YAML 파일 로드 확인."""
        # YAML에 정의된 VC 확인
        assert real_classifier.classify("Binance Labs") == 1
        assert real_classifier.classify("a16z") == 1

    def test_real_yaml_vc_count(self, real_classifier):
        """YAML의 VC 개수 확인."""
        # 최소 10개 이상의 Tier 1 VC가 있어야 함
        tier1_count = len(real_classifier._tier1_vcs)
        assert tier1_count >= 10, f"Tier 1 VC가 {tier1_count}개로 너무 적음"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
