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
    deposit_time: Optional[datetime] = None  # 입금 시작 시간
    withdraw_time: Optional[datetime] = None  # 출금 시작 시간
    pairs: List[str] = field(default_factory=list)  # 거래쌍 (BTC, USDT 등)
    
    # 전략 관련
    has_spot: bool = False
    has_futures: bool = False
    seed_tag: bool = False
    
    # 바이낸스 알파 관련
    has_alpha: bool = False
    alpha_time: Optional[datetime] = None
    alpha_note: Optional[str] = None  # "time will be announced later" 등
    
    # 본문 (파싱용)
    content: Optional[str] = None
    
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
        
        # 상장 시간 계산 (공지 발표 후 예상 시간)
        # Seed Tag: 보통 공지 후 4-6시간 뒤 상장
        # 일반 현물: 보통 공지에 명시된 시간 (UTC 기준)
        self._estimate_listing_time()
    
    def _estimate_listing_time(self):
        """상장 시간 예측."""
        from datetime import timedelta
        
        if not self.release_date:
            return
        
        # Seed Tag / Pre-Market: 공지 후 약 5-6시간 뒤 (바이낸스 패턴)
        if self.seed_tag or self.listing_type == BinanceListingType.PRE_MARKET:
            # 보통 UTC 10:00 또는 14:00에 상장
            release_hour = self.release_date.hour
            
            # 공지가 UTC 04-08시면 → UTC 10:00 (KST 19:00) 상장
            if 4 <= release_hour < 10:
                target_hour = 10
            # 공지가 UTC 08-14시면 → UTC 14:00 (KST 23:00) 상장
            elif 10 <= release_hour < 16:
                target_hour = 14
            # 그 외 → 다음날 UTC 10:00
            else:
                target_hour = 10
                self.listing_time = self.release_date.replace(
                    hour=target_hour, minute=0, second=0, microsecond=0
                ) + timedelta(days=1)
                return
            
            self.listing_time = self.release_date.replace(
                hour=target_hour, minute=0, second=0, microsecond=0
            )
            
            # 만약 예측 시간이 공지 시간보다 이전이면 다음날로
            if self.listing_time <= self.release_date:
                self.listing_time += timedelta(days=1)
        
        # 일반 현물/선물: 공지 후 약 1-2시간 (즉시 상장 패턴)
        elif self.has_spot or self.has_futures:
            self.listing_time = self.release_date + timedelta(hours=1)
    
    def parse_content_times(self, content: str) -> None:
        """공지 본문에서 정확한 시간 파싱.
        
        파싱 패턴:
        - "open trading ... at 2026-02-02 13:00 (UTC)" → 상장 시간
        - "start depositing ... one hour later" → 입금 시간 (상장 1시간 전)
        - "Withdrawals will open at 2026-02-03 13:00 (UTC)" → 출금 시간
        """
        from datetime import timedelta
        import pytz
        
        self.content = content
        
        # UTC → KST 변환용
        utc = pytz.UTC
        kst = pytz.timezone('Asia/Seoul')
        
        # 1. 상장 시간 파싱: "open trading at YYYY-MM-DD HH:MM (UTC)"
        listing_match = re.search(
            r'open trading[^0-9]*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s*\(?UTC\)?',
            content, re.IGNORECASE
        )
        if listing_match:
            try:
                date_str = listing_match.group(1)
                hour = int(listing_match.group(2))
                minute = int(listing_match.group(3))
                listing_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=hour, minute=minute, tzinfo=utc
                )
                self.listing_time = listing_dt.astimezone(kst).replace(tzinfo=None)
            except:
                pass
        
        # 2. 입금 시간 파싱 (명시적 날짜가 있는 경우만)
        # "Deposits will open at YYYY-MM-DD HH:MM (UTC)" 또는 "Deposit available at ..."
        deposit_match = re.search(
            r'[Dd]eposit[s]?\s+(?:will\s+)?(?:open|be\s+available)\s+(?:at\s+)?(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s*\(?UTC\)?',
            content
        )
        if deposit_match:
            try:
                date_str = deposit_match.group(1)
                hour = int(deposit_match.group(2))
                minute = int(deposit_match.group(3))
                deposit_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=hour, minute=minute, tzinfo=utc
                )
                self.deposit_time = deposit_dt.astimezone(kst).replace(tzinfo=None)
            except:
                pass
        
        # "start depositing" + "in preparation" → 상장 전 입금 가능 (정확한 시간 없음)
        # 이 경우 상장 시간 표시만 하고 입금 시간은 별도 표시 안함
        
        # 3. 출금 시간 파싱: "Withdrawals will open at YYYY-MM-DD HH:MM (UTC)"
        withdraw_match = re.search(
            r'[Ww]ithdrawal[s]?\s+will\s+open\s+at\s+(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s*\(?UTC\)?',
            content
        )
        if withdraw_match:
            try:
                date_str = withdraw_match.group(1)
                hour = int(withdraw_match.group(2))
                minute = int(withdraw_match.group(3))
                withdraw_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=hour, minute=minute, tzinfo=utc
                )
                self.withdraw_time = withdraw_dt.astimezone(kst).replace(tzinfo=None)
            except:
                pass
        
        # 4. 바이낸스 알파 파싱
        if 'binance alpha' in content.lower():
            self.has_alpha = True
            
            # "time will be announced later" 체크 먼저!
            time_announced_later = 'announced later' in content.lower() or 'will be announced' in content.lower()
            
            if time_announced_later:
                # 알파 시간이 공지에 없음 → 스팟 상장 1시간 전으로 추정
                if self.listing_time:
                    self.alpha_time = self.listing_time - timedelta(hours=1)
                    self.alpha_note = "추정 (스팟 1시간 전)"
                else:
                    self.alpha_note = "시간 추후 공지"
            else:
                # 알파 상장 시간이 명시된 경우: "Binance Alpha at YYYY-MM-DD HH:MM (UTC)"
                alpha_time_match = re.search(
                    r'[Bb]inance\s+[Aa]lpha[^0-9]*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s*\(?UTC\)?',
                    content
                )
                if alpha_time_match:
                    try:
                        date_str = alpha_time_match.group(1)
                        hour = int(alpha_time_match.group(2))
                        minute = int(alpha_time_match.group(3))
                        alpha_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                            hour=hour, minute=minute, tzinfo=utc
                        )
                        self.alpha_time = alpha_dt.astimezone(kst).replace(tzinfo=None)
                    except:
                        pass
                
                if not self.alpha_time:
                    # 시간 파싱 실패 시 스팟 1시간 전으로 추정
                    if self.listing_time:
                        self.alpha_time = self.listing_time - timedelta(hours=1)
                        self.alpha_note = "추정 (스팟 1시간 전)"
                    else:
                        self.alpha_note = "알파 상장 예정"


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
    
    async def fetch_article_content(self, notice: BinanceNotice) -> str:
        """공지 본문 가져오기 + 시간 파싱."""
        session = await self._get_session()
        
        # 바이낸스 공지 상세 API (정확한 엔드포인트)
        detail_url = f"https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode={notice.code}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'lang': 'en',
        }
        
        try:
            async with session.get(detail_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning("[Binance] 공지 상세 조회 실패: %d", resp.status)
                    return ""
                
                data = await resp.json()
                if not data.get("success"):
                    return ""
                
                # body 키에 본문 있음 (JSON 또는 HTML)
                article = data.get("data", {})
                content = article.get("body", "")
                
                # JSON 형식인 경우 텍스트 추출
                if content.startswith('{'):
                    import json
                    try:
                        def extract_text_from_json(obj):
                            """JSON 구조에서 텍스트 추출"""
                            texts = []
                            if isinstance(obj, dict):
                                if obj.get('node') == 'text':
                                    texts.append(obj.get('text', ''))
                                for v in obj.values():
                                    texts.extend(extract_text_from_json(v))
                            elif isinstance(obj, list):
                                for item in obj:
                                    texts.extend(extract_text_from_json(item))
                            return texts
                        
                        json_data = json.loads(content)
                        content = ' '.join(extract_text_from_json(json_data))
                    except:
                        pass
                
                # HTML 태그 제거 (fallback)
                content = re.sub(r'<[^>]+>', ' ', content)
                content = re.sub(r'\s+', ' ', content).strip()
                
                # 시간 파싱
                if content:
                    notice.parse_content_times(content)
                    logger.info(f"[Binance] {notice.symbols} 시간 파싱 완료 - 상장:{notice.listing_time}, 입금:{notice.deposit_time}, 출금:{notice.withdraw_time}")
                
                return content
                
        except Exception as e:
            logger.error("[Binance] 공지 본문 조회 에러: %s", e)
            return ""


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
