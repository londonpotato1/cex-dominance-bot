"""텔레그램 알림 시스템 (Phase 3).

AlertLevel 5단계:
  - CRITICAL/HIGH → 즉시 전송
  - MEDIUM → 5분 debounce
  - LOW → batch buffer (1시간 flush)
  - INFO → 로그만

DB 쓰기 원칙: 모든 write → Writer Queue (enqueue_sync)
bot_token/chat_id 미설정 시 로그만 (실제 전송 없음).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Optional, TYPE_CHECKING

import aiohttp

from analysis.gate import AlertLevel

if TYPE_CHECKING:
    from store.writer import DatabaseWriter

logger = logging.getLogger(__name__)

# Debounce 기본 간격 (초)
_DEFAULT_DEBOUNCE_SEC = 300  # 5분

# LOW 레벨 배치 버퍼 flush 간격 (초)
_BATCH_FLUSH_INTERVAL = 3600  # 1시간

# Debounce SQL
_DEBOUNCE_UPSERT_SQL = (
    "INSERT OR REPLACE INTO alert_debounce (key, last_sent_at, expires_at) "
    "VALUES (?, ?, ?)"
)

# Telegram API
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramAlert:
    """텔레그램 알림 발송기.

    - 레벨별 전송 전략 (즉시/debounce/batch/로그)
    - Debounce DB 관리 (Writer Queue 경유)
    - bot_token 미설정 시 로그만 출력
    """

    def __init__(
        self,
        writer: DatabaseWriter,
        read_conn: sqlite3.Connection,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        """
        Args:
            writer: DB Writer Queue.
            read_conn: 읽기 전용 커넥션 (debounce 조회용).
            bot_token: 텔레그램 봇 토큰. None이면 환경변수 TELEGRAM_BOT_TOKEN.
            chat_id: 텔레그램 채팅 ID. None이면 환경변수 TELEGRAM_CHAT_ID.
        """
        self._writer = writer
        self._read_conn = read_conn
        self._bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self._chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self._batch_buffer: list[str] = []
        self._last_batch_flush: float = time.time()

    @property
    def is_configured(self) -> bool:
        """텔레그램 봇 설정 여부."""
        return bool(self._bot_token and self._chat_id)

    async def send(
        self,
        level: AlertLevel,
        message: str,
        key: str | None = None,
    ) -> None:
        """레벨별 알림 전송.

        Args:
            level: 알림 레벨.
            message: 알림 메시지.
            key: 디바운스 키 (None이면 디바운스 없음).
        """
        prefix = self._level_prefix(level)
        formatted = f"{prefix} {message}"

        if level == AlertLevel.INFO:
            logger.info("[Alert/INFO] %s", message)
            return

        if level == AlertLevel.LOW:
            self._batch_buffer.append(formatted)
            logger.info("[Alert/LOW] 배치 버퍼 추가: %s", message[:80])
            await self._try_flush_batch()
            return

        if level == AlertLevel.MEDIUM:
            if key and not self._debounce_check(key, _DEFAULT_DEBOUNCE_SEC):
                logger.debug("[Alert/MEDIUM] 디바운스 skip: %s", key)
                return
            if key:
                self._debounce_update(key, _DEFAULT_DEBOUNCE_SEC)

        # CRITICAL, HIGH, MEDIUM → 전송
        logger.info("[Alert/%s] %s", level.value, message[:100])
        await self._send_telegram(formatted)

    async def flush_batch(self) -> None:
        """배치 버퍼 강제 flush."""
        if not self._batch_buffer:
            return

        combined = "\n\n".join(self._batch_buffer)
        header = f"--- LOW 알림 모음 ({len(self._batch_buffer)}건) ---\n\n"
        await self._send_telegram(header + combined)
        self._batch_buffer.clear()
        self._last_batch_flush = time.time()

    def _debounce_check(self, key: str, min_interval: float) -> bool:
        """디바운스 체크: 전송 가능 여부 반환.

        Args:
            key: 디바운스 키.
            min_interval: 최소 간격 (초).

        Returns:
            True = 전송 가능, False = 디바운스 중.
        """
        try:
            row = self._read_conn.execute(
                "SELECT last_sent_at, expires_at FROM alert_debounce WHERE key = ?",
                (key,),
            ).fetchone()

            if row is None:
                return True

            expires_at = row["expires_at"]
            return time.time() >= expires_at

        except Exception as e:
            logger.warning("디바운스 조회 실패 (%s), 전송 허용: %s", key, e)
            return True  # 조회 실패 시 전송 허용

    def _debounce_update(self, key: str, interval: float) -> None:
        """디바운스 기록 갱신 (Writer Queue 경유).

        Args:
            key: 디바운스 키.
            interval: 디바운스 간격 (초).
        """
        now = time.time()
        expires_at = now + interval
        self._writer.enqueue_sync(
            _DEBOUNCE_UPSERT_SQL,
            (key, now, expires_at),
        )

    async def _send_telegram(self, message: str) -> None:
        """텔레그램 메시지 전송.

        bot_token/chat_id 미설정 시 로그만 출력.
        """
        if not self.is_configured:
            logger.info("[Telegram/dry-run] %s", message[:200])
            return

        url = _TELEGRAM_API.format(token=self._bot_token)
        payload = {
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            "텔레그램 전송 실패: status=%d, body=%s",
                            resp.status, body[:200],
                        )
                    else:
                        logger.debug("텔레그램 전송 성공")
        except Exception as e:
            logger.warning("텔레그램 전송 에러: %s", e)

    async def _try_flush_batch(self) -> None:
        """배치 flush 조건 확인."""
        if (time.time() - self._last_batch_flush) >= _BATCH_FLUSH_INTERVAL:
            await self.flush_batch()

    @staticmethod
    def _level_prefix(level: AlertLevel) -> str:
        """레벨별 이모지 접두사."""
        prefixes = {
            AlertLevel.CRITICAL: "[CRITICAL]",
            AlertLevel.HIGH: "[HIGH]",
            AlertLevel.MEDIUM: "[MEDIUM]",
            AlertLevel.LOW: "[LOW]",
            AlertLevel.INFO: "[INFO]",
        }
        return prefixes.get(level, "[?]")
