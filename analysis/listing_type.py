"""상장 유형 분류 (Phase 5a).

ListingType Enum:
  - TGE: Token Generation Event (세계 최초 상장)
  - DIRECT: 직상장 (해외 거래소 기존재 → 국내 신규)
  - SIDE: 옆상장 (국내 경쟁 거래소 뒤따라 상장)
  - UNKNOWN: 분류 실패 (v12: WATCH_ONLY 강제)

분류 기준:
  1. TGE: 해외 top_exchange 없음 + 최근 생성 토큰 (7일 이내)
  2. SIDE: 국내 경쟁 거래소에 기존 상장
  3. DIRECT: 해외 거래소에만 상장
  4. UNKNOWN: 판단 불가
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from store.token_registry import TokenRegistry

logger = logging.getLogger(__name__)

# 국내 거래소 목록
_DOMESTIC_EXCHANGES = {"upbit", "bithumb"}

# TGE 판정 임계값
_TGE_DAYS_THRESHOLD = 7  # 최초 상장 후 7일 이내면 TGE로 간주


class ListingType(Enum):
    """상장 유형."""
    TGE = "TGE"           # Token Generation Event
    DIRECT = "DIRECT"     # 직상장 (해외→국내)
    SIDE = "SIDE"         # 옆상장 (국내 경쟁)
    UNKNOWN = "UNKNOWN"   # 분류 실패


@dataclass
class ListingTypeResult:
    """상장 유형 분류 결과."""
    listing_type: ListingType
    confidence: float              # 신뢰도 (0.0~1.0)
    top_exchange: str              # 글로벌 주요 거래소
    first_listed_at: Optional[datetime] = None  # 최초 상장 시각
    domestic_competitor: Optional[str] = None   # 국내 경쟁 거래소 (SIDE일 때)
    reason: str = ""               # 분류 사유


class ListingTypeClassifier:
    """상장 유형 분류기.

    분류 우선순위:
      1. SIDE: 국내 경쟁 거래소에 기존 상장
      2. TGE: 글로벌 첫 상장 (7일 이내)
      3. DIRECT: 해외 거래소 기존재
      4. UNKNOWN: 분류 불가
    """

    def __init__(
        self,
        registry: Optional[TokenRegistry] = None,
    ) -> None:
        """
        Args:
            registry: 토큰 레지스트리 (국내 상장 이력 조회).
        """
        self._registry = registry

    async def classify(
        self,
        symbol: str,
        exchange: str,
        top_exchange: str = "",
        first_listed_at: Optional[datetime] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> ListingTypeResult:
        """상장 유형 분류.

        Args:
            symbol: 토큰 심볼 (e.g., "XYZ").
            exchange: 상장 거래소 (e.g., "upbit", "bithumb").
            top_exchange: 글로벌 주요 거래소 (VWAP 소스).
            first_listed_at: 토큰 최초 상장 시각.
            session: aiohttp 세션 (외부 API 호출용).

        Returns:
            ListingTypeResult.
        """
        try:
            return await self._classify_internal(
                symbol, exchange, top_exchange, first_listed_at, session,
            )
        except Exception as e:
            logger.warning(
                "[ListingType] 분류 실패 (%s@%s): %s",
                symbol, exchange, e,
            )
            return ListingTypeResult(
                listing_type=ListingType.UNKNOWN,
                confidence=0.0,
                top_exchange=top_exchange,
                reason=f"분류 실패: {e}",
            )

    async def _classify_internal(
        self,
        symbol: str,
        exchange: str,
        top_exchange: str,
        first_listed_at: Optional[datetime],
        session: Optional[aiohttp.ClientSession],
    ) -> ListingTypeResult:
        """내부 분류 로직."""

        # 1. 국내 경쟁 거래소 상장 체크 (SIDE)
        competitor = await self._check_domestic_competitor(symbol, exchange, session)
        if competitor:
            logger.info(
                "[ListingType] %s@%s → SIDE (경쟁: %s)",
                symbol, exchange, competitor,
            )
            return ListingTypeResult(
                listing_type=ListingType.SIDE,
                confidence=0.95,
                top_exchange=top_exchange,
                domestic_competitor=competitor,
                reason=f"국내 경쟁 거래소 {competitor}에 기존 상장",
            )

        # 2. TGE 체크: 글로벌 주요 거래소 없음 + 최근 생성
        if self._is_tge(top_exchange, first_listed_at):
            logger.info(
                "[ListingType] %s@%s → TGE (top=%s, first=%s)",
                symbol, exchange, top_exchange or "없음",
                first_listed_at,
            )
            return ListingTypeResult(
                listing_type=ListingType.TGE,
                confidence=0.85 if first_listed_at else 0.6,
                top_exchange=top_exchange,
                first_listed_at=first_listed_at,
                reason="글로벌 최초 상장 (TGE)",
            )

        # 3. DIRECT: 해외 거래소 존재
        if top_exchange and top_exchange.lower() not in _DOMESTIC_EXCHANGES:
            logger.info(
                "[ListingType] %s@%s → DIRECT (top=%s)",
                symbol, exchange, top_exchange,
            )
            return ListingTypeResult(
                listing_type=ListingType.DIRECT,
                confidence=0.9,
                top_exchange=top_exchange,
                first_listed_at=first_listed_at,
                reason=f"해외 거래소 {top_exchange}에 기존 상장",
            )

        # 4. UNKNOWN
        logger.warning(
            "[ListingType] %s@%s → UNKNOWN (분류 불가)",
            symbol, exchange,
        )
        return ListingTypeResult(
            listing_type=ListingType.UNKNOWN,
            confidence=0.0,
            top_exchange=top_exchange,
            reason="분류 불가",
        )

    def _is_tge(
        self,
        top_exchange: str,
        first_listed_at: Optional[datetime],
    ) -> bool:
        """TGE 여부 판정.

        조건:
          - 글로벌 top_exchange가 없거나 국내 거래소임
          - first_listed_at이 7일 이내이거나 정보 없음
        """
        # top_exchange가 없거나 국내 거래소면 TGE 가능성
        if not top_exchange or top_exchange.lower() in _DOMESTIC_EXCHANGES:
            if first_listed_at is None:
                # 정보 없음 → TGE로 가정 (낮은 신뢰도)
                return True
            # 7일 이내면 TGE (UTC 기준 비교)
            return datetime.now(timezone.utc) - first_listed_at < timedelta(days=_TGE_DAYS_THRESHOLD)
        return False

    async def _check_domestic_competitor(
        self,
        symbol: str,
        exchange: str,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> Optional[str]:
        """국내 경쟁 거래소 상장 여부 체크.

        Args:
            symbol: 토큰 심볼.
            exchange: 현재 상장 거래소.
            session: aiohttp 세션 (재사용).

        Returns:
            경쟁 거래소명 또는 None.
        """
        if self._registry is None:
            return None

        # 국내 거래소 중 경쟁자 찾기
        competitors = _DOMESTIC_EXCHANGES - {exchange}

        for competitor in competitors:
            # TokenRegistry에서 해당 거래소 상장 여부 조회
            # Phase 5+: listing_history 테이블 조회
            # 현재: 간단한 체크 (실제 구현은 DB 조회 필요)
            if await self._is_listed_on_exchange(symbol, competitor, session):
                return competitor

        return None

    async def _is_listed_on_exchange(
        self,
        symbol: str,
        exchange: str,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> bool:
        """특정 거래소 상장 여부 체크.

        Phase 5+: listing_history DB 조회.
        현재: API 호출로 간단 체크.

        Args:
            symbol: 토큰 심볼.
            exchange: 거래소명.
            session: aiohttp 세션 (재사용, 없으면 새로 생성).
        """
        # 세션이 없으면 새로 생성
        if session is None:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            ) as new_session:
                return await self._check_exchange_api(symbol, exchange, new_session)
        return await self._check_exchange_api(symbol, exchange, session)

    async def _check_exchange_api(
        self,
        symbol: str,
        exchange: str,
        session: aiohttp.ClientSession,
    ) -> bool:
        """거래소 API로 상장 여부 확인."""
        try:
            if exchange == "upbit":
                url = f"https://api.upbit.com/v1/ticker?markets=KRW-{symbol}"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return len(data) > 0
            elif exchange == "bithumb":
                url = f"https://api.bithumb.com/public/ticker/{symbol}_KRW"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        return data.get("status") == "0000"
        except Exception as e:
            logger.debug(
                "[ListingType] %s@%s 상장 체크 실패: %s",
                symbol, exchange, e,
            )
        return False


# ------------------------------------------------------------------
# 전략 결정 헬퍼 (Phase 6 scenario.py에서 사용)
# ------------------------------------------------------------------

def get_strategy_modifier(listing_type: ListingType) -> float:
    """상장 유형별 전략 보정 계수.

    Args:
        listing_type: 상장 유형.

    Returns:
        보정 계수 (-1.0 ~ +1.0).
        양수: 흥따리 가능성 증가, 음수: 망따리 가능성 증가.
    """
    modifiers = {
        ListingType.TGE: +0.3,      # TGE는 흥따리 가능성 높음
        ListingType.DIRECT: 0.0,    # 직상장은 중립
        ListingType.SIDE: -0.2,     # 옆상장은 망따리 가능성 높음 (경쟁)
        ListingType.UNKNOWN: 0.0,   # UNKNOWN은 중립 (WATCH_ONLY)
    }
    return modifiers.get(listing_type, 0.0)
