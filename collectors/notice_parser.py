"""공지사항 텍스트에서 상장 심볼/시간 추출 (업비트 + 빗썸).

순수 로직 (I/O 없음) — 단위 테스트 용이.
Phase 7: WARNING/HALT/MIGRATION/DEPEG 이벤트 아비트라지 패턴 구현.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum


class EventSeverity(Enum):
    """이벤트 심각도."""
    LOW = "low"           # 일반 공지
    MEDIUM = "medium"     # 주의 필요
    HIGH = "high"         # 긴급 대응 필요
    CRITICAL = "critical" # 즉시 조치 필요


class EventAction(Enum):
    """권장 조치."""
    NONE = "none"         # 조치 불필요
    MONITOR = "monitor"   # 모니터링
    ALERT = "alert"       # 알림만
    TRADE = "trade"       # 거래 기회


@dataclass
class NoticeParseResult:
    """공지 파싱 결과 (Phase 7 확장)."""
    symbols: list[str] = field(default_factory=list)  # ["SENT", "ELSA"] 복수 지원
    listing_time: str | None = None     # "2024-01-15 14:00:00" (추출 실패 시 None)
    notice_type: str = "unknown"        # "listing", "warning", "halt", "migration", "depeg", "unknown"
    exchange: str = "unknown"           # "upbit", "bithumb"
    raw_title: str = ""                 # 원본 제목
    notice_id: str | None = None        # 공지 고유 ID (중복 방지)
    notice_url: str | None = None       # 공지 URL

    # Phase 7: 이벤트 아비트라지 필드
    event_severity: EventSeverity = EventSeverity.LOW
    event_action: EventAction = EventAction.NONE
    event_details: dict = field(default_factory=dict)  # 추가 메타데이터

    @property
    def symbol(self) -> str | None:
        """하위 호환: 첫 번째 심볼 반환."""
        return self.symbols[0] if self.symbols else None


# 일반적인 단어 제외 (심볼 오탐 방지)
# Phase 7 수정: ETH, USDT, USDC 제거 (이벤트 대상이 될 수 있음)
_EXCLUDE_WORDS = frozenset({
    "KRW", "USD", "API", "FAQ", "APP", "THE", "FOR",
    "NFT", "APY", "APR", "NEW", "VIP", "PRO", "AMA", "IEO", "ICO", "IDO",
    # BTC도 제거 (BTC 출금 중단 이벤트 가능)
})


class BithumbNoticeParser:
    """빗썸 공지사항 파싱 엔진.

    정규식 다중 패턴으로 심볼 + 상장 시간 추출.
    Phase 7: 이벤트 아비트라지 패턴 (WARNING/HALT/MIGRATION/DEPEG) 지원.
    """

    # 상장 관련 키워드 (제목 필터링)
    LISTING_KEYWORDS: list[str] = [
        "마켓 추가",
        "신규 상장",
        "마켓 오픈",
        "신규",
        "상장",
    ]

    # Phase 7: 이벤트 아비트라지 키워드
    WARNING_KEYWORDS: list[str] = [
        "출금 중단",
        "입출금 중단",
        "입금 중단",
        "지갑 점검",
        "출금 제한",
        "입출금 제한",
        "네트워크 점검",
    ]

    HALT_KEYWORDS: list[str] = [
        "거래 중단",
        "거래 정지",
        "거래 일시 중단",
        "매매 중단",
        "매매 정지",
    ]

    MIGRATION_KEYWORDS: list[str] = [
        "스왑",
        "마이그레이션",
        "전환",
        "체인 변경",
        "토큰 전환",
        "컨트랙트 변경",
    ]

    DEPEG_KEYWORDS: list[str] = [
        "가격 급락",
        "이상 거래",
        "시세 오류",
        "가격 오류",
        "급등락",
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

    def parse(
        self,
        title: str,
        content: str = "",
        notice_id: str | None = None,
        notice_url: str | None = None,
    ) -> NoticeParseResult:
        """공지 제목/본문에서 이벤트 정보 추출 (Phase 7 확장).

        Args:
            title: 공지 제목.
            content: 공지 본문 (선택적).
            notice_id: 공지 고유 ID.
            notice_url: 공지 URL.

        Returns:
            NoticeParseResult.
        """
        # Phase 7: 이벤트 유형 분류
        notice_type, severity, action = self._classify_event(title, content)

        if notice_type == "unknown":
            return NoticeParseResult(
                notice_type="unknown",
                exchange="bithumb",
                raw_title=title,
                notice_id=notice_id,
                notice_url=notice_url,
                event_severity=severity,
                event_action=action,
            )

        # 심볼 추출 (제목 + 본문에서 모두 추출)
        symbols = self._extract_symbols(title)
        if content:
            symbols.extend(self._extract_symbols(content))

        # 중복 제거 + 순서 유지
        seen = set()
        unique_symbols = []
        for s in symbols:
            if s not in seen and s not in _EXCLUDE_WORDS:
                seen.add(s)
                unique_symbols.append(s)

        # 시간 추출 (본문 → 제목 순서)
        event_time = None
        if content:
            event_time = self._extract_time(content)
        if event_time is None:
            event_time = self._extract_time(title)

        # 날짜 + 시간 결합 (날짜가 없으면 오늘)
        full_time = None
        if event_time:
            today = datetime.now(
                tz=timezone(timedelta(hours=9))  # KST
            ).strftime("%Y-%m-%d")
            full_time = f"{today} {event_time}"

        # Phase 7: 이벤트 상세 정보
        event_details = {
            "has_time": event_time is not None,
            "symbol_count": len(unique_symbols),
        }

        return NoticeParseResult(
            symbols=unique_symbols,
            listing_time=full_time,  # 하위 호환 (event_time으로도 사용)
            notice_type=notice_type,
            exchange="bithumb",
            raw_title=title,
            notice_id=notice_id,
            notice_url=notice_url,
            event_severity=severity,
            event_action=action,
            event_details=event_details,
        )

    def is_listing_notice(self, title: str) -> bool:
        """상장 관련 공지인지 빠르게 판단."""
        return any(kw in title for kw in self.LISTING_KEYWORDS)

    def is_warning_notice(self, title: str) -> bool:
        """출금/입금 중단 경고 공지인지 판단."""
        return any(kw in title for kw in self.WARNING_KEYWORDS)

    def is_halt_notice(self, title: str) -> bool:
        """거래 중단 공지인지 판단."""
        return any(kw in title for kw in self.HALT_KEYWORDS)

    def is_migration_notice(self, title: str) -> bool:
        """체인 마이그레이션/스왑 공지인지 판단."""
        return any(kw in title for kw in self.MIGRATION_KEYWORDS)

    def is_depeg_notice(self, title: str) -> bool:
        """가격 이상/디페깅 공지인지 판단."""
        return any(kw in title for kw in self.DEPEG_KEYWORDS)

    def _classify_event(self, title: str, content: str = "") -> tuple[str, EventSeverity, EventAction]:
        """공지 유형 분류 및 심각도/조치 결정.

        Returns:
            (notice_type, severity, action)
        """
        text = title + " " + content

        # 우선순위: HALT > DEPEG > WARNING > MIGRATION > LISTING
        # Phase 7 수정: DEPEG가 MIGRATION보다 우선 (더 긴급)
        if self.is_halt_notice(title):
            # 거래 중단: HIGH severity, MONITOR action
            return "halt", EventSeverity.HIGH, EventAction.MONITOR

        if self.is_depeg_notice(title):
            # 가격 급락 → CRITICAL, 즉시 확인 필요
            return "depeg", EventSeverity.CRITICAL, EventAction.ALERT

        if self.is_warning_notice(title):
            # 출금 중단 → 프리미엄 상승 가능성 → TRADE 기회
            if "출금" in text:
                return "warning", EventSeverity.MEDIUM, EventAction.TRADE
            else:
                return "warning", EventSeverity.MEDIUM, EventAction.MONITOR

        if self.is_migration_notice(title):
            # 마이그레이션 → 스왑 기회
            return "migration", EventSeverity.MEDIUM, EventAction.ALERT

        if self.is_listing_notice(title):
            return "listing", EventSeverity.LOW, EventAction.TRADE

        return "unknown", EventSeverity.LOW, EventAction.NONE

    def _extract_symbol(self, text: str) -> str | None:
        """텍스트에서 심볼 추출. 첫 매칭 반환. (하위 호환)"""
        symbols = self._extract_symbols(text)
        return symbols[0] if symbols else None

    def _extract_symbols(self, text: str) -> list[str]:
        """텍스트에서 모든 심볼 추출. 복수 심볼 지원."""
        symbols = []
        for pattern in self.LISTING_PATTERNS:
            matches = pattern.findall(text)
            symbols.extend(matches)
        return symbols

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


class UpbitNoticeParser:
    """업비트 공지사항 파싱 엔진.

    업비트 공지 형식에 맞춘 심볼 + 상장 시간 추출.
    Phase 7: 이벤트 아비트라지 패턴 (WARNING/HALT/MIGRATION/DEPEG) 지원.
    """

    # 상장 관련 키워드 (제목 필터링)
    LISTING_KEYWORDS: list[str] = [
        "신규 거래",
        "원화 마켓",
        "마켓 디지털 자산 추가",
        "디지털 자산 추가",
        "신규 상장",
        "상장",
    ]

    # Phase 7: 이벤트 아비트라지 키워드 (빗썸과 동일)
    WARNING_KEYWORDS: list[str] = [
        "출금 중단",
        "입출금 중단",
        "입금 중단",
        "지갑 점검",
        "출금 제한",
        "입출금 제한",
        "네트워크 점검",
        "입출금 일시 중단",
    ]

    HALT_KEYWORDS: list[str] = [
        "거래 중단",
        "거래 정지",
        "거래 일시 중단",
        "매매 중단",
        "매매 정지",
        "거래지원 종료",
    ]

    MIGRATION_KEYWORDS: list[str] = [
        "스왑",
        "마이그레이션",
        "전환",
        "체인 변경",
        "토큰 전환",
        "컨트랙트 변경",
        "네트워크 전환",
    ]

    DEPEG_KEYWORDS: list[str] = [
        "가격 급락",
        "이상 거래",
        "시세 오류",
        "가격 오류",
        "급등락",
        "이상 체결",
    ]

    # 상장 공지 제목에서 심볼 추출 패턴 (우선순위 순)
    LISTING_PATTERNS: list[re.Pattern[str]] = [
        # "[거래] 신규 거래지원 안내 - 비트코인(BTC)"
        re.compile(r"\(([A-Z]{2,10})\)"),
        # "BTC/KRW, ETH/KRW 마켓"
        re.compile(r"([A-Z]{2,10})/KRW"),
        # "BTC 원화 마켓"
        re.compile(r"([A-Z]{2,10})\s*원화"),
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

    def parse(
        self,
        title: str,
        content: str = "",
        notice_id: str | None = None,
        notice_url: str | None = None,
    ) -> NoticeParseResult:
        """공지 제목/본문에서 이벤트 정보 추출 (Phase 7 확장)."""
        # Phase 7: 이벤트 유형 분류
        notice_type, severity, action = self._classify_event(title, content)

        if notice_type == "unknown":
            return NoticeParseResult(
                notice_type="unknown",
                exchange="upbit",
                raw_title=title,
                notice_id=notice_id,
                notice_url=notice_url,
                event_severity=severity,
                event_action=action,
            )

        # 심볼 추출 (제목 + 본문에서 모두 추출)
        symbols = self._extract_symbols(title)
        if content:
            symbols.extend(self._extract_symbols(content))

        # 중복 제거 + 순서 유지
        seen = set()
        unique_symbols = []
        for s in symbols:
            if s not in seen and s not in _EXCLUDE_WORDS:
                seen.add(s)
                unique_symbols.append(s)

        # 시간 추출 (본문 → 제목 순서)
        event_time = self._extract_time(content) if content else None
        if event_time is None:
            event_time = self._extract_time(title)

        # 날짜 + 시간 결합 (날짜가 없으면 오늘)
        full_time = None
        if event_time:
            today = datetime.now(
                tz=timezone(timedelta(hours=9))  # KST
            ).strftime("%Y-%m-%d")
            full_time = f"{today} {event_time}"

        # Phase 7: 이벤트 상세 정보
        event_details = {
            "has_time": event_time is not None,
            "symbol_count": len(unique_symbols),
        }

        return NoticeParseResult(
            symbols=unique_symbols,
            listing_time=full_time,
            notice_type=notice_type,
            exchange="upbit",
            raw_title=title,
            notice_id=notice_id,
            notice_url=notice_url,
            event_severity=severity,
            event_action=action,
            event_details=event_details,
        )

    def is_listing_notice(self, title: str) -> bool:
        """상장 관련 공지인지 빠르게 판단."""
        return any(kw in title for kw in self.LISTING_KEYWORDS)

    def is_warning_notice(self, title: str) -> bool:
        """출금/입금 중단 경고 공지인지 판단."""
        return any(kw in title for kw in self.WARNING_KEYWORDS)

    def is_halt_notice(self, title: str) -> bool:
        """거래 중단 공지인지 판단."""
        return any(kw in title for kw in self.HALT_KEYWORDS)

    def is_migration_notice(self, title: str) -> bool:
        """체인 마이그레이션/스왑 공지인지 판단."""
        return any(kw in title for kw in self.MIGRATION_KEYWORDS)

    def is_depeg_notice(self, title: str) -> bool:
        """가격 이상/디페깅 공지인지 판단."""
        return any(kw in title for kw in self.DEPEG_KEYWORDS)

    def _classify_event(self, title: str, content: str = "") -> tuple[str, EventSeverity, EventAction]:
        """공지 유형 분류 및 심각도/조치 결정.

        Returns:
            (notice_type, severity, action)
        """
        text = title + " " + content

        # 우선순위: HALT > DEPEG > WARNING > MIGRATION > LISTING
        # Phase 7 수정: DEPEG가 MIGRATION보다 우선 (더 긴급)
        if self.is_halt_notice(title):
            return "halt", EventSeverity.HIGH, EventAction.MONITOR

        if self.is_depeg_notice(title):
            return "depeg", EventSeverity.CRITICAL, EventAction.ALERT

        if self.is_warning_notice(title):
            if "출금" in text:
                return "warning", EventSeverity.MEDIUM, EventAction.TRADE
            else:
                return "warning", EventSeverity.MEDIUM, EventAction.MONITOR

        if self.is_migration_notice(title):
            return "migration", EventSeverity.MEDIUM, EventAction.ALERT

        if self.is_listing_notice(title):
            return "listing", EventSeverity.LOW, EventAction.TRADE

        return "unknown", EventSeverity.LOW, EventAction.NONE

    def _extract_symbols(self, text: str) -> list[str]:
        """텍스트에서 모든 심볼 추출."""
        symbols = []
        for pattern in self.LISTING_PATTERNS:
            matches = pattern.findall(text)
            symbols.extend(matches)
        return symbols

    def _extract_time(self, text: str) -> str | None:
        """텍스트에서 상장 시간 추출 → "HH:MM:SS" 형식."""
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

        # "HH:MM" 패턴 (마지막)
        hm_match = self.TIME_PATTERNS[0].search(text)
        if hm_match:
            hour = int(hm_match.group(1))
            minute = int(hm_match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}:00"

        return None


class UnifiedNoticeParser:
    """통합 공지 파서 (업비트 + 빗썸)."""

    def __init__(self) -> None:
        self._upbit_parser = UpbitNoticeParser()
        self._bithumb_parser = BithumbNoticeParser()

    def parse(
        self,
        title: str,
        content: str = "",
        exchange: str = "unknown",
        notice_id: str | None = None,
        notice_url: str | None = None,
    ) -> NoticeParseResult:
        """거래소에 맞는 파서 자동 선택."""
        # URL에서 거래소 판별
        if notice_url:
            if "upbit" in notice_url.lower():
                exchange = "upbit"
            elif "bithumb" in notice_url.lower():
                exchange = "bithumb"

        if exchange == "upbit":
            return self._upbit_parser.parse(title, content, notice_id, notice_url)
        elif exchange == "bithumb":
            return self._bithumb_parser.parse(title, content, notice_id, notice_url)
        else:
            # 자동 판별: 두 파서 모두 시도, 심볼 추출 성공한 쪽 반환
            upbit_result = self._upbit_parser.parse(title, content, notice_id, notice_url)
            if upbit_result.symbols:
                return upbit_result
            return self._bithumb_parser.parse(title, content, notice_id, notice_url)

    def is_listing_notice(self, title: str) -> bool:
        """상장 공지 여부 (어느 거래소든)."""
        return (
            self._upbit_parser.is_listing_notice(title)
            or self._bithumb_parser.is_listing_notice(title)
        )
