"""상장 모니터링 데몬.

상장 공지 감지 → GO/NO-GO 분석 → 텔레그램 알림 자동 실행.

사용법:
    python listing_daemon.py
    
Railway에서 별도 서비스로 실행 권장.
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("listing_daemon")

# 모니터링 간격 (초)
POLL_INTERVAL = int(os.environ.get("LISTING_POLL_INTERVAL", "30"))


async def on_listing_detected(notice: dict) -> None:
    """상장 공지 감지 콜백."""
    from pipelines.listing_pipeline import process_new_listing
    
    symbol = notice.get("symbol")
    exchange = notice.get("exchange", "bithumb")
    listing_type = notice.get("listing_type", "직상장")
    
    if not symbol:
        logger.warning(f"심볼 없는 공지 무시: {notice}")
        return
    
    logger.info(f"🚀 상장 감지: {symbol} @ {exchange} ({listing_type})")
    
    try:
        result = await process_new_listing(
            symbol=symbol,
            exchange=exchange,
            listing_type=listing_type,
        )
        
        if result:
            logger.info(
                f"✅ 분석 완료: {symbol} → {result.go_signal} "
                f"({result.score:.0f}점) | 알림: {'✓' if result.alert_sent else '✗'}"
            )
    except Exception as e:
        logger.error(f"파이프라인 실행 실패: {e}")


async def run_daemon(stop_event: asyncio.Event) -> None:
    """데몬 메인 루프."""
    from collectors.listing_monitor import ListingMonitor
    
    logger.info("="*50)
    logger.info("🔍 상장 모니터링 데몬 시작")
    logger.info(f"   폴링 간격: {POLL_INTERVAL}초")
    logger.info("="*50)
    
    # 상태 파일 경로
    state_file = _ROOT / "data" / "listing_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    monitor = ListingMonitor(
        on_listing=on_listing_detected,
        poll_interval=float(POLL_INTERVAL),
        state_file=str(state_file),
    )
    
    try:
        await monitor.run(stop_event)
    except Exception as e:
        logger.error(f"모니터링 오류: {e}")
        raise


async def main() -> None:
    """메인 함수."""
    stop_event = asyncio.Event()
    
    # 시그널 핸들링
    loop = asyncio.get_running_loop()
    
    if sys.platform == "win32":
        def _win_handler(signum: int, frame: object) -> None:
            loop.call_soon_threadsafe(stop_event.set)
        
        signal.signal(signal.SIGINT, _win_handler)
        signal.signal(signal.SIGTERM, _win_handler)
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
    
    try:
        await run_daemon(stop_event)
    except KeyboardInterrupt:
        logger.info("키보드 인터럽트")
    finally:
        logger.info("데몬 종료")


if __name__ == "__main__":
    asyncio.run(main())
