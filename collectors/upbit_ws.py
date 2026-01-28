"""업비트 WebSocket 수집기 (스냅샷 교체 방식).

업비트 WS 특성:
- 기본 JSON 텍스트 수신 (format=SIMPLE은 데이터 미수신 이슈로 미사용)
- 120초 idle timeout → ping_interval=30 으로 방지
- 오더북: 전체 스냅샷 교체 (델타 아님)
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from store.writer import DatabaseWriter

from .robust_ws import RobustWebSocket
from .second_bucket import SecondBucket

logger = logging.getLogger(__name__)

_UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1"


class UpbitCollector(RobustWebSocket):
    """업비트 체결(trade) 데이터 수집기."""

    def __init__(
        self,
        markets: list[str],
        writer: DatabaseWriter,
        *,
        ping_interval: float = 30.0,
    ) -> None:
        """
        Args:
            markets: 감시 마켓 목록. 예: ["KRW-BTC", "KRW-ETH"]
            writer: DatabaseWriter 인스턴스.
        """
        super().__init__(
            url=_UPBIT_WS_URL,
            ping_interval=ping_interval,
        )
        self.markets = markets
        self.writer = writer
        self._bucket = SecondBucket(writer)

    # ------------------------------------------------------------------
    # 추상 메서드 구현
    # ------------------------------------------------------------------

    async def subscribe(self) -> None:
        """업비트 trade 구독."""
        ticket = str(uuid.uuid4())[:8]
        payload = json.dumps([
            {"ticket": f"upbit-{ticket}"},
            {"type": "trade", "codes": self.markets},
        ])
        await self.send(payload)
        logger.info("[UpbitCollector] 구독 전송: %d 마켓", len(self.markets))

    async def on_message(self, data: bytes | str) -> None:
        """수신 메시지 파싱 → SecondBucket 집계."""
        msg = self._decode(data)
        if msg is None:
            return

        msg_type = msg.get("type")
        if msg_type == "trade":
            await self._handle_trade(msg)

    async def on_reconnected(self) -> None:
        """재연결 시 집계 버퍼 유지 (스냅샷 방식이라 리셋 불필요)."""
        logger.info("[UpbitCollector] 재연결 완료, 수신 재개")

    async def _fetch_gap_data(self, gap_seconds: float) -> None:
        """REST API로 누락 데이터 보충.

        Phase 1: 로그만 남김. Phase 2에서 업비트 REST API 구현.
        """
        logger.warning(
            "[UpbitCollector] %0.1f초 gap 발생, REST 보충 미구현 (Phase 2)",
            gap_seconds,
        )

    # ------------------------------------------------------------------
    # Trade 처리
    # ------------------------------------------------------------------

    async def _handle_trade(self, msg: dict) -> None:
        """체결 데이터 → SecondBucket 집계."""
        code = msg.get("code", "")           # "KRW-BTC"
        price = msg.get("trade_price", 0.0)
        volume = msg.get("trade_volume", 0.0)

        if not code or not price:
            return

        market = f"UPBIT:{code}"

        # 체결 시간에서 1초 단위 타임스탬프
        # trade_timestamp: 밀리초 epoch
        ts_ms = msg.get("trade_timestamp")
        if ts_ms:
            ts_sec = int(ts_ms) // 1000
        else:
            ts_sec = int(datetime.now(timezone.utc).timestamp())

        self._bucket.add_trade(market, price, volume, ts_sec)
        await self._bucket.flush_completed(ts_sec)

    # ------------------------------------------------------------------
    # Phase 2: 동적 구독 + Shutdown flush
    # ------------------------------------------------------------------

    async def flush_pending(self) -> int:
        """Shutdown 시 미완료 SecondBucket 데이터 flush.

        daemon에서 private _bucket 직접 접근 대신 이 메서드 사용.
        """
        return await self._bucket.flush_all()

    async def add_market(self, market: str) -> None:
        """실행 중 마켓 동적 추가 — WS 재구독.

        MarketMonitor가 신규 상장 감지 시 호출.
        """
        if market in self.markets:
            return
        self.markets.append(market)
        logger.info("[UpbitCollector] 마켓 추가: %s (총 %d)", market, len(self.markets))
        # 업비트: 전체 재구독 (추가 구독 메시지)
        await self.subscribe()

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    @staticmethod
    def _decode(data: bytes | str) -> Optional[dict]:
        """업비트 WS 메시지 디코딩 (JSON 텍스트)."""
        try:
            if isinstance(data, bytes):
                return json.loads(data.decode("utf-8"))
            return json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("메시지 디코딩 실패: %s", e)
            return None
