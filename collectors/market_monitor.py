"""상장 감지 모니터 (업비트 + 빗썸 마켓 Diff).

- 업비트: /v1/market/all API Diff (30초 주기)
- 빗썸: /public/ticker/ALL_KRW API Diff (60초 주기)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, TYPE_CHECKING

import aiohttp

from store.token_registry import TokenRegistry, fetch_token_by_symbol

if TYPE_CHECKING:
    from store.writer import DatabaseWriter
    from collectors.upbit_ws import UpbitCollector
    from collectors.bithumb_ws import BithumbCollector
    from analysis.gate import GateChecker, GateResult
    from alerts.telegram import TelegramAlert

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
        upbit_interval: float = 30.0,
        bithumb_interval: float = 60.0,
    ) -> None:
        self._writer = writer
        self._registry = token_registry
        self._upbit_collector = upbit_collector
        self._bithumb_collector = bithumb_collector
        self._gate_checker = gate_checker
        self._alert = alert
        self._upbit_interval = upbit_interval
        self._bithumb_interval = bithumb_interval
        self._session: Optional[aiohttp.ClientSession] = None

        # 이전 상태 (Diff 용)
        self._upbit_markets: set[str] = set()
        self._bithumb_markets: set[str] = set()
        self._upbit_baseline_set = False
        self._bithumb_baseline_set = False

    async def run(self, stop_event: asyncio.Event) -> None:
        """메인 실행: 업비트 + 빗썸 감시를 병렬 실행."""
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            self._session = session
            await asyncio.gather(
                self._upbit_loop(stop_event),
                self._bithumb_loop(stop_event),
                return_exceptions=True,
            )

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
        """신규 상장 감지 시 처리."""
        logger.critical(
            "[MarketMonitor] 신규 상장 감지: %s @ %s (시간: %s)",
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

                # 4. 텔레그램 알림
                if self._alert:
                    alert_msg = self._format_alert(symbol, exchange, result)
                    await self._alert.send(
                        result.alert_level,
                        alert_msg,
                        key=f"listing:{symbol}",
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
    def _format_alert(symbol: str, exchange: str, result: GateResult) -> str:
        """Gate 결과를 알림 메시지로 포맷."""
        gi = result.gate_input
        status = "GO" if result.can_proceed else "NO-GO"

        lines = [
            f"*{status}* | {symbol} @ {exchange.upper()}",
        ]

        if gi:
            lines.append(
                f"프리미엄: {gi.premium_pct:+.2f}% | "
                f"순수익: {gi.cost_result.net_profit_pct:+.2f}%"
            )
            lines.append(f"FX: {gi.fx_source} ({gi.cost_result.total_cost_pct:.2f}% 비용)")

        if result.blockers:
            lines.append("Blockers:")
            for b in result.blockers:
                lines.append(f"  - {b}")

        if result.warnings:
            lines.append("Warnings:")
            for w in result.warnings:
                lines.append(f"  - {w}")

        return "\n".join(lines)

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
