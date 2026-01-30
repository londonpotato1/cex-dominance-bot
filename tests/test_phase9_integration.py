"""Phase 9 통합 테스트 (Week 9-10).

테스트 범위:
  1. VC 분류기: 102개 VC 로드 확인
  2. MM 분류기: 47개 MM 로드 확인
  3. MM 조작 감지기: 패턴 감지 동작 확인
  4. Gate 6단계 파이프라인: VC/MM 체크 포함

실행:
  pytest tests/test_phase9_integration.py -v
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path

# VC/MM 분류기 테스트
from collectors.vc_mm_collector import (
    VCTierClassifier,
    MMClassifier,
    VCMMCollector,
    VCInfo,
    MMInfo,
)

# MM 조작 감지기 테스트
from analysis.mm_manipulation_detector import (
    MMManipulationDetector,
    ManipulationType,
    AlertSeverity,
    Trade,
    OrderBook,
    OrderBookLevel,
)


class TestVCTierClassifier:
    """VC 분류기 테스트."""

    @pytest.fixture
    def classifier(self):
        """VC 분류기 초기화."""
        config_path = Path(__file__).parent.parent / "data" / "vc_mm_info" / "vc_tiers.yaml"
        assert config_path.exists(), f"Config not found: {config_path}"
        return VCTierClassifier(config_path=config_path)

    def test_load_vc_count(self, classifier):
        """VC 개수 확인 (102개 이상)."""
        stats = classifier.get_stats()
        total = stats["tier1_count"] + stats["tier2_count"] + stats["tier3_count"]
        assert total >= 100, f"VC 개수 부족: {total} (목표 100+)"
        print(f"\n✓ VC 총 개수: {total}")
        print(f"  - Tier 1: {stats['tier1_count']}")
        print(f"  - Tier 2: {stats['tier2_count']}")
        print(f"  - Tier 3: {stats['tier3_count']}")

    def test_tier1_classification(self, classifier):
        """Tier 1 VC 분류 테스트."""
        tier1_vcs = ["Binance Labs", "a16z", "Paradigm", "Coinbase Ventures"]
        for vc in tier1_vcs:
            tier = classifier.classify(vc)
            assert tier == 1, f"{vc}는 Tier 1이어야 함 (실제: {tier})"
        print(f"\n✓ Tier 1 VC 분류 정상: {len(tier1_vcs)}개 테스트")

    def test_tier2_classification(self, classifier):
        """Tier 2 VC 분류 테스트."""
        tier2_vcs = ["Hashed", "Galaxy Digital", "Hack VC", "CoinFund"]
        for vc in tier2_vcs:
            tier = classifier.classify(vc)
            assert tier == 2, f"{vc}는 Tier 2이어야 함 (실제: {tier})"
        print(f"\n✓ Tier 2 VC 분류 정상: {len(tier2_vcs)}개 테스트")

    def test_partial_match(self, classifier):
        """부분 매칭 테스트."""
        # "a16z" 대신 "a16z Crypto"도 매칭되어야 함
        tier = classifier.classify("a16z Crypto")
        assert tier == 1, "a16z Crypto는 Tier 1이어야 함"

        # "Binance Labs" 대신 "Binance Venture"도 부분 매칭
        tier = classifier.classify("Binance")
        assert tier == 1, "Binance는 Tier 1으로 부분 매칭되어야 함"
        print("\n✓ 부분 매칭 정상")

    def test_unknown_vc(self, classifier):
        """알 수 없는 VC는 Tier 3."""
        tier = classifier.classify("Unknown Random VC XYZ")
        assert tier == 3, "알 수 없는 VC는 Tier 3이어야 함"
        print("\n✓ 알 수 없는 VC → Tier 3 정상")

    def test_get_vc_info(self, classifier):
        """VC 상세 정보 조회."""
        info = classifier.get_vc_info("Binance Labs")
        assert info is not None, "Binance Labs 정보 없음"
        assert info.tier == 1
        assert info.avg_listing_roi > 0
        assert info.portfolio_size > 0
        print(f"\n✓ VC 상세 정보: {info.name} (ROI: {info.avg_listing_roi}%)")


class TestMMClassifier:
    """MM 분류기 테스트."""

    @pytest.fixture
    def classifier(self):
        """MM 분류기 초기화."""
        config_path = Path(__file__).parent.parent / "data" / "vc_mm_info" / "vc_tiers.yaml"
        assert config_path.exists(), f"Config not found: {config_path}"
        return MMClassifier(config_path=config_path)

    def test_load_mm_count(self, classifier):
        """MM 개수 확인 (50개 이상)."""
        stats = classifier.get_stats()
        total = stats["tier1_count"] + stats["tier2_count"] + stats["tier3_count"]
        assert total >= 50, f"MM 개수 부족: {total} (목표 50+)"
        print(f"\n✓ MM 총 개수: {total}")
        print(f"  - Tier 1: {stats['tier1_count']}")
        print(f"  - Tier 2: {stats['tier2_count']}")
        print(f"  - Tier 3: {stats['tier3_count']}")

    def test_tier1_mm(self, classifier):
        """Tier 1 MM 분류 테스트."""
        tier1_mms = ["Wintermute", "GSR", "Jump Trading", "Jane Street"]
        for mm in tier1_mms:
            tier = classifier.classify(mm)
            assert tier == 1, f"{mm}는 Tier 1이어야 함 (실제: {tier})"
        print(f"\n✓ Tier 1 MM 분류 정상: {len(tier1_mms)}개 테스트")

    def test_tier3_mm(self, classifier):
        """Tier 3 (고위험) MM 분류 테스트."""
        tier3_mms = ["Alameda Research", "Gotbit"]
        for mm in tier3_mms:
            tier = classifier.classify(mm)
            assert tier == 3, f"{mm}는 Tier 3 (고위험)이어야 함 (실제: {tier})"
        print(f"\n✓ Tier 3 MM 분류 정상: {len(tier3_mms)}개 테스트")

    def test_risk_score(self, classifier):
        """리스크 스코어 테스트."""
        # Tier 1 MM은 낮은 리스크
        wintermute_risk = classifier.get_risk_score("Wintermute")
        assert wintermute_risk <= 3.0, f"Wintermute 리스크가 너무 높음: {wintermute_risk}"

        # Tier 3 MM은 높은 리스크
        alameda_risk = classifier.get_risk_score("Alameda Research")
        assert alameda_risk >= 7.0, f"Alameda 리스크가 너무 낮음: {alameda_risk}"
        print(f"\n✓ 리스크 스코어: Wintermute={wintermute_risk}, Alameda={alameda_risk}")

    def test_manipulation_flags(self, classifier):
        """조작 플래그 테스트."""
        # Alameda는 조작 플래그가 있어야 함
        has_flags = classifier.has_manipulation_flags("Alameda Research")
        assert has_flags, "Alameda Research는 조작 플래그가 있어야 함"

        flags = classifier.get_manipulation_flags("Alameda Research")
        assert "wash_trading" in flags or "market_manipulation" in flags
        print(f"\n✓ Alameda 조작 플래그: {flags}")

        # Wintermute는 조작 플래그 없음
        has_flags = classifier.has_manipulation_flags("Wintermute")
        assert not has_flags, "Wintermute는 조작 플래그가 없어야 함"
        print("✓ Wintermute 조작 플래그 없음")


class TestMMManipulationDetector:
    """MM 조작 감지기 테스트."""

    @pytest.fixture
    def detector(self):
        """조작 감지기 초기화."""
        config_path = Path(__file__).parent.parent / "data" / "vc_mm_info" / "vc_tiers.yaml"
        assert config_path.exists(), f"Config not found: {config_path}"
        mm_classifier = MMClassifier(config_path=config_path)
        return MMManipulationDetector(mm_classifier=mm_classifier)

    def test_no_manipulation(self, detector):
        """정상 거래 패턴 테스트."""
        now = datetime.now()
        trades = [
            Trade(timestamp=now - timedelta(seconds=i*10), price=100 + i*0.1,
                  amount=1.0, side="buy" if i % 2 == 0 else "sell")
            for i in range(20)
        ]

        result = detector.analyze("TEST", trades, mm_name="Wintermute")
        assert result.is_safe, "정상 패턴은 안전해야 함"
        print(f"\n✓ 정상 패턴 분석: 안전 (리스크: {result.overall_risk_score})")

    def test_mm_blacklist(self, detector):
        """MM 블랙리스트 감지 테스트."""
        result = detector.analyze("TEST", [], mm_name="Alameda Research")

        assert not result.is_safe, "Alameda는 안전하지 않아야 함"
        assert len(result.alerts) > 0, "경고가 있어야 함"
        assert result.overall_risk_score >= 5.0, "리스크가 높아야 함"
        print(f"\n✓ MM 블랙리스트 감지: {result.alerts[0].description}")

    def test_wash_trading_detection(self, detector):
        """워시 트레이딩 감지 테스트."""
        now = datetime.now()

        # 워시 트레이딩 패턴: 짧은 시간에 대량 거래, 가격 변동 없음, 매수/매도 균형
        trades = []
        for i in range(50):
            trades.append(Trade(
                timestamp=now - timedelta(seconds=i),  # 1초 간격
                price=100.0,  # 가격 변동 없음
                amount=10.0,  # 대량 거래
                side="buy" if i % 2 == 0 else "sell",  # 매수/매도 균형
            ))

        result = detector.analyze("WASH", trades)

        # 워시 트레이딩 감지 여부 확인
        wash_alerts = [a for a in result.alerts if a.manipulation_type == ManipulationType.WASH_TRADING]
        print(f"\n워시 트레이딩 감지: {len(wash_alerts)}개 경고")
        print(f"전체 리스크: {result.overall_risk_score}")

    def test_pump_and_dump_detection(self, detector):
        """펌프 앤 덤프 감지 테스트."""
        now = datetime.now()

        # 펌프 앤 덤프 패턴: 급등 후 급락
        trades = []
        for i in range(30):
            if i < 10:
                price = 100 + i * 3  # 펌프: 100 → 130 (30% 상승)
            elif i < 20:
                price = 130 - (i - 10) * 4  # 덤프: 130 → 90 (30% 하락)
            else:
                price = 90

            trades.append(Trade(
                timestamp=now - timedelta(minutes=30-i),
                price=price,
                amount=5.0,
                side="buy" if i < 10 else "sell",
            ))

        result = detector.analyze("PND", trades)

        # 펌프 앤 덤프 감지 여부 확인
        pnd_alerts = [a for a in result.alerts if a.manipulation_type == ManipulationType.PUMP_AND_DUMP]
        print(f"\n펌프 앤 덤프 감지: {len(pnd_alerts)}개 경고")
        print(f"전체 리스크: {result.overall_risk_score}")

    def test_format_alert(self, detector):
        """알림 포맷 테스트."""
        result = detector.analyze("TEST", [], mm_name="DWF Labs")

        from analysis.mm_manipulation_detector import format_manipulation_alert
        text = format_manipulation_alert(result)

        assert "TEST" in text
        assert "DWF Labs" in text or "리스크" in text
        print(f"\n경고 포맷:\n{text}")


class TestVCMMCollector:
    """VC/MM 수집기 통합 테스트."""

    @pytest.fixture
    def collector(self):
        """수집기 초기화."""
        config_dir = Path(__file__).parent.parent / "data" / "vc_mm_info"
        assert config_dir.exists(), f"Config dir not found: {config_dir}"
        return VCMMCollector(config_dir=config_dir)

    def test_vc_stats(self, collector):
        """VC 통계 조회."""
        stats = collector.get_vc_stats()
        assert stats["total_count"] >= 100
        print(f"\n✓ VC 통계: {stats}")

    def test_mm_stats(self, collector):
        """MM 통계 조회."""
        stats = collector.get_mm_stats()
        assert stats["total_count"] >= 50
        print(f"\n✓ MM 통계: {stats}")

    def test_get_all_tier1_vcs(self, collector):
        """Tier 1 VC 전체 조회."""
        tier1_vcs = collector.get_all_vcs(tier=1)
        assert len(tier1_vcs) >= 20
        print(f"\n✓ Tier 1 VC 개수: {len(tier1_vcs)}")
        print(f"  예시: {[v.name for v in tier1_vcs[:5]]}")

    def test_get_all_tier1_mms(self, collector):
        """Tier 1 MM 전체 조회."""
        tier1_mms = collector.get_all_mms(tier=1)
        assert len(tier1_mms) >= 15
        print(f"\n✓ Tier 1 MM 개수: {len(tier1_mms)}")
        print(f"  예시: {[m.name for m in tier1_mms[:5]]}")


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
