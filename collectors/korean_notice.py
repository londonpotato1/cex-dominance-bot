#!/usr/bin/env python3
"""한국 거래소(업비트/빗썸) 공지사항 수집기.

모니터링 대상:
- 업비트: 입출금 정지/재개, 거래유의, 원화마켓 추가
- 빗썸: 거래유의, 입출금, 마켓 추가

v1: 2026-02-02
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
        if any(kw in title for kw in ['마켓 추가', '원화 마켓 유의사항', '신규 상장', '거래 지원']):
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
    
    def __init__(self, seen_ids: set[str] | None = None):
        """
        Args:
            seen_ids: 이미 처리한 공지 ID 집합.
        """
        self._seen_ids = seen_ids or set()
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
    
    # ------------------------------------------------------------------
    # 업비트 공지 수집
    # ------------------------------------------------------------------
    
    async def fetch_upbit_notices(self, limit: int = 20) -> List[KoreanNotice]:
        """업비트 공지 조회 (Playwright 크롤링)."""
        notices = []
        
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # 업비트 공지 페이지 접속
                await page.goto("https://upbit.com/service_center/notice", wait_until="networkidle", timeout=30000)
                await page.wait_for_selector(".NoticeList", timeout=10000)
                
                # 공지 목록 파싱
                items = await page.query_selector_all(".NoticeList .NoticeItem")
                
                for i, item in enumerate(items[:limit]):
                    try:
                        # 제목
                        title_el = await item.query_selector(".NoticeItem__title")
                        title = await title_el.inner_text() if title_el else ""
                        
                        # 날짜
                        date_el = await item.query_selector(".NoticeItem__date")
                        date_str = await date_el.inner_text() if date_el else ""
                        
                        # 링크
                        link_el = await item.query_selector("a")
                        href = await link_el.get_attribute("href") if link_el else ""
                        notice_id = href.split("id=")[-1] if "id=" in href else f"upbit_{i}"
                        url = f"https://upbit.com{href}" if href.startswith("/") else href
                        
                        # 날짜 파싱
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
                
            logger.info(f"[KoreanNotice] 업비트 공지 {len(notices)}개 조회 완료")
            
        except ImportError:
            logger.warning("[KoreanNotice] Playwright 미설치 - pip install playwright")
        except Exception as e:
            logger.warning("[KoreanNotice] 업비트 공지 조회 실패: %s", e)
        
        return notices
    
    # ------------------------------------------------------------------
    # 빗썸 공지 수집
    # ------------------------------------------------------------------
    
    async def fetch_bithumb_notices(
        self, 
        categories: List[int] | None = None,
        limit: int = 20,
    ) -> List[KoreanNotice]:
        """빗썸 공지 조회 (Playwright 크롤링).
        
        Args:
            categories: 카테고리 목록. 5=거래유의, 7=입출금
            limit: 조회 개수
        """
        if categories is None:
            categories = [5, 7]  # 거래유의, 입출금
        
        notices = []
        
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                for category in categories:
                    try:
                        # 빗썸 공지 페이지 (카테고리별)
                        url = f"https://feed.bithumb.com/notice?category={category}&page=1"
                        await page.goto(url, wait_until="networkidle", timeout=30000)
                        
                        # Cloudflare 체크 통과 대기
                        await page.wait_for_timeout(2000)
                        
                        # 공지 목록 파싱
                        items = await page.query_selector_all("table tbody tr")
                        
                        for i, item in enumerate(items[:limit // len(categories)]):
                            try:
                                # 제목
                                title_el = await item.query_selector("td:nth-child(2)")
                                title = await title_el.inner_text() if title_el else ""
                                
                                # 날짜
                                date_el = await item.query_selector("td:last-child")
                                date_str = await date_el.inner_text() if date_el else ""
                                
                                # 링크
                                link_el = await item.query_selector("a")
                                href = await link_el.get_attribute("href") if link_el else ""
                                notice_id = href.split("/")[-1] if href else f"bithumb_{category}_{i}"
                                
                                # 날짜 파싱
                                try:
                                    pub_date = datetime.strptime(date_str.strip(), "%Y.%m.%d")
                                except:
                                    pub_date = datetime.now()
                                
                                notice = KoreanNotice(
                                    exchange=Exchange.BITHUMB,
                                    notice_id=f"bithumb_{notice_id}",
                                    title=title.strip(),
                                    url=f"https://feed.bithumb.com{href}" if href.startswith("/") else href,
                                    published_at=pub_date,
                                )
                                notices.append(notice)
                                
                            except Exception as e:
                                logger.debug(f"[Bithumb] 항목 파싱 실패: {e}")
                                continue
                                
                    except Exception as e:
                        logger.warning(f"[Bithumb] 카테고리 {category} 조회 실패: {e}")
                        continue
                
                await browser.close()
            
            logger.info(f"[KoreanNotice] 빗썸 공지 {len(notices)}개 조회 완료")
            
        except ImportError:
            logger.warning("[KoreanNotice] Playwright 미설치 - pip install playwright")
        except Exception as e:
            logger.warning("[KoreanNotice] 빗썸 공지 조회 실패: %s", e)
        
        return notices
    
    # ------------------------------------------------------------------
    # 통합 조회
    # ------------------------------------------------------------------
    
    async def fetch_all_notices(self, limit: int = 20) -> List[KoreanNotice]:
        """모든 한국 거래소 공지 조회."""
        upbit_notices = await self.fetch_upbit_notices(limit)
        bithumb_notices = await self.fetch_bithumb_notices(limit=limit)
        
        all_notices = upbit_notices + bithumb_notices
        
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
