"""텔레그램 인터랙티브 봇 (Phase 4).

Feature Flag: telegram_interactive: true 에서만 활성화.
기본 false → daemon 시작 시 skip.

명령어:
  /status — 시스템 상태 (health.json → RED/YELLOW/GREEN)
  /recent — 최근 Gate 분석 5건 요약
  /gate <SYMBOL> — 수동 Gate 분석 실행
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

    @staticmethod
    def _cmd_help() -> str:
        """도움말."""
        return (
            "따리봇 명령어:\n"
            "  /status — 시스템 상태\n"
            "  /recent — 최근 분석 5건\n"
            "  /gate <SYMBOL> — 수동 Gate 분석\n"
            "  /help — 이 도움말"
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
