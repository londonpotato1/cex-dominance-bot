"""CEX Dominance Bot 수집 데몬.

시작 순서:
  1. DB 커넥션 + 마이그레이션 (실패 시 즉시 종료)
  2. Writer 스레드 시작
  3. CoinGecko 부트스트랩 (token_registry)
  4. WS 수집기 시작 (업비트 + 빗썸)
  5. Aggregator 시작 (롤업 + self-healing)
  6. MarketMonitor 시작 (상장 감지)
  7. Health 갱신 루프 시작

종료 순서 (Graceful Shutdown):
  1. stop_event.set() → 모든 루프에 종료 신호
  2. WS 수집기 close
  3. flush_pending() → 미완료 1s 데이터 flush (캡슐화 준수)
  4. Aggregator force_rollup_current (진행 중 분 데이터)
  5. Writer shutdown (sentinel → 잔여 flush → thread.join)
  6. DB 연결 종료

사용법:
    python collector_daemon.py
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

from store.database import get_connection, apply_migrations
from store.writer import DatabaseWriter
from store.token_registry import TokenRegistry, bootstrap_top_tokens
from collectors.upbit_ws import UpbitCollector
from collectors.bithumb_ws import BithumbCollector
from collectors.aggregator import Aggregator
from collectors.market_monitor import MarketMonitor
from analysis.premium import PremiumCalculator
from analysis.cost_model import CostModel
from analysis.gate import GateChecker
from alerts.telegram import TelegramAlert

# 로깅 설정: 이미 설정된 핸들러가 있으면 재설정하지 않음
# (app.py에서 파일 핸들러를 설정했을 수 있음)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
logger = logging.getLogger("collector_daemon")

# ---- 감시 마켓 (Phase 2: 주요 20개) ----
UPBIT_MARKETS = [
    "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-MATIC",
    "KRW-SHIB", "KRW-TRX", "KRW-ETC", "KRW-ATOM", "KRW-NEAR",
    "KRW-BCH", "KRW-APT", "KRW-ARB", "KRW-OP", "KRW-SUI",
]

BITHUMB_MARKETS = [
    "BTC_KRW", "ETH_KRW", "XRP_KRW", "SOL_KRW", "DOGE_KRW",
    "ADA_KRW", "AVAX_KRW", "LINK_KRW", "DOT_KRW", "MATIC_KRW",
    "SHIB_KRW", "TRX_KRW", "ETC_KRW", "ATOM_KRW", "NEAR_KRW",
    "BCH_KRW", "APT_KRW", "ARB_KRW", "OP_KRW", "SUI_KRW",
]

# ---- health.json 경로 (Railway Volume 지원) ----
_HEALTH_PATH = Path(os.environ.get("HEALTH_PATH", str(_ROOT / "health.json")))
_HEALTH_INTERVAL = 30.0  # 초


async def main() -> None:
    """데몬 메인 함수."""

    # ---- 1. DB 초기화 ----
    logger.info("DB 초기화 시작")
    conn = get_connection()
    try:
        schema_version = apply_migrations(conn)
    except Exception as e:
        logger.critical("마이그레이션 실패 — 즉시 종료: %s", e)
        conn.close()
        sys.exit(1)
    logger.info("DB 준비 완료 (스키마 v%d)", schema_version)

    # ---- 2. Writer 시작 ----
    writer_conn = get_connection()
    writer = DatabaseWriter(writer_conn)
    writer.start()

    # ---- 3. 읽기 전용 커넥션 ----
    read_conn = get_connection()

    # ---- 4. Token Registry (CoinGecko 부트스트랩은 백그라운드에서) ----
    registry = TokenRegistry(read_conn, writer=writer)
    # 부트스트랩은 별도 태스크로 실행하여 데몬 시작 차단 방지
    async def _background_bootstrap():
        try:
            bootstrap_count = await asyncio.wait_for(
                bootstrap_top_tokens(registry),
                timeout=120.0,  # 2분 타임아웃
            )
            logger.info("CoinGecko 부트스트랩 완료: %d개 토큰", bootstrap_count)
        except asyncio.TimeoutError:
            logger.warning("CoinGecko 부트스트랩 타임아웃 (2분) — 계속 진행")
        except Exception as e:
            logger.warning("CoinGecko 부트스트랩 실패 (계속 진행): %s", e)

    # ---- 5. 종료 이벤트 ----
    stop_event = asyncio.Event()

    # ---- 6a. Phase 3 분석 컴포넌트 생성 ----
    try:
        premium_calc = PremiumCalculator(writer)
        cost_model = CostModel()
        gate_checker = GateChecker(premium_calc, cost_model, writer)
        alert = TelegramAlert(writer, read_conn)
        logger.info(
            "Phase 3 컴포넌트 초기화 (텔레그램: %s)",
            "설정됨" if alert.is_configured else "미설정 (로그만)",
        )
    except Exception as e:
        logger.critical("Phase 3 컴포넌트 초기화 실패 — 즉시 종료: %s", e)
        writer.shutdown()
        read_conn.close()
        conn.close()
        sys.exit(1)

    # ---- 6b. 수집 컴포넌트 생성 ----
    upbit = UpbitCollector(markets=list(UPBIT_MARKETS), writer=writer)
    bithumb = BithumbCollector(markets=list(BITHUMB_MARKETS), writer=writer)
    aggregator = Aggregator(read_conn, writer)
    monitor = MarketMonitor(
        writer, registry, upbit, bithumb,
        gate_checker=gate_checker, alert=alert,
    )

    # ---- 7. 태스크 실행 ----
    tasks = [
        asyncio.create_task(upbit.run(), name="upbit"),
        asyncio.create_task(bithumb.run(), name="bithumb"),
        asyncio.create_task(aggregator.run(stop_event), name="aggregator"),
        asyncio.create_task(monitor.run(stop_event), name="monitor"),
        asyncio.create_task(
            _health_loop(writer, upbit, bithumb, schema_version, stop_event),
            name="health",
        ),
        asyncio.create_task(_background_bootstrap(), name="bootstrap"),
    ]

    # ---- 7b. Telegram 인터랙티브 봇 (Feature Flag) ----
    features = gate_checker._features
    if features.get("telegram_interactive") and alert.is_configured:
        from alerts.telegram_bot import TelegramBot
        bot = TelegramBot(
            alert._bot_token, alert._chat_id,
            read_conn, gate_checker, writer,
        )
        tasks.append(asyncio.create_task(bot.run(stop_event), name="telegram_bot"))
        logger.info("Telegram 인터랙티브 봇 활성화")
    else:
        logger.info(
            "Telegram 봇 비활성 (feature=%s, configured=%s)",
            features.get("telegram_interactive", False),
            alert.is_configured,
        )

    logger.info(
        "데몬 시작 완료: 업비트 %d마켓, 빗썸 %d마켓",
        len(UPBIT_MARKETS), len(BITHUMB_MARKETS),
    )

    # ---- 8. 시그널 핸들링 (메인 스레드에서만) ----
    loop = asyncio.get_running_loop()
    import threading
    is_main_thread = threading.current_thread() is threading.main_thread()

    if is_main_thread:
        if sys.platform == "win32":
            # Windows: signal 모듈 사용.
            def _win_handler(signum: int, frame: object) -> None:
                loop.call_soon_threadsafe(stop_event.set)

            signal.signal(signal.SIGINT, _win_handler)
            signal.signal(signal.SIGTERM, _win_handler)
        else:
            # Unix: 이벤트루프 시그널 핸들러
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop_event.set)
    else:
        # 백그라운드 스레드: signal 핸들러 설정 불가, 무한 실행
        logger.info("백그라운드 스레드 실행 모드 (signal 핸들러 없음)")

    # ---- 9. 실행 대기 ----
    # 백그라운드 스레드 모드에서는 태스크가 끝날 때까지 대기
    if not is_main_thread:
        logger.info("백그라운드 모드: gather로 태스크 실행")
        try:
            # gather는 모든 태스크가 완료되거나 예외 발생 시 반환
            # WS 태스크는 무한 실행이므로 정상적으로는 여기서 영원히 대기
            await asyncio.gather(*tasks)
            logger.warning("백그라운드 모드: 모든 태스크 완료 — 예상치 못한 종료")
        except Exception as e:
            logger.error(f"백그라운드 모드: 태스크 예외 발생 — {type(e).__name__}: {e}")
            raise
    else:
        await stop_event.wait()
        logger.info("종료 시그널 수신, Graceful Shutdown 시작")

    # ---- 10. Graceful Shutdown ----
    await _graceful_shutdown(upbit, bithumb, aggregator, writer, tasks, alert)
    read_conn.close()
    conn.close()
    logger.info("데몬 종료 완료")


async def _health_loop(
    writer: DatabaseWriter,
    upbit: UpbitCollector,
    bithumb: BithumbCollector,
    schema_version: int,
    stop_event: asyncio.Event,
) -> None:
    """30초마다 health.json 갱신 (원자적 교체)."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=_HEALTH_INTERVAL
            )
            break
        except asyncio.TimeoutError:
            pass

        try:
            health_data = {
                "heartbeat_timestamp": time.time(),
                "schema_version": schema_version,
                "ws_connected": {
                    "upbit": upbit.is_connected,
                    "bithumb": bithumb.is_connected,
                },
                "last_msg_time": {
                    "upbit": upbit.last_msg_time,
                    "bithumb": bithumb.last_msg_time,
                },
                "queue_size": writer.queue_size,
                "queue_drops": writer.drop_count,
                "last_trade_time": max(
                    upbit.last_msg_time,
                    bithumb.last_msg_time,
                ),
            }

            # 원자적 교체: tmp에 쓰고 rename
            tmp_path = str(_HEALTH_PATH) + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(health_data, f, indent=2)
            os.replace(tmp_path, str(_HEALTH_PATH))

        except Exception as e:
            logger.debug("Health 갱신 실패: %s", e)


