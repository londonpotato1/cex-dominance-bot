#!/usr/bin/env python3
"""한국 거래소(업비트/빗썸) 공지사항 수집기.

모니터링 대상:
- 업비트: 입출금 정지/재개, 거래유의, 원화마켓 추가
- 빗썸: 거래유의, 입출금, 마켓 추가

v1: 2026-02-02
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from enum import Enum

import aiohttp

logger = logging.getLogger(__name__)

# HTTP 설정
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


class NoticeType(Enum):
    """공지 유형."""
    LISTING = "listing"              # 신규 상장
    DELISTING = "delisting"          # 상장 폐지
    DEPOSIT_SUSPEND = "deposit_suspend"    # 입금 정지
    DEPOSIT_RESUME = "deposit_resume"      # 입금 재개
    WITHDRAW_SUSPEND = "withdraw_suspend"  # 출금 정지
    WITHDRAW_RESUME = "withdraw_resume"    # 출금 재개
    TRADING_CAUTION = "trading_caution"    # 거래유의 지정
    CAUTION_RELEASE = "caution_release"    # 거래유의 해제
    NETWORK_ISSUE = "network_issue"        # 네트워크 이슈
    OTHER = "other"


class Exchange(Enum):
    """거래소."""
    UPBIT = "upbit"
    BITHUMB = "bithumb"
    COINONE = "coinone"


@dataclass
class KoreanNotice:
    """한국 거래소 공지 데이터."""
    exchange: Exchange
    notice_id: str
    title: str
    url: str
    published_at: datetime
    
    # 파싱된 정보
    notice_type: NoticeType = NoticeType.OTHER
    symbols: List[str] = field(default_factory=list)
    networks: List[str] = field(default_factory=list)
    
    # 시간 정보 (파싱된 경우)
    effective_time: Optional[datetime] = None  # 적용 시간
    
    def __post_init__(self):
        """제목에서 정보 추출."""
        self._parse_title()
    
    def _parse_title(self):
        """제목 파싱하여 유형 및 심볼 추출."""
        title = self.title
        
        # 심볼 추출: (SYMBOL) 또는 한글명(SYMBOL) 패턴
        # 예: "비트코인(BTC) 입금 일시 중지", "솔라(SXP) 거래유의종목 지정"
        symbol_matches = re.findall(r'\(([A-Z0-9]+)\)', title)
        self.symbols = list(set(symbol_matches))
        
        # 네트워크 추출
        network_patterns = [
            r'(이더리움|ETH)\s*네트워크',
            r'(솔라나|SOL)\s*네트워크',
            r'(트론|TRX|TRC20)\s*네트워크',
            r'(BNB|BSC)\s*네트워크',
            r'(폴리곤|MATIC|POL)\s*네트워크',
            r'(아비트럼|ARB)\s*네트워크',
            r'(옵티미즘|OP)\s*네트워크',
        ]
        for pattern in network_patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                self.networks.append(match.group(1).upper())
        
        # 공지 유형 판별
        title_lower = title.lower()
        
        # 신규 상장
        if any(kw in title for kw in ['마켓 추가', '원화 마켓 유의사항', '신규 상장', '거래 지원', '신규 거래지원', '거래지원 안내']):
            self.notice_type = NoticeType.LISTING
        
        # 상장 폐지
        elif any(kw in title for kw in ['거래지원 종료', '상장 폐지', '마켓 삭제']):
            self.notice_type = NoticeType.DELISTING
        
        # 거래유의 지정
        elif '거래유의' in title and '해제' not in title:
            self.notice_type = NoticeType.TRADING_CAUTION
        
        # 거래유의 해제
        elif '거래유의' in title and '해제' in title:
            self.notice_type = NoticeType.CAUTION_RELEASE
        
        # 입금 정지
        elif any(kw in title for kw in ['입금 일시 중지', '입금 중지', '입출금 일시 중지', '입출금 중지']):
            if '재개' not in title and '정상화' not in title:
                self.notice_type = NoticeType.DEPOSIT_SUSPEND
        
        # 입금 재개
        elif any(kw in title for kw in ['입금 재개', '입금 정상화', '입출금 재개', '입출금 정상화']):
            self.notice_type = NoticeType.DEPOSIT_RESUME
        
        # 출금 정지
        elif any(kw in title for kw in ['출금 일시 중지', '출금 중지']):
            if '재개' not in title and '정상화' not in title:
                self.notice_type = NoticeType.WITHDRAW_SUSPEND
        
        # 출금 재개
        elif any(kw in title for kw in ['출금 재개', '출금 정상화']):
            self.notice_type = NoticeType.WITHDRAW_RESUME
        
        # 네트워크 이슈
        elif any(kw in title for kw in ['네트워크 점검', '네트워크 업그레이드', '하드포크']):
            self.notice_type = NoticeType.NETWORK_ISSUE
    
    def is_actionable(self) -> bool:
        """따리 전략에 영향을 주는 공지인지 확인."""
        actionable_types = [
            NoticeType.LISTING,
            NoticeType.DEPOSIT_SUSPEND,
            NoticeType.DEPOSIT_RESUME,
            NoticeType.WITHDRAW_SUSPEND,
            NoticeType.WITHDRAW_RESUME,
            NoticeType.TRADING_CAUTION,
        ]
        return self.notice_type in actionable_types
    
    def get_emoji(self) -> str:
        """공지 유형별 이모지."""
        emoji_map = {
            NoticeType.LISTING: "🚀",
            NoticeType.DELISTING: "⛔",
            NoticeType.DEPOSIT_SUSPEND: "🔒",
            NoticeType.DEPOSIT_RESUME: "🔓",
            NoticeType.WITHDRAW_SUSPEND: "🔒",
            NoticeType.WITHDRAW_RESUME: "🔓",
            NoticeType.TRADING_CAUTION: "⚠️",
            NoticeType.CAUTION_RELEASE: "✅",
            NoticeType.NETWORK_ISSUE: "🔧",
            NoticeType.OTHER: "📢",
        }
        return emoji_map.get(self.notice_type, "📢")
    
    def get_type_text(self) -> str:
        """공지 유형 한글 텍스트."""
        text_map = {
            NoticeType.LISTING: "신규 상장",
            NoticeType.DELISTING: "상장 폐지",
            NoticeType.DEPOSIT_SUSPEND: "입금 정지",
            NoticeType.DEPOSIT_RESUME: "입금 재개",
            NoticeType.WITHDRAW_SUSPEND: "출금 정지",
            NoticeType.WITHDRAW_RESUME: "출금 재개",
            NoticeType.TRADING_CAUTION: "거래유의",
            NoticeType.CAUTION_RELEASE: "유의 해제",
            NoticeType.NETWORK_ISSUE: "네트워크",
            NoticeType.OTHER: "공지",
        }
        return text_map.get(self.notice_type, "공지")


class KoreanNoticeFetcher:
    """한국 거래소 공지 수집기."""
    
    # 마켓 목록 캐시 파일 경로
    _MARKET_CACHE_FILE = Path(__file__).parent.parent / "data" / "korean_markets_cache.json"
    
    def __init__(self, seen_ids: set[str] | None = None):
        """
        Args:
            seen_ids: 이미 처리한 공지 ID 집합.
        """
        self._seen_ids = seen_ids or set()
        self._session: Optional[aiohttp.ClientSession] = None
        self._market_cache = self._load_market_cache()
    
    def _load_market_cache(self) -> dict:
        """마켓 캐시 로드."""
        try:
            if self._MARKET_CACHE_FILE.exists():
                with open(self._MARKET_CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {"upbit": [], "bithumb": [], "last_updated": None}
    
    def _save_market_cache(self, upbit_markets: list, bithumb_markets: list):
        """마켓 캐시 저장."""
        try:
            self._MARKET_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            cache = {
                "upbit": upbit_markets,
                "bithumb": bithumb_markets,
                "last_updated": datetime.now().isoformat()
            }
            with open(self._MARKET_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            self._market_cache = cache
        except Exception as e:
            logger.warning(f"마켓 캐시 저장 실패: {e}")
    
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
    
    # ------------------------------------------------------------------
    # 업비트 공지 수집
    # ------------------------------------------------------------------
    
    async def fetch_upbit_notices(self, limit: int = 20) -> List[KoreanNotice]:
        """업비트 입출금 상태 조회 (API 기반).
        
        UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY 환경변수 필요.
        """
        notices = []
        
        try:
            import os
            import jwt
            import uuid
            import hashlib
            
            access_key = os.getenv("UPBIT_ACCESS_KEY")
            secret_key = os.getenv("UPBIT_SECRET_KEY")
            
            if not access_key or not secret_key:
                logger.warning("[Upbit] API 키 없음 - 크롤링 폴백")
                return await self._fetch_upbit_notices_crawl(limit)
            
            # JWT 토큰 생성
            payload = {
                'access_key': access_key,
                'nonce': str(uuid.uuid4()),
            }
            jwt_token = jwt.encode(payload, secret_key)
            auth_header = f'Bearer {jwt_token}'
            
            session = await self._get_session()
            
            # 업비트 입출금 상태 API
            url = "https://api.upbit.com/v1/status/wallet"
            headers = {"Authorization": auth_header}
            
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"[Upbit] API 응답 오류: {resp.status}")
                    return await self._fetch_upbit_notices_crawl(limit)
                
                data = await resp.json()
                
                # 입출금 중단된 코인 찾기
                for coin in data:
                    currency = coin.get("currency", "")
                    wallet_state = coin.get("wallet_state", "")
                    
                    # working = 정상, withdraw_only = 출금만, paused = 중단
                    if wallet_state in ["paused", "withdraw_only", "deposit_only"]:
                        if wallet_state == "paused":
                            title = f"{currency} 입출금 일시 중지"
                            notice_type = NoticeType.DEPOSIT_SUSPEND
                        elif wallet_state == "withdraw_only":
                            title = f"{currency} 입금 일시 중지"
                            notice_type = NoticeType.DEPOSIT_SUSPEND
                        else:
                            title = f"{currency} 출금 일시 중지"
                            notice_type = NoticeType.WITHDRAW_SUSPEND
                        
                        notice = KoreanNotice(
                            exchange=Exchange.UPBIT,
                            notice_id=f"upbit_status_{currency}",
                            title=title,
                            url="https://upbit.com/service_center/notice",
                            published_at=datetime.now(),
                        )
                        notice.symbols = [currency]
                        notice.notice_type = notice_type
                        notices.append(notice)
                
                logger.info(f"[KoreanNotice] 업비트 API - 입출금 중단 코인 {len(notices)}개 감지")
            
        except ImportError as e:
            logger.warning(f"[KoreanNotice] JWT 라이브러리 없음: {e}")
        except Exception as e:
            logger.warning("[KoreanNotice] 업비트 API 조회 실패: %s", e)
        
        # 크롤링으로 예정된 공지도 추가 (API는 현재 상태만 반환)
        try:
            crawl_notices = await self._fetch_upbit_notices_crawl(limit)
            # 중복 제거하고 합치기
            existing_symbols = {n.symbols[0] if n.symbols else "" for n in notices}
            for cn in crawl_notices:
                if cn.symbols and cn.symbols[0] not in existing_symbols:
                    notices.append(cn)
                    existing_symbols.add(cn.symbols[0])
            logger.info(f"[KoreanNotice] 업비트 크롤링 추가 후 총 {len(notices)}개")
        except Exception as e:
            logger.debug(f"[KoreanNotice] 업비트 크롤링 실패 (무시): {e}")
        
        return notices[:limit]
    
    async def _fetch_upbit_notices_crawl(self, limit: int = 20) -> List[KoreanNotice]:
        """업비트 공지 크롤링 (API 실패 시 폴백)."""
        notices = []
        
        try:
            from playwright.async_api import async_playwright
            import asyncio as _asyncio
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.goto("https://upbit.com/service_center/notice", timeout=30000)
                await _asyncio.sleep(5)
                
                rows = await page.query_selector_all("tbody tr")
                
                for i, row in enumerate(rows[:limit]):
                    try:
                        cells = await row.query_selector_all("td")
                        if len(cells) < 2:
                            continue
                        
                        title = await cells[0].inner_text()
                        date_str = await cells[-1].inner_text()
                        
                        link_el = await row.query_selector("a")
                        href = await link_el.get_attribute("href") if link_el else ""
                        notice_id = href.split("id=")[-1] if "id=" in href else f"upbit_{i}"
                        url = f"https://upbit.com{href}" if href.startswith("/") else href
                        
                        try:
                            pub_date = datetime.strptime(date_str.strip(), "%Y.%m.%d")
                        except:
                            pub_date = datetime.now()
                        
                        notice = KoreanNotice(
                            exchange=Exchange.UPBIT,
                            notice_id=f"upbit_{notice_id}",
                            title=title.strip(),
                            url=url,
                            published_at=pub_date,
                        )
                        notices.append(notice)
                        
                    except Exception as e:
                        logger.debug(f"[Upbit] 항목 파싱 실패: {e}")
                        continue
                
                await browser.close()
                
            logger.info(f"[KoreanNotice] 업비트 공지 크롤링 {len(notices)}개 완료")
            
        except Exception as e:
            logger.warning("[KoreanNotice] 업비트 크롤링 실패: %s", e)
        
        return notices
    
    # ------------------------------------------------------------------
    # 빗썸 공지 수집
    # ------------------------------------------------------------------
    
    async def fetch_bithumb_notices(
        self, 
        categories: List[int] | None = None,
        limit: int = 20,
    ) -> List[KoreanNotice]:
        """빗썸 입출금 상태 조회 (API 기반).
        
        빗썸은 Cloudflare 보호로 크롤링 불가.
        대신 assetsstatus API로 입출금 상태 변화 감지.
        """
        notices = []
        
        try:
            session = await self._get_session()
            
            # 빗썸 입출금 상태 API
            url = "https://api.bithumb.com/public/assetsstatus/ALL"
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"[Bithumb] API 응답 오류: {resp.status}")
                    return notices
                
                data = await resp.json()
                if data.get("status") != "0000":
                    logger.warning(f"[Bithumb] API 상태 오류: {data.get('status')}")
                    return notices
                
                assets = data.get("data", {})
                
                # 입출금 중단된 코인 찾기
                for symbol, status in assets.items():
                    if not isinstance(status, dict):
                        continue
                    
                    deposit = status.get("deposit_status", 1)
                    withdrawal = status.get("withdrawal_status", 1)
                    
                    # 입금 또는 출금 중단된 경우
                    if deposit == 0 or withdrawal == 0:
                        # 상태에 따른 제목 생성
                        if deposit == 0 and withdrawal == 0:
                            title = f"{symbol} 입출금 일시 중지"
                            notice_type = NoticeType.DEPOSIT_SUSPEND
                        elif deposit == 0:
                            title = f"{symbol} 입금 일시 중지"
                            notice_type = NoticeType.DEPOSIT_SUSPEND
                        else:
                            title = f"{symbol} 출금 일시 중지"
                            notice_type = NoticeType.WITHDRAW_SUSPEND
                        
                        notice = KoreanNotice(
                            exchange=Exchange.BITHUMB,
                            notice_id=f"bithumb_status_{symbol}",
                            title=title,
                            url="https://www.bithumb.com/",
                            published_at=datetime.now(),
                        )
                        # 직접 심볼과 타입 설정
                        notice.symbols = [symbol]
                        notice.notice_type = notice_type
                        notices.append(notice)
                
                logger.info(f"[KoreanNotice] 빗썸 입출금 중단 코인 {len(notices)}개 감지")
                
        except Exception as e:
            logger.warning("[KoreanNotice] 빗썸 상태 조회 실패: %s", e)
        
        return notices[:limit]
    
    # ------------------------------------------------------------------
    # 신규 상장 감지 (마켓 API 기반)
    # ------------------------------------------------------------------
    
    async def fetch_new_listings(self) -> List[KoreanNotice]:
        """업비트/빗썸 신규 상장 감지 (마켓 API 비교)."""
        notices = []
        session = await self._get_session()
        
        # 현재 마켓 목록 조회
        current_upbit = []
        current_bithumb = []
        
        try:
            # 업비트 마켓 조회
            async with session.get("https://api.upbit.com/v1/market/all") as resp:
                if resp.status == 200:
                    markets = await resp.json()
                    current_upbit = [m["market"].replace("KRW-", "") 
                                    for m in markets if m["market"].startswith("KRW-")]
                    logger.debug(f"[KoreanNotice] 업비트 KRW 마켓: {len(current_upbit)}개")
        except Exception as e:
            logger.warning(f"[KoreanNotice] 업비트 마켓 조회 실패: {e}")
        
        try:
            # 빗썸 마켓 조회
            async with session.get("https://api.bithumb.com/public/ticker/ALL_KRW") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "0000":
                        tickers = data.get("data", {})
                        current_bithumb = [k for k in tickers.keys() if k != "date"]
                        logger.debug(f"[KoreanNotice] 빗썸 KRW 마켓: {len(current_bithumb)}개")
        except Exception as e:
            logger.warning(f"[KoreanNotice] 빗썸 마켓 조회 실패: {e}")
        
        # 이전 캐시와 비교
        prev_upbit = set(self._market_cache.get("upbit", []))
        prev_bithumb = set(self._market_cache.get("bithumb", []))
        
        # 신규 상장 감지
        new_upbit = set(current_upbit) - prev_upbit if prev_upbit else set()
        new_bithumb = set(current_bithumb) - prev_bithumb if prev_bithumb else set()
        
        # 업비트 신규 상장 알림 생성
        for symbol in new_upbit:
            notice = KoreanNotice(
                exchange=Exchange.UPBIT,
                notice_id=f"upbit_listing_{symbol}_{datetime.now().strftime('%Y%m%d')}",
                title=f"{symbol} 원화(KRW) 마켓 신규 상장",
                url="https://upbit.com/service_center/notice",
                published_at=datetime.now(),
            )
            notice.symbols = [symbol]
            notice.notice_type = NoticeType.LISTING
            notices.append(notice)
            logger.info(f"[KoreanNotice] 업비트 신규 상장 감지: {symbol}")
        
        # 빗썸 신규 상장 알림 생성
        for symbol in new_bithumb:
            notice = KoreanNotice(
                exchange=Exchange.BITHUMB,
                notice_id=f"bithumb_listing_{symbol}_{datetime.now().strftime('%Y%m%d')}",
                title=f"{symbol} 원화(KRW) 마켓 신규 상장",
                url="https://www.bithumb.com/",
                published_at=datetime.now(),
            )
            notice.symbols = [symbol]
            notice.notice_type = NoticeType.LISTING
            notices.append(notice)
            logger.info(f"[KoreanNotice] 빗썸 신규 상장 감지: {symbol}")
        
        # 캐시 업데이트 (현재 목록 저장)
        if current_upbit or current_bithumb:
            self._save_market_cache(current_upbit, current_bithumb)
        
        return notices
    
    # ------------------------------------------------------------------
    # 통합 조회
    # ------------------------------------------------------------------
    
    async def fetch_all_notices(self, limit: int = 20) -> List[KoreanNotice]:
        """모든 한국 거래소 공지 조회 (신규 상장 포함)."""
        # 병렬 조회
        results = await asyncio.gather(
            self.fetch_upbit_notices(limit),
            self.fetch_bithumb_notices(limit=limit),
            self.fetch_new_listings(),
            return_exceptions=True
        )
        
        all_notices = []
        for r in results:
            if isinstance(r, list):
                all_notices.extend(r)
        
        # 최신순 정렬
        all_notices.sort(key=lambda x: x.published_at, reverse=True)
        
        return all_notices[:limit]
    
    async def fetch_new_notices(self, limit: int = 20) -> List[KoreanNotice]:
        """새 공지만 조회 (이미 본 것 제외)."""
        all_notices = await self.fetch_all_notices(limit)
        new_notices = [n for n in all_notices if n.notice_id not in self._seen_ids]
        
        # seen 업데이트
        for n in new_notices:
            self._seen_ids.add(n.notice_id)
        
        return new_notices
    
    async def fetch_actionable_notices(self, limit: int = 20) -> List[KoreanNotice]:
        """따리 전략에 영향을 주는 공지만 조회."""
        notices = await self.fetch_all_notices(limit)
        return [n for n in notices if n.is_actionable()]


# ------------------------------------------------------------------
# 유틸리티 함수
# ------------------------------------------------------------------

async def fetch_korean_notices(limit: int = 20) -> List[KoreanNotice]:
    """한국 거래소 공지 조회 (유틸리티 함수)."""
    fetcher = KoreanNoticeFetcher()
    try:
        return await fetcher.fetch_all_notices(limit)
    finally:
        await fetcher.close()


# ------------------------------------------------------------------
# CLI 테스트
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    # 테스트용 목업 데이터
    test_titles = [
        "솔라(SXP) 거래유의종목 지정",
        "비트코인(BTC) 입금 일시 중지 안내",
        "이더리움(ETH) 네트워크 계열 출금 일시 중지 안내 (정상화)",
        "세이(SEI) 입출금 일시 중지 안내",
        "스토리(IP) 원화 마켓 추가",
        "루프링(LRC) 거래유의종목 지정",
    ]
    
    print("=== 한국 거래소 공지 파싱 테스트 ===\n")
    
    for i, title in enumerate(test_titles):
        notice = KoreanNotice(
            exchange=Exchange.UPBIT,
            notice_id=f"test_{i}",
            title=title,
            url="https://upbit.com/service_center/notice",
            published_at=datetime.now(),
        )
        
        print(f"{notice.get_emoji()} [{notice.get_type_text()}] {title}")
        print(f"   심볼: {notice.symbols}")
        print(f"   네트워크: {notice.networks}")
        print(f"   액션 필요: {notice.is_actionable()}")
        print()
