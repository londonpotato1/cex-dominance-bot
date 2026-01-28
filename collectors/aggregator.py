"""1s → 1m 롤업 + self-healing + 데이터 보존 정책.

매분 00초에 직전 1분의 1s 데이터를 1m으로 집계.
재시작 시 최근 15분 스캔하여 누락 롤업 자동 수행.
10분 초과 1s 데이터 주기적 삭제.
"""

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone, timedelta

from store.writer import DatabaseWriter

logger = logging.getLogger(__name__)

_INSERT_TRADE_1M = """
    INSERT OR REPLACE INTO trade_snapshot_1m
        (market, ts, open, high, low, close, volume, volume_krw)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_DELETE_OLD_1S = """
    DELETE FROM trade_snapshot_1s WHERE ts < datetime('now', '-10 minutes')
"""


class Aggregator:
    """1s → 1m 롤업 + self-healing + 데이터 보존."""

    def __init__(self, conn: sqlite3.Connection, writer: DatabaseWriter) -> None:
        """
        Args:
            conn: 읽기 전용 커넥션 (SELECT).
            writer: 쓰기용 (INSERT/DELETE는 Writer Queue 경유).
        """
        self._conn = conn
        self._writer = writer

    async def run(self, stop_event: asyncio.Event) -> None:
        """메인 루프: 매분 00초에 롤업 + purge."""
        # 1) 시작 시 self-heal
        await self.self_heal()

        # 2) 다음 정각(분) 00초까지 대기
        await self._wait_until_next_minute(stop_event)

        # 3) 무한 루프
        while not stop_event.is_set():
            now = datetime.now(timezone.utc)
            # 직전 1분 시작 시각 (예: 12:35:00에 실행 → 12:34:00 롤업)
            prev_minute = (now - timedelta(minutes=1)).replace(second=0, microsecond=0)
            minute_ts = prev_minute.strftime("%Y-%m-%d %H:%M:%S")

            count = await self.rollup_minute(minute_ts)
            if count > 0:
                logger.info("롤업 완료: %s → %d 마켓", minute_ts, count)

            purged = await self.purge_old_data()
            if purged:
                logger.debug("Purge 요청: 10분 초과 1s 데이터 삭제")

            # 다음 분 00초까지 sleep (stop_event.wait with timeout)
            try:
                await self._wait_until_next_minute(stop_event)
            except asyncio.CancelledError:
                break

    async def self_heal(self) -> None:
        """재시작 시 최근 15분 재롤업.

        INSERT OR REPLACE이므로 기존 데이터가 불완전했더라도
        최신(더 완전한) 데이터로 덮어써 정확성을 보장한다.
        """
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        rolled_up = 0
        no_data = 0

        for i in range(1, 16):  # 1분 전 ~ 15분 전
            target = now - timedelta(minutes=i)
            minute_ts = target.strftime("%Y-%m-%d %H:%M:%S")

            count = await self.rollup_minute(minute_ts)
            if count > 0:
                rolled_up += 1
            else:
                no_data += 1

        logger.info(
            "Self-heal 완료: %d분 롤업, %d분 1s 데이터 없음",
            rolled_up, no_data,
        )

    async def rollup_minute(self, minute_ts: str) -> int:
        """특정 1분간 1s → 1m 롤업.

        Args:
            minute_ts: "2024-01-15 12:34:00" (초 = 00).

        Returns:
            롤업된 마켓 수.
        """
        # 1분 범위: minute_ts <= ts < minute_ts + 1분
        start = minute_ts
        end_dt = datetime.strptime(minute_ts, "%Y-%m-%d %H:%M:%S") + timedelta(minutes=1)
        end = end_dt.strftime("%Y-%m-%d %H:%M:%S")

        # 해당 분에 데이터가 있는 마켓 목록
        rows = self._conn.execute(
            "SELECT DISTINCT market FROM trade_snapshot_1s "
            "WHERE ts >= ? AND ts < ?",
            (start, end),
        ).fetchall()

        if not rows:
            return 0

        count = 0
        for row in rows:
            market = row["market"]

            # OHLCV 집계
            agg = self._conn.execute(
                """
                SELECT
                    (SELECT open FROM trade_snapshot_1s
                     WHERE market = ? AND ts >= ? AND ts < ?
                     ORDER BY ts ASC LIMIT 1) as first_open,
                    MAX(high) as high,
                    MIN(low) as low,
                    (SELECT close FROM trade_snapshot_1s
                     WHERE market = ? AND ts >= ? AND ts < ?
                     ORDER BY ts DESC LIMIT 1) as last_close,
                    SUM(volume) as volume,
                    SUM(volume_krw) as volume_krw
                FROM trade_snapshot_1s
                WHERE market = ? AND ts >= ? AND ts < ?
                """,
                (
                    market, start, end,   # first_open 서브쿼리
                    market, start, end,   # last_close 서브쿼리
                    market, start, end,   # 메인 WHERE
                ),
            ).fetchone()

            if agg and agg["first_open"] is not None:
                await self._writer.enqueue(
                    _INSERT_TRADE_1M,
                    (
                        market,
                        start,
                        agg["first_open"],
                        agg["high"],
                        agg["low"],
                        agg["last_close"],
                        agg["volume"],
                        agg["volume_krw"],
                    ),
                )
                count += 1

        return count

    async def purge_old_data(self) -> bool:
        """10분 초과 1s 데이터 삭제 요청."""
        await self._writer.enqueue(_DELETE_OLD_1S, ())
        return True

    async def force_rollup_current(self) -> None:
        """Shutdown 시 진행 중인 분 데이터 강제 롤업."""
        now = datetime.now(timezone.utc)
        current_minute = now.replace(second=0, microsecond=0)
        minute_ts = current_minute.strftime("%Y-%m-%d %H:%M:%S")

        count = await self.rollup_minute(minute_ts)
        if count > 0:
            logger.info("Force rollup (shutdown): %s → %d 마켓", minute_ts, count)

    @staticmethod
    async def _wait_until_next_minute(stop_event: asyncio.Event) -> None:
        """다음 분 00초까지 대기."""
        now = datetime.now(timezone.utc)
        next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        wait_seconds = (next_minute - now).total_seconds()

        if wait_seconds > 0:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass  # 정상: 다음 분 도달
