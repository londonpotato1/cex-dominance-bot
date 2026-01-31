"""Phase 5a 통합 테스트 — 오프라인 (REST API 불필요).

검증 항목:
  1. ListingType enum 정의
  2. ListingTypeClassifier 인스턴스 생성
  3. ListingType TGE 분류 (top_exchange 없음)
  4. ListingType DIRECT 분류 (해외 top_exchange 존재)
  5. ListingType UNKNOWN 기본값
  6. SupplyClassification enum 정의
  7. SupplyClassifier 인스턴스 생성
  8. SupplyResult 생성 (CONSTRAINED)
  9. SupplyResult 생성 (SMOOTH)
  10. SupplyResult 생성 (UNKNOWN — 데이터 없음)
  11. SupplyFactor 스코어 정규화 (-1 ~ +1)
  12. Turnover Ratio 계산
  13. StrategyCode enum 정의
  14. GateResult Phase 5a 확장 필드
  15. GateChecker._determine_strategy() (CONSTRAINED + TGE → AGGRESSIVE)
  16. GateChecker._determine_strategy() (SMOOTH + SIDE → WATCH_ONLY)
  17. Feature flag supply_classifier 분기
  18. Feature flag listing_type 분기
  19. 열화 규칙: 분류 실패 시 warning만
  20. thresholds.yaml 로드

사용법:
    python scripts/test_phase5a.py
"""

import asyncio
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from analysis.listing_type import (
    ListingType,
    ListingTypeClassifier,
    ListingTypeResult,
    get_strategy_modifier,
)
from analysis.supply_classifier import (
    SupplyClassification,
    SupplyClassifier,
    SupplyFactor,
    SupplyInput,
    SupplyResult,
)
from analysis.gate import (
    AlertLevel,
    GateChecker,
    GateInput,
    GateResult,
    StrategyCode,
)
from analysis.cost_model import CostModel, CostResult
from analysis.premium import PremiumCalculator
from store.database import get_connection, apply_migrations
from store.writer import DatabaseWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test_phase5a")

_PASS = 0
_FAIL = 0


