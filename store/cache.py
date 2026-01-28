"""CoinGecko TTL 캐시 (Phase 3).

3단계 TTL:
  - static(24h): 카테고리, 코인 목록 등 거의 변하지 않는 데이터
  - semi_static(1h): 토크노믹스(MC/FDV/유통량) 등 느리게 변하는 데이터
  - dynamic(1min): 가격 등 빠르게 변하는 데이터

Soft Fail: 429 응답 시 만료된 캐시를 반환하여 서비스 연속성 보장.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

# CoinGecko Free tier base URL
_CG_BASE = "https://api.coingecko.com/api/v3"

# TTL 상수 (초)
TTL_STATIC = 86_400       # 24시간
TTL_SEMI_STATIC = 3_600   # 1시간
TTL_DYNAMIC = 60           # 1분


@dataclass
class _CacheEntry:
    """캐시 엔트리."""
    data: Any
    fetched_at: float
    ttl: float

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.fetched_at) > self.ttl

    @property
    def age_sec(self) -> float:
        return time.time() - self.fetched_at


class CoinGeckoCache:
    """CoinGecko API 응답 TTL 캐시.

    - 키 기반 인메모리 캐시
    - TTL 만료 시 재요청, 429 시 stale 캐시 반환
    - aiohttp 세션 관리 포함
    """

    def __init__(self, api_key: str | None = None) -> None:
        """
        Args:
            api_key: CoinGecko Pro API 키 (없으면 Free tier).
        """
        self._cache: dict[str, _CacheEntry] = {}
        self._api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limited_until: float = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        """세션 lazy 생성."""
        if self._session is None or self._session.closed:
            headers = {}
            if self._api_key:
                headers["x-cg-pro-api-key"] = self._api_key
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers=headers,
            )
        return self._session

    async def close(self) -> None:
        """세션 종료."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def get(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
        ttl: float = TTL_SEMI_STATIC,
    ) -> Any | None:
        """캐시 경유 CoinGecko API 호출.

        Args:
            endpoint: API 엔드포인트 (e.g., "/coins/markets").
            params: 쿼리 파라미터.
            ttl: 캐시 유효 시간 (초).

        Returns:
            JSON 응답 데이터 또는 None (실패 시).
        """
        cache_key = self._make_key(endpoint, params)

        # 캐시 히트 (유효)
        entry = self._cache.get(cache_key)
        if entry and not entry.is_expired:
            return entry.data

        # Rate limit 상태 체크
        now = time.time()
        if now < self._rate_limited_until:
            # 아직 rate limit 상태 → stale 캐시 반환
            if entry:
                logger.debug(
                    "Rate limit 중, stale 캐시 반환: %s (age=%.0fs)",
                    endpoint, entry.age_sec,
                )
                return entry.data
            return None

        # API 호출
        url = f"{_CG_BASE}{endpoint}"
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._cache[cache_key] = _CacheEntry(
                        data=data, fetched_at=time.time(), ttl=ttl,
                    )
                    return data

                if resp.status == 429:
                    # Rate limited → 60초 대기, stale 캐시 반환
                    self._rate_limited_until = time.time() + 60.0
                    logger.warning(
                        "CoinGecko 429 rate limit, 60초 대기: %s", endpoint,
                    )
                    if entry:
                        return entry.data
                    return None

                logger.warning(
                    "CoinGecko API 실패: %s status=%d", endpoint, resp.status,
                )
                # 실패 시에도 stale 캐시가 있으면 반환
                if entry:
                    return entry.data
                return None

        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warning("CoinGecko API 에러: %s — %s", endpoint, e)
            if entry:
                return entry.data
            return None

    async def get_coin_data(self, coin_id: str) -> dict | None:
        """코인 상세 데이터 조회 (market_data 포함).

        Args:
            coin_id: CoinGecko 코인 ID (e.g., "bitcoin").

        Returns:
            코인 데이터 dict 또는 None.
        """
        return await self.get(
            f"/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
            },
            ttl=TTL_SEMI_STATIC,
        )

    async def get_coin_market_data(
        self,
        vs_currency: str = "usd",
        ids: str | None = None,
        per_page: int = 250,
        page: int = 1,
    ) -> list[dict] | None:
        """코인 마켓 데이터 목록 조회.

        Args:
            vs_currency: 기준 통화.
            ids: 쉼표 구분 코인 ID 목록.
            per_page: 페이지당 결과 수.
            page: 페이지 번호.

        Returns:
            코인 마켓 데이터 목록 또는 None.
        """
        params: dict[str, str] = {
            "vs_currency": vs_currency,
            "order": "market_cap_desc",
            "per_page": str(per_page),
            "page": str(page),
            "sparkline": "false",
        }
        if ids:
            params["ids"] = ids
        return await self.get("/coins/markets", params=params, ttl=TTL_SEMI_STATIC)

    def invalidate(self, endpoint: str, params: dict[str, str] | None = None) -> None:
        """특정 캐시 키 무효화."""
        cache_key = self._make_key(endpoint, params)
        self._cache.pop(cache_key, None)

    def clear(self) -> None:
        """전체 캐시 초기화."""
        self._cache.clear()

    @staticmethod
    def _make_key(endpoint: str, params: dict[str, str] | None) -> str:
        """캐시 키 생성."""
        if params:
            sorted_params = "&".join(
                f"{k}={v}" for k, v in sorted(params.items())
            )
            return f"{endpoint}?{sorted_params}"
        return endpoint
