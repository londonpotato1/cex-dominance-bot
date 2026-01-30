"""토크노믹스 조회 (Phase 3) + TGE 언락 분석 (Phase 7 Quick Win #1).

CoinGecko API 경유 MC/FDV/유통량/가격 조회.
store/cache.py TTL 캐시를 사용하여 API rate limit 관리.

Phase 7 추가:
  - TGE (Token Generation Event) 당일 언락 비율 분석
  - Cliff/베스팅 스케줄 분석
  - 에어드랍/VC 덤핑 리스크 평가

핵심 인사이트:
  "TGE 당일 언락 10%가 3년 락업 70%보다 위험"
  → 언락 시점이 덤핑 리스크의 핵심
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

from store.cache import CoinGeckoCache

logger = logging.getLogger(__name__)


class TGERiskLevel(Enum):
    """TGE 언락 리스크 레벨."""
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"
    UNKNOWN = "unknown"


@dataclass
class TGEUnlockData:
    """TGE 언락 스케줄 데이터."""
    symbol: str
    tge_unlock_pct: float  # TGE 당일 언락 비율
    cliff_months: int  # Cliff 기간 (개월)
    vesting_months: int  # 베스팅 기간 (개월)
    categories: dict[str, float] = field(default_factory=dict)  # 카테고리별 비율
    unlock_schedule: list[dict] = field(default_factory=list)  # 월별 언락 스케줄
    risk_assessment: TGERiskLevel = TGERiskLevel.UNKNOWN
    reason: str = ""
    risk_score: float = 0.0  # 통합 리스크 스코어


@dataclass
class TokenomicsData:
    """토크노믹스 데이터."""
    symbol: str
    market_cap_usd: Optional[float] = None
    fdv_usd: Optional[float] = None
    circulating_supply: Optional[float] = None
    total_supply: Optional[float] = None
    price_usd: Optional[float] = None

    # Phase 7: TGE 언락 분석
    tge_unlock: Optional[TGEUnlockData] = None
    mc_fdv_ratio: Optional[float] = None  # MC/FDV (기존 공급 지표)
    locked_supply_pct: Optional[float] = None  # 잠금 공급 비율


async def get_tokenomics(
    symbol: str,
    cache: CoinGeckoCache,
    coingecko_id: str | None = None,
    include_tge_analysis: bool = True,
) -> TokenomicsData | None:
    """토크노믹스 데이터 조회.

    Args:
        symbol: 토큰 심볼 (e.g., "BTC").
        cache: CoinGeckoCache 인스턴스.
        coingecko_id: CoinGecko 코인 ID. None이면 심볼로 검색.
        include_tge_analysis: TGE 언락 분석 포함 여부.

    Returns:
        TokenomicsData 또는 조회 실패 시 None.
    """
    if not coingecko_id:
        # 심볼로 검색하여 coingecko_id 확보
        coingecko_id = await _resolve_coingecko_id(symbol, cache)
        if not coingecko_id:
            logger.debug("CoinGecko ID 조회 실패: %s", symbol)
            return None

    data = await cache.get_coin_data(coingecko_id)
    if not data:
        return None

    market_data = data.get("market_data", {})
    if not market_data:
        return TokenomicsData(symbol=symbol)

    # 기본 토크노믹스 데이터
    mc = market_data.get("market_cap", {}).get("usd")
    fdv = market_data.get("fully_diluted_valuation", {}).get("usd")
    circ_supply = market_data.get("circulating_supply")
    total_supply = market_data.get("total_supply")

    # MC/FDV 비율 계산
    mc_fdv_ratio = None
    locked_pct = None
    if mc and fdv and fdv > 0:
        mc_fdv_ratio = mc / fdv
        locked_pct = (1 - mc_fdv_ratio) * 100  # 잠금 공급 비율

    # TGE 언락 분석
    tge_unlock = None
    if include_tge_analysis:
        tge_unlock = await get_tge_unlock_data(symbol)

    return TokenomicsData(
        symbol=symbol,
        market_cap_usd=mc,
        fdv_usd=fdv,
        circulating_supply=circ_supply,
        total_supply=total_supply,
        price_usd=market_data.get("current_price", {}).get("usd"),
        tge_unlock=tge_unlock,
        mc_fdv_ratio=mc_fdv_ratio,
        locked_supply_pct=locked_pct,
    )


async def _resolve_coingecko_id(
    symbol: str, cache: CoinGeckoCache
) -> str | None:
    """심볼에서 CoinGecko ID 추출.

    /coins/markets 엔드포인트로 상위 코인 목록에서 매칭 시도.
    """
    coins = await cache.get_coin_market_data(ids=None, per_page=250, page=1)
    if not coins:
        return None

    symbol_upper = symbol.upper()
    for coin in coins:
        if coin.get("symbol", "").upper() == symbol_upper:
            return coin.get("id")

    return None


# ==================================================================================
# Phase 7: TGE 언락 분석
# ==================================================================================


async def get_tge_unlock_data(symbol: str) -> TGEUnlockData | None:
    """TGE 언락 데이터 조회 및 리스크 평가.

    Args:
        symbol: 토큰 심볼 (e.g., "SENT").

    Returns:
        TGEUnlockData 또는 데이터 없을 시 None.
    """
    unlock_db = _load_unlock_schedules()
    if not unlock_db:
        return None

    tokens = unlock_db.get("tokens", {})
    token_data = tokens.get(symbol.upper())
    if not token_data:
        logger.debug("TGE 언락 데이터 없음: %s", symbol)
        return None

    # 데이터 파싱
    tge_unlock_pct = token_data.get("tge_unlock_pct", 0.0)
    cliff_months = token_data.get("cliff_months", 0)
    vesting_months = token_data.get("vesting_months", 0)
    categories = token_data.get("categories", {})
    unlock_schedule = token_data.get("unlock_schedule", [])
    risk_assessment_str = token_data.get("risk_assessment", "UNKNOWN")
    reason = token_data.get("reason", "")

    # 리스크 레벨 변환
    try:
        risk_assessment = TGERiskLevel(risk_assessment_str.lower())
    except ValueError:
        risk_assessment = TGERiskLevel.UNKNOWN

    # 리스크 스코어 계산
    risk_score = calculate_tge_risk_score(
        tge_unlock_pct=tge_unlock_pct,
        cliff_months=cliff_months,
        vesting_months=vesting_months,
        categories=categories,
        config=unlock_db.get("category_risk", {}),
    )

    logger.info(
        "[TGE] %s → %s (TGE: %.1f%%, cliff: %dm, risk_score: %.2f)",
        symbol, risk_assessment.value, tge_unlock_pct, cliff_months, risk_score,
    )

    return TGEUnlockData(
        symbol=symbol.upper(),
        tge_unlock_pct=tge_unlock_pct,
        cliff_months=cliff_months,
        vesting_months=vesting_months,
        categories=categories,
        unlock_schedule=unlock_schedule,
        risk_assessment=risk_assessment,
        reason=reason,
        risk_score=risk_score,
    )


def calculate_tge_risk_score(
    tge_unlock_pct: float,
    cliff_months: int,
    vesting_months: int,
    categories: dict[str, float],
    config: dict[str, float],
) -> float:
    """TGE 통합 리스크 스코어 계산.

    공식:
        risk_score = (tge_unlock_pct * avg_category_risk) / (cliff_months + 1)

    높을수록 위험:
      - TGE 언락 비율 높음
      - 카테고리 리스크 높음 (VC/에어드랍)
      - Cliff 짧음

    Args:
        tge_unlock_pct: TGE 당일 언락 비율 (%).
        cliff_months: Cliff 기간 (개월).
        vesting_months: 베스팅 기간 (개월).
        categories: 카테고리별 비율 dict (team/vc/public/ecosystem/airdrop).
        config: 카테고리별 덤핑 리스크 가중치.

    Returns:
        리스크 스코어 (0.0 ~ 10.0+).
          - 0-2: 매우 낮음 (안전)
          - 2-5: 낮음
          - 5-8: 보통
          - 8-12: 높음
          - 12+: 매우 높음 (위험)
    """
    # 카테고리별 가중 리스크
    if not categories:
        avg_risk = 0.5  # 기본값
    else:
        total_weight = 0.0
        weighted_risk = 0.0

        for cat, pct in categories.items():
            cat_risk = config.get(cat, 0.5)  # 기본 0.5
            weighted_risk += pct * cat_risk
            total_weight += pct

        avg_risk = weighted_risk / total_weight if total_weight > 0 else 0.5

    # 리스크 스코어 계산
    cliff_factor = cliff_months + 1  # +1로 divide-by-zero 방지
    risk_score = (tge_unlock_pct * avg_risk) / cliff_factor

    # 베스팅이 짧으면 추가 페널티
    if vesting_months > 0 and vesting_months < 24:
        risk_score *= 1.2  # 2년 미만 → 20% 증가

    return round(risk_score, 2)


def _load_unlock_schedules() -> dict:
    """unlock_schedules.yaml 로드."""
    # 파일 위치: data/tokenomics/unlock_schedules.yaml
    data_dir = Path(__file__).parent.parent / "data" / "tokenomics"
    yaml_path = data_dir / "unlock_schedules.yaml"

    if not yaml_path.exists():
        logger.warning("TGE 언락 데이터 파일 없음: %s", yaml_path)
        return {}

    try:
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("TGE 언락 데이터 파싱 실패: %s", e)
        return {}


def get_tge_risk_level_emoji(level: TGERiskLevel) -> str:
    """TGE 리스크 레벨 이모지 반환."""
    emoji_map = {
        TGERiskLevel.VERY_LOW: "🟢",
        TGERiskLevel.LOW: "🟡",
        TGERiskLevel.MEDIUM: "🟠",
        TGERiskLevel.HIGH: "🔴",
        TGERiskLevel.VERY_HIGH: "🚨",
        TGERiskLevel.UNKNOWN: "❓",
    }
    return emoji_map.get(level, "❓")


def format_tge_warning(tge: TGEUnlockData) -> str:
    """TGE 경고 메시지 포맷."""
    emoji = get_tge_risk_level_emoji(tge.risk_assessment)
    return (
        f"{emoji} TGE 리스크: {tge.risk_assessment.value.upper()}\n"
        f"  • TGE 당일 언락: {tge.tge_unlock_pct:.1f}%\n"
        f"  • Cliff: {tge.cliff_months}개월\n"
        f"  • 베스팅: {tge.vesting_months}개월\n"
        f"  • 리스크 스코어: {tge.risk_score:.2f}\n"
        f"  • 사유: {tge.reason}"
    )
