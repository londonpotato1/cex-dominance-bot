"""공지사항 크롤러 (업비트 + 빗썸).

주기적으로 공지 페이지를 폴링하여 신규 상장 감지.
MarketMonitor와 연동하여 마켓 오픈 전 pre-detection.

CloudFlare 우회를 위해 cloudscraper 사용 (설치 필요: pip install cloudscraper)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor

# cloudscraper 선택적 import (CloudFlare 우회)
try:
    import cloudscraper
    _HAS_CLOUDSCRAPER = True
except ImportError:
    _HAS_CLOUDSCRAPER = False
    cloudscraper = None

# Playwright 선택적 import (JavaScript 렌더링)
# Railway/Docker에서 브라우저 바이너리 없으면 import 자체가 실패할 수 있음
try:
    from playwright.async_api import async_playwright, Browser
    _HAS_PLAYWRIGHT = True
except Exception as _pw_err:
    _HAS_PLAYWRIGHT = False
    async_playwright = None  # type: ignore[assignment]
    Browser = None  # type: ignore[assignment,misc]
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "[NoticeFetcher] Playwright import 실패 (업비트 공지 비활성): %s", _pw_err
    )

import aiohttp

from collectors.notice_parser import (
    NoticeParseResult,
    UnifiedNoticeParser,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# 공지 페이지 URL
_UPBIT_NOTICE_URL = "https://upbit.com/service_center/notice"
_BITHUMB_NOTICE_URL = "https://feed.bithumb.com/notice"
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)

# 봇 차단 우회용 헤더
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.google.com/",
}


@dataclass
class RawNotice:
    """원시 공지 데이터."""
    notice_id: str
    title: str
    url: str
    exchange: str
    created_at: str | None = None


class NoticeFetcher:
    """공지 크롤러.

    - 업비트: HTML 스크래핑 (CloudFlare 우회 필요)
    - 빗썸: HTML 스크래핑 (CloudFlare 우회 필요)

    cloudscraper 설치 시 CloudFlare 자동 우회.
    중복 방지를 위해 이미 처리한 notice_id 추적.
    """

    def __init__(
        self,
        on_listing: callable | None = None,
        upbit_interval: float = 30.0,
        bithumb_interval: float = 30.0,
    ) -> None:
        """
        Args:
            on_listing: 상장 감지 시 호출할 콜백 (NoticeParseResult).
            upbit_interval: 업비트 폴링 간격 (초).
            bithumb_interval: 빗썸 폴링 간격 (초).
        """
        self._on_listing = on_listing
        self._upbit_interval = upbit_interval
        self._bithumb_interval = bithumb_interval
        self._parser = UnifiedNoticeParser()
        self._session: aiohttp.ClientSession | None = None
        self._executor = ThreadPoolExecutor(max_workers=2)

        # CloudScraper 인스턴스 (CloudFlare 우회 - 빗썸용)
        self._scraper = None
        if _HAS_CLOUDSCRAPER:
            try:
                self._scraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False}
                )
                logger.info("[NoticeFetcher] CloudScraper 초기화 성공")
            except Exception as e:
                logger.warning("[NoticeFetcher] CloudScraper 초기화 실패: %s", e)
        else:
            logger.warning(
                "[NoticeFetcher] cloudscraper 미설치 - 빗썸 공지 크롤링 제한. "
                "설치: pip install cloudscraper"
            )

        # Playwright 브라우저 (JavaScript 렌더링 - 업비트용)
        self._playwright = None
        self._browser: Browser | None = None
        self._has_playwright = _HAS_PLAYWRIGHT
        if not _HAS_PLAYWRIGHT:
            logger.warning(
                "[NoticeFetcher] playwright 미설치 - 업비트 공지 크롤링 불가. "
                "설치: pip install playwright && playwright install chromium"
            )

        # 이미 처리한 공지 ID (중복 방지)
        self._seen_upbit: set[str] = set()
        self._seen_bithumb: set[str] = set()
        self._baseline_set_upbit = False
        self._baseline_set_bithumb = False

    async def run(self, stop_event: asyncio.Event) -> None:
        """메인 실행: 업비트 + 빗썸 공지 폴링 병렬 실행."""
        # Playwright 브라우저 초기화 (업비트용)
        if self._has_playwright:
            try:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                logger.info("[NoticeFetcher] Playwright 브라우저 초기화 성공")
            except Exception as e:
                logger.warning("[NoticeFetcher] Playwright 초기화 실패: %s", e)
                self._browser = None

        try:
            async with aiohttp.ClientSession(
                timeout=_HTTP_TIMEOUT,
                headers=_HTTP_HEADERS,
            ) as session:
                self._session = session
                await asyncio.gather(
                    self._upbit_loop(stop_event),
                    self._bithumb_loop(stop_event),
                    return_exceptions=True,
                )
        finally:
            # Playwright 브라우저 종료
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            logger.info("[NoticeFetcher] 브라우저 종료 완료")

    # ------------------------------------------------------------------
    # 업비트 공지 폴링
    # ------------------------------------------------------------------

    async def _upbit_loop(self, stop_event: asyncio.Event) -> None:
        """업비트 공지 폴링 루프 (Playwright 사용)."""
        # Playwright 없으면 비활성화
        if not self._browser:
            logger.warning(
                "[NoticeFetcher] 업비트 공지 폴링 비활성화 (Playwright 없음). "
                "설치: pip install playwright && playwright install chromium"
            )
            await stop_event.wait()
            return

        # 초기 공지 목록 로드 (베이스라인)
        try:
            notices = await self._fetch_upbit_notices()
            self._seen_upbit = {n.notice_id for n in notices}
            self._baseline_set_upbit = True
            logger.info(
                "[NoticeFetcher] 업비트 초기 공지 로드: %d개",
                len(self._seen_upbit),
            )
        except Exception as e:
            logger.warning("[NoticeFetcher] 업비트 초기 로드 실패: %s", e)

        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._upbit_interval
                )
                break
            except asyncio.TimeoutError:
                pass

            try:
                notices = await self._fetch_upbit_notices()

                if not self._baseline_set_upbit:
                    self._seen_upbit = {n.notice_id for n in notices}
                    self._baseline_set_upbit = True
                    logger.info(
                        "[NoticeFetcher] 업비트 베이스라인 설정: %d개",
                        len(self._seen_upbit),
                    )
                    continue

                # 신규 공지 확인
                for notice in notices:
                    if notice.notice_id in self._seen_upbit:
                        continue

                    self._seen_upbit.add(notice.notice_id)
                    logger.info(
                        "[NoticeFetcher] 업비트 신규 공지: %s",
                        notice.title[:50],
                    )

                    # 상장 공지 파싱
                    result = self._parser.parse(
                        title=notice.title,
                        exchange="upbit",
                        notice_id=notice.notice_id,
                        notice_url=notice.url,
                    )

                    if result.notice_type == "listing" and result.symbols:
                        logger.critical(
                            "[NoticeFetcher] 업비트 상장 감지! 심볼: %s",
                            result.symbols,
                        )
                        if self._on_listing:
                            await self._on_listing(result)

            except Exception as e:
                logger.warning("[NoticeFetcher] 업비트 폴링 에러: %s", e)

    async def _fetch_upbit_notices(self) -> list[RawNotice]:
        """업비트 공지 목록 조회 (Playwright 사용 - JavaScript 렌더링)."""
        if not self._browser:
            return []

        url = _UPBIT_NOTICE_URL

        try:
            page = await self._browser.new_page()
            try:
                # 페이지 로드 (네트워크 요청 완료까지 대기)
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # 공지 목록이 렌더링될 때까지 잠시 대기
                await page.wait_for_timeout(2000)

                # HTML 가져오기
                html = await page.content()

                return self._parse_upbit_html(html)
            finally:
                await page.close()
        except Exception as e:
            logger.warning("[NoticeFetcher] 업비트 Playwright 실패: %s", e)
            return []

    def _parse_upbit_html(self, html: str) -> list[RawNotice]:
        """업비트 HTML에서 공지 목록 파싱 (Playwright 렌더링 후)."""
        notices = []
        seen_ids = set()

        # 방법 1: 공지 링크 + 근처 텍스트에서 제목 추출
        # <a href="/service_center/notice?id=5961">...</a> 패턴
        link_pattern = re.compile(
            r'<a[^>]*href="[/]?service_center/notice\?id=(\d+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in link_pattern.finditer(html):
            notice_id = match.group(1)
            if notice_id in seen_ids:
                continue
            seen_ids.add(notice_id)

            # 링크 내부 텍스트에서 제목 추출 (HTML 태그 제거)
            inner_html = match.group(2)
            title = re.sub(r'<[^>]+>', '', inner_html).strip()

            # 제목이 비어있으면 주변에서 찾기
            if not title or len(title) < 3:
                # 링크 이후 200자 내에서 텍스트 찾기
                start_pos = match.end()
                nearby = html[start_pos:start_pos + 500]
                # 첫 번째 의미있는 텍스트
                text_match = re.search(r'>([^<]{10,100})<', nearby)
                if text_match:
                    title = text_match.group(1).strip()

            if title and len(title) >= 3:
                notices.append(
                    RawNotice(
                        notice_id=notice_id,
                        title=title[:200],  # 제목 길이 제한
                        url=f"https://upbit.com/service_center/notice?id={notice_id}",
                        exchange="upbit",
                    )
                )

        # 방법 2: notice?id=만 있고 제목은 별도 위치에 있는 경우
        if not notices:
            id_pattern = re.compile(r'notice\?id=(\d+)')
            found_ids = id_pattern.findall(html)
            unique_ids = list(dict.fromkeys(found_ids))  # 중복 제거, 순서 유지

            for notice_id in unique_ids[:20]:
                if notice_id in seen_ids:
                    continue
                seen_ids.add(notice_id)
                notices.append(
                    RawNotice(
                        notice_id=notice_id,
                        title=f"업비트 공지 #{notice_id}",  # 제목 미확인
                        url=f"https://upbit.com/service_center/notice?id={notice_id}",
                        exchange="upbit",
                    )
                )

        return notices[:20]

    # ------------------------------------------------------------------
    # 빗썸 공지 폴링
    # ------------------------------------------------------------------

    async def _bithumb_loop(self, stop_event: asyncio.Event) -> None:
        """빗썸 공지 폴링 루프."""
        # 초기 공지 목록 로드 (베이스라인)
        try:
            notices = await self._fetch_bithumb_notices()
            self._seen_bithumb = {n.notice_id for n in notices}
            self._baseline_set_bithumb = True
            logger.info(
                "[NoticeFetcher] 빗썸 초기 공지 로드: %d개",
                len(self._seen_bithumb),
            )
        except Exception as e:
            logger.warning("[NoticeFetcher] 빗썸 초기 로드 실패: %s", e)

        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._bithumb_interval
                )
                break
            except asyncio.TimeoutError:
                pass

            try:
                notices = await self._fetch_bithumb_notices()

                if not self._baseline_set_bithumb:
                    self._seen_bithumb = {n.notice_id for n in notices}
                    self._baseline_set_bithumb = True
                    logger.info(
                        "[NoticeFetcher] 빗썸 베이스라인 설정: %d개",
                        len(self._seen_bithumb),
                    )
                    continue

                # 신규 공지 확인
                for notice in notices:
                    if notice.notice_id in self._seen_bithumb:
                        continue

                    self._seen_bithumb.add(notice.notice_id)
                    logger.info(
                        "[NoticeFetcher] 빗썸 신규 공지: %s",
                        notice.title[:50],
                    )

                    # 상장 공지 파싱
                    result = self._parser.parse(
                        title=notice.title,
                        exchange="bithumb",
                        notice_id=notice.notice_id,
                        notice_url=notice.url,
                    )

                    if result.notice_type == "listing" and result.symbols:
                        logger.critical(
                            "[NoticeFetcher] 빗썸 상장 감지! 심볼: %s",
                            result.symbols,
                        )
                        if self._on_listing:
                            await self._on_listing(result)

            except Exception as e:
                logger.warning("[NoticeFetcher] 빗썸 폴링 에러: %s", e)

    async def _fetch_bithumb_notices(self) -> list[RawNotice]:
        """빗썸 공지 목록 조회 (CloudScraper 사용)."""
        url = _BITHUMB_NOTICE_URL

        # CloudScraper 사용 (CloudFlare 우회)
        if self._scraper:
            loop = asyncio.get_event_loop()
            try:
                html = await loop.run_in_executor(
                    self._executor,
                    self._fetch_with_cloudscraper,
                    url,
                )
            except Exception as e:
                logger.warning("[NoticeFetcher] 빗썸 CloudScraper 실패: %s", e)
                html = None
        else:
            # fallback: aiohttp
            if self._session is None:
                raise RuntimeError("HTTP 세션 미초기화")
            try:
                async with self._session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning("[NoticeFetcher] 빗썸 HTTP %d", resp.status)
                        return []
                    html = await resp.text()
            except Exception as e:
                logger.warning("[NoticeFetcher] 빗썸 aiohttp 실패: %s", e)
                return []

        if not html:
            return []

        return self._parse_bithumb_html(html)

    def _fetch_with_cloudscraper(self, url: str) -> str | None:
        """CloudScraper로 동기 fetch (ThreadPoolExecutor에서 실행)."""
        try:
            resp = self._scraper.get(url, timeout=20)
            if resp.status_code == 200:
                return resp.text
            logger.warning("[NoticeFetcher] CloudScraper HTTP %d for %s", resp.status_code, url)
            return None
        except Exception as e:
            logger.warning("[NoticeFetcher] CloudScraper 에러: %s", e)
            return None

    def _parse_bithumb_html(self, html: str) -> list[RawNotice]:
        """빗썸 HTML에서 공지 목록 파싱."""
        notices = []

        # 방법 1: __NEXT_DATA__ JSON (Next.js 앱)
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
                    notices.append(
                        RawNotice(
                            notice_id=str(item.get("id", "")),
                            title=item.get("title", ""),
                            url=f"https://feed.bithumb.com/notice/{item.get('id')}",
                            exchange="bithumb",
                            created_at=item.get("createdAt"),
                        )
                    )
                if notices:
                    return notices
            except json.JSONDecodeError:
                pass

        # 방법 2: HTML 패턴 매칭
        pattern = re.compile(
            r'href="[/]?notice/(\d+)"[^>]*>([^<]+)</a>',
            re.IGNORECASE,
        )
        for match in pattern.findall(html):
            notice_id, title = match
            notices.append(
                RawNotice(
                    notice_id=notice_id,
                    title=title.strip(),
                    url=f"https://feed.bithumb.com/notice/{notice_id}",
                    exchange="bithumb",
                )
            )

        # 방법 3: JSON 패턴 (인라인 데이터)
        if not notices:
            json_pattern = re.compile(r'"id":(\d+),"title":"([^"]+)"')
            for match in json_pattern.findall(html):
                notice_id, title = match
                notices.append(
                    RawNotice(
                        notice_id=notice_id,
                        title=title.strip(),
                        url=f"https://feed.bithumb.com/notice/{notice_id}",
                        exchange="bithumb",
                    )
                )

        return notices[:20]
