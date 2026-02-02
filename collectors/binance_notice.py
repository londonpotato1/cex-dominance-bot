#!/usr/bin/env python3
"""바이낸스 공지사항 수집기.

기능:
- 바이낸스 신규 상장 공지 모니터링
- 현물 상장 / 선물 상장 / Pre-Market 구분
- 업빗/빗썸 따리 전략 연동

API:
- https://www.binance.com/bapi/composite/v1/public/cms/article/list/query

Catalog IDs:
- 48: New Cryptocurrency Listing (현물)
- 49: New Futures Listing (선물)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum

import aiohttp

logger = logging.getLogger(__name__)

# 바이낸스 공지 API
_BINANCE_API_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
_BINANCE_ARTICLE_URL = "https://www.binance.com/en/support/announcement/{code}"

# Catalog IDs
_CATALOG_SPOT_LISTING = 48      # New Cryptocurrency Listing
_CATALOG_FUTURES_LISTING = 49   # Futures Listing

# HTTP 설정
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15)
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


class BinanceListingType(Enum):
    """바이낸스 상장 유형."""
    SPOT = "spot"                    # 현물 상장
    FUTURES = "futures"              # 선물 상장
    PRE_MARKET = "pre_market"        # Pre-Market
    SEED_TAG = "seed_tag"            # Seed Tag 상장
    ALPHA = "alpha"                  # Alpha 상장
    UNKNOWN = "unknown"


@dataclass
class BinanceNotice:
    """바이낸스 공지 데이터."""
    notice_id: int
    code: str
    title: str
    release_date: datetime
    url: str
    
    # 파싱된 정보
    symbols: List[str] = field(default_factory=list)
    listing_type: BinanceListingType = BinanceListingType.UNKNOWN
    listing_time: Optional[datetime] = None
    pairs: List[str] = field(default_factory=list)  # 거래쌍 (BTC, USDT 등)
    
    # 전략 관련
    has_spot: bool = False
    has_futures: bool = False
    seed_tag: bool = False
    
    def __post_init__(self):
        """제목에서 정보 추출."""
        self._parse_title()
    
    def _parse_title(self):
        """제목 파싱."""
        title = self.title
        
        # Seed Tag 체크
        if "Seed Tag" in title:
            self.seed_tag = True
            self.listing_type = BinanceListingType.SEED_TAG
        
        # Pre-Market 체크
        if "Pre-Market" in title:
            self.listing_type = BinanceListingType.PRE_MARKET
        
        # 선물 체크
        if "Futures" in title:
            self.has_futures = True
            if self.listing_type == BinanceListingType.UNKNOWN:
                self.listing_type = BinanceListingType.FUTURES
        
        # 현물 체크 (Will List, Lists)
        if "Will List" in title or " Lists " in title:
            self.has_spot = True
            if self.listing_type == BinanceListingType.UNKNOWN:
                self.listing_type = BinanceListingType.SPOT
        
        # Alpha 체크
        if "Alpha" in title:
            self.listing_type = BinanceListingType.ALPHA
        
        # 심볼 추출: (SYMBOL) 또는 SYMBOLUSDT 패턴
        # 예: "Binance Will List Zama (ZAMA)"
        symbol_match = re.search(r'\(([A-Z0-9]+)\)', title)
        if symbol_match:
            self.symbols.append(symbol_match.group(1))
        
        # 선물 티커에서 추출: XXXUSDT
        futures_match = re.findall(r'([A-Z0-9]+)USDT', title)
        for sym in futures_match:
            if sym not in self.symbols and sym not in ['USD']:
                self.symbols.append(sym)


class BinanceNoticeFetcher:
    """바이낸스 공지 수집기."""
    
    def __init__(self, seen_codes: set[str] | None = None):
        """
        Args:
            seen_codes: 이미 처리한 공지 코드 집합.
        """
        self._seen_codes = seen_codes or set()
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=_HTTP_TIMEOUT,
                headers=_HTTP_HEADERS,
            )
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def fetch_spot_listings(self, page_size: int = 10) -> List[BinanceNotice]:
        """현물 상장 공지 조회."""
        return await self._fetch_catalog(_CATALOG_SPOT_LISTING, page_size)
    
    async def fetch_futures_listings(self, page_size: int = 10) -> List[BinanceNotice]:
        """선물 상장 공지 조회."""
        return await self._fetch_catalog(_CATALOG_FUTURES_LISTING, page_size)
    
    async def fetch_all_listings(self, page_size: int = 10) -> List[BinanceNotice]:
        """현물 + 선물 공지 모두 조회."""
        spot = await self.fetch_spot_listings(page_size)
        futures = await self.fetch_futures_listings(page_size)
        
        # 중복 제거 (code 기준)
        seen = set()
        result = []
        for notice in spot + futures:
            if notice.code not in seen:
                seen.add(notice.code)
                result.append(notice)
        
        # 최신순 정렬
        result.sort(key=lambda x: x.release_date, reverse=True)
        return result
    
    async def fetch_new_listings(self, page_size: int = 10) -> List[BinanceNotice]:
        """새 공지만 조회 (이미 본 것 제외)."""
        all_notices = await self.fetch_all_listings(page_size)
        new_notices = [n for n in all_notices if n.code not in self._seen_codes]
        
        # seen 업데이트
        for n in new_notices:
            self._seen_codes.add(n.code)
        
        return new_notices
    
    async def _fetch_catalog(
        self, 
        catalog_id: int, 
        page_size: int = 10,
    ) -> List[BinanceNotice]:
        """특정 카탈로그 공지 조회."""
        session = await self._get_session()
        
        params = {
            "type": 1,
            "catalogId": catalog_id,
            "pageNo": 1,
            "pageSize": page_size,
        }
        
        try:
            async with session.get(_BINANCE_API_URL, params=params) as resp:
                if resp.status != 200:
                    logger.warning("[Binance] API 응답 에러: %d", resp.status)
                    return []
                
                data = await resp.json()
                
                if not data.get("success"):
                    logger.warning("[Binance] API 실패: %s", data.get("message"))
                    return []
                
                catalogs = data.get("data", {}).get("catalogs", [])
                if not catalogs:
                    return []
                
                articles = catalogs[0].get("articles", [])
                notices = []
                
                for article in articles:
                    notice = BinanceNotice(
                        notice_id=article["id"],
                        code=article["code"],
                        title=article["title"],
                        release_date=datetime.fromtimestamp(article["releaseDate"] / 1000),
                        url=_BINANCE_ARTICLE_URL.format(code=article["code"]),
                    )
                    notices.append(notice)
                
                return notices
                
        except asyncio.TimeoutError:
            logger.warning("[Binance] API 타임아웃")
            return []
        except Exception as e:
            logger.error("[Binance] API 에러: %s", e)
            return []


@dataclass
class BinanceListingStrategy:
    """바이낸스 상장에 대한 한국 거래소 전략."""
    
    symbol: str
    notice: BinanceNotice
    
    # 전략 판단
    upbit_potential: str = ""       # 업비트 상장 가능성
    bithumb_potential: str = ""     # 빗썸 상장 가능성
    
    # 추천 액션
    actions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # 전략 스코어
    score: int = 0  # 0-100
    
    def analyze(self):
        """전략 분석."""
        # Seed Tag = 신규 코인, 업빗/빗썸 상장 가능성 높음
        if self.notice.seed_tag:
            self.upbit_potential = "HIGH"
            self.bithumb_potential = "HIGH"
            self.actions.append("🎯 Seed Tag 코인 - 업빗/빗썸 상장 대기")
            self.actions.append("📊 DEX 유동성 모니터링")
            self.actions.append("🔥 핫월렛 입금 추적 시작")
            self.score = 80
        
        # 바이낸스 선물만 있으면 현선 갭 플레이 가능
        elif self.notice.has_futures and not self.notice.has_spot:
            self.actions.append("📈 바이낸스 선물 헷지 가능")
            self.actions.append("⏰ 한국 거래소 상장 시 현선갭 체크")
            self.score = 60
        
        # 바이낸스 현물 상장 = 한국 상장 임박 가능
        elif self.notice.has_spot:
            self.upbit_potential = "MEDIUM"
            self.bithumb_potential = "MEDIUM"
            self.actions.append("👀 한국 거래소 공지 모니터링")
            self.actions.append("💰 입금 주소 준비")
            self.score = 70
        
        # Pre-Market은 정식 상장 전
        if self.notice.listing_type == BinanceListingType.PRE_MARKET:
            self.warnings.append("⚠️ Pre-Market - 정식 상장 아님")
            self.score = max(0, self.score - 20)
        
        return self


async def check_binance_listings() -> List[BinanceNotice]:
    """바이낸스 최신 상장 공지 조회 (유틸리티 함수)."""
    fetcher = BinanceNoticeFetcher()
    try:
        notices = await fetcher.fetch_all_listings(page_size=5)
        return notices
    finally:
        await fetcher.close()


# CLI 테스트
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    async def main():
        fetcher = BinanceNoticeFetcher()
        try:
            notices = await fetcher.fetch_all_listings(page_size=5)
            
            print("=== 바이낸스 최신 상장 공지 ===\n")
            for notice in notices:
                print(f"📢 {notice.title}")
                print(f"   유형: {notice.listing_type.value}")
                print(f"   심볼: {notice.symbols}")
                print(f"   시간: {notice.release_date}")
                print(f"   Seed Tag: {notice.seed_tag}")
                print(f"   URL: {notice.url}")
                print()
                
                # 전략 분석
                if notice.symbols:
                    strategy = BinanceListingStrategy(
                        symbol=notice.symbols[0],
                        notice=notice,
                    ).analyze()
                    
                    print(f"   📊 전략 스코어: {strategy.score}")
                    for action in strategy.actions:
                        print(f"   → {action}")
                    for warn in strategy.warnings:
                        print(f"   {warn}")
                print("-" * 50)
        finally:
            await fetcher.close()
    
    asyncio.run(main())
