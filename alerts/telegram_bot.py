"""텔레그램 인터랙티브 봇 (Phase 4 + 공지 분석).

Feature Flag: telegram_interactive: true 에서만 활성화.
기본 false → daemon 시작 시 skip.

명령어:
  /status — 시스템 상태 (health.json → RED/YELLOW/GREEN)
  /recent — 최근 Gate 분석 5건 요약
  /gate <SYMBOL> — 수동 Gate 분석 (업비트 기본)
  /analyze <SYMBOL> <EXCHANGE> — 지정 거래소 Gate 분석
  /notice <URL> — 공지 URL 파싱 후 자동 분석
  /help — 명령어 목록

aiohttp 기반 long polling (추가 의존성 없음).
collector_daemon 이벤트 루프 내 asyncio.Task로 실행.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from typing import TYPE_CHECKING

import aiohttp

from ui.health_display import load_health, evaluate_health

if TYPE_CHECKING:
    from analysis.gate import GateChecker
    from store.writer import DatabaseWriter

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}"
_POLL_TIMEOUT = 30  # getUpdates long polling timeout (초)
_POLL_INTERVAL = 2  # 에러 시 재시도 간격 (초)


class TelegramBot:
    """인터랙티브 텔레그램 봇.

    long polling으로 메시지 수신, 허가된 chat_id만 처리.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        read_conn: sqlite3.Connection,
        gate_checker: GateChecker,
        writer: DatabaseWriter,
    ) -> None:
        self._token = bot_token
        self._chat_id = str(chat_id)
        self._read_conn = read_conn
        self._read_conn.row_factory = sqlite3.Row  # dict-like 접근 보장
        self._gate_checker = gate_checker
        self._writer = writer
        self._offset = 0  # getUpdates offset

    async def run(self, stop_event: asyncio.Event) -> None:
        """봇 메인 루프 (stop_event까지 실행)."""
        logger.info("[TelegramBot] 인터랙티브 봇 시작")

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_POLL_TIMEOUT + 10)
        ) as session:
            while not stop_event.is_set():
                try:
                    updates = await self._get_updates(session)
                    for update in updates:
                        await self._handle_update(session, update)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning("[TelegramBot] 폴링 에러: %s", e)
                    try:
                        await asyncio.wait_for(
                            stop_event.wait(), timeout=_POLL_INTERVAL
                        )
                        break
                    except asyncio.TimeoutError:
                        pass

        logger.info("[TelegramBot] 봇 종료")

    async def _get_updates(self, session: aiohttp.ClientSession) -> list[dict]:
        """Telegram getUpdates (long polling)."""
        url = f"{_TELEGRAM_API.format(token=self._token)}/getUpdates"
        params = {
            "offset": self._offset,
            "timeout": _POLL_TIMEOUT,
            "allowed_updates": json.dumps(["message"]),
        }

        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        if not data.get("ok"):
            return []

        results = data.get("result", [])
        if results:
            self._offset = results[-1]["update_id"] + 1

        return results

    async def _handle_update(
        self, session: aiohttp.ClientSession, update: dict
    ) -> None:
        """개별 업데이트 처리."""
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()

        logger.info("[TelegramBot] 메시지 수신: chat_id=%s, text=%s", chat_id, text[:50] if text else "(empty)")

        # 보안: 허가된 chat_id만 처리
        if chat_id != self._chat_id:
            logger.warning("[TelegramBot] 미인가 chat_id 무시: %s (허가=%s)", chat_id, self._chat_id)
            return

        if not text.startswith("/"):
            return

        parts = text.split(maxsplit=1)
        command = parts[0].lower().split("@")[0]  # /command@botname 처리
        args = parts[1] if len(parts) > 1 else ""

        if command == "/status":
            response = self._cmd_status()
        elif command == "/recent":
            response = self._cmd_recent()
        elif command == "/gate":
            response = await self._cmd_gate(args)
        elif command == "/analyze":
            response = await self._cmd_analyze(args)
        elif command == "/notice":
            response = await self._cmd_notice(args, session)
        elif command == "/record":
            response = self._cmd_record(args)
        elif command == "/stats":
            response = self._cmd_stats(args)
        elif command == "/help":
            response = self._cmd_help()
        else:
            response = f"알 수 없는 명령: {command}\n/help 로 명령어 확인"

        await self._send_message(session, response)

    def _cmd_status(self) -> str:
        """시스템 상태 조회."""
        data = load_health()
        if data is None:
            return "수집 데몬 미실행 (health.json 없음)"

        status, issues = evaluate_health(data)

        emoji = {"RED": "\U0001f534", "YELLOW": "\U0001f7e1", "GREEN": "\U0001f7e2"}
        lines = [f"시스템 상태: {emoji.get(status, '?')} {status}"]

        if issues:
            for issue in issues:
                lines.append(f"  - {issue}")

        # WS 연결 상태
        ws = data.get("ws_connected", {})
        lines.append(
            f"\nWS: Upbit={'ON' if ws.get('upbit') else 'OFF'}, "
            f"Bithumb={'ON' if ws.get('bithumb') else 'OFF'}"
        )

        # 큐 상태
        queue = data.get("queue_size", 0)
        drops = data.get("queue_drops", 0)
        lines.append(f"큐: {queue:,}건 / 드롭: {drops:,}건")

        return "\n".join(lines)

    def _cmd_recent(self) -> str:
        """최근 Gate 분석 5건 조회."""
        try:
            rows = self._read_conn.execute(
                "SELECT symbol, exchange, can_proceed, alert_level, "
                "premium_pct, net_profit_pct, timestamp "
                "FROM gate_analysis_log ORDER BY timestamp DESC LIMIT 5"
            ).fetchall()
        except sqlite3.OperationalError:
            return "gate_analysis_log 테이블 없음 (마이그레이션 필요)"

        if not rows:
            return "분석 기록 없음"

        lines = ["최근 Gate 분석 (5건):"]
        for r in rows:
            from datetime import datetime
            status = "GO" if r["can_proceed"] else "NO-GO"
            ts = datetime.fromtimestamp(r["timestamp"]).strftime("%m/%d %H:%M")
            premium = f"{r['premium_pct']:.1f}%" if r["premium_pct"] is not None else "N/A"
            profit = f"{r['net_profit_pct']:.1f}%" if r["net_profit_pct"] is not None else "N/A"
            lines.append(
                f"  {status} {r['symbol']}@{r['exchange']} "
                f"P:{premium} NP:{profit} [{ts}]"
            )

        return "\n".join(lines)

    async def _cmd_gate(self, symbol: str) -> str:
        """수동 Gate 분석 실행."""
        symbol = symbol.strip().upper()
        if not symbol:
            return "사용법: /gate <SYMBOL>\n예: /gate BTC"

        try:
            t0 = time.monotonic()
            result = await self._gate_checker.analyze_listing(symbol, "upbit")
            duration_ms = (time.monotonic() - t0) * 1000

            # 로그 기록
            try:
                from metrics.observability import log_gate_analysis
                await log_gate_analysis(self._writer, result, duration_ms)
            except Exception:
                pass

            gi = result.gate_input
            status = "GO" if result.can_proceed else "NO-GO"

            lines = [
                f"Gate 분석: {symbol} ({status})",
                f"Level: {result.alert_level.value}",
            ]

            if gi:
                lines.append(
                    f"프리미엄: {gi.premium_pct:+.2f}% | "
                    f"순수익: {gi.cost_result.net_profit_pct:+.2f}%"
                )
                lines.append(
                    f"비용: {gi.cost_result.total_cost_pct:.2f}% | "
                    f"FX: {gi.fx_source}"
                )
                lines.append(f"소요: {duration_ms:.0f}ms")

            if result.blockers:
                lines.append("Blockers:")
                for b in result.blockers:
                    lines.append(f"  - {b}")

            if result.warnings:
                lines.append("Warnings:")
                for w in result.warnings:
                    lines.append(f"  - {w}")

            return "\n".join(lines)

        except Exception as e:
            return f"Gate 분석 실패: {e}"

    async def _cmd_analyze(self, args: str) -> str:
        """지정 거래소 Gate 분석 실행.

        사용법: /analyze SYMBOL EXCHANGE
        예: /analyze SENT bithumb
        """
        parts = args.strip().upper().split()
        if len(parts) < 2:
            return (
                "사용법: /analyze <SYMBOL> <EXCHANGE>\n"
                "예: /analyze SENT bithumb\n"
                "    /analyze ELSA upbit\n"
                "지원 거래소: upbit, bithumb"
            )

        symbol = parts[0]
        exchange = parts[1].lower()

        if exchange not in ("upbit", "bithumb"):
            return f"미지원 거래소: {exchange}\n지원: upbit, bithumb"

        try:
            t0 = time.monotonic()
            result = await self._gate_checker.analyze_listing(symbol, exchange)
            duration_ms = (time.monotonic() - t0) * 1000

            # 로그 기록
            try:
                from metrics.observability import log_gate_analysis
                await log_gate_analysis(self._writer, result, duration_ms)
            except Exception:
                pass

            return self._format_gate_result(symbol, exchange, result, duration_ms)

        except Exception as e:
            logger.exception("[TelegramBot] analyze 에러: %s", e)
            return f"분석 실패: {e}"

    async def _cmd_notice(
        self, url: str, session: aiohttp.ClientSession
    ) -> str:
        """공지 URL 파싱 후 자동 분석.

        사용법: /notice <URL>
        예: /notice https://feed.bithumb.com/notice/1651725
        """
        url = url.strip()
        if not url:
            return (
                "사용법: /notice <URL>\n"
                "예: /notice https://feed.bithumb.com/notice/1651725"
            )

        # URL에서 거래소 판별
        exchange = None
        if "bithumb" in url.lower():
            exchange = "bithumb"
        elif "upbit" in url.lower():
            exchange = "upbit"
        else:
            return "지원하지 않는 공지 URL입니다.\n빗썸/업비트 공지만 지원"

        # 공지 페이지에서 심볼 추출 시도
        try:
            symbols = await self._parse_notice_symbols(url, session)
        except Exception as e:
            logger.warning("[TelegramBot] 공지 파싱 실패: %s", e)
            return (
                f"공지 파싱 실패: {e}\n"
                f"직접 분석: /analyze SYMBOL {exchange}"
            )

        if not symbols:
            return (
                "공지에서 심볼을 추출하지 못했습니다.\n"
                f"직접 분석: /analyze SYMBOL {exchange}"
            )

        # 추출된 심볼들 분석
        results = []
        for symbol in symbols[:5]:  # 최대 5개
            try:
                t0 = time.monotonic()
                result = await self._gate_checker.analyze_listing(symbol, exchange)
                duration_ms = (time.monotonic() - t0) * 1000

                # 로그 기록
                try:
                    from metrics.observability import log_gate_analysis
                    await log_gate_analysis(self._writer, result, duration_ms)
                except Exception:
                    pass

                results.append(
                    self._format_gate_result(symbol, exchange, result, duration_ms)
                )
            except Exception as e:
                results.append(f"❌ {symbol}@{exchange}: 분석 실패 - {e}")

        return "\n\n".join(results)

    async def _parse_notice_symbols(
        self, url: str, session: aiohttp.ClientSession
    ) -> list[str]:
        """공지 URL에서 심볼 추출."""
        import re

        # 공지 페이지 fetch (JavaScript 렌더링 불가 → 제한적)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
        except Exception:
            return []

        symbols = []

        # 패턴 1: (SYMBOL) 형태 - "센티언트(SENT)"
        pattern1 = re.compile(r"\(([A-Z]{2,10})\)")
        symbols.extend(pattern1.findall(html))

        # 패턴 2: SYMBOL/KRW 형태
        pattern2 = re.compile(r"([A-Z]{2,10})/KRW")
        symbols.extend(pattern2.findall(html))

        # 패턴 3: SYMBOL_KRW 형태
        pattern3 = re.compile(r"([A-Z]{2,10})_KRW")
        symbols.extend(pattern3.findall(html))

        # 중복 제거 + 순서 유지
        seen = set()
        unique = []
        for s in symbols:
            if s not in seen and len(s) >= 2:
                seen.add(s)
                unique.append(s)

        # 일반적인 단어 제외
        exclude = {"KRW", "USD", "USDT", "BTC", "ETH", "API", "FAQ", "APP", "THE", "FOR"}
        return [s for s in unique if s not in exclude]

    def _format_gate_result(
        self, symbol: str, exchange: str, result, duration_ms: float
    ) -> str:
        """Gate 결과 포맷팅."""
        gi = result.gate_input
        status = "✅ GO" if result.can_proceed else "❌ NO-GO"

        lines = [
            f"*{status}* | {symbol}@{exchange.upper()}",
            f"Level: {result.alert_level.value}",
        ]

        if gi:
            lines.append(
                f"프리미엄: {gi.premium_pct:+.2f}% | "
                f"순수익: {gi.cost_result.net_profit_pct:+.2f}%"
            )
            lines.append(
                f"비용: {gi.cost_result.total_cost_pct:.2f}% | "
                f"FX: {gi.fx_source}"
            )

        # Phase 5a 결과
        if result.supply_result:
            lines.append(
                f"공급: {result.supply_result.classification.value} "
                f"(score={result.supply_result.total_score:.2f})"
            )

        if result.listing_type_result:
            lines.append(
                f"유형: {result.listing_type_result.listing_type.value}"
            )

        if result.recommended_strategy:
            lines.append(f"전략: {result.recommended_strategy.value}")

        lines.append(f"⏱️ {duration_ms:.0f}ms")

        if result.blockers:
            lines.append("🚫 Blockers:")
            for b in result.blockers[:3]:  # 최대 3개
                lines.append(f"  • {b[:50]}")

        if result.warnings:
            lines.append("⚠️ Warnings:")
            for w in result.warnings[:3]:
                lines.append(f"  • {w[:50]}")

        return "\n".join(lines)

    def _cmd_record(self, args: str) -> str:
        """거래 결과 기록 (Phase 4.1).
        
        사용법: /record SYMBOL EXCHANGE 수익률 결과
        예: /record PYTH bithumb 2.5 WIN
            /record SENT upbit -1.2 LOSS
            /record ABC bithumb 0 SKIP "안 탔음"
        """
        parts = args.strip().split()
        
        if len(parts) < 4:
            return (
                "📝 *거래 결과 기록*\n\n"
                "사용법:\n"
                "`/record SYMBOL EXCHANGE 수익률 결과`\n\n"
                "결과 종류:\n"
                "• WIN — 수익\n"
                "• LOSS — 손실\n"
                "• BREAKEVEN — 본전\n"
                "• SKIP — 미참여\n\n"
                "예시:\n"
                "`/record PYTH bithumb 2.5 WIN`\n"
                "`/record SENT upbit -1.2 LOSS`\n"
                "`/record ABC bithumb 0 SKIP`"
            )
        
        symbol = parts[0].upper()
        exchange = parts[1].lower()
        
        try:
            profit_pct = float(parts[2])
        except ValueError:
            return f"❌ 수익률 형식 오류: {parts[2]} (숫자로 입력)"
        
        result_label = parts[3].upper()
        if result_label not in ("WIN", "LOSS", "BREAKEVEN", "SKIP"):
            return f"❌ 결과 형식 오류: {result_label}\n허용: WIN, LOSS, BREAKEVEN, SKIP"
        
        # 메모 (선택)
        user_note = " ".join(parts[4:]) if len(parts) > 4 else None
        
        try:
            from store.performance import PerformanceTracker
            tracker = PerformanceTracker(self._writer, self._read_conn)
            
            import time
            success = tracker.record_trade_sync(
                symbol=symbol,
                exchange=exchange,
                signal_timestamp=time.time(),
                actual_profit_pct=profit_pct,
                result_label=result_label,
                user_note=user_note,
            )
            
            if success:
                emoji = {"WIN": "🎉", "LOSS": "😢", "BREAKEVEN": "😐", "SKIP": "⏭️"}.get(result_label, "✅")
                return (
                    f"{emoji} *거래 기록 완료*\n\n"
                    f"심볼: {symbol}@{exchange.upper()}\n"
                    f"수익률: {profit_pct:+.2f}%\n"
                    f"결과: {result_label}"
                    + (f"\n메모: {user_note}" if user_note else "")
                )
            else:
                return "❌ 기록 실패 (DB 오류)"
                
        except Exception as e:
            logger.error("[TelegramBot] record 에러: %s", e)
            return f"❌ 기록 실패: {e}"
    
    def _cmd_stats(self, args: str) -> str:
        """성과 통계 조회 (Phase 4.1).
        
        사용법: /stats [일수]
        예: /stats (기본 30일)
            /stats 7 (최근 7일)
        """
        # 기간 파싱
        days = 30
        if args.strip():
            try:
                days = int(args.strip())
                days = max(1, min(365, days))  # 1~365일
            except ValueError:
                pass
        
        try:
            from store.performance import PerformanceTracker
            tracker = PerformanceTracker(self._writer, self._read_conn)
            stats = tracker.get_stats(days=days)
            
            if stats.total_trades == 0:
                return (
                    f"📊 *성과 통계* (최근 {days}일)\n\n"
                    "기록된 거래가 없습니다.\n"
                    "`/record`로 거래 결과를 기록하세요."
                )
            
            # 승률 색상
            if stats.win_rate >= 60:
                win_emoji = "🟢"
            elif stats.win_rate >= 40:
                win_emoji = "🟡"
            else:
                win_emoji = "🔴"
            
            # 수익 색상
            if stats.total_profit_pct > 0:
                profit_emoji = "📈"
            elif stats.total_profit_pct < 0:
                profit_emoji = "📉"
            else:
                profit_emoji = "➖"
            
            lines = [
                f"📊 *성과 통계* (최근 {days}일)",
                "",
                f"*거래 현황*",
                f"  총 {stats.total_trades}건 | ✅ {stats.wins} | ❌ {stats.losses} | ⏭️ {stats.skips}",
                f"  {win_emoji} 승률: *{stats.win_rate:.1f}%*",
                "",
                f"*수익 현황*",
                f"  {profit_emoji} 총 수익: *{stats.total_profit_pct:+.2f}%*",
                f"  평균: {stats.avg_profit_pct:+.2f}%",
                f"  최고: {stats.best_trade_pct:+.2f}% | 최저: {stats.worst_trade_pct:+.2f}%",
                "",
                f"*예측 정확도*",
                f"  🎯 {stats.prediction_accuracy:.1f}%",
                f"  예측 평균: {stats.avg_predicted_pct:+.2f}%",
            ]
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error("[TelegramBot] stats 에러: %s", e)
            return f"❌ 통계 조회 실패: {e}"

    @staticmethod
    def _cmd_help() -> str:
        """도움말."""
        return (
            "📊 *따리봇 명령어*\n\n"
            "*분석*\n"
            "  /status — 시스템 상태\n"
            "  /recent — 최근 분석 5건\n"
            "  /gate <SYMBOL> — 수동 분석 (업비트)\n"
            "  /analyze <SYMBOL> <EXCHANGE> — 거래소 지정\n"
            "  /notice <URL> — 공지 URL 자동 분석\n\n"
            "*성과 기록* (Phase 4)\n"
            "  /record <SYMBOL> <EX> <수익%> <결과>\n"
            "  /stats [일수] — 성과 통계\n\n"
            "예시:\n"
            "  `/analyze SENT bithumb`\n"
            "  `/record PYTH bithumb 2.5 WIN`\n"
            "  `/stats 7`"
        )

    async def _send_message(
        self, session: aiohttp.ClientSession, text: str
    ) -> None:
        """텔레그램 메시지 전송."""
        url = f"{_TELEGRAM_API.format(token=self._token)}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(
                        "[TelegramBot] 전송 실패: status=%d, body=%s",
                        resp.status, body[:200],
                    )
        except Exception as e:
            logger.warning("[TelegramBot] 전송 에러: %s", e)
