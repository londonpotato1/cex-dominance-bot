"""흥/망따리 시나리오 카드 생성 (Phase 6 + Phase 7 Quick Win #4).

ScenarioPlanner:
  - 공급 분류(SupplyResult) + 상장 유형(ListingTypeResult) + 헤징 가능성 조합
  - 흥따리 확률 계산 (Phase 0 데이터 기반 베이지안)
  - 시나리오 카드 생성 (UI/텔레그램 표시용)

확률 계수 (thresholds.yaml 기반):
  - base_probability: 0.51 (전체) / 0.42 (업비트만)
  - supply_constrained: +0.18
  - supply_smooth: -0.16
  - hedge_cex: 0.0 (baseline)
  - hedge_dex_only: -0.15 (망따리 방향)
  - hedge_none: +0.37 (최강 시그널)
  - market_bull: +0.07
  - market_neutral: +0.15
  - market_bear: -0.38

Phase 7 Quick Win #4 추가:
  - TGE 언락 리스크 통합 (VERY_HIGH: -0.25, HIGH: -0.15, MEDIUM: -0.05)
  - Reference price confidence 조정 (< 0.8: 보수적, < 0.6: WATCH_ONLY)
  - 다중 시나리오 생성 (BEST/LIKELY/WORST 케이스)

계수 신뢰성 관리 (v15 shrinkage):
  - 표본 < 10건 시 baseline 수렴
  - shrinkage = coeff * min(1.0, sample_count / min_sample_size)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from analysis.supply_classifier import SupplyResult, SupplyClassification
    from analysis.listing_type import ListingTypeResult, ListingType
    from analysis.tokenomics import TGEUnlockData, TGERiskLevel
    from analysis.reference_price import ReferencePrice

logger = logging.getLogger(__name__)


class ScenarioOutcome(Enum):
    """시나리오 결과 분류."""
    HEUNG_BIG = "heung_big"    # 대흥따리 (최대 김프 >= 30%)
    HEUNG = "heung"            # 흥따리 (최대 김프 >= 8%, 5분+ 유지)
    NEUTRAL = "neutral"        # 보통 (최대 김프 3~8% OR 피뢰침)
    MANG = "mang"              # 망따리 (최대 김프 < 3% OR 역프)


@dataclass
class ScenarioCard:
    """시나리오 카드 (UI 표시용)."""
    symbol: str
    exchange: str

    # 확률 (0.0 ~ 1.0)
    heung_probability: float
    heung_big_probability: float  # 대흥따리 확률 (heung 중 30%+ 비율)

    # 기여 요인
    supply_contribution: float    # 공급 요인 기여도
    hedge_contribution: float     # 헤징 요인 기여도
    market_contribution: float    # 시장 요인 기여도

    # 분류 결과
    predicted_outcome: ScenarioOutcome
    confidence: float             # 예측 신뢰도

    # 설명
    headline: str                 # 한줄 요약

    # 기여 요인 (default 있음, 뒤로 이동)
    tge_contribution: float = 0.0  # TGE 언락 리스크 기여도 (Phase 7)
    factors: list[str] = field(default_factory=list)  # 기여 요인 설명
    warnings: list[str] = field(default_factory=list)  # 주의사항

    # 메타데이터
    supply_class: str = ""        # constrained/smooth/neutral/unknown
    listing_type: str = ""        # TGE/DIRECT/SIDE/UNKNOWN
    hedge_type: str = ""          # cex/dex_only/none
    market_condition: str = ""    # bull/neutral/bear
    tge_risk_level: str = ""      # TGE 리스크 레벨 (Phase 7)
    ref_price_confidence: float = 1.0  # Reference price 신뢰도 (Phase 7)
    scenario_type: str = "likely"  # best/likely/worst (Phase 7)


# 전략 코드 ↔ 한국어 매핑 (strategies.yaml 대체)
STRATEGY_NAMES = {
    "AGGRESSIVE": "공격적 매수 (확신)",
    "MODERATE": "보통 매수 (표준)",
    "CONSERVATIVE": "보수적 매수 (주의)",
    "WATCH_ONLY": "관망 (정보 부족)",
    "NO_TRADE": "거래 금지 (NO-GO)",
}

# 시나리오 한줄 요약 템플릿
HEADLINE_TEMPLATES = {
    ScenarioOutcome.HEUNG_BIG: "대흥따리 기대! 공급 제약 + 헤징 어려움",
    ScenarioOutcome.HEUNG: "흥따리 가능성 높음",
    ScenarioOutcome.NEUTRAL: "평범한 상장 예상",
    ScenarioOutcome.MANG: "망따리 위험 - 공급 과잉 또는 헤징 용이",
}


class ScenarioPlanner:
    """흥/망따리 시나리오 플래너.

    Phase 0 데이터 기반 확률 계수 사용.
    v15 shrinkage 원칙: 표본 < 10건 시 baseline 수렴.

    사용법:
        planner = ScenarioPlanner()
        card = planner.generate_card(
            symbol="XYZ",
            exchange="upbit",
            supply_result=...,
            listing_type_result=...,
            hedge_type="none",
            market_condition="neutral",
        )
    """

    # 표본 수 (Phase 0 데이터 기반, 계수 shrinkage용)
    # 충분한 표본 확보 후 업데이트 필요
    _SAMPLE_COUNTS = {
        "supply_constrained": 29,   # 67건 중 constrained 분류
        "supply_smooth": 37,        # 67건 중 smooth 분류
        "hedge_cex": 45,            # CEX 선물 가능
        "hedge_dex_only": 4,        # DEX 선물만 (표본 부족!)
        "hedge_none": 8,            # 헤징 불가 (표본 부족!)
        "market_bull": 25,          # 불장
        "market_neutral": 32,       # 중립
        "market_bear": 8,           # 약세장 (표본 부족!)
        "prev_heung": 0,            # 전례 흥따리 (데이터 없음)
        # Phase 7: TGE 언락 리스크 (표본 부족, 추정값)
        "tge_very_high": 3,         # 표본 부족!
        "tge_high": 5,              # 표본 부족!
        "tge_medium": 8,            # 표본 부족!
    }

    # Phase 7: TGE 리스크 계수 (추정값, Phase 0 데이터 확보 후 재조정)
    _TGE_RISK_COEFFICIENTS = {
        "very_high": -0.25,  # MATIC 같은 케이스: TGE 20% → 망따리 위험
        "high": -0.15,       # XAI 같은 케이스: TGE 12% → 주의
        "medium": -0.05,     # MOCA/ACE: TGE 5-8% → 약간 불리
        "low": 0.0,          # ARB/OP: TGE < 5% → 영향 없음
        "very_low": 0.0,     # STRK: TGE 1.3% → 영향 없음
        "unknown": 0.0,      # 데이터 없음
    }

    def __init__(
        self,
        config_dir: str | Path | None = None,
        use_upbit_base: bool = True,
    ) -> None:
        """
        Args:
            config_dir: 설정 디렉토리 (thresholds.yaml 위치).
            use_upbit_base: True면 업비트 전용 base_probability 사용 (균형 데이터).
        """
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self._config_dir = Path(config_dir)
        self._use_upbit_base = use_upbit_base

        # 설정 로드
        self._coefficients = self._load_coefficients()
        self._heung_definition = self._load_heung_definition()
        self._min_sample_size = self._coefficients.get(
            "min_sample_size", 10,
        )

    def _load_coefficients(self) -> dict:
        """thresholds.yaml에서 시나리오 계수 로드."""
        thresholds_path = self._config_dir / "thresholds.yaml"
        try:
            with open(thresholds_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            coeffs = config.get("scenario_coefficients", {})
            governance = config.get("coefficient_governance", {})

            # governance 설정 병합
            coeffs["min_sample_size"] = governance.get("min_sample_size", 10)

            logger.info(
                "[Scenario] 계수 로드 완료: base=%.2f, upbit_base=%.2f",
                coeffs.get("base_probability", 0.51),
                coeffs.get("base_probability_upbit", 0.42),
            )
            return coeffs

        except Exception as e:
            logger.warning(
                "[Scenario] thresholds.yaml 로드 실패, 기본값 사용: %s", e,
            )
            return self._default_coefficients()

    def _load_heung_definition(self) -> dict:
        """흥따리 판정 기준 로드."""
        thresholds_path = self._config_dir / "thresholds.yaml"
        try:
            with open(thresholds_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            return config.get("heung_definition", {
                "min_premium_pct": 8,
                "min_duration_sec": 300,
                "lightning_rod_window_sec": 60,
            })
        except Exception:
            return {
                "min_premium_pct": 8,
                "min_duration_sec": 300,
                "lightning_rod_window_sec": 60,
            }

    def _default_coefficients(self) -> dict:
        """기본 계수 (fallback)."""
        return {
            "base_probability": 0.51,
            "base_probability_upbit": 0.42,
            "supply_constrained": 0.18,
            "supply_smooth": -0.16,
            "hedge_cex": 0.0,
            "hedge_dex_only": -0.15,
            "hedge_none": 0.37,
            "market_bull": 0.07,
            "market_neutral": 0.15,
            "market_bear": -0.38,
            "prev_heung": 0.0,
            # Phase 7: TGE 리스크
            "tge_very_high": -0.25,
            "tge_high": -0.15,
            "tge_medium": -0.05,
            "tge_low": 0.0,
            "tge_very_low": 0.0,
            "min_sample_size": 10,
        }

    def _apply_shrinkage(self, key: str, raw_coeff: float) -> float:
        """계수에 shrinkage 적용 (v15).

        표본 수가 min_sample_size 미만이면 baseline(0.0)으로 수렴.
        shrinkage = coeff * min(1.0, sample_count / min_sample_size)
        """
        sample_count = self._SAMPLE_COUNTS.get(key, 0)
        if sample_count >= self._min_sample_size:
            return raw_coeff

        shrinkage_factor = sample_count / self._min_sample_size
        shrunk = raw_coeff * shrinkage_factor

        logger.debug(
            "[Scenario] shrinkage 적용: %s %.3f → %.3f (표본 %d/%d)",
            key, raw_coeff, shrunk, sample_count, self._min_sample_size,
        )
        return shrunk

    def _get_coeff(self, key: str) -> float:
        """shrinkage 적용된 계수 반환."""
        raw = self._coefficients.get(key, 0.0)
        return self._apply_shrinkage(key, raw)

    def _calculate_heung_probability(
        self,
        supply_class: str,
        hedge_type: str,
        market_condition: str,
        exchange: str = "upbit",
        tge_risk_level: str = "unknown",
    ) -> tuple[float, float, float, float, float]:
        """흥따리 확률 계산.

        Returns:
            (total_prob, supply_contrib, hedge_contrib, market_contrib, tge_contrib)
        """
        # 기저 확률
        if self._use_upbit_base and exchange.lower() == "upbit":
            base = self._coefficients.get("base_probability_upbit", 0.42)
        else:
            base = self._coefficients.get("base_probability", 0.51)

        # 1. 공급 요인
        if supply_class == "constrained":
            supply_coeff = self._get_coeff("supply_constrained")
        elif supply_class == "smooth":
            supply_coeff = self._get_coeff("supply_smooth")
        else:
            supply_coeff = 0.0

        # 2. 헤징 요인
        if hedge_type == "cex":
            hedge_coeff = self._get_coeff("hedge_cex")
        elif hedge_type == "dex_only":
            hedge_coeff = self._get_coeff("hedge_dex_only")
        elif hedge_type == "none":
            hedge_coeff = self._get_coeff("hedge_none")
        else:
            hedge_coeff = 0.0

        # 3. 시장 요인
        if market_condition == "bull":
            market_coeff = self._get_coeff("market_bull")
        elif market_condition == "bear":
            market_coeff = self._get_coeff("market_bear")
        else:  # neutral
            market_coeff = self._get_coeff("market_neutral")

        # 4. TGE 언락 리스크 (Phase 7)
        tge_key = f"tge_{tge_risk_level}"
        tge_coeff = self._get_coeff(tge_key)

        # 총 확률 (0.0~1.0 클램핑)
        total = base + supply_coeff + hedge_coeff + market_coeff + tge_coeff
        total = max(0.0, min(1.0, total))

        return total, supply_coeff, hedge_coeff, market_coeff, tge_coeff

    def _predict_outcome(
        self,
        heung_prob: float,
        hedge_type: str,
        supply_class: str,
    ) -> tuple[ScenarioOutcome, float]:
        """시나리오 결과 예측.

        Returns:
            (predicted_outcome, confidence)
        """
        # 대흥따리 조건: 헤징 불가 + 공급 제약 + 높은 흥따리 확률
        if (
            hedge_type == "none"
            and supply_class == "constrained"
            and heung_prob >= 0.7
        ):
            return ScenarioOutcome.HEUNG_BIG, heung_prob

        # 흥따리 (v10: 55% → 50% 낮춤 - 백테스트 개선)
        if heung_prob >= 0.50:
            return ScenarioOutcome.HEUNG, heung_prob

        # 보통 (v10: 35-50% 범위로 축소)
        if heung_prob >= 0.40:
            return ScenarioOutcome.NEUTRAL, 1.0 - abs(heung_prob - 0.45) * 4

        # 망따리
        return ScenarioOutcome.MANG, 1.0 - heung_prob

    def _generate_factors(
        self,
        supply_class: str,
        supply_contrib: float,
        hedge_type: str,
        hedge_contrib: float,
        market_condition: str,
        market_contrib: float,
        listing_type: str,
        tge_risk_level: str = "unknown",
        tge_contrib: float = 0.0,
    ) -> list[str]:
        """기여 요인 설명 생성."""
        factors = []

        # 공급 요인
        if supply_class == "constrained":
            factors.append(f"공급 제약 (+{supply_contrib*100:.1f}%p)")
        elif supply_class == "smooth":
            factors.append(f"공급 원활 ({supply_contrib*100:.1f}%p)")
        elif supply_class == "unknown":
            factors.append("공급 상태 미확인 (neutral)")

        # 헤징 요인
        if hedge_type == "none":
            factors.append(f"헤징 불가 (+{hedge_contrib*100:.1f}%p) - 최강 시그널")
        elif hedge_type == "dex_only":
            factors.append(f"DEX 선물만 ({hedge_contrib*100:.1f}%p)")
        else:
            factors.append("CEX 선물 헤징 가능 (baseline)")

        # 시장 요인
        if market_condition == "bull":
            factors.append(f"불장 (+{market_contrib*100:.1f}%p)")
        elif market_condition == "bear":
            factors.append(f"약세장 ({market_contrib*100:.1f}%p) - 최강 역시그널")
        else:
            factors.append(f"중립 시장 (+{market_contrib*100:.1f}%p)")

        # Phase 7: TGE 언락 리스크
        if tge_risk_level != "unknown":
            tge_emoji = {
                "very_high": "🚨",
                "high": "🔴",
                "medium": "🟠",
                "low": "🟡",
                "very_low": "🟢",
            }
            emoji = tge_emoji.get(tge_risk_level, "")
            factors.append(
                f"{emoji} TGE 리스크: {tge_risk_level.upper()} ({tge_contrib*100:.1f}%p)"
            )

        # 상장 유형 (참고)
        listing_names = {
            "TGE": "세계 최초 상장 (TGE)",
            "DIRECT": "직상장 (해외→국내)",
            "SIDE": "옆상장 (국내 경쟁)",
            "UNKNOWN": "상장 유형 미확인",
        }
        factors.append(f"상장 유형: {listing_names.get(listing_type, listing_type)}")

        return factors

    def _generate_warnings(
        self,
        supply_class: str,
        hedge_type: str,
        listing_type: str,
        confidence: float,
        tge_risk_level: str = "unknown",
        ref_price_confidence: float = 1.0,
    ) -> list[str]:
        """주의사항 생성."""
        warnings = []

        # 정보 부족
        if supply_class == "unknown":
            warnings.append("공급 데이터 부족 - 예측 신뢰도 낮음")
        if listing_type == "UNKNOWN":
            warnings.append("상장 유형 미확인 - WATCH_ONLY 강제")

        # 표본 부족 계수
        if hedge_type == "dex_only":
            warnings.append("DEX-only 계수는 표본 부족 (shrinkage 적용됨)")
        if hedge_type == "none":
            warnings.append("헤징불가 계수는 표본 부족 (shrinkage 적용됨)")

        # Phase 7: TGE 리스크 경고
        if tge_risk_level in ("very_high", "high"):
            warnings.append(
                f"⚠️ TGE 언락 리스크 {tge_risk_level.upper()} - 에어드랍/VC 덤핑 우려"
            )

        # Phase 7: Reference price 신뢰도 경고
        if ref_price_confidence < 0.6:
            warnings.append(
                f"⚠️ Reference 가격 신뢰도 낮음 ({ref_price_confidence:.0%}) - WATCH_ONLY 권장"
            )
        elif ref_price_confidence < 0.8:
            warnings.append(
                f"참조 가격 신뢰도 보통 ({ref_price_confidence:.0%}) - 보수적 진입 권장"
            )

        # 낮은 신뢰도
        if confidence < 0.5:
            warnings.append(f"예측 신뢰도 낮음 ({confidence*100:.0f}%)")

        return warnings

    def generate_card(
        self,
        symbol: str,
        exchange: str,
        supply_result: Optional[SupplyResult] = None,
        listing_type_result: Optional[ListingTypeResult] = None,
        hedge_type: str = "cex",
        market_condition: str = "neutral",
        tge_unlock: Optional[TGEUnlockData] = None,
        ref_price: Optional[ReferencePrice] = None,
        scenario_type: str = "likely",
    ) -> ScenarioCard:
        """시나리오 카드 생성.

        Args:
            symbol: 토큰 심볼.
            exchange: 상장 거래소.
            supply_result: 공급 분류 결과.
            listing_type_result: 상장 유형 결과.
            hedge_type: 헤징 유형 ("cex", "dex_only", "none").
            market_condition: 시장 상황 ("bull", "neutral", "bear").
            tge_unlock: TGE 언락 데이터 (Phase 7).
            ref_price: Reference price 결과 (Phase 7).
            scenario_type: 시나리오 유형 ("best", "likely", "worst").

        Returns:
            ScenarioCard.
        """
        # 공급 분류 추출
        if supply_result:
            supply_class = supply_result.classification.value
        else:
            supply_class = "unknown"

        # 상장 유형 추출
        if listing_type_result:
            listing_type = listing_type_result.listing_type.value
        else:
            listing_type = "UNKNOWN"

        # Phase 7: TGE 리스크 레벨
        tge_risk_level = "unknown"
        if tge_unlock:
            tge_risk_level = tge_unlock.risk_assessment.value

        # Phase 7: Reference price 신뢰도
        ref_price_confidence = 1.0
        if ref_price:
            ref_price_confidence = ref_price.confidence

        # 확률 계산
        (
            heung_prob,
            supply_contrib,
            hedge_contrib,
            market_contrib,
            tge_contrib,
        ) = self._calculate_heung_probability(
            supply_class, hedge_type, market_condition, exchange, tge_risk_level,
        )

        # Phase 7: Reference price 신뢰도에 따른 확률 조정
        if ref_price_confidence < 0.8:
            # 낮은 신뢰도 → 보수적 조정 (흥따리 확률 감소)
            adjustment = (0.8 - ref_price_confidence) * 0.5  # 최대 -0.1
            heung_prob = max(0.0, heung_prob - adjustment)
            logger.debug(
                "[Scenario] Reference 신뢰도 조정: %.2f → 확률 %.3f 감소",
                ref_price_confidence, adjustment,
            )

        # 대흥따리 확률 (heung 중 30%+ 비율, Phase 0 데이터 기반)
        # 67건 중 대흥따리 21건, 흥따리 13건 → 대흥따리/전체흥따리 = 21/34 ≈ 62%
        heung_big_ratio = 0.62 if heung_prob > 0.6 else 0.4
        heung_big_prob = heung_prob * heung_big_ratio

        # 결과 예측
        outcome, confidence = self._predict_outcome(
            heung_prob, hedge_type, supply_class,
        )

        # Phase 7: Reference price 낮으면 신뢰도 감소
        if ref_price_confidence < 0.8:
            confidence *= ref_price_confidence

        # 설명 생성
        factors = self._generate_factors(
            supply_class, supply_contrib,
            hedge_type, hedge_contrib,
            market_condition, market_contrib,
            listing_type,
            tge_risk_level, tge_contrib,
        )
        warnings = self._generate_warnings(
            supply_class, hedge_type, listing_type, confidence,
            tge_risk_level, ref_price_confidence,
        )

        # 헤드라인
        headline = HEADLINE_TEMPLATES.get(outcome, "")
        if not headline:
            headline = f"예측: {outcome.value} (확률 {heung_prob*100:.0f}%)"

        # Phase 7: 시나리오 유형별 헤드라인 수정
        if scenario_type == "best":
            headline = f"✨ BEST 케이스: {headline}"
        elif scenario_type == "worst":
            headline = f"💀 WORST 케이스: {headline}"

        card = ScenarioCard(
            symbol=symbol,
            exchange=exchange,
            heung_probability=heung_prob,
            heung_big_probability=heung_big_prob,
            supply_contribution=supply_contrib,
            hedge_contribution=hedge_contrib,
            market_contribution=market_contrib,
            tge_contribution=tge_contrib,
            predicted_outcome=outcome,
            confidence=confidence,
            headline=headline,
            factors=factors,
            warnings=warnings,
            supply_class=supply_class,
            listing_type=listing_type,
            hedge_type=hedge_type,
            market_condition=market_condition,
            tge_risk_level=tge_risk_level,
            ref_price_confidence=ref_price_confidence,
            scenario_type=scenario_type,
        )

        logger.info(
            "[Scenario] %s@%s 카드 생성 (%s): outcome=%s, prob=%.1f%%, "
            "supply=%s(%+.1f), hedge=%s(%+.1f), market=%s(%+.1f), tge=%s(%+.1f)",
            symbol, exchange, scenario_type, outcome.value, heung_prob * 100,
            supply_class, supply_contrib * 100,
            hedge_type, hedge_contrib * 100,
            market_condition, market_contrib * 100,
            tge_risk_level, tge_contrib * 100,
        )

        return card


def generate_multiple_scenarios(
    symbol: str,
    exchange: str,
    planner: ScenarioPlanner,
    supply_result: Optional[SupplyResult] = None,
    listing_type_result: Optional[ListingTypeResult] = None,
    hedge_type: str = "cex",
    market_condition: str = "neutral",
    tge_unlock: Optional[TGEUnlockData] = None,
    ref_price: Optional[ReferencePrice] = None,
) -> list[ScenarioCard]:
    """다중 시나리오 생성 (BEST/LIKELY/WORST 케이스).

    Phase 7 Quick Win #4: 3개 이상 시나리오 카드 제공.

    시나리오 유형:
      - BEST: 가장 낙관적 (market=bull, 공급 제약 강조)
      - LIKELY: 현실적 (실제 입력값)
      - WORST: 가장 비관적 (TGE 리스크 강조, ref 신뢰도 낮음 가정)

    Args:
        symbol: 토큰 심볼.
        exchange: 거래소.
        planner: ScenarioPlanner 인스턴스.
        supply_result: 공급 분류 결과.
        listing_type_result: 상장 유형 결과.
        hedge_type: 헤징 유형.
        market_condition: 시장 상황.
        tge_unlock: TGE 언락 데이터.
        ref_price: Reference price 결과.

    Returns:
        [best_card, likely_card, worst_card] 리스트.
    """
    scenarios = []

    # 1. BEST 케이스 (낙관적) — docstring 순서: [best, likely, worst]
    # - 시장 상황을 bull로 가정
    # - TGE 리스크 무시 (very_low로 강제)
    best_market = "bull"
    best_tge = None  # TGE 리스크 무시
    if tge_unlock and tge_unlock.risk_assessment.value in ("low", "very_low"):
        best_tge = tge_unlock  # 원래 낮으면 그대로

    best_card = planner.generate_card(
        symbol=symbol,
        exchange=exchange,
        supply_result=supply_result,
        listing_type_result=listing_type_result,
        hedge_type=hedge_type,
        market_condition=best_market,
        tge_unlock=best_tge,
        ref_price=ref_price,
        scenario_type="best",
    )
    scenarios.append(best_card)

    # 2. LIKELY 케이스 (현실적)
    likely_card = planner.generate_card(
        symbol=symbol,
        exchange=exchange,
        supply_result=supply_result,
        listing_type_result=listing_type_result,
        hedge_type=hedge_type,
        market_condition=market_condition,
        tge_unlock=tge_unlock,
        ref_price=ref_price,
        scenario_type="likely",
    )
    scenarios.append(likely_card)

    # 3. WORST 케이스 (비관적)
    # - 시장 상황을 bear로 가정
    # - TGE 리스크 최대 강조
    # - Reference 신뢰도 낮게 가정
    worst_market = "bear"
    worst_ref = ref_price
    if ref_price and ref_price.confidence > 0.6:
        # 신뢰도를 0.6으로 강제 (가정: 참조 가격 불확실)
        from analysis.reference_price import ReferencePrice, ReferenceSource
        worst_ref = ReferencePrice(
            symbol=ref_price.symbol,
            price_usd=ref_price.price_usd,
            source=ref_price.source,
            confidence=0.6,  # 낮춤
            volume_24h_usd=ref_price.volume_24h_usd,
        )

    worst_card = planner.generate_card(
        symbol=symbol,
        exchange=exchange,
        supply_result=supply_result,
        listing_type_result=listing_type_result,
        hedge_type=hedge_type,
        market_condition=worst_market,
        tge_unlock=tge_unlock,  # TGE 리스크 그대로
        ref_price=worst_ref,
        scenario_type="worst",
    )
    scenarios.append(worst_card)

    logger.info(
        "[Scenario] %s@%s 다중 시나리오 생성 완료: BEST(%.0f%%), LIKELY(%.0f%%), WORST(%.0f%%)",
        symbol, exchange,
        best_card.heung_probability * 100,
        likely_card.heung_probability * 100,
        worst_card.heung_probability * 100,
    )

    return scenarios


def format_scenario_card_text(card: ScenarioCard) -> str:
    """시나리오 카드 텍스트 포맷 (텔레그램/UI용).

    Returns:
        Formatted string for display.
    """
    outcome_emoji = {
        ScenarioOutcome.HEUNG_BIG: "🔥",
        ScenarioOutcome.HEUNG: "✨",
        ScenarioOutcome.NEUTRAL: "➖",
        ScenarioOutcome.MANG: "💀",
    }

    outcome_name = {
        ScenarioOutcome.HEUNG_BIG: "대흥따리",
        ScenarioOutcome.HEUNG: "흥따리",
        ScenarioOutcome.NEUTRAL: "보통",
        ScenarioOutcome.MANG: "망따리",
    }

    emoji = outcome_emoji.get(card.predicted_outcome, "❓")
    name = outcome_name.get(card.predicted_outcome, "???")

    # Phase 7: 시나리오 타입 표시
    scenario_label = {
        "best": "✨ BEST 케이스",
        "likely": "📊 LIKELY 케이스",
        "worst": "💀 WORST 케이스",
    }
    type_label = scenario_label.get(card.scenario_type, "")

    lines = [
        f"{emoji} {card.symbol}@{card.exchange} 시나리오",
        f"━━━━━━━━━━━━━━━",
    ]

    if type_label:
        lines.append(f"{type_label}")

    lines.extend([
        f"예측: {name} ({card.heung_probability*100:.0f}%)",
        f"",
        f"📊 기여 요인:",
    ])

    for factor in card.factors:
        lines.append(f"  • {factor}")

    # Phase 7: Reference price 신뢰도 표시
    if card.ref_price_confidence < 1.0:
        lines.append("")
        lines.append(f"🔍 참조 가격 신뢰도: {card.ref_price_confidence:.0%}")

    if card.warnings:
        lines.append("")
        lines.append("⚠️ 주의:")
        for warning in card.warnings:
            lines.append(f"  • {warning}")

    lines.append(f"━━━━━━━━━━━━━━━")
    lines.append(f"신뢰도: {card.confidence*100:.0f}%")

    return "\n".join(lines)