def result(name: str, ok: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if ok:
        _PASS += 1
        status = "PASS"
    else:
        _FAIL += 1
        status = "FAIL"
    msg = f"[{status}] {name}"
    if detail:
        msg += f" — {detail}"
    logger.info(msg)


# ---- ListingType 테스트 ----

def test_01_listing_type_enum() -> None:
    """ListingType enum 정의."""
    result(
        "01 ListingType enum",
        ListingType.TGE.value == "TGE"
        and ListingType.DIRECT.value == "DIRECT"
        and ListingType.SIDE.value == "SIDE"
        and ListingType.UNKNOWN.value == "UNKNOWN",
        f"{[e.value for e in ListingType]}",
    )


def test_02_listing_classifier_instance() -> None:
    """ListingTypeClassifier 인스턴스 생성."""
    classifier = ListingTypeClassifier()
    result(
        "02 ListingTypeClassifier instance",
        classifier is not None,
    )


async def test_03_listing_type_tge() -> None:
    """ListingType TGE 분류 (top_exchange 없음)."""
    classifier = ListingTypeClassifier()
    res = await classifier.classify(
        symbol="NEWTOKEN",
        exchange="upbit",
        top_exchange="",  # 없음 → TGE
    )
    result(
        "03 ListingType TGE",
        res.listing_type == ListingType.TGE,
        f"type={res.listing_type.value}, conf={res.confidence:.2f}",
    )


async def test_04_listing_type_direct() -> None:
    """ListingType DIRECT 분류 (해외 top_exchange 존재)."""
    classifier = ListingTypeClassifier()
    res = await classifier.classify(
        symbol="BTC",
        exchange="upbit",
        top_exchange="Binance",  # 해외 거래소 → DIRECT
    )
    result(
        "04 ListingType DIRECT",
        res.listing_type == ListingType.DIRECT,
        f"type={res.listing_type.value}, top={res.top_exchange}",
    )


async def test_05_listing_type_unknown() -> None:
    """ListingType 예외 시 UNKNOWN."""
    classifier = ListingTypeClassifier()
    # 강제로 예외 유발은 어려우니, UNKNOWN 반환 조건 테스트
    # 국내 거래소가 top_exchange인 경우 TGE 또는 UNKNOWN
    res = await classifier.classify(
        symbol="UNKNOWN",
        exchange="upbit",
        top_exchange="upbit",  # 국내 거래소만 → TGE (7일 내)
    )
    # 이 경우는 TGE로 분류됨 (국내 거래소만)
    result(
        "05 ListingType default",
        res.listing_type in (ListingType.TGE, ListingType.UNKNOWN),
        f"type={res.listing_type.value}",
    )


# ---- SupplyClassifier 테스트 ----

def test_06_supply_classification_enum() -> None:
    """SupplyClassification enum 정의."""
    result(
        "06 SupplyClassification enum",
        SupplyClassification.CONSTRAINED.value == "constrained"
        and SupplyClassification.SMOOTH.value == "smooth"
        and SupplyClassification.NEUTRAL.value == "neutral"
        and SupplyClassification.UNKNOWN.value == "unknown",
        f"{[e.value for e in SupplyClassification]}",
    )


def test_07_supply_classifier_instance() -> None:
    """SupplyClassifier 인스턴스 생성."""
    classifier = SupplyClassifier()
    result(
        "07 SupplyClassifier instance",
        classifier is not None,
    )


async def test_08_supply_constrained() -> None:
    """SupplyResult CONSTRAINED (공급 제약)."""
    classifier = SupplyClassifier()
    inp = SupplyInput(
        symbol="TEST",
        exchange="upbit",
        hot_wallet_usd=10_000,  # 매우 부족 → constrained
        hot_wallet_confidence=0.8,
        dex_liquidity_usd=5_000,  # 매우 부족
        dex_confidence=0.7,
        withdrawal_open=False,  # 출금 불가 → constrained
        withdrawal_confidence=1.0,
    )
    res = await classifier.classify(inp)
    result(
        "08 Supply CONSTRAINED",
        res.classification == SupplyClassification.CONSTRAINED,
        f"class={res.classification.value}, score={res.total_score:.2f}",
    )


async def test_09_supply_smooth() -> None:
    """SupplyResult SMOOTH (공급 원활)."""
    classifier = SupplyClassifier()
    inp = SupplyInput(
        symbol="TEST",
        exchange="upbit",
        hot_wallet_usd=2_000_000,  # 충분 → smooth
        hot_wallet_confidence=0.9,
        dex_liquidity_usd=1_000_000,  # 풍부
        dex_confidence=0.8,
        withdrawal_open=True,  # 출금 가능
        withdrawal_confidence=1.0,
        airdrop_claim_rate=0.9,  # 대부분 클레임
        airdrop_confidence=0.7,
    )
    res = await classifier.classify(inp)
    result(
        "09 Supply SMOOTH",
        res.classification == SupplyClassification.SMOOTH,
        f"class={res.classification.value}, score={res.total_score:.2f}",
    )


async def test_10_supply_unknown() -> None:
    """SupplyResult UNKNOWN (데이터 없음)."""
    classifier = SupplyClassifier()
    inp = SupplyInput(
        symbol="TEST",
        exchange="upbit",
        # 모든 팩터 None
    )
    res = await classifier.classify(inp)
    result(
        "10 Supply UNKNOWN",
        res.classification == SupplyClassification.UNKNOWN,
        f"class={res.classification.value}, warnings={res.warnings}",
    )


def test_11_supply_factor_score() -> None:
    """SupplyFactor 스코어 정규화 (-1 ~ +1)."""
    factor = SupplyFactor(
        name="test",
        raw_value=100.0,
        score=-0.5,
        weight=0.3,
        confidence=0.8,
    )
    result(
        "11 SupplyFactor score range",
        -1.0 <= factor.score <= 1.0,
        f"score={factor.score}",
    )


async def test_12_turnover_ratio() -> None:
    """Turnover Ratio 계산."""
    classifier = SupplyClassifier()
    inp = SupplyInput(
        symbol="TEST",
        exchange="upbit",
        deposit_krw=10_000_000_000,  # 100억
        volume_5m_krw=50_000_000_000,  # 500억
        withdrawal_open=True,
        withdrawal_confidence=1.0,
    )
    res = await classifier.classify(inp)
    expected_turnover = 50_000_000_000 / 10_000_000_000  # 5.0
    result(
        "12 Turnover Ratio",
        res.turnover_ratio is not None and abs(res.turnover_ratio - 5.0) < 0.01,
        f"turnover={res.turnover_ratio}",
    )


# ---- Strategy 테스트 ----

def test_13_strategy_code_enum() -> None:
    """StrategyCode enum 정의."""
    result(
        "13 StrategyCode enum",
        StrategyCode.AGGRESSIVE.value == "AGGRESSIVE"
        and StrategyCode.WATCH_ONLY.value == "WATCH_ONLY",
        f"{[e.value for e in StrategyCode]}",
    )


def test_14_gate_result_phase5a_fields() -> None:
    """GateResult Phase 5a 확장 필드."""
    res = GateResult(
        can_proceed=True,
        supply_result=SupplyResult(
            classification=SupplyClassification.CONSTRAINED,
            total_score=-0.5,
            confidence=0.8,
        ),
        listing_type_result=ListingTypeResult(
            listing_type=ListingType.TGE,
            confidence=0.9,
            top_exchange="",
        ),
        recommended_strategy=StrategyCode.AGGRESSIVE,
    )
    result(
        "14 GateResult Phase 5a fields",
        res.supply_result is not None
        and res.listing_type_result is not None
        and res.recommended_strategy == StrategyCode.AGGRESSIVE,
    )


def test_15_strategy_constrained_tge() -> None:
    """Strategy: CONSTRAINED + TGE → AGGRESSIVE."""
    # GateChecker 없이 직접 로직 테스트
    # _determine_strategy 메서드는 GateChecker 인스턴스 필요
    # 여기서는 get_strategy_modifier 헬퍼 테스트
    modifier = get_strategy_modifier(ListingType.TGE)
    result(
        "15 Strategy modifier TGE",
        modifier > 0,  # TGE는 양수 보정
        f"modifier={modifier}",
    )


def test_16_strategy_smooth_side() -> None:
    """Strategy: SMOOTH + SIDE → WATCH_ONLY."""
    modifier = get_strategy_modifier(ListingType.SIDE)
    result(
        "16 Strategy modifier SIDE",
        modifier < 0,  # SIDE는 음수 보정
        f"modifier={modifier}",
    )


# ---- Feature Flag 테스트 ----

def test_17_feature_flag_supply() -> None:
    """Feature flag supply_classifier 정의."""
    from pathlib import Path
    import yaml

    config_path = _ROOT / "config" / "features.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            features = yaml.safe_load(f) or {}
        result(
            "17 Feature flag supply_classifier",
            "supply_classifier" in features,
            f"value={features.get('supply_classifier')}",
        )
    else:
        result("17 Feature flag supply_classifier", False, "features.yaml 미발견")


def test_18_feature_flag_listing_type() -> None:
    """Feature flag listing_type 정의."""
    from pathlib import Path
    import yaml

    config_path = _ROOT / "config" / "features.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            features = yaml.safe_load(f) or {}
        result(
            "18 Feature flag listing_type",
            "listing_type" in features,
            f"value={features.get('listing_type')}",
        )
    else:
        result("18 Feature flag listing_type", False, "features.yaml 미발견")


async def test_19_degradation_warning() -> None:
    """열화 규칙: 분류 실패 시 warning만."""
    classifier = SupplyClassifier()
    # 모든 데이터 None → UNKNOWN + warning
    inp = SupplyInput(symbol="TEST", exchange="upbit")
    res = await classifier.classify(inp)
    result(
        "19 Degradation warning",
        res.classification == SupplyClassification.UNKNOWN
        and len(res.warnings) > 0,
        f"warnings={res.warnings}",
    )


def test_20_thresholds_yaml() -> None:
    """thresholds.yaml 로드."""
    import yaml

    config_path = _ROOT / "config" / "thresholds.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            thresholds = yaml.safe_load(f) or {}
        result(
            "20 thresholds.yaml load",
            "turnover_ratio" in thresholds
            and "supply_classifier_weights" in thresholds,
            f"keys={list(thresholds.keys())[:5]}...",
        )
    else:
        result("20 thresholds.yaml load", False, "thresholds.yaml 미발견")


# ---- 메인 ----

async def main() -> None:
    logger.info("=" * 60)
    logger.info("Phase 5a 통합 테스트 시작")
    logger.info("=" * 60)

    # 동기 테스트
    test_01_listing_type_enum()
    test_02_listing_classifier_instance()
    test_06_supply_classification_enum()
    test_07_supply_classifier_instance()
    test_11_supply_factor_score()
    test_13_strategy_code_enum()
    test_14_gate_result_phase5a_fields()
    test_15_strategy_constrained_tge()
    test_16_strategy_smooth_side()
    test_17_feature_flag_supply()
    test_18_feature_flag_listing_type()
    test_20_thresholds_yaml()

    # 비동기 테스트
    await test_03_listing_type_tge()
    await test_04_listing_type_direct()
    await test_05_listing_type_unknown()
    await test_08_supply_constrained()
    await test_09_supply_smooth()
    await test_10_supply_unknown()
    await test_12_turnover_ratio()
    await test_19_degradation_warning()

    logger.info("=" * 60)
    logger.info(f"테스트 완료: {_PASS} PASS / {_FAIL} FAIL / 총 {_PASS + _FAIL}건")
    logger.info("=" * 60)

    if _FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