async def _graceful_shutdown(
    upbit: UpbitCollector,
    bithumb: BithumbCollector,
    aggregator: Aggregator,
    writer: DatabaseWriter,
    tasks: list[asyncio.Task],
    alert: TelegramAlert | None = None,
) -> None:
    """Graceful Shutdown 시퀀스."""
    # 1. WS 종료
    logger.info("Shutdown 1/6: WS 수집기 종료")
    await upbit.close()
    await bithumb.close()

    # 2. SecondBucket flush (public 메서드 경유)
    logger.info("Shutdown 2/6: 미완료 SecondBucket flush")
    upbit_flushed = await upbit.flush_pending()
    bithumb_flushed = await bithumb.flush_pending()
    logger.info(
        "SecondBucket flush: 업비트 %d건, 빗썸 %d건",
        upbit_flushed, bithumb_flushed,
    )

    # 3. Aggregator 강제 롤업
    logger.info("Shutdown 3/6: Aggregator 강제 롤업")
    await aggregator.force_rollup_current()

    # 4. 알림 배치 flush (Phase 3)
    if alert:
        logger.info("Shutdown 4/6: 알림 배치 flush")
        await alert.flush_batch()

    # 5. 태스크 취소
    logger.info("Shutdown 5/6: 태스크 취소")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    # 6. Writer 종료
    logger.info("Shutdown 6/6: Writer 종료")
    writer.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("프로세스 종료 (KeyboardInterrupt)")
