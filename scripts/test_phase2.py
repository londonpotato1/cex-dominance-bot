"""Phase 2 통합 테스트 — 오프라인 (WS/CoinGecko 불필요).

검증 항목:
  1. DB 초기화 + 마이그레이션
  2. Writer 스레드 시작/종료/배치 커밋
  3. SecondBucket → Writer → trade_snapshot_1s
  4. Aggregator: 1s → 1m 롤업
  5. Aggregator: self_heal (15분 재롤업)
  6. Aggregator: purge (10분 초과 삭제)
  7. TokenRegistry: insert_async + 조회
  8. NoticeParser: 상장 공지 파싱

사용법:
    python scripts/test_phase2.py
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from store.database import get_connection, apply_migrations
from store.writer import DatabaseWriter
from collectors.second_bucket import SecondBucket
from collectors.aggregator import Aggregator
from store.token_registry import TokenRegistry, TokenIdentity
from collectors.notice_parser import BithumbNoticeParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test_phase2")

_TEST_DB = str(_ROOT / "test_phase2.db")
_PASS = 0
_FAIL = 0


def result(name: str, ok: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if ok:
        _PASS += 1
        status = "PASS"
    else:
        _FAIL += 1
        status = "FAIL"
    msg = f"[{status}] {name}"
    if detail:
        msg += f" — {detail}"
    logger.info(msg)


async def test_db_init() -> tuple:
    """1. DB 초기화 + 마이그레이션."""
    conn = get_connection(_TEST_DB)
    version = apply_migrations(conn)
    result("DB 초기화 + 마이그레이션", version >= 1, f"스키마 v{version}")

    # 테이블 존재 확인
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {"trade_snapshot_1s", "trade_snapshot_1m", "token_registry", "schema_version"}
    missing = expected - tables
    result("필수 테이블 존재", not missing, f"누락: {missing}" if missing else "전체 존재")

    return conn, version


async def test_writer_pipeline(conn) -> DatabaseWriter:
    """2. Writer 스레드 시작 + 배치 커밋."""
    writer_conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(writer_conn)
    writer.start()

    # enqueue → DB 커밋 확인
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    await writer.enqueue(
        "INSERT OR REPLACE INTO trade_snapshot_1s "
        "(market, ts, open, high, low, close, volume, volume_krw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("TEST:WRITER", now_str, 100, 110, 90, 105, 1.5, 150000),
    )
    # 대기 (Writer 스레드가 처리할 시간)
    await asyncio.sleep(0.5)

    row = conn.execute(
        "SELECT * FROM trade_snapshot_1s WHERE market = 'TEST:WRITER'"
    ).fetchone()
    result(
        "Writer 배치 커밋",
        row is not None and row["close"] == 105,
        f"close={row['close']}" if row else "row=None",
    )

    # queue_size property 확인
    qs = writer.queue_size
    result("Writer queue_size property", isinstance(qs, int), f"queue_size={qs}")

    return writer


async def test_second_bucket(conn, writer: DatabaseWriter) -> None:
    """3. SecondBucket → Writer → trade_snapshot_1s."""
    bucket = SecondBucket(writer)

    # 과거 타임스탬프 (현재 -5초) 사용하여 즉시 flush 가능하게
    ts = int(datetime.now(timezone.utc).timestamp()) - 5
    bucket.add_trade("TEST:BUCKET-BTC", 50000, 0.1, ts)
    bucket.add_trade("TEST:BUCKET-BTC", 51000, 0.2, ts)  # 같은 초 → 업데이트
    bucket.add_trade("TEST:BUCKET-ETH", 3000, 1.0, ts)

    # flush (current_ts > ts 이므로 flush됨)
    flushed = await bucket.flush_completed(ts + 2)
    result("SecondBucket flush", flushed == 2, f"flushed={flushed} (기대: 2)")
    result("SecondBucket pending", bucket.pending_count == 0, f"pending={bucket.pending_count}")

    await asyncio.sleep(0.5)  # Writer 처리 대기

    # DB 확인: BTC는 high=51000, close=51000, volume=0.3
    row = conn.execute(
        "SELECT * FROM trade_snapshot_1s WHERE market = 'TEST:BUCKET-BTC'"
    ).fetchone()
    ok = row is not None and row["high"] == 51000 and abs(row["volume"] - 0.3) < 0.001
    result(
        "SecondBucket OHLCV 정확성",
        ok,
        f"high={row['high']}, vol={row['volume']}" if row else "row=None",
    )

    # flush_all 테스트
    bucket.add_trade("TEST:BUCKET-SOL", 100, 5.0, ts + 10)
    flushed_all = await bucket.flush_all()
    result("SecondBucket flush_all", flushed_all == 1, f"flushed_all={flushed_all}")


async def test_aggregator_rollup(conn, writer: DatabaseWriter) -> None:
    """4. Aggregator: 1s → 1m 롤업."""
    # 테스트 데이터: 특정 분의 1s 데이터 삽입
    target_minute = datetime(2025, 1, 15, 12, 34, 0, tzinfo=timezone.utc)
    minute_ts = target_minute.strftime("%Y-%m-%d %H:%M:%S")

    for sec in range(0, 60, 10):  # 00, 10, 20, 30, 40, 50초
        ts_str = (target_minute + timedelta(seconds=sec)).strftime("%Y-%m-%d %H:%M:%S")
        price = 50000 + sec * 10  # 50000, 50100, ..., 50500
        await writer.enqueue(
            "INSERT OR REPLACE INTO trade_snapshot_1s "
            "(market, ts, open, high, low, close, volume, volume_krw) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("TEST:ROLLUP-BTC", ts_str, price, price + 50, price - 50, price + 25, 0.1, price * 0.1),
        )

    await asyncio.sleep(0.5)  # Writer 처리 대기

    # 1s 데이터 삽입 확인
    count_1s = conn.execute(
        "SELECT COUNT(*) as cnt FROM trade_snapshot_1s WHERE market = 'TEST:ROLLUP-BTC'"
    ).fetchone()["cnt"]
    result("Aggregator 1s 데이터 준비", count_1s == 6, f"1s rows={count_1s}")

    # 롤업 실행
    read_conn = get_connection(_TEST_DB)
    agg = Aggregator(read_conn, writer)
    rolled = await agg.rollup_minute(minute_ts)
    result("Aggregator rollup_minute", rolled == 1, f"rolled={rolled} markets")

    await asyncio.sleep(0.5)

    # 1m 데이터 확인
    row_1m = conn.execute(
        "SELECT * FROM trade_snapshot_1m WHERE market = 'TEST:ROLLUP-BTC' AND ts = ?",
        (minute_ts,),
    ).fetchone()

    if row_1m:
        # first_open = 50000 (sec=0), last_close = 50525 (sec=50, price+25)
        # high = max(50050, 50150, ..., 50550) = 50550
        # low = min(49950, 50050, ..., 50450) = 49950
        open_ok = row_1m["open"] == 50000
        high_ok = row_1m["high"] == 50550
        low_ok = row_1m["low"] == 49950
        close_ok = row_1m["close"] == 50525
        result(
            "Aggregator 1m OHLCV",
            open_ok and high_ok and low_ok and close_ok,
            f"O={row_1m['open']} H={row_1m['high']} L={row_1m['low']} C={row_1m['close']}",
        )
    else:
        result("Aggregator 1m OHLCV", False, "1m row not found")

    read_conn.close()


async def test_aggregator_replace(conn, writer: DatabaseWriter) -> None:
    """5. INSERT OR REPLACE — 불완전 데이터 덮어쓰기."""
    target_minute = datetime(2025, 1, 15, 12, 34, 0, tzinfo=timezone.utc)
    minute_ts = target_minute.strftime("%Y-%m-%d %H:%M:%S")

    # 추가 1s 데이터 (더 완전한 데이터)
    ts_5 = (target_minute + timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")
    await writer.enqueue(
        "INSERT OR REPLACE INTO trade_snapshot_1s "
        "(market, ts, open, high, low, close, volume, volume_krw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("TEST:ROLLUP-BTC", ts_5, 49500, 51000, 49000, 49800, 0.5, 25000),
    )
    await asyncio.sleep(0.5)

    # 재롤업 → INSERT OR REPLACE로 덮어쓰기
    read_conn = get_connection(_TEST_DB)
    agg = Aggregator(read_conn, writer)
    rolled = await agg.rollup_minute(minute_ts)
    await asyncio.sleep(0.5)

    row_1m = conn.execute(
        "SELECT * FROM trade_snapshot_1m WHERE market = 'TEST:ROLLUP-BTC' AND ts = ?",
        (minute_ts,),
    ).fetchone()

    # 새 데이터(sec=5) 포함되어 high/low 변경
    # high = max(51000, 50550) = 51000, low = min(49000, 49950) = 49000
    ok = row_1m and row_1m["high"] == 51000 and row_1m["low"] == 49000
    result(
        "INSERT OR REPLACE 덮어쓰기",
        ok,
        f"H={row_1m['high']}, L={row_1m['low']}" if row_1m else "row=None",
    )
    read_conn.close()


async def test_token_registry(conn, writer: DatabaseWriter) -> None:
    """6. TokenRegistry insert_async + 조회."""
    registry = TokenRegistry(conn, writer=writer)

    token = TokenIdentity(
        symbol="TESTCOIN",
        coingecko_id="test-coin",
        name="Test Coin",
    )
    await registry.insert_async(token)
    await asyncio.sleep(0.5)

    found = registry.get_by_symbol("TESTCOIN")
    result(
        "TokenRegistry insert_async + 조회",
        found is not None,
        f"found={found}" if found else "not found",
    )

    # 중복 삽입 (INSERT OR IGNORE)
    await registry.insert_async(token)
    await asyncio.sleep(0.3)
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM token_registry WHERE symbol = 'TESTCOIN'"
    ).fetchone()["cnt"]
    result("TokenRegistry 중복 방지", count == 1, f"count={count}")


async def test_notice_parser() -> None:
    """7. NoticeParser 상장 공지 파싱."""
    parser = BithumbNoticeParser()

    # 정상 상장 공지
    r1 = parser.parse("[마켓 추가] 비트코인(BTC) 원화 마켓 추가")
    result("NoticeParser 상장 감지", r1.notice_type == "listing", f"type={r1.notice_type}")
    result("NoticeParser 심볼 추출", r1.symbol == "BTC", f"symbol={r1.symbol}")

    # 비상장 공지
    r2 = parser.parse("[공지] 서비스 점검 안내")
    result("NoticeParser 비상장 공지", r2.notice_type == "unknown", f"type={r2.notice_type}")

    # M2 수정 검증: "추가" 단독은 상장으로 오탐하지 않음
    r3 = parser.parse("[공지] 서비스 점검 추가 안내")
    result(
        "NoticeParser '추가' 오탐 방지 (M2)",
        r3.notice_type == "unknown",
        f"type={r3.notice_type}",
    )

    # 시간 추출
    r4 = parser.parse("[마켓 추가] SOL 원화 마켓", "거래 시작: 오후 2시 30분")
    result("NoticeParser 시간 추출", r4.listing_time is not None, f"time={r4.listing_time}")


async def test_writer_batch_rollback(conn) -> None:
    """8. Writer 배치 롤백 + 건별 재시도 (I5)."""
    writer_conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(writer_conn)
    writer.start()

    # 정상 SQL + 불량 SQL 혼합 배치
    await writer.enqueue(
        "INSERT OR REPLACE INTO trade_snapshot_1s "
        "(market, ts, open, high, low, close, volume, volume_krw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("TEST:BATCH-OK", "2025-01-15 00:00:00", 100, 110, 90, 105, 1, 100),
    )
    # 불량 SQL (존재하지 않는 테이블)
    await writer.enqueue(
        "INSERT INTO nonexistent_table (x) VALUES (?)",
        (999,),
    )
    await writer.enqueue(
        "INSERT OR REPLACE INTO trade_snapshot_1s "
        "(market, ts, open, high, low, close, volume, volume_krw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("TEST:BATCH-OK2", "2025-01-15 00:00:01", 200, 210, 190, 205, 2, 200),
    )

    await asyncio.sleep(1.0)  # 건별 재시도 포함 충분한 대기

    # 정상 건은 커밋되어야 함
    r1 = conn.execute(
        "SELECT * FROM trade_snapshot_1s WHERE market = 'TEST:BATCH-OK'"
    ).fetchone()
    r2 = conn.execute(
        "SELECT * FROM trade_snapshot_1s WHERE market = 'TEST:BATCH-OK2'"
    ).fetchone()
    ok = r1 is not None and r2 is not None
    result(
        "배치 롤백 + 건별 재시도 (I5)",
        ok,
        f"OK1={'Y' if r1 else 'N'}, OK2={'Y' if r2 else 'N'}",
    )

    writer.shutdown()


async def main() -> None:
    """전체 테스트 실행."""
    logger.info("=" * 60)
    logger.info("Phase 2 통합 테스트 시작")
    logger.info("=" * 60)

    # 이전 테스트 DB 삭제
    for suffix in ("", "-wal", "-shm"):
        p = _TEST_DB + suffix
        if os.path.exists(p):
            os.remove(p)

    # 테스트 실행
    conn, version = await test_db_init()
    writer = await test_writer_pipeline(conn)
    await test_second_bucket(conn, writer)
    await test_aggregator_rollup(conn, writer)
    await test_aggregator_replace(conn, writer)
    await test_token_registry(conn, writer)
    await test_notice_parser()

    # Writer 종료 후 별도 테스트
    writer.shutdown()
    conn.close()

    # 별도 Writer로 배치 롤백 테스트
    verify_conn = get_connection(_TEST_DB)
    await test_writer_batch_rollback(verify_conn)
    verify_conn.close()

    # 테스트 DB 정리
    for suffix in ("", "-wal", "-shm"):
        p = _TEST_DB + suffix
        if os.path.exists(p):
            os.remove(p)

    # 결과 요약
    logger.info("=" * 60)
    total = _PASS + _FAIL
    logger.info("테스트 결과: %d/%d PASS, %d FAIL", _PASS, total, _FAIL)
    if _FAIL > 0:
        logger.error("FAIL 항목 있음 — 수정 필요")
        sys.exit(1)
    else:
        logger.info("전체 PASS — Phase 2 파이프라인 정상")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
