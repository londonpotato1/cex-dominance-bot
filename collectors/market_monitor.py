"""상장 감지 모니터 (업비트 + 빗썸 마켓 Diff + 공지 폴링).

- 업비트: /v1/market/all API Diff (30초 주기)
- 빗썸: /public/ticker/ALL_KRW API Diff (60초 주기)
- 공지 폴링: 마켓 오픈 전 pre-detection (30초 주기)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, TYPE_CHECKING

import aiohttp

from store.token_registry import TokenRegistry, fetch_token_by_symbol
from collectors.notice_parser import NoticeParseResult

# NoticeFetcher는 notice_polling=True일 때만 lazy import (Playwright 의존성 회피)

if TYPE_CHECKING:
    from store.writer import DatabaseWriter
    from collectors.upbit_ws import UpbitCollector
    from collectors.bithumb_ws import BithumbCollector
    from analysis.gate import GateChecker, GateResult
    from alerts.telegram import TelegramAlert
    from analysis.event_strategy import EventStrategyExecutor

logger = logging.getLogger(__name__)

_UPBIT_MARKET_URL = "https://api.upbit.com/v1/market/all"
_BITHUMB_TICKER_URL = "https://api.bithumb.com/public/ticker/ALL_KRW"
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15)
_MAX_CONSECUTIVE_FAILURES = 5
_FALSE_POSITIVE_THRESHOLD = 10  # 한 번에 이 수 이상 감지 시 오탐으로 간주


class MarketMonitor:
    """상장 감지 모니터.

    - 업비트: /v1/market/all API Diff (30초 주기)
    - 빗썸: /public/ticker/ALL_KRW API Diff (60초 주기)
    """

    def __init__(
        self,
        writer: DatabaseWriter,
        token_registry: TokenRegistry,
        upbit_collector: Optional[UpbitCollector] = None,
        bithumb_collector: Optional[BithumbCollector] = None,
        *,
        gate_checker: Optional[GateChecker] = None,
        alert: Optional[TelegramAlert] = None,
        event_strategy: Optional[EventStrategyExecutor] = None,
        upbit_interval: float = 30.0,
        bithumb_interval: float = 60.0,
        notice_polling: bool = True,
        notice_interval: float = 30.0,
    ) -> None:
        self._writer = writer
        self._registry = token_registry
        self._upbit_collector = upbit_collector
        self._bithumb_collector = bithumb_collector
        self._gate_checker = gate_checker
        self._alert = alert
        self._event_strategy = event_strategy
        self._upbit_interval = upbit_interval
        self._bithumb_interval = bithumb_interval
        self._session: Optional[aiohttp.ClientSession] = None

        # 이전 상태 (Diff 용)
        self._upbit_markets: set[str] = set()
        self._bithumb_markets: set[str] = set()
        self._upbit_baseline_set = False
        self._bithumb_baseline_set = False

        # 공지 폴링 (pre-detection) - Playwright 의존성으로 lazy import
        self._notice_polling = notice_polling
        self._notice_fetcher = None  # type: ignore[assignment]
        if notice_polling:
            try:
                from collectors.notice_fetcher import NoticeFetcher
                self._notice_fetcher = NoticeFetcher(
                    on_listing=self._on_notice_listing,
                    upbit_interval=notice_interval,
                    bithumb_interval=notice_interval,
                )
            except ImportError as e:
                logger.warning("[MarketMonitor] NoticeFetcher import 실패: %s", e)
                self._notice_polling = False

        # 이미 공지로 감지한 심볼 (마켓 Diff 중복 알림 방지)
        self._notice_detected_symbols: set[str] = set()

    async def run(self, stop_event: asyncio.Event) -> None:
        """메인 실행: 업비트 + 빗썸 감시 + 공지 폴링 병렬 실행."""
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            self._session = session

            tasks = [
                self._upbit_loop(stop_event),
                self._bithumb_loop(stop_event),
            ]

            # 공지 폴링 활성화 시 추가
            if self._notice_fetcher:
                tasks.append(self._notice_fetcher.run(stop_event))
                logger.info("[MarketMonitor] 공지 폴링 활성화")

            await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------
    # 업비트 마켓 Diff
    # ------------------------------------------------------------------

    async def _upbit_loop(self, stop_event: asyncio.Event) -> None:
        """업비트 마켓 목록 Diff 루프."""
        consecutive_failures = 0

        # 초기 마켓 목록 로드 (최대 3회 재시도)
        for attempt in range(3):
            try:
                self._upbit_markets = await self._fetch_upbit_markets()
                self._upbit_baseline_set = True
                logger.info(
                    "[MarketMonitor] 업비트 초기 마켓 로드: %d개",
                    len(self._upbit_markets),
                )
                break
            except Exception as e:
                logger.warning(
                    "[MarketMonitor] 업비트 초기 마켓 로드 실패 (%d/3): %s",
                    attempt + 1, e,
                )
                if attempt < 2 and not stop_event.is_set():
                    await asyncio.sleep(2 ** attempt)

        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._upbit_interval
                )
                break  # stop_event set
            except asyncio.TimeoutError:
                pass  # 정상: 주기 도달

            try:
                current = await self._fetch_upbit_markets()
                consecutive_failures = 0

                # 베이스라인 미설정 시 첫 성공을 베이스라인으로 사용
                if not self._upbit_baseline_set:
                    self._upbit_markets = current
                    self._upbit_baseline_set = True
                    logger.info(
                        "[MarketMonitor] 업비트 베이스라인 설정: %d개",
                        len(current),
                    )
                    continue

                # KRW 마켓만 Diff (BTC/USDT 마켓 제외)
                new_markets = current - self._upbit_markets
                krw_new = {m for m in new_markets if m.startswith("KRW-")}

                # 오탐 방지: 한 번에 다수 감지 시 베이스라인 리셋
                if len(krw_new) > _FALSE_POSITIVE_THRESHOLD:
                    logger.warning(
                        "[MarketMonitor] 업비트 %d개 동시 감지 → 오탐 판정, "
                        "베이스라인 리셋",
                        len(krw_new),
                    )
                    self._upbit_markets = current
                    continue

                for market in krw_new:
                    symbol = market.replace("KRW-", "")
                    await self._on_new_listing("upbit", symbol)

                self._upbit_markets = current

            except Exception as e:
                consecutive_failures += 1
                level = (
                    logging.ERROR if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES
                    else logging.WARNING
                )
                logger.log(
                    level,
                    "[MarketMonitor] 업비트 마켓 조회 실패 (%d연속): %s",
                    consecutive_failures, e,
                )

    async def _fetch_upbit_markets(self) -> set[str]:
        """업비트 마켓 목록 조회."""
        if self._session is None:
            raise RuntimeError("HTTP 세션 미초기화 — run() 내에서만 호출 가능")
        async with self._session.get(_UPBIT_MARKET_URL) as resp:
            resp.raise_for_status()
            data = await resp.json()
        # [{"market":"KRW-BTC","korean_name":"비트코인","english_name":"Bitcoin"}, ...]
        return {item["market"] for item in data if "market" in item}

    # ------------------------------------------------------------------
    # 빗썸 마켓 Diff
    # ------------------------------------------------------------------

    async def _bithumb_loop(self, stop_event: asyncio.Event) -> None:
        """빗썸 마켓 목록 Diff 루프."""
        consecutive_failures = 0

        # 초기 마켓 목록 로드 (최대 3회 재시도)
        for attempt in range(3):
            try:
                self._bithumb_markets = await self._fetch_bithumb_markets()
                self._bithumb_baseline_set = True
                logger.info(
                    "[MarketMonitor] 빗썸 초기 마켓 로드: %d개",
                    len(self._bithumb_markets),
                )
                break
            except Exception as e:
                logger.warning(
                    "[MarketMonitor] 빗썸 초기 마켓 로드 실패 (%d/3): %s",
                    attempt + 1, e,
                )
                if attempt < 2 and not stop_event.is_set():
                    await asyncio.sleep(2 ** attempt)

        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._bithumb_interval
                )
                break
            except asyncio.TimeoutError:
                pass

            try:
                current = await self._fetch_bithumb_markets()
                consecutive_failures = 0

                # 베이스라인 미설정 시 첫 성공을 베이스라인으로 사용
                if not self._bithumb_baseline_set:
                    self._bithumb_markets = current
                    self._bithumb_baseline_set = True
                    logger.info(
                        "[MarketMonitor] 빗썸 베이스라인 설정: %d개",
                        len(current),
                    )
                    continue

                new_symbols = current - self._bithumb_markets

                # 오탐 방지: 한 번에 다수 감지 시 베이스라인 리셋
                if len(new_symbols) > _FALSE_POSITIVE_THRESHOLD:
                    logger.warning(
                        "[MarketMonitor] 빗썸 %d개 동시 감지 → 오탐 판정, "
                        "베이스라인 리셋",
                        len(new_symbols),
                    )
                    self._bithumb_markets = current
                    continue

                for symbol in new_symbols:
                    await self._on_new_listing("bithumb", symbol)

                self._bithumb_markets = current

            except Exception as e:
                consecutive_failures += 1
                level = (
                    logging.ERROR if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES
                    else logging.WARNING
                )
                logger.log(
                    level,
                    "[MarketMonitor] 빗썸 마켓 조회 실패 (%d연속): %s",
                    consecutive_failures, e,
                )

    async def _fetch_bithumb_markets(self) -> set[str]:
        """빗썸 KRW 마켓 심볼 목록 조회."""
        if self._session is None:
            raise RuntimeError("HTTP 세션 미초기화 — run() 내에서만 호출 가능")
        async with self._session.get(_BITHUMB_TICKER_URL) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        # {"status":"0000","data":{"BTC":{...},"ETH":{...},...,"date":"..."}}
        if data.get("status") != "0000":
            raise RuntimeError(f"빗썸 API 오류: {data.get('message', 'unknown')}")
        return {k for k in data.get("data", {}) if k != "date"}

    # ------------------------------------------------------------------
    # 신규 상장 처리
    # ------------------------------------------------------------------

    async def _on_new_listing(
        self, exchange: str, symbol: str, listing_time: Optional[str] = None
    ) -> None:
        """신규 상장 감지 시 처리 (마켓 API Diff)."""
        # 이미 공지로 감지된 심볼이면 Gate 분석 스킵 (중복 방지)
        key = f"{symbol}@{exchange}"
        if key in self._notice_detected_symbols:
            logger.info(
                "[MarketMonitor] 마켓 오픈 확인 (공지로 이미 처리됨): %s @ %s",
                symbol, exchange,
            )
            # WS 수집기에만 추가하고 Gate 파이프라인은 스킵
            await self._add_market_to_collectors(exchange, symbol)
            return

        logger.critical(
            "[MarketMonitor] 🚀 마켓 신규 상장 감지: %s @ %s (시간: %s)",
            symbol, exchange, listing_time or "미정",
        )

        # 1. token_registry 자동 등록
        await self._auto_register_token(symbol)

        # 2. WS 수집기에 동적 마켓 추가
        await self._add_market_to_collectors(exchange, symbol)

        # 3. Gate 파이프라인 (Phase 3) + 관측성 (Phase 4)
        if self._gate_checker:
            try:
                t0 = time.monotonic()
                result = await self._gate_checker.analyze_listing(symbol, exchange)
                duration_ms = (time.monotonic() - t0) * 1000

                # Gate 분석 로그 DB 기록 (Phase 4)
                try:
                    from metrics.observability import log_gate_analysis
                    await log_gate_analysis(self._writer, result, duration_ms)
                except Exception as e:
                    logger.warning(
                        "[MarketMonitor] Gate 로그 기록 실패 (%s@%s): %s",
                        symbol, exchange, e,
                    )

                # Listing History 기록 (Phase 5a)
                try:
                    from metrics.observability import record_listing_history
                    await record_listing_history(
                        self._writer,
                        result,
                        listing_time=listing_time,
                    )
                except Exception as e:
                    logger.warning(
                        "[MarketMonitor] Listing history 기록 실패 (%s@%s): %s",
                        symbol, exchange, e,
                    )

                # 4. 텔레그램 알림 (속도 정보 + 인라인 버튼)
                if self._alert:
                    alert_msg, buttons = self._format_alert(symbol, exchange, result, duration_ms)
                    await self._alert.send(
                        result.alert_level,
                        alert_msg,
                        key=f"listing:{symbol}",
                        buttons=buttons,
                    )
            except Exception as e:
                logger.error(
                    "[MarketMonitor] Gate 파이프라인 에러 (%s@%s): %s",
                    symbol, exchange, e,
                )

    async def _add_market_to_collectors(
        self, exchange: str, symbol: str
    ) -> None:
        """WS 수집기에 새 마켓 동적 추가."""
        if exchange == "upbit" and self._upbit_collector:
            market = f"KRW-{symbol}"
            await self._upbit_collector.add_market(market)

        elif exchange == "bithumb" and self._bithumb_collector:
            market = f"{symbol}_KRW"
            await self._bithumb_collector.add_market(market)

    @staticmethod
    def _format_alert(
        symbol: str, 
        exchange: str, 
        result: GateResult,
        duration_ms: float = 0,
    ) -> tuple[str, list[list[dict]] | None]:
        """Gate 결과를 알림 메시지로 포맷 (Phase 1.1 개선).
        
        Args:
            symbol: 토큰 심볼.
            exchange: 거래소.
            result: Gate 분석 결과.
            duration_ms: 감지→분석 완료 시간 (ms).
            
        Returns:
            tuple: (메시지 텍스트, 인라인 버튼 배열 또는 None)
        """
        gi = result.gate_input
        is_go = result.can_proceed
        
        # ===== 헤더: 크고 명확하게 =====
        if is_go:
            header = f"🚀 *GO!* {symbol} @{exchange.upper()}"
        else:
            header = f"🔴 *NO-GO* {symbol} @{exchange.upper()}"
        
        lines = [header, ""]
        
        # ===== 핵심 지표: 수익 중심 =====
        if gi:
            net_profit = gi.cost_result.net_profit_pct
            premium = gi.premium_pct
            
            # 예상 수익 계산 (50만원 기준)
            base_krw = 500_000
            profit_krw = int(base_krw * net_profit / 100)
            
            if is_go:
                lines.append(f"💰 *예상 수익: {net_profit:+.2f}%* (≈₩{profit_krw:,})")
            else:
                lines.append(f"💸 순수익: {net_profit:+.2f}% (≈₩{profit_krw:,})")
            
            lines.append(f"📈 김프: {premium:+.2f}% | 비용: {gi.cost_result.total_cost_pct:.2f}%")
        
        # ===== 공급 분류 + 전략 =====
        if result.supply_result:
            supply = result.supply_result.classification.value
            confidence = result.supply_result.total_score
            
            # 흥/망따리 이모지
            if "smooth" in supply.lower() or confidence > 6:
                supply_emoji = "🔥"
                supply_text = "흥따리 유력"
            elif "tight" in supply.lower() or confidence < 3:
                supply_emoji = "💀"
                supply_text = "망따리 주의"
            else:
                supply_emoji = "😐"
                supply_text = "보통"
            
            lines.append(f"{supply_emoji} {supply_text} (점수: {confidence:.1f})")
        
        # ===== 속도 정보 =====
        if duration_ms > 0:
            lines.append(f"⚡ 감지 → 분석: *{duration_ms:.0f}ms*")
        
        # ===== 경고사항 (간결하게) =====
        if result.blockers:
            lines.append("")
            lines.append("🚫 *차단 사유:*")
            for b in result.blockers[:2]:  # 최대 2개
                lines.append(f"  • {b[:40]}")
        
        if result.warnings and is_go:  # GO일 때만 경고 표시
            lines.append("")
            lines.append("⚠️ *주의:*")
            for w in result.warnings[:2]:  # 최대 2개
                lines.append(f"  • {w[:40]}")
        
        message = "\n".join(lines)
        
        # ===== 인라인 버튼 (GO일 때만) =====
        buttons = None
        if is_go:
            buttons = MarketMonitor._get_exchange_buttons(symbol, exchange)
        
        return message, buttons
    
    @staticmethod
    def _get_exchange_buttons(symbol: str, exchange: str) -> list[list[dict]]:
        """거래소 바로가기 인라인 버튼 생성."""
        buttons = []
        
        # 국내 거래소 (입금 페이지)
        if exchange == "upbit":
            buttons.append([
                {"text": "📥 업비트", "url": f"https://upbit.com/exchange?code=CRIX.UPBIT.KRW-{symbol}"},
            ])
        elif exchange == "bithumb":
            buttons.append([
                {"text": "📥 빗썸", "url": f"https://www.bithumb.com/trade/order/{symbol}_KRW"},
            ])
        
        # 해외 거래소 (숏 페이지)
        buttons.append([
            {"text": "📉 바이낸스 숏", "url": f"https://www.binance.com/futures/{symbol}USDT"},
            {"text": "📉 바이빗 숏", "url": f"https://www.bybit.com/trade/usdt/{symbol}USDT"},
        ])
        
        return buttons

    async def _auto_register_token(self, symbol: str) -> None:
        """CoinGecko에서 토큰 정보 조회 → token_registry 등록."""
        # 기존 등록 확인
        existing = self._registry.get_by_symbol(symbol)
        if existing:
            logger.debug("[MarketMonitor] 토큰 이미 등록됨: %s", symbol)
            return

        # CoinGecko 조회 시도
        token = await fetch_token_by_symbol(symbol)
        if token:
            try:
                await self._registry.insert_async(token)
                logger.info("[MarketMonitor] 토큰 자동 등록: %s", symbol)
            except Exception as e:
                logger.warning("[MarketMonitor] 토큰 등록 실패 (%s): %s", symbol, e)
        else:
            # CoinGecko 조회 실패 → 최소 정보로 등록
            from store.token_registry import TokenIdentity
            minimal = TokenIdentity(symbol=symbol)
            try:
                await self._registry.insert_async(minimal)
                logger.info("[MarketMonitor] 토큰 최소 등록: %s", symbol)
            except Exception as e:
                logger.warning("[MarketMonitor] 토큰 최소 등록 실패 (%s): %s", symbol, e)

    # ------------------------------------------------------------------
    # 공지 폴링 콜백 (pre-detection)
    # ------------------------------------------------------------------

    async def _on_notice_listing(self, result: NoticeParseResult) -> None:
        """공지에서 상장 감지 시 콜백 (Phase 7 확장).

        마켓 오픈 전에 공지를 통해 먼저 감지된 경우.
        Phase 7: WARNING/HALT/MIGRATION/DEPEG 이벤트도 처리.
        """
        # Phase 7: 비상장 이벤트 처리 (WARNING/HALT/MIGRATION/DEPEG)
        if result.notice_type != "listing" and self._event_strategy:
            await self._handle_non_listing_event(result)
            return

        exchange = result.exchange
        symbols = result.symbols

        for symbol in symbols:
            # 이미 처리한 심볼이면 스킵
            key = f"{symbol}@{exchange}"
            if key in self._notice_detected_symbols:
                logger.debug("[MarketMonitor] 이미 공지로 처리됨: %s", key)
                continue

            self._notice_detected_symbols.add(key)

            logger.critical(
                "[MarketMonitor] 📢 공지 상장 감지: %s @ %s (시간: %s)",
                symbol, exchange, result.listing_time or "미정",
            )

            # 1. token_registry 자동 등록
            await self._auto_register_token(symbol)

            # 2. Gate 파이프라인 (Phase 3) + 관측성 (Phase 4)
            if self._gate_checker:
                try:
                    t0 = time.monotonic()
                    gate_result = await self._gate_checker.analyze_listing(
                        symbol, exchange
                    )
                    duration_ms = (time.monotonic() - t0) * 1000

                    # Gate 분석 로그 DB 기록 (Phase 4)
                    try:
                        from metrics.observability import log_gate_analysis
                        await log_gate_analysis(self._writer, gate_result, duration_ms)
                    except Exception as e:
                        logger.warning(
                            "[MarketMonitor] Gate 로그 기록 실패 (%s@%s): %s",
                            symbol, exchange, e,
                        )

                    # Listing History 기록 (Phase 5a)
                    try:
                        from metrics.observability import record_listing_history
                        await record_listing_history(
                            self._writer,
                            gate_result,
                            listing_time=result.listing_time,
                        )
                    except Exception as e:
                        logger.warning(
                            "[MarketMonitor] Listing history 기록 실패 (%s@%s): %s",
                            symbol, exchange, e,
                        )

                    # 3. 텔레그램 알림 (공지 링크 + 속도 정보 + 인라인 버튼)
                    if self._alert:
                        alert_msg, buttons = self._format_notice_alert(
                            symbol, exchange, gate_result, result, duration_ms
                        )
                        await self._alert.send(
                            gate_result.alert_level,
                            alert_msg,
                            key=f"notice_listing:{symbol}",
                            buttons=buttons,
                        )
                except Exception as e:
                    logger.error(
                        "[MarketMonitor] Gate 파이프라인 에러 (%s@%s): %s",
                        symbol, exchange, e,
                    )

    @staticmethod
    def _format_notice_alert(
        symbol: str,
        exchange: str,
        result: GateResult,
        notice: NoticeParseResult,
        duration_ms: float = 0,
    ) -> tuple[str, list[list[dict]] | None]:
        """공지 기반 Gate 결과를 알림 메시지로 포맷 (Phase 1.1 개선).
        
        Args:
            symbol: 토큰 심볼.
            exchange: 거래소.
            result: Gate 분석 결과.
            notice: 공지 파싱 결과.
            duration_ms: 감지→분석 완료 시간 (ms).
            
        Returns:
            tuple: (메시지 텍스트, 인라인 버튼 배열 또는 None)
        """
        gi = result.gate_input
        is_go = result.can_proceed
        
        # ===== 헤더: 공지 감지 강조 =====
        if is_go:
            header = f"📢 *공지 감지!* 🚀 *GO!*\n{symbol} @{exchange.upper()}"
        else:
            header = f"📢 *공지 감지* 🔴 *NO-GO*\n{symbol} @{exchange.upper()}"
        
        lines = [header, ""]
        
        # ===== 상장 시간 =====
        if notice.listing_time:
            lines.append(f"🕐 *상장 시간: {notice.listing_time}*")
            lines.append("")
        
        # ===== 핵심 지표: 수익 중심 =====
        if gi:
            net_profit = gi.cost_result.net_profit_pct
            premium = gi.premium_pct
            
            # 예상 수익 계산 (50만원 기준)
            base_krw = 500_000
            profit_krw = int(base_krw * net_profit / 100)
            
            if is_go:
                lines.append(f"💰 *예상 수익: {net_profit:+.2f}%* (≈₩{profit_krw:,})")
            else:
                lines.append(f"💸 순수익: {net_profit:+.2f}% (≈₩{profit_krw:,})")
            
            lines.append(f"📈 김프: {premium:+.2f}% | 비용: {gi.cost_result.total_cost_pct:.2f}%")
        
        # ===== 공급 분류 + 전략 =====
        if result.supply_result:
            supply = result.supply_result.classification.value
            confidence = result.supply_result.total_score
            
            if "smooth" in supply.lower() or confidence > 6:
                supply_emoji = "🔥"
                supply_text = "흥따리 유력"
            elif "tight" in supply.lower() or confidence < 3:
                supply_emoji = "💀"
                supply_text = "망따리 주의"
            else:
                supply_emoji = "😐"
                supply_text = "보통"
            
            lines.append(f"{supply_emoji} {supply_text} (점수: {confidence:.1f})")
        
        # ===== 속도 정보 =====
        if duration_ms > 0:
            lines.append(f"⚡ 공지 → 분석: *{duration_ms:.0f}ms*")
        
        # ===== 경고사항 =====
        if result.blockers:
            lines.append("")
            lines.append("🚫 *차단 사유:*")
            for b in result.blockers[:2]:
                lines.append(f"  • {b[:40]}")
        
        if result.warnings and is_go:
            lines.append("")
            lines.append("⚠️ *주의:*")
            for w in result.warnings[:2]:
                lines.append(f"  • {w[:40]}")
        
        message = "\n".join(lines)
        
        # ===== 인라인 버튼 =====
        buttons = []
        
        # 공지 링크 버튼
        if notice.notice_url:
            buttons.append([{"text": "📎 공지 보기", "url": notice.notice_url}])
        
        # GO일 때 거래소 버튼 추가
        if is_go:
            exchange_buttons = MarketMonitor._get_exchange_buttons(symbol, exchange)
            buttons.extend(exchange_buttons)
        
        return message, buttons if buttons else None

    async def _handle_non_listing_event(self, result: NoticeParseResult) -> None:
        """Phase 7: 비상장 이벤트 처리 (WARNING/HALT/MIGRATION/DEPEG).

        Args:
            result: NoticeParseResult (notice_type != "listing")
        """
        logger.critical(
            "[MarketMonitor] 🚨 이벤트 감지: %s @ %s (%s)",
            result.symbols or ["N/A"],
            result.exchange,
            result.notice_type.upper(),
        )

        if not self._event_strategy:
            logger.warning("[MarketMonitor] EventStrategy 미설정")
            return

        try:
            # 이벤트 전략 생성
            strategy = await self._event_strategy.process_event(result)

            if strategy is None:
                logger.debug(
                    "[MarketMonitor] 조치 불필요 이벤트: %s", result.notice_type
                )
                return

            logger.info(
                "[MarketMonitor] 전략 생성: %s (%s) → %s",
                strategy.symbol,
                strategy.event_type,
                strategy.recommended_action,
            )

            # 텔레그램 알림 발송
            if self._alert:
                from analysis.event_strategy import format_strategy_alert

                alert_msg = format_strategy_alert(strategy)

                # 심각도에 따라 알림 레벨 결정
                from analysis.gate import AlertLevel

                severity_to_level = {
                    "low": AlertLevel.LOW,
                    "medium": AlertLevel.MEDIUM,
                    "high": AlertLevel.HIGH,
                    "critical": AlertLevel.CRITICAL,
                }
                alert_level = severity_to_level.get(
                    strategy.severity.value, AlertLevel.MEDIUM
                )

                await self._alert.send(
                    alert_level,
                    alert_msg,
                    key=f"event:{strategy.event_type}:{strategy.symbol}",
                )

                logger.info(
                    "[MarketMonitor] 이벤트 알림 발송 완료: %s (%s)",
                    strategy.symbol,
                    strategy.event_type,
                )

        except Exception as e:
            logger.error(
                "[MarketMonitor] 이벤트 전략 처리 실패: %s",
                e,
                exc_info=True,
            )
