"""상장 공지 모니터링 모듈.

업비트/빗썸의 신규 상장 공지를 자동으로 감지.
기존 notice_fetcher.py보다 가벼운 독립 모듈.

사용법:
    monitor = ListingMonitor(on_listing=my_callback)
    await monitor.run(stop_event)

또는 단일 체크:
    monitor = ListingMonitor()
    listings = await monitor.check_once()
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Awaitable, Any
from concurrent.futures import ThreadPoolExecutor

import aiohttp

# cloudscraper 선택적 import (CloudFlare 우회)
try:
    import cloudscraper
    _HAS_CLOUDSCRAPER = True
except ImportError:
    _HAS_CLOUDSCRAPER = False
    cloudscraper = None  # type: ignore

logger = logging.getLogger(__name__)

# 공지 URL
_UPBIT_NOTICE_URL = "https://upbit.com/service_center/notice"
_BITHUMB_NOTICE_URL = "https://feed.bithumb.com/notice"

# HTTP 설정
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15)
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

# 상장 키워드
_LISTING_KEYWORDS = [
    "마켓 추가",
    "신규 상장",
    "마켓 오픈",
    "원화 마켓",
    "신규 거래",
    "디지털 자산 추가",
    "거래 지원",
    "거래지원",
]

# 제외할 단어 (심볼 오탐 방지) - BTC/ETH는 상장 대상이 될 수 있으므로 포함
_EXCLUDE_SYMBOLS = frozenset({
    "KRW", "USD", "API", "FAQ", "APP", "THE", "FOR", "AND", "NEW", "VIP",
    "PRO", "AMA", "IEO", "ICO", "IDO", "NFT", "APY", "APR",
})

# 심볼 추출 패턴
_SYMBOL_PATTERNS = [
    re.compile(r"\(([A-Z]{2,10})\)"),         # (BTC)
    re.compile(r"([A-Z]{2,10})/KRW"),          # BTC/KRW
    re.compile(r"([A-Z]{2,10})_KRW"),          # BTC_KRW
    re.compile(r"([A-Z]{2,10})\s*원화"),       # BTC 원화
]

# 시간 추출 패턴
_TIME_PATTERNS = [
    re.compile(r"오후\s*(\d{1,2})시(?:\s*(\d{1,2})분)?"),
    re.compile(r"오전\s*(\d{1,2})시(?:\s*(\d{1,2})분)?"),
    re.compile(r"(\d{1,2}):(\d{2})"),
]


@dataclass
class ListingNotice:
    """상장 공지 정보."""
    notice_id: str
    title: str
    url: str
    exchange: str  # "upbit" | "bithumb"
    symbols: list[str] = field(default_factory=list)
    listing_time: str | None = None  # "2024-01-15 14:00:00" 형식
    detected_at: str = field(default_factory=lambda: datetime.now(
        tz=timezone(timedelta(hours=9))
    ).isoformat())

    def to_dict(self) -> dict:
        """딕셔너리 변환."""
        return asdict(self)


@dataclass
class MonitorState:
    """모니터링 상태 (영속성)."""
    last_upbit_ids: set[str] = field(default_factory=set)
    last_bithumb_ids: set[str] = field(default_factory=set)
    last_check_time: str | None = None

    def to_dict(self) -> dict:
        return {
            "last_upbit_ids": list(self.last_upbit_ids),
            "last_bithumb_ids": list(self.last_bithumb_ids),
            "last_check_time": self.last_check_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MonitorState":
        return cls(
            last_upbit_ids=set(data.get("last_upbit_ids", [])),
            last_bithumb_ids=set(data.get("last_bithumb_ids", [])),
            last_check_time=data.get("last_check_time"),
        )


class ListingMonitor:
    """상장 공지 모니터.

    업비트/빗썸 공지 페이지를 주기적으로 확인하여 신규 상장 감지.
    CloudScraper 사용 시 CloudFlare 우회.

    Args:
        on_listing: 상장 감지 시 호출할 콜백 (async).
        poll_interval: 폴링 간격 (초). 기본 30초.
        state_file: 상태 저장 파일 경로. None이면 저장 안 함.
    """

    def __init__(
        self,
        on_listing: Callable[[ListingNotice], Awaitable[None]] | None = None,
        poll_interval: float = 30.0,
        state_file: str | Path | None = None,
    ) -> None:
        self._on_listing = on_listing
        self._poll_interval = poll_interval
        self._state_file = Path(state_file) if state_file else None
        self._state = MonitorState()
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._session: aiohttp.ClientSession | None = None
        self._scraper = None
        self._baseline_set = False

        # CloudScraper 초기화
        if _HAS_CLOUDSCRAPER:
            try:
                self._scraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False}
                )
                logger.info("[ListingMonitor] CloudScraper 초기화 성공")
            except Exception as e:
                logger.warning("[ListingMonitor] CloudScraper 초기화 실패: %s", e)
        else:
            logger.warning(
                "[ListingMonitor] cloudscraper 미설치. pip install cloudscraper 권장"
            )

        # 상태 로드
        self._load_state()

    def _load_state(self) -> None:
        """저장된 상태 로드."""
        if not self._state_file or not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            self._state = MonitorState.from_dict(data)
            logger.info(
                "[ListingMonitor] 상태 로드: upbit=%d, bithumb=%d",
                len(self._state.last_upbit_ids),
                len(self._state.last_bithumb_ids),
            )
        except Exception as e:
            logger.warning("[ListingMonitor] 상태 로드 실패: %s", e)

    def _save_state(self) -> None:
        """상태 저장."""
        if not self._state_file:
            return
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(
                json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("[ListingMonitor] 상태 저장 실패: %s", e)

    async def run(self, stop_event: asyncio.Event) -> None:
        """메인 실행 루프."""
        async with aiohttp.ClientSession(
            timeout=_HTTP_TIMEOUT,
            headers=_HTTP_HEADERS,
        ) as session:
            self._session = session

            # 첫 실행: 베이스라인 설정
            await self._set_baseline()

            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self._poll_interval,
                    )
                    break
                except asyncio.TimeoutError:
                    pass

                try:
                    await self._check_and_notify()
                except Exception as e:
                    logger.error("[ListingMonitor] 체크 에러: %s", e)

    async def check_once(self) -> list[ListingNotice]:
        """단일 체크 (테스트/수동 실행용).

        Returns:
            감지된 신규 상장 공지 목록.
        """
        async with aiohttp.ClientSession(
            timeout=_HTTP_TIMEOUT,
            headers=_HTTP_HEADERS,
        ) as session:
            self._session = session

            if not self._baseline_set:
                await self._set_baseline()

            return await self._check_and_notify()

    async def _set_baseline(self) -> None:
        """현재 공지 목록을 베이스라인으로 설정."""
        try:
            upbit_notices = await self._fetch_upbit()
            bithumb_notices = await self._fetch_bithumb()

            self._state.last_upbit_ids = {n.notice_id for n in upbit_notices}
            self._state.last_bithumb_ids = {n.notice_id for n in bithumb_notices}
            self._baseline_set = True

            logger.info(
                "[ListingMonitor] 베이스라인 설정: upbit=%d, bithumb=%d",
                len(self._state.last_upbit_ids),
                len(self._state.last_bithumb_ids),
            )
            self._save_state()
        except Exception as e:
            logger.warning("[ListingMonitor] 베이스라인 설정 실패: %s", e)

    async def _check_and_notify(self) -> list[ListingNotice]:
        """공지 체크 및 콜백 호출."""
        new_listings: list[ListingNotice] = []

        # 업비트 체크
        try:
            upbit_notices = await self._fetch_upbit()
            for notice in upbit_notices:
                if notice.notice_id in self._state.last_upbit_ids:
                    continue

                self._state.last_upbit_ids.add(notice.notice_id)
                logger.info("[ListingMonitor] 업비트 신규: %s", notice.title[:50])

                # 상장 공지인지 확인
                if self._is_listing_notice(notice.title):
                    listing = self._parse_listing(notice, "upbit")
                    if listing.symbols:
                        new_listings.append(listing)
                        logger.critical(
                            "[ListingMonitor] 업비트 상장 감지! %s",
                            listing.symbols,
                        )
                        if self._on_listing:
                            await self._on_listing(listing)
        except Exception as e:
            logger.warning("[ListingMonitor] 업비트 체크 에러: %s", e)

        # 빗썸 체크
        try:
            bithumb_notices = await self._fetch_bithumb()
            for notice in bithumb_notices:
                if notice.notice_id in self._state.last_bithumb_ids:
                    continue

                self._state.last_bithumb_ids.add(notice.notice_id)
                logger.info("[ListingMonitor] 빗썸 신규: %s", notice.title[:50])

                if self._is_listing_notice(notice.title):
                    listing = self._parse_listing(notice, "bithumb")
                    if listing.symbols:
                        new_listings.append(listing)
                        logger.critical(
                            "[ListingMonitor] 빗썸 상장 감지! %s",
                            listing.symbols,
                        )
                        if self._on_listing:
                            await self._on_listing(listing)
        except Exception as e:
            logger.warning("[ListingMonitor] 빗썸 체크 에러: %s", e)

        # 상태 업데이트
        self._state.last_check_time = datetime.now(
            tz=timezone(timedelta(hours=9))
        ).isoformat()
        self._save_state()

        return new_listings

    # -------------------------------------------------------------------------
    # 업비트 크롤링
    # -------------------------------------------------------------------------

    async def _fetch_upbit(self) -> list[ListingNotice]:
        """업비트 공지 목록 조회.

        Note: 업비트는 JavaScript 렌더링이 필요해 제한적.
              완전한 크롤링은 notice_fetcher.py의 Playwright 사용 권장.
        """
        # 방법 1: CloudScraper로 시도
        if self._scraper:
            loop = asyncio.get_event_loop()
            try:
                html = await loop.run_in_executor(
                    self._executor,
                    self._fetch_sync,
                    _UPBIT_NOTICE_URL,
                )
                if html:
                    return self._parse_upbit_html(html)
            except Exception as e:
                logger.warning("[ListingMonitor] 업비트 CloudScraper 실패: %s", e)

        # 방법 2: aiohttp (대부분 실패할 것임)
        if self._session:
            try:
                async with self._session.get(_UPBIT_NOTICE_URL) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        return self._parse_upbit_html(html)
            except Exception as e:
                logger.debug("[ListingMonitor] 업비트 aiohttp 실패: %s", e)

        return []

    def _parse_upbit_html(self, html: str) -> list[ListingNotice]:
        """업비트 HTML 파싱."""
        notices = []
        seen_ids = set()

        # notice?id=XXXX 패턴으로 공지 ID 추출
        link_pattern = re.compile(
            r'service_center/notice\?id=(\d+)[^>]*>([^<]*(?:<[^/a][^>]*>[^<]*)*)</a>',
            re.IGNORECASE | re.DOTALL,
        )

        for match in link_pattern.finditer(html):
            notice_id = match.group(1)
            if notice_id in seen_ids:
                continue
            seen_ids.add(notice_id)

            # 제목 추출 (HTML 태그 제거)
            inner = match.group(2)
            title = re.sub(r'<[^>]+>', '', inner).strip()

            if not title or len(title) < 3:
                continue

            notices.append(ListingNotice(
                notice_id=notice_id,
                title=title[:200],
                url=f"https://upbit.com/service_center/notice?id={notice_id}",
                exchange="upbit",
            ))

        # ID만 있는 경우
        if not notices:
            id_pattern = re.compile(r'notice\?id=(\d+)')
            for notice_id in id_pattern.findall(html)[:20]:
                if notice_id not in seen_ids:
                    seen_ids.add(notice_id)
                    notices.append(ListingNotice(
                        notice_id=notice_id,
                        title=f"업비트 공지 #{notice_id}",
                        url=f"https://upbit.com/service_center/notice?id={notice_id}",
                        exchange="upbit",
                    ))

        return notices[:20]

    # -------------------------------------------------------------------------
    # 빗썸 크롤링
    # -------------------------------------------------------------------------

    async def _fetch_bithumb(self) -> list[ListingNotice]:
        """빗썸 공지 목록 조회."""
        html = None

        # CloudScraper 사용 (CloudFlare 우회)
        if self._scraper:
            loop = asyncio.get_event_loop()
            try:
                html = await loop.run_in_executor(
                    self._executor,
                    self._fetch_sync,
                    _BITHUMB_NOTICE_URL,
                )
            except Exception as e:
                logger.warning("[ListingMonitor] 빗썸 CloudScraper 실패: %s", e)

        # Fallback: aiohttp (CloudFlare 차단될 가능성 높음)
        if not html and self._session:
            try:
                async with self._session.get(_BITHUMB_NOTICE_URL) as resp:
                    if resp.status == 200:
                        html = await resp.text()
            except Exception as e:
                logger.debug("[ListingMonitor] 빗썸 aiohttp 실패: %s", e)

        if not html:
            return []

        return self._parse_bithumb_html(html)

    def _parse_bithumb_html(self, html: str) -> list[ListingNotice]:
        """빗썸 HTML 파싱."""
        notices = []

        # __NEXT_DATA__ JSON (Next.js)
        next_data_match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>([^<]+)</script>',
            html,
        )
        if next_data_match:
            try:
                data = json.loads(next_data_match.group(1))
                notice_list = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("noticeList", [])
                )
                if not notice_list:
                    notice_list = (
                        data.get("props", {})
                        .get("pageProps", {})
                        .get("notices", [])
                    )

                for item in notice_list[:20]:
                    notices.append(ListingNotice(
                        notice_id=str(item.get("id", "")),
                        title=item.get("title", ""),
                        url=f"https://feed.bithumb.com/notice/{item.get('id')}",
                        exchange="bithumb",
                    ))

                if notices:
                    return notices
            except json.JSONDecodeError:
                pass

        # HTML 패턴 매칭
        pattern = re.compile(r'href="[/]?notice/(\d+)"[^>]*>([^<]+)</a>', re.IGNORECASE)
        for notice_id, title in pattern.findall(html):
            notices.append(ListingNotice(
                notice_id=notice_id,
                title=title.strip(),
                url=f"https://feed.bithumb.com/notice/{notice_id}",
                exchange="bithumb",
            ))

        # JSON 패턴 (인라인)
        if not notices:
            json_pattern = re.compile(r'"id":(\d+),"title":"([^"]+)"')
            for notice_id, title in json_pattern.findall(html):
                notices.append(ListingNotice(
                    notice_id=notice_id,
                    title=title.strip(),
                    url=f"https://feed.bithumb.com/notice/{notice_id}",
                    exchange="bithumb",
                ))

        return notices[:20]

    def _fetch_sync(self, url: str) -> str | None:
        """동기 fetch (ThreadPoolExecutor용)."""
        if not self._scraper:
            return None
        try:
            resp = self._scraper.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.text
            logger.warning("[ListingMonitor] HTTP %d: %s", resp.status_code, url)
        except Exception as e:
            logger.warning("[ListingMonitor] fetch 에러: %s", e)
        return None

    # -------------------------------------------------------------------------
    # 파싱 유틸
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_listing_notice(title: str) -> bool:
        """상장 관련 공지인지 확인."""
        return any(kw in title for kw in _LISTING_KEYWORDS)

    def _parse_listing(self, notice: ListingNotice, exchange: str) -> ListingNotice:
        """상장 공지에서 심볼/시간 추출."""
        symbols = self._extract_symbols(notice.title)
        listing_time = self._extract_time(notice.title)

        return ListingNotice(
            notice_id=notice.notice_id,
            title=notice.title,
            url=notice.url,
            exchange=exchange,
            symbols=symbols,
            listing_time=listing_time,
        )

    @staticmethod
    def _extract_symbols(text: str) -> list[str]:
        """텍스트에서 심볼 추출."""
        symbols = []
        seen = set()

        for pattern in _SYMBOL_PATTERNS:
            for match in pattern.findall(text):
                symbol = match.upper()
                if symbol not in seen and symbol not in _EXCLUDE_SYMBOLS:
                    seen.add(symbol)
                    symbols.append(symbol)

        return symbols

    @staticmethod
    def _extract_time(text: str) -> str | None:
        """텍스트에서 시간 추출 → "YYYY-MM-DD HH:MM:SS" 형식."""
        today = datetime.now(tz=timezone(timedelta(hours=9))).strftime("%Y-%m-%d")

        # 오후 N시
        pm_match = _TIME_PATTERNS[0].search(text)
        if pm_match:
            hour = int(pm_match.group(1))
            minute = int(pm_match.group(2) or 0)
            if hour < 12:
                hour += 12
            return f"{today} {hour:02d}:{minute:02d}:00"

        # 오전 N시
        am_match = _TIME_PATTERNS[1].search(text)
        if am_match:
            hour = int(am_match.group(1))
            minute = int(am_match.group(2) or 0)
            return f"{today} {hour:02d}:{minute:02d}:00"

        # HH:MM
        hm_match = _TIME_PATTERNS[2].search(text)
        if hm_match:
            hour = int(hm_match.group(1))
            minute = int(hm_match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{today} {hour:02d}:{minute:02d}:00"

        return None


# =============================================================================
# 테스트 코드
# =============================================================================

async def _test_parsing():
    """파싱 테스트."""
    print("=" * 60)
    print("파싱 테스트")
    print("=" * 60)

    monitor = ListingMonitor()

    test_titles = [
        "[마켓 추가] 비트코인(BTC) 원화 마켓 추가",
        "[신규 상장] 이더리움(ETH), 리플(XRP) 마켓 오픈 안내",
        "[거래] 신규 거래지원 안내 - 솔라나(SOL)",
        "도지코인(DOGE) 원화 마켓 오픈 예정 (오후 2시 30분)",
        "[공지] 서버 점검 안내",  # 상장 아님
        "BTC/KRW, ETH/KRW 마켓 추가 안내",
    ]

    for title in test_titles:
        is_listing = monitor._is_listing_notice(title)
        symbols = monitor._extract_symbols(title)
        time_str = monitor._extract_time(title)

        print(f"\n제목: {title}")
        print(f"  상장공지: {is_listing}")
        print(f"  심볼: {symbols}")
        print(f"  시간: {time_str}")


async def _test_fetch():
    """실제 크롤링 테스트."""
    print("\n" + "=" * 60)
    print("크롤링 테스트")
    print("=" * 60)

    monitor = ListingMonitor(state_file=None)

    async with aiohttp.ClientSession(
        timeout=_HTTP_TIMEOUT,
        headers=_HTTP_HEADERS,
    ) as session:
        monitor._session = session

        # 업비트
        print("\n[업비트 공지]")
        try:
            upbit_notices = await monitor._fetch_upbit()
            print(f"  총 {len(upbit_notices)}개 공지")
            for notice in upbit_notices[:5]:
                print(f"  - {notice.title[:50]}...")
                if monitor._is_listing_notice(notice.title):
                    symbols = monitor._extract_symbols(notice.title)
                    print(f"    → 상장공지! 심볼: {symbols}")
        except Exception as e:
            print(f"  에러: {e}")

        # 빗썸
        print("\n[빗썸 공지]")
        try:
            bithumb_notices = await monitor._fetch_bithumb()
            print(f"  총 {len(bithumb_notices)}개 공지")
            for notice in bithumb_notices[:5]:
                print(f"  - {notice.title[:50]}...")
                if monitor._is_listing_notice(notice.title):
                    symbols = monitor._extract_symbols(notice.title)
                    print(f"    → 상장공지! 심볼: {symbols}")
        except Exception as e:
            print(f"  에러: {e}")


async def _test_callback():
    """콜백 테스트."""
    print("\n" + "=" * 60)
    print("콜백 테스트")
    print("=" * 60)

    detected = []

    async def on_listing(listing: ListingNotice):
        detected.append(listing)
        print(f"  [콜백 호출] {listing.exchange}: {listing.symbols}")

    monitor = ListingMonitor(on_listing=on_listing, state_file=None)

    # 첫 체크 (베이스라인)
    print("\n첫 번째 체크 (베이스라인 설정)...")
    listings = await monitor.check_once()
    print(f"  감지된 상장: {len(listings)}개")

    # 두 번째 체크 (변화 없음)
    print("\n두 번째 체크 (변화 없어야 함)...")
    listings = await monitor.check_once()
    print(f"  감지된 상장: {len(listings)}개")

    print(f"\n총 콜백 호출: {len(detected)}회")


async def _test_state_persistence():
    """상태 저장/로드 테스트."""
    print("\n" + "=" * 60)
    print("상태 저장/로드 테스트")
    print("=" * 60)

    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        state_file = f.name

    try:
        # 첫 번째 인스턴스: 상태 저장
        monitor1 = ListingMonitor(state_file=state_file)
        monitor1._state.last_upbit_ids = {"123", "456"}
        monitor1._state.last_bithumb_ids = {"789"}
        monitor1._save_state()
        print(f"  저장: upbit={monitor1._state.last_upbit_ids}")

        # 두 번째 인스턴스: 상태 로드
        monitor2 = ListingMonitor(state_file=state_file)
        print(f"  로드: upbit={monitor2._state.last_upbit_ids}")

        assert monitor2._state.last_upbit_ids == {"123", "456"}
        assert monitor2._state.last_bithumb_ids == {"789"}
        print("  [OK] 상태 저장/로드 성공")

    finally:
        Path(state_file).unlink(missing_ok=True)


async def main():
    """전체 테스트 실행."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    await _test_parsing()
    await _test_state_persistence()
    await _test_fetch()
    await _test_callback()

    print("\n" + "=" * 60)
    print("모든 테스트 완료!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
