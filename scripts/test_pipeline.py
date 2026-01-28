"""Phase 1 파이프라인 검증 스크립트.

WS → SecondBucket → Writer Queue → SQLite 전체 파이프라인 동작 확인.
Phase 2에서 collector_daemon.py로 정식화 예정.

사용법:
    python scripts/test_pipeline.py                  # 업비트+빗썸 동시
    python scripts/test_pipeline.py --upbit-only     # 업비트만
    python scripts/test_pipeline.py --bithumb-only   # 빗썸만
    python scripts/test_pipeline.py --duration 60    # 60초 후 자동 종료
"""

import argparse
import asyncio
import logging
import signal
import sqlite3
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from store.database import get_connection, apply_migrations
from store.writer import DatabaseWriter
from collectors.upbit_ws import UpbitCollector
from collectors.bithumb_ws import BithumbCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test_pipeline")

# 기본 감시 마켓
UPBIT_MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
BITHUMB_MARKETS = ["BTC_KRW", "ETH_KRW", "XRP_KRW", "SOL_KRW", "DOGE_KRW"]


async def run_pipeline(
    *,
    enable_upbit: bool = True,
    enable_bithumb: bool = True,
    duration: int | None = None,
) -> None:
    """전체 파이프라인 실행."""

    # 1. DB 초기화
    db_path = str(_ROOT / "ddari.db")
    conn = get_connection(db_path)
    version = apply_migrations(conn)
    logger.info("DB 준비 완료: %s (스키마 v%d)", db_path, version)

    # 2. Writer 시작
    writer_conn = get_connection(db_path)
    writer = DatabaseWriter(writer_conn)
    writer.start()

    # 3. Collector 생성
    tasks: list[asyncio.Task] = []

    if enable_upbit:
        upbit = UpbitCollector(markets=UPBIT_MARKETS, writer=writer)
        tasks.append(asyncio.create_task(upbit.run(), name="upbit"))
        logger.info("업비트 수집기 시작: %d 마켓", len(UPBIT_MARKETS))

    if enable_bithumb:
        bithumb = BithumbCollector(markets=BITHUMB_MARKETS, writer=writer)
        tasks.append(asyncio.create_task(bithumb.run(), name="bithumb"))
        logger.info("빗썸 수집기 시작: %d 마켓", len(BITHUMB_MARKETS))

    if not tasks:
        logger.error("활성 수집기 없음")
        writer.shutdown()
        conn.close()
        return

    # 4. 통계 출력 태스크
    stats_task = asyncio.create_task(
        _print_stats(conn, writer, interval=10), name="stats"
    )

    # 5. 종료 시그널 처리
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("종료 시그널 수신")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows에서는 signal handler 미지원
            pass

    # 6. 실행
    try:
        if duration:
            logger.info("%d초 후 자동 종료", duration)
            await asyncio.wait_for(stop_event.wait(), timeout=duration)
        else:
            await stop_event.wait()
    except asyncio.TimeoutError:
        logger.info("지정 시간 %d초 도달, 종료", duration)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt 수신")

    # 7. 정리
    logger.info("수집기 종료 중...")
    for t in tasks:
        t.cancel()
    stats_task.cancel()

    await asyncio.gather(*tasks, stats_task, return_exceptions=True)

    writer.shutdown()
    conn.close()
    logger.info("파이프라인 종료 완료")


async def _print_stats(
    conn: sqlite3.Connection, writer: DatabaseWriter, interval: float = 10
) -> None:
    """주기적으로 DB 저장 통계 출력."""
    while True:
        await asyncio.sleep(interval)
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM trade_snapshot_1s"
            ).fetchone()
            count = row["cnt"] if row else 0
            logger.info(
                "=== 통계: trade_1s=%d건 | Writer큐=%d | 드롭=%d ===",
                count,
                writer.queue_size,
                writer.drop_count,
            )
        except Exception as e:
            logger.debug("통계 조회 실패: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 파이프라인 검증")
    parser.add_argument("--upbit-only", action="store_true", help="업비트만 실행")
    parser.add_argument("--bithumb-only", action="store_true", help="빗썸만 실행")
    parser.add_argument("--duration", type=int, default=None, help="실행 시간(초), 미지정 시 무한")
    args = parser.parse_args()

    enable_upbit = not args.bithumb_only
    enable_bithumb = not args.upbit_only

    try:
        asyncio.run(
            run_pipeline(
                enable_upbit=enable_upbit,
                enable_bithumb=enable_bithumb,
                duration=args.duration,
            )
        )
    except KeyboardInterrupt:
        logger.info("프로세스 종료")


if __name__ == "__main__":
    main()
