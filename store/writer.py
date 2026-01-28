"""단일 Writer 스레드로 모든 DB 쓰기를 직렬화.

queue.Queue 기반. SQLite cursor.execute()가 동기 블로킹이므로
전용 스레드에서 처리하여 이벤트루프 블로킹을 제거한다.
"""

import asyncio
import logging
import queue
import sqlite3
import threading
from queue import Empty, Full

logger = logging.getLogger(__name__)

# sentinel: shutdown 신호
_SENTINEL = None

# 배치 커밋 최대 크기
_BATCH_SIZE = 100


class DatabaseWriter:
    """비동기/동기 코드에서 DB 쓰기를 큐잉하고 단일 스레드로 실행."""

    def __init__(self, conn: sqlite3.Connection, maxsize: int = 50_000) -> None:
        self._conn = conn
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)  # type: ignore[type-arg]
        self._thread = threading.Thread(target=self._run, daemon=True, name="db-writer")
        self._started = False
        self.drop_count: int = 0

    @property
    def queue_size(self) -> int:
        """현재 큐 대기 건수."""
        return self._queue.qsize()

    def start(self) -> None:
        """Writer 스레드 시작."""
        if self._started:
            return
        self._started = True
        self._thread.start()
        logger.info("Writer 스레드 시작 (큐 최대=%d)", self._queue.maxsize)

    async def enqueue(
        self, sql: str, params: tuple = (), priority: str = "normal"
    ) -> None:
        """비동기 컨텍스트에서 쓰기 요청 큐잉.

        Args:
            sql: SQL 문.
            params: 바인드 파라미터.
            priority: "critical"이면 블로킹 put (절대 드롭 금지),
                      "normal"이면 put_nowait (큐 full 시 드롭).
        """
        item = (sql, params)
        if priority == "critical":
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._queue.put, item)
        else:
            try:
                self._queue.put_nowait(item)
            except Full:
                self.drop_count += 1
                self._log_drop()

    def enqueue_sync(self, sql: str, params: tuple = ()) -> None:
        """동기 컨텍스트에서 쓰기 요청 큐잉 (put_nowait, full 시 드롭)."""
        try:
            self._queue.put_nowait((sql, params))
        except Full:
            self.drop_count += 1
            self._log_drop()

    def _log_drop(self) -> None:
        """드롭 발생 시 로깅 (1, 10, 100, 1000, 이후 매 1000건)."""
        c = self.drop_count
        if c == 1 or c == 10 or c == 100 or c == 1000 or c % 1000 == 0:
            logger.warning("Writer 큐 full, 드롭 (누적 %d건)", c)

    def _run(self) -> None:
        """Writer 스레드 메인 루프: 큐에서 꺼내 배치 커밋."""
        logger.info("Writer 스레드 실행 중")
        while True:
            # 블로킹 대기로 첫 아이템 수신
            item = self._queue.get()
            if item is _SENTINEL:
                break

            batch = [item]
            sentinel_received = False

            # 추가 아이템 비블로킹 수집 (최대 _BATCH_SIZE)
            for _ in range(_BATCH_SIZE - 1):
                try:
                    item = self._queue.get_nowait()
                except Empty:
                    break
                if item is _SENTINEL:
                    sentinel_received = True
                    break
                batch.append(item)

            # 배치 커밋
            self._commit_batch(batch)

            if sentinel_received:
                break

        # 잔여 아이템 처리
        remaining = []
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                break
            if item is _SENTINEL:
                continue
            remaining.append(item)
        if remaining:
            self._commit_batch(remaining)
            logger.info("잔여 %d건 커밋 완료", len(remaining))

        logger.info("Writer 스레드 종료")

    def _commit_batch(self, batch: list[tuple[str, tuple]]) -> None:
        """단일 트랜잭션으로 배치 커밋.

        전체 배치를 한 트랜잭션으로 시도.
        개별 SQL 실패 시 전체 롤백 후 건별 재시도.
        """
        try:
            cursor = self._conn.cursor()
            cursor.execute("BEGIN")
            for sql, params in batch:
                cursor.execute(sql, params)
            self._conn.commit()
        except sqlite3.Error:
            # 배치 내 실패 발생 → 전체 롤백 후 건별 재시도
            try:
                self._conn.rollback()
            except Exception:
                pass
            self._commit_individually(batch)
        except Exception:
            logger.exception("배치 커밋 실패 (%d건)", len(batch))
            try:
                self._conn.rollback()
            except Exception:
                pass

    def _commit_individually(self, batch: list[tuple[str, tuple]]) -> None:
        """건별 커밋 (배치 실패 시 폴백)."""
        success = 0
        fail = 0
        for sql, params in batch:
            try:
                self._conn.execute(sql, params)
                self._conn.commit()
                success += 1
            except sqlite3.Error as e:
                fail += 1
                logger.error(
                    "SQL 개별 실행 실패: %s | params=%s | %s",
                    sql[:80], params, e,
                )
                try:
                    self._conn.rollback()
                except Exception:
                    pass
        if fail:
            logger.warning(
                "배치 건별 재시도 결과: 성공=%d, 실패=%d", success, fail
            )

    def shutdown(self, timeout: float = 10.0) -> None:
        """Writer 스레드 종료. sentinel 전송 후 join 대기."""
        if not self._started:
            return
        logger.info("Writer 종료 요청 (큐 잔량=%d)", self._queue.qsize())
        self._queue.put(_SENTINEL)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            logger.warning("Writer 스레드 타임아웃 (%0.1f초)", timeout)
        self._conn.close()
        logger.info("Writer 종료 완료 (드롭 총 %d건)", self.drop_count)
