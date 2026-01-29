"""공급 분류기 (Phase 5a).

5-factor 공급 분류:
  1. hot_wallet (0.30) - 핫월렛 잔액
  2. dex_liquidity (0.25) - DEX 유동성
  3. withdrawal (0.20) - 출금 상태
  4. airdrop (0.15) - 에어드랍 클레임률
  5. network (0.10) - 네트워크 속도

스코어: -1.0 (constrained) ~ +1.0 (smooth)
  - constrained: 공급 제약 → 흥따리 가능성 높음
  - smooth: 공급 원활 → 망따리 가능성 높음

v8: airdrop 데이터 없을 시 가중치 재분배
v9: None/저신뢰도 처리 (unknown → 경고만)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# 기본 가중치 (Phase 0에서 재조정)
_DEFAULT_WEIGHTS = {
    "hot_wallet": 0.30,
    "dex_liquidity": 0.25,
    "withdrawal": 0.20,
    "airdrop": 0.15,
    "network": 0.10,
}

# airdrop 없을 때 fallback 가중치 (v8)
_FALLBACK_NO_AIRDROP = {
    "hot_wallet": 0.35,
    "dex_liquidity": 0.30,
    "withdrawal": 0.23,
    "network": 0.12,
}

# Turnover Ratio 임계값 (Phase 0 도출)
_TURNOVER_THRESHOLDS = {
    "extreme_high": 10.0,  # P90+: 극단적 흥따리
    "high": 5.0,           # P75: 흥따리 유력
    "normal": 2.1,         # P50: 보통
    "low": 1.0,            # P25: 낮음
}


class SupplyClassification(Enum):
    """공급 분류."""
    CONSTRAINED = "constrained"  # 공급 제약 (흥따리 유리)
    NEUTRAL = "neutral"          # 중립
    SMOOTH = "smooth"            # 공급 원활 (망따리 위험)
    UNKNOWN = "unknown"          # 분류 실패


@dataclass
class SupplyFactor:
    """개별 공급 팩터."""
    name: str
    raw_value: Optional[float]     # 원본 값
    score: float                   # 정규화 스코어 (-1 ~ +1)
    weight: float                  # 가중치
    confidence: float              # 신뢰도 (0.0 ~ 1.0)
    reason: str = ""               # 스코어 산정 사유


@dataclass
class SupplyResult:
    """공급 분류 결과."""
    classification: SupplyClassification
    total_score: float              # 가중 합계 스코어 (-1 ~ +1)
    confidence: float               # 전체 신뢰도
    factors: list[SupplyFactor] = field(default_factory=list)
    turnover_ratio: Optional[float] = None  # 손바뀜 비율
    warnings: list[str] = field(default_factory=list)


@dataclass
class SupplyInput:
    """공급 분류 입력 데이터.

    Phase 5b 데이터 수집기에서 채워짐.
    Phase 5a에서는 부분 데이터로 분류 가능 (열화 규칙).
    """
    symbol: str
    exchange: str

    # Factor 1: 핫월렛 (Phase 5b: hot_wallet_tracker)
    hot_wallet_usd: Optional[float] = None
    hot_wallet_confidence: float = 0.5

    # Factor 2: DEX 유동성 (Phase 5b: dex_monitor)
    dex_liquidity_usd: Optional[float] = None
    dex_confidence: float = 0.5

    # Factor 3: 출금 상태 (Phase 5b: withdrawal_tracker)
    withdrawal_open: Optional[bool] = None
    withdrawal_confidence: float = 1.0

    # Factor 4: 에어드랍 (Phase 5b: 수동입력 / Phase 6: 자동화)
    airdrop_claim_rate: Optional[float] = None  # 0.0 ~ 1.0
    airdrop_confidence: float = 0.5

    # Factor 5: 네트워크 (config/networks.yaml)
    network_speed_min: Optional[float] = None
    network_confidence: float = 0.8

    # Turnover Ratio (volume / deposit)
    deposit_krw: Optional[float] = None
    volume_5m_krw: Optional[float] = None

    # 시장 상황 (Phase 6)
    market_condition: str = "neutral"  # bull/bear/neutral


class SupplyClassifier:
    """5-factor 공급 분류기.

    열화 규칙 (v9):
      - 모든 팩터 None → classification="unknown", 경고만
      - 일부 팩터 None → 해당 팩터 제외, 가중치 재분배
      - confidence < 0.3 → 해당 팩터 가중치 50% 감소

    사용법:
        classifier = SupplyClassifier()
        result = await classifier.classify(input_data)
    """

    def __init__(
        self,
        config_dir: str | Path | None = None,
    ) -> None:
        """
        Args:
            config_dir: 설정 디렉토리 (thresholds.yaml 위치).
        """
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self._config_dir = Path(config_dir)

        # 설정 로드
        self._thresholds = self._load_thresholds()
        self._weights = self._get_weights()

    async def classify(self, data: SupplyInput) -> SupplyResult:
        """공급 분류 실행.

        Args:
            data: 공급 분류 입력 데이터.

        Returns:
            SupplyResult.
        """
        try:
            return await self._classify_internal(data)
        except Exception as e:
            logger.warning(
                "[Supply] 분류 실패 (%s@%s): %s",
                data.symbol, data.exchange, e,
            )
            return SupplyResult(
                classification=SupplyClassification.UNKNOWN,
                total_score=0.0,
                confidence=0.0,
                warnings=[f"분류 실패: {e}"],
            )

    async def _classify_internal(self, data: SupplyInput) -> SupplyResult:
        """내부 분류 로직."""
        factors: list[SupplyFactor] = []
        warnings: list[str] = []

        # 사용 가능한 팩터 수집
        weights = dict(self._weights)

        # airdrop 없으면 가중치 재분배 (v8)
        if data.airdrop_claim_rate is None:
            weights = dict(_FALLBACK_NO_AIRDROP)
            warnings.append("airdrop 데이터 없음 — 가중치 재분배")

        # Factor 1: 핫월렛
        hot_wallet_factor = self._score_hot_wallet(data, weights)
        if hot_wallet_factor:
            factors.append(hot_wallet_factor)

        # Factor 2: DEX 유동성
        dex_factor = self._score_dex_liquidity(data, weights)
        if dex_factor:
            factors.append(dex_factor)

        # Factor 3: 출금 상태
        withdrawal_factor = self._score_withdrawal(data, weights)
        if withdrawal_factor:
            factors.append(withdrawal_factor)

        # Factor 4: 에어드랍
        if data.airdrop_claim_rate is not None:
            airdrop_factor = self._score_airdrop(data, weights)
            if airdrop_factor:
                factors.append(airdrop_factor)

        # Factor 5: 네트워크
        network_factor = self._score_network(data, weights)
        if network_factor:
            factors.append(network_factor)

        # 모든 팩터 None → UNKNOWN (v9)
        if not factors:
            logger.warning(
                "[Supply] %s@%s → UNKNOWN (모든 팩터 없음)",
                data.symbol, data.exchange,
            )
            return SupplyResult(
                classification=SupplyClassification.UNKNOWN,
                total_score=0.0,
                confidence=0.0,
                warnings=["모든 공급 팩터 데이터 없음"],
            )

        # 가중 합계 계산
        # confidence < 0.3인 팩터는 가중치 50% 감소 (v9)
        total_score = 0.0
        total_weight = 0.0

        for f in factors:
            effective_weight = f.weight
            if f.confidence < 0.3:
                effective_weight *= 0.5
                warnings.append(f"{f.name} 저신뢰도 ({f.confidence:.1f}) — 가중치 50% 감소")

            total_score += f.score * effective_weight
            total_weight += effective_weight

        # 정규화
        if total_weight > 0:
            total_score /= total_weight

        # 전체 신뢰도 = 팩터 신뢰도의 가중 평균
        avg_confidence = sum(f.confidence * f.weight for f in factors) / sum(f.weight for f in factors)

        # Turnover Ratio 계산
        turnover = self._calculate_turnover(data)
        if turnover:
            # Turnover Ratio로 스코어 보정
            turnover_adj = self._turnover_adjustment(turnover)
            total_score = (total_score + turnover_adj) / 2
            logger.debug(
                "[Supply] Turnover %.2f → 보정 %.2f",
                turnover, turnover_adj,
            )

        # 분류 결정
        classification = self._determine_classification(total_score)

        logger.info(
            "[Supply] %s@%s → %s (score=%.2f, confidence=%.2f, factors=%d)",
            data.symbol, data.exchange,
            classification.value, total_score, avg_confidence, len(factors),
        )

        return SupplyResult(
            classification=classification,
            total_score=total_score,
            confidence=avg_confidence,
            factors=factors,
            turnover_ratio=turnover,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 개별 팩터 스코어링
    # ------------------------------------------------------------------

    def _score_hot_wallet(
        self, data: SupplyInput, weights: dict,
    ) -> Optional[SupplyFactor]:
        """핫월렛 잔액 스코어.

        높은 핫월렛 잔액 → 공급 원활 (smooth, +)
        낮은 핫월렛 잔액 → 공급 제약 (constrained, -)
        """
        if data.hot_wallet_usd is None:
            return None

        # 임계값: $1M 이상 = smooth, $100K 이하 = constrained
        hw = data.hot_wallet_usd
        if hw >= 1_000_000:
            score = +0.8
            reason = f"핫월렛 ${hw:,.0f} (충분)"
        elif hw >= 500_000:
            score = +0.4
            reason = f"핫월렛 ${hw:,.0f} (양호)"
        elif hw >= 100_000:
            score = 0.0
            reason = f"핫월렛 ${hw:,.0f} (보통)"
        elif hw >= 50_000:
            score = -0.4
            reason = f"핫월렛 ${hw:,.0f} (부족)"
        else:
            score = -0.8
            reason = f"핫월렛 ${hw:,.0f} (매우 부족)"

        return SupplyFactor(
            name="hot_wallet",
            raw_value=hw,
            score=score,
            weight=weights.get("hot_wallet", 0.30),
            confidence=data.hot_wallet_confidence,
            reason=reason,
        )

    def _score_dex_liquidity(
        self, data: SupplyInput, weights: dict,
    ) -> Optional[SupplyFactor]:
        """DEX 유동성 스코어.

        높은 DEX 유동성 → 공급 원활 (smooth, +)
        낮은 DEX 유동성 → 공급 제약 (constrained, -)
        """
        if data.dex_liquidity_usd is None:
            return None

        dex = data.dex_liquidity_usd
        if dex >= 500_000:
            score = +0.8
            reason = f"DEX ${dex:,.0f} (풍부)"
        elif dex >= 200_000:
            score = +0.4
            reason = f"DEX ${dex:,.0f} (양호)"
        elif dex >= 50_000:
            score = 0.0
            reason = f"DEX ${dex:,.0f} (보통)"
        elif dex >= 10_000:
            score = -0.4
            reason = f"DEX ${dex:,.0f} (부족)"
        else:
            score = -0.8
            reason = f"DEX ${dex:,.0f} (매우 부족)"

        return SupplyFactor(
            name="dex_liquidity",
            raw_value=dex,
            score=score,
            weight=weights.get("dex_liquidity", 0.25),
            confidence=data.dex_confidence,
            reason=reason,
        )

    def _score_withdrawal(
        self, data: SupplyInput, weights: dict,
    ) -> Optional[SupplyFactor]:
        """출금 상태 스코어.

        출금 가능 → 공급 원활 (smooth, +)
        출금 불가 → 공급 제약 (constrained, -)
        """
        if data.withdrawal_open is None:
            return None

        if data.withdrawal_open:
            score = +0.6
            reason = "출금 가능"
        else:
            score = -1.0
            reason = "출금 불가 (공급 차단)"

        return SupplyFactor(
            name="withdrawal",
            raw_value=1.0 if data.withdrawal_open else 0.0,
            score=score,
            weight=weights.get("withdrawal", 0.20),
            confidence=data.withdrawal_confidence,
            reason=reason,
        )

    def _score_airdrop(
        self, data: SupplyInput, weights: dict,
    ) -> Optional[SupplyFactor]:
        """에어드랍 클레임률 스코어.

        높은 클레임률 → 공급 원활 (smooth, +)
        낮은 클레임률 → 공급 제약 (constrained, -)
        """
        if data.airdrop_claim_rate is None:
            return None

        rate = data.airdrop_claim_rate
        if rate >= 0.8:
            score = +0.8
            reason = f"클레임률 {rate:.0%} (대부분 클레임)"
        elif rate >= 0.5:
            score = +0.3
            reason = f"클레임률 {rate:.0%} (절반 이상)"
        elif rate >= 0.2:
            score = -0.3
            reason = f"클레임률 {rate:.0%} (낮음)"
        else:
            score = -0.8
            reason = f"클레임률 {rate:.0%} (매우 낮음)"

        return SupplyFactor(
            name="airdrop",
            raw_value=rate,
            score=score,
            weight=weights.get("airdrop", 0.15),
            confidence=data.airdrop_confidence,
            reason=reason,
        )

    def _score_network(
        self, data: SupplyInput, weights: dict,
    ) -> Optional[SupplyFactor]:
        """네트워크 속도 스코어.

        빠른 네트워크 → 공급 원활 (smooth, +)
        느린 네트워크 → 공급 제약 (constrained, -)
        """
        if data.network_speed_min is None:
            return None

        speed = data.network_speed_min
        if speed <= 2:
            score = +0.6
            reason = f"전송 {speed:.0f}분 (매우 빠름)"
        elif speed <= 5:
            score = +0.3
            reason = f"전송 {speed:.0f}분 (빠름)"
        elif speed <= 15:
            score = 0.0
            reason = f"전송 {speed:.0f}분 (보통)"
        elif speed <= 30:
            score = -0.4
            reason = f"전송 {speed:.0f}분 (느림)"
        else:
            score = -0.8
            reason = f"전송 {speed:.0f}분 (매우 느림)"

        return SupplyFactor(
            name="network",
            raw_value=speed,
            score=score,
            weight=weights.get("network", 0.10),
            confidence=data.network_confidence,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Turnover Ratio
    # ------------------------------------------------------------------

    def _calculate_turnover(self, data: SupplyInput) -> Optional[float]:
        """Turnover Ratio 계산.

        turnover = volume_5m / deposit
        높을수록 흥따리 (거래량 대비 입금 적음)
        """
        if data.deposit_krw is None or data.volume_5m_krw is None:
            return None
        if data.deposit_krw <= 0:
            return None

        return data.volume_5m_krw / data.deposit_krw

    def _turnover_adjustment(self, turnover: float) -> float:
        """Turnover Ratio → 스코어 보정값.

        높은 Turnover → constrained (-)
        낮은 Turnover → smooth (+)
        """
        thresholds = self._thresholds.get("turnover_ratio", _TURNOVER_THRESHOLDS)

        if turnover >= thresholds.get("extreme_high", 10.0):
            return -1.0  # 극단적 흥따리
        if turnover >= thresholds.get("high", 5.0):
            return -0.6
        if turnover >= thresholds.get("normal", 2.1):
            return -0.2
        if turnover >= thresholds.get("low", 1.0):
            return +0.2
        return +0.6  # 매우 낮은 Turnover

    # ------------------------------------------------------------------
    # 분류 결정
    # ------------------------------------------------------------------

    def _determine_classification(
        self, score: float,
    ) -> SupplyClassification:
        """스코어 → 분류 결정.

        score < -0.3: CONSTRAINED (공급 제약)
        score > +0.3: SMOOTH (공급 원활)
        otherwise: NEUTRAL
        """
        if score < -0.3:
            return SupplyClassification.CONSTRAINED
        if score > +0.3:
            return SupplyClassification.SMOOTH
        return SupplyClassification.NEUTRAL

    # ------------------------------------------------------------------
    # 설정 로드
    # ------------------------------------------------------------------

    def _load_thresholds(self) -> dict:
        """thresholds.yaml 로드."""
        path = self._config_dir / "thresholds.yaml"
        if not path.exists():
            logger.debug("thresholds.yaml 미발견 — 기본값 사용")
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("thresholds.yaml 파싱 실패: %s — 기본값 사용", e)
            return {}

    def _get_weights(self) -> dict:
        """가중치 설정."""
        config_weights = self._thresholds.get(
            "supply_classifier_weights", {},
        )
        weights = dict(_DEFAULT_WEIGHTS)
        weights.update(config_weights)
        return weights
