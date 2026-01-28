"""빗썸 공지사항 텍스트에서 상장 심볼/시간 추출.

순수 로직 (I/O 없음) — 단위 테스트 용이.
Phase 7에서 WARNING/HALT/MIGRATION/DEPEG 패턴 추가 예정.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


@dataclass
class NoticeParseResult:
    """공지 파싱 결과."""
    symbol: str | None           # "BTC", "ETH" 등 (추출 실패 시 None)
    listing_time: str | None     # "2024-01-15 14:00:00" (추출 실패 시 None)
    notice_type: str             # "listing", "unknown"
    raw_title: str               # 원본 제목


class BithumbNoticeParser:
    """빗썸 공지사항 파싱 엔진.

    정규식 다중 패턴으로 심볼 + 상장 시간 추출.
    Phase 7에서 이벤트 아비트라지 패턴 확장 가능하도록 패턴 리스트 구조.
    """

    # 상장 관련 키워드 (제목 필터링)
    LISTING_KEYWORDS: list[str] = [
        "마켓 추가",
        "신규 상장",
        "마켓 오픈",
        "신규",
        "상장",
    ]

    # 상장 공지 제목에서 심볼 추출 패턴 (우선순위 순)
    LISTING_PATTERNS: list[re.Pattern[str]] = [
        # "[마켓 추가] 비트코인(BTC) 원화 마켓 추가"
        re.compile(r"\(([A-Z]{2,10})\)"),
        # "BTC/KRW 마켓 추가"
        re.compile(r"([A-Z]{2,10})/KRW"),
        # "BTC 원화 마켓"
        re.compile(r"([A-Z]{2,10})\s*원화"),
        # "BTC_KRW 마켓 추가"
        re.compile(r"([A-Z]{2,10})_KRW"),
    ]

    # 상장 시간 추출 패턴
    TIME_PATTERNS: list[re.Pattern[str]] = [
        # "14:00", "15:30"
        re.compile(r"(\d{1,2}):(\d{2})"),
        # "오후 2시 30분"
        re.compile(r"오후\s*(\d{1,2})시(?:\s*(\d{1,2})분)?"),
        # "오전 11시 30분"
        re.compile(r"오전\s*(\d{1,2})시(?:\s*(\d{1,2})분)?"),
    ]

    def parse(self, title: str, content: str = "") -> NoticeParseResult:
        """공지 제목/본문에서 상장 정보 추출.

        Args:
            title: 공지 제목.
            content: 공지 본문 (선택적).

        Returns:
            NoticeParseResult.
        """
        if not self.is_listing_notice(title):
            return NoticeParseResult(
                symbol=None,
                listing_time=None,
                notice_type="unknown",
                raw_title=title,
            )

        # 심볼 추출 (제목 → 본문 순서)
        symbol = self._extract_symbol(title)
        if symbol is None and content:
            symbol = self._extract_symbol(content)

        # 시간 추출 (본문 → 제목 순서)
        listing_time = None
        if content:
            listing_time = self._extract_time(content)
        if listing_time is None:
            listing_time = self._extract_time(title)

        # 날짜 + 시간 결합 (날짜가 없으면 오늘)
        full_time = None
        if listing_time:
            today = datetime.now(
                tz=timezone(timedelta(hours=9))  # KST
            ).strftime("%Y-%m-%d")
            full_time = f"{today} {listing_time}"

        return NoticeParseResult(
            symbol=symbol,
            listing_time=full_time,
            notice_type="listing",
            raw_title=title,
        )

    def is_listing_notice(self, title: str) -> bool:
        """상장 관련 공지인지 빠르게 판단."""
        return any(kw in title for kw in self.LISTING_KEYWORDS)

    def _extract_symbol(self, text: str) -> str | None:
        """텍스트에서 심볼 추출. 첫 매칭 반환."""
        for pattern in self.LISTING_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1)
        return None

    def _extract_time(self, text: str) -> str | None:
        """텍스트에서 상장 시간 추출 → "HH:MM:SS" 형식 (KST).

        Returns:
            "14:00:00" 형식 또는 None.
        """
        # "오후 N시" 패턴 먼저 시도
        pm_match = self.TIME_PATTERNS[1].search(text)
        if pm_match:
            hour = int(pm_match.group(1))
            minute = int(pm_match.group(2) or 0)
            if hour < 12:
                hour += 12
            return f"{hour:02d}:{minute:02d}:00"

        # "오전 N시" 패턴
        am_match = self.TIME_PATTERNS[2].search(text)
        if am_match:
            hour = int(am_match.group(1))
            minute = int(am_match.group(2) or 0)
            return f"{hour:02d}:{minute:02d}:00"

        # "HH:MM" 패턴 (마지막 — 가장 일반적이라 오탐 가능)
        hm_match = self.TIME_PATTERNS[0].search(text)
        if hm_match:
            hour = int(hm_match.group(1))
            minute = int(hm_match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}:00"

        return None
