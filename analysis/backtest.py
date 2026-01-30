"""백테스팅 프레임워크 - Phase 7 Week 2.

시나리오 예측 정확도 검증:
  - listing_data.csv 67건 히스토리 사용
  - GOOD/BAD 시나리오 예측 vs 실제 결과 비교
  - 목표: 70%+ 정확도

사용법:
    from analysis.backtest import BacktestEngine

    engine = BacktestEngine()
    results = await engine.run_backtest()
    print(f"정확도: {results.accuracy:.1%}")
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from analysis.scenario import ScenarioPlanner, ScenarioOutcome, ScenarioCard
from analysis.supply_classifier import (
    SupplyClassifier,
    SupplyInput,
    SupplyClassification,
)
from analysis.listing_type import ListingTypeClassifier, ListingType
from analysis.tokenomics import get_tokenomics
from analysis.reference_price import ReferencePriceFetcher
from store.cache import CoinGeckoCache

logger = logging.getLogger(__name__)


@dataclass
class HistoricalListing:
    """히스토리 상장 데이터."""
    symbol: str
    exchange: str
    date: str
    listing_type: str

    # 공급 요인
    deposit_krw: Optional[float] = None
    volume_5m_krw: Optional[float] = None
    turnover_ratio: Optional[float] = None
    supply_label: str = ""
    hot_wallet_usd: Optional[float] = None
    dex_liquidity_usd: Optional[float] = None
    withdrawal_open: Optional[bool] = None
    airdrop_claim_rate: Optional[float] = None

    # 헤징 요인
    hedge_type: str = "cex"

    # 시장 요인
    market_condition: str = "neutral"

    # 실제 결과
    max_premium_pct: Optional[float] = None
    premium_at_5m_pct: Optional[float] = None
    result_label: str = ""  # 대흥따리/흥따리/보통/망따리
    result_notes: str = ""


@dataclass
class BacktestResult:
    """백테스트 결과."""
    symbol: str
    exchange: str

    # 예측
    predicted_outcome: ScenarioOutcome
    heung_probability: float

    # 실제
    actual_label: str  # 대흥따리/흥따리/보통/망따리
    actual_max_premium: Optional[float]

    # 평가
    correct: bool
    confidence: float

    # 메타데이터
    scenario_card: Optional[ScenarioCard] = None
    error_reason: str = ""


@dataclass
class BacktestSummary:
    """백테스트 전체 요약."""
    total_count: int
    correct_count: int
    accuracy: float

    # 결과별 정확도
    heung_big_accuracy: float = 0.0
    heung_accuracy: float = 0.0
    neutral_accuracy: float = 0.0
    mang_accuracy: float = 0.0

    # 세부 결과
    results: list[BacktestResult] = field(default_factory=list)

    # 에러
    errors: list[str] = field(default_factory=list)


class BacktestEngine:
    """백테스팅 엔진.

    listing_data.csv를 로드하여 각 상장에 대해:
    1. 시나리오 예측 생성
    2. 실제 결과와 비교
    3. 정확도 계산

    사용법:
        engine = BacktestEngine()
        summary = await engine.run_backtest()
        engine.print_report(summary)
    """

    def __init__(
        self,
        data_path: str | Path | None = None,
    ) -> None:
        """
        Args:
            data_path: listing_data.csv 경로. None이면 기본 경로 사용.
        """
        if data_path is None:
            data_path = Path(__file__).parent.parent / "data" / "labeling" / "listing_data.csv"
        self._data_path = Path(data_path)

        # 컴포넌트 초기화
        self._planner = ScenarioPlanner(use_upbit_base=True)
        self._classifier = SupplyClassifier()
        self._cache = CoinGeckoCache()

    async def run_backtest(self) -> BacktestSummary:
        """백테스트 실행.

        Returns:
            BacktestSummary.
        """
        # 데이터 로드
        listings = self._load_listings()
        logger.info("[Backtest] 로드된 데이터: %d건", len(listings))

        results: list[BacktestResult] = []
        errors: list[str] = []

        # 각 상장에 대해 백테스트
        for listing in listings:
            try:
                result = await self._backtest_one(listing)
                results.append(result)

                if result.correct:
                    logger.debug(
                        "[Backtest] ✓ %s: 예측=%s, 실제=%s",
                        listing.symbol, result.predicted_outcome.value, result.actual_label,
                    )
                else:
                    logger.debug(
                        "[Backtest] ✗ %s: 예측=%s, 실제=%s",
                        listing.symbol, result.predicted_outcome.value, result.actual_label,
                    )

            except Exception as e:
                error_msg = f"{listing.symbol}: {e}"
                errors.append(error_msg)
                logger.warning("[Backtest] 에러 (%s): %s", listing.symbol, e)

        # 정확도 계산
        correct_count = sum(1 for r in results if r.correct)
        total_count = len(results)
        accuracy = correct_count / total_count if total_count > 0 else 0.0

        # 결과별 정확도
        heung_big_acc = self._calculate_accuracy_by_label(results, "대흥따리")
        heung_acc = self._calculate_accuracy_by_label(results, "흥따리")
        neutral_acc = self._calculate_accuracy_by_label(results, "보통")
        mang_acc = self._calculate_accuracy_by_label(results, "망따리")

        summary = BacktestSummary(
            total_count=total_count,
            correct_count=correct_count,
            accuracy=accuracy,
            heung_big_accuracy=heung_big_acc,
            heung_accuracy=heung_acc,
            neutral_accuracy=neutral_acc,
            mang_accuracy=mang_acc,
            results=results,
            errors=errors,
        )

        logger.info(
            "[Backtest] 완료: %d/%d 정확 (%.1f%%)",
            correct_count, total_count, accuracy * 100,
        )

        return summary

    async def _backtest_one(self, listing: HistoricalListing) -> BacktestResult:
        """개별 상장 백테스트.

        Args:
            listing: 히스토리 데이터.

        Returns:
            BacktestResult.
        """
        # Supply 입력 구성
        supply_input = SupplyInput(
            symbol=listing.symbol,
            exchange=listing.exchange,
            hot_wallet_usd=listing.hot_wallet_usd,
            dex_liquidity_usd=listing.dex_liquidity_usd,
            withdrawal_open=listing.withdrawal_open,
            airdrop_claim_rate=listing.airdrop_claim_rate,
            deposit_krw=listing.deposit_krw,
            volume_5m_krw=listing.volume_5m_krw,
            turnover_ratio=listing.turnover_ratio,  # v10: 백테스트 정확도 개선
            market_condition=listing.market_condition,
        )

        # Supply 분류
        supply_result = await self._classifier.classify(supply_input)

        # 시나리오 생성 (LIKELY만)
        card = self._planner.generate_card(
            symbol=listing.symbol,
            exchange=listing.exchange,
            supply_result=supply_result,
            hedge_type=listing.hedge_type,
            market_condition=listing.market_condition,
            scenario_type="likely",
        )

        # 실제 결과 매핑
        actual_label = listing.result_label.strip()

        # 예측 vs 실제 비교
        correct = self._is_prediction_correct(card.predicted_outcome, actual_label)

        return BacktestResult(
            symbol=listing.symbol,
            exchange=listing.exchange,
            predicted_outcome=card.predicted_outcome,
            heung_probability=card.heung_probability,
            actual_label=actual_label,
            actual_max_premium=listing.max_premium_pct,
            correct=correct,
            confidence=card.confidence,
            scenario_card=card,
        )

    def _is_prediction_correct(
        self,
        predicted: ScenarioOutcome,
        actual_label: str,
    ) -> bool:
        """예측이 정확한지 판정.

        매핑:
          - 대흥따리 → HEUNG_BIG
          - 흥따리 → HEUNG
          - 보통 → NEUTRAL
          - 망따리 → MANG

        Args:
            predicted: 예측된 ScenarioOutcome.
            actual_label: 실제 라벨 (한글).

        Returns:
            정확 여부.
        """
        label_map = {
            "대흥따리": ScenarioOutcome.HEUNG_BIG,
            "흥따리": ScenarioOutcome.HEUNG,
            "보통": ScenarioOutcome.NEUTRAL,
            "망따리": ScenarioOutcome.MANG,
        }

        expected = label_map.get(actual_label)
        if expected is None:
            logger.warning("[Backtest] 알 수 없는 라벨: %s", actual_label)
            return False

        # HEUNG_BIG과 HEUNG은 모두 "흥따리" 범주로 통합 판정
        if predicted in (ScenarioOutcome.HEUNG_BIG, ScenarioOutcome.HEUNG):
            return expected in (ScenarioOutcome.HEUNG_BIG, ScenarioOutcome.HEUNG)

        return predicted == expected

    def _calculate_accuracy_by_label(
        self,
        results: list[BacktestResult],
        label: str,
    ) -> float:
        """특정 라벨에 대한 정확도.

        Args:
            results: 백테스트 결과 리스트.
            label: 실제 라벨 (대흥따리/흥따리/보통/망따리).

        Returns:
            정확도 (0.0 ~ 1.0).
        """
        filtered = [r for r in results if r.actual_label == label]
        if not filtered:
            return 0.0

        correct = sum(1 for r in filtered if r.correct)
        return correct / len(filtered)

    def _load_listings(self) -> list[HistoricalListing]:
        """listing_data.csv 로드.

        Returns:
            HistoricalListing 리스트.
        """
        listings: list[HistoricalListing] = []

        with open(self._data_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                listing = HistoricalListing(
                    symbol=row["symbol"],
                    exchange=row["exchange"],
                    date=row["date"],
                    listing_type=row["listing_type"],
                    deposit_krw=self._parse_float(row.get("deposit_krw")),
                    volume_5m_krw=self._parse_float(row.get("volume_5m_krw")),
                    turnover_ratio=self._parse_float(row.get("turnover_ratio")),
                    supply_label=row.get("supply_label", ""),
                    hot_wallet_usd=self._parse_float(row.get("hot_wallet_usd")),
                    dex_liquidity_usd=self._parse_float(row.get("dex_liquidity_usd")),
                    withdrawal_open=self._parse_bool(row.get("withdrawal_open")),
                    airdrop_claim_rate=self._parse_float(row.get("airdrop_claim_rate")),
                    hedge_type=row.get("hedge_type", "cex"),
                    market_condition=row.get("market_condition", "neutral"),
                    max_premium_pct=self._parse_float(row.get("max_premium_pct")),
                    premium_at_5m_pct=self._parse_float(row.get("premium_at_5m_pct")),
                    result_label=row.get("result_label", ""),
                    result_notes=row.get("result_notes", ""),
                )
                listings.append(listing)

        return listings

    @staticmethod
    def _parse_float(value: str | None) -> Optional[float]:
        """문자열 → float 변환 (빈 값 처리)."""
        if not value or value.strip() == "":
            return None
        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _parse_bool(value: str | None) -> Optional[bool]:
        """문자열 → bool 변환."""
        if not value or value.strip() == "":
            return None
        return value.strip().lower() in ("true", "1", "yes", "t")

    def print_report(self, summary: BacktestSummary) -> None:
        """백테스트 리포트 출력.

        Args:
            summary: BacktestSummary.
        """
        print("=" * 70)
        print(" 백테스트 리포트")
        print("=" * 70)
        print()
        print(f"총 테스트: {summary.total_count}건")
        print(f"정확: {summary.correct_count}건")
        print(f"부정확: {summary.total_count - summary.correct_count}건")
        print(f"**전체 정확도: {summary.accuracy:.1%}**")
        print()

        print("결과별 정확도:")
        print(f"  - 대흥따리: {summary.heung_big_accuracy:.1%}")
        print(f"  - 흥따리: {summary.heung_accuracy:.1%}")
        print(f"  - 보통: {summary.neutral_accuracy:.1%}")
        print(f"  - 망따리: {summary.mang_accuracy:.1%}")
        print()

        # 에러 summary
        if summary.errors:
            print(f"⚠ 에러: {len(summary.errors)}건")
            for err in summary.errors[:5]:
                print(f"  - {err}")
            if len(summary.errors) > 5:
                print(f"  ... 외 {len(summary.errors) - 5}건")
            print()

        # 오예측 샘플
        incorrect = [r for r in summary.results if not r.correct]
        if incorrect:
            print(f"❌ 오예측 샘플 (총 {len(incorrect)}건):")
            for r in incorrect[:10]:
                print(f"  {r.symbol}: 예측={r.predicted_outcome.value}, 실제={r.actual_label}")
            if len(incorrect) > 10:
                print(f"  ... 외 {len(incorrect) - 10}건")

        print()
        print("=" * 70)
