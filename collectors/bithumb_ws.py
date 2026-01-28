"""빗썸 WebSocket 수집기 (델타 동기화 방식).

빗썸 WS 특성:
- JSON 텍스트 수신
- 오더북: 델타 업데이트 (price=0 → 삭제)
- 재연결 시 오더북 캐시 전체 무효화 필요
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from store.writer import DatabaseWriter

from .robust_ws import RobustWebSocket
from .second_bucket import SecondBucket

logger = logging.getLogger(__name__)

_BITHUMB_WS_URL = "wss://pubwss.bithumb.com/pub/ws"
_MAX_OB_LEVELS = 50  # 오더북 사이드별 최대 가격 레벨 수


class BithumbCollector(RobustWebSocket):
    """빗썸 체결(transaction) 데이터 수집기."""

    def __init__(
        self,
        markets: list[str],
        writer: DatabaseWriter,
    ) -> None:
        """
        Args:
            markets: 감시 마켓 목록. 예: ["BTC_KRW", "ETH_KRW"]
            writer: DatabaseWriter 인스턴스.
        """
        super().__init__(url=_BITHUMB_WS_URL)
        self.markets = markets
        self.writer = writer
        self._bucket = SecondBucket(writer)

        # 오더북 캐시 (Phase 1: 메모리만, DB 저장 안 함)
        self._orderbook_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # 추상 메서드 구현
    # ------------------------------------------------------------------

    async def subscribe(self) -> None:
        """빗썸 transaction + orderbookdepth 구독."""
        # transaction 구독
        tx_msg = json.dumps({
            "type": "transaction",
            "symbols": self.markets,
        })
        await self.send(tx_msg)

        # orderbookdepth 구독 (메모리 캐시용)
        ob_msg = json.dumps({
            "type": "orderbookdepth",
            "symbols": self.markets,
        })
        await self.send(ob_msg)

        logger.info("[BithumbCollector] 구독 전송: %d 마켓", len(self.markets))

    async def on_message(self, data: bytes | str) -> None:
        """수신 메시지 분기."""
        msg = self._decode(data)
        if msg is None:
            return

        msg_type = msg.get("type")
        content = msg.get("content")
        if not content:
            status = msg.get("status")
            if status:
                logger.debug("[BithumbCollector] status=%s", status)
            return

        if msg_type == "transaction":
            await self._handle_transaction(content)
        elif msg_type == "orderbookdepth":
            self._handle_orderbookdepth(content)

    async def on_reconnected(self) -> None:
        """재연결 시 오더북 캐시 전체 무효화."""
        self._orderbook_cache.clear()
        logger.info("[BithumbCollector] 재연결 완료, 오더북 캐시 초기화")

    async def _fetch_gap_data(self, gap_seconds: float) -> None:
        """REST API로 누락 데이터 보충.

        Phase 1: 로그만 남김. Phase 2에서 빗썸 REST API 구현.
        """
        logger.warning(
            "[BithumbCollector] %0.1f초 gap 발생, REST 보충 미구현 (Phase 2)",
            gap_seconds,
        )

    # ------------------------------------------------------------------
    # Transaction 처리
    # ------------------------------------------------------------------

    async def _handle_transaction(self, content: dict) -> None:
        """체결 데이터 → SecondBucket 집계."""
        tx_list = content.get("list", [])

        for tx in tx_list:
            symbol = tx.get("symbol", "")   # "BTC_KRW"
            price_str = tx.get("contPrice", "0")
            volume_str = tx.get("contQty", "0")
            ts_str = tx.get("contDtm")      # "2024-01-15 12:34:56.123456"

            try:
                price = float(price_str.replace(",", ""))
                volume = float(volume_str.replace(",", ""))
            except (ValueError, AttributeError):
                continue

            if not symbol or not price:
                continue

            market = f"BITHUMB:{symbol}"
            ts_sec = self._parse_ts(ts_str)

            self._bucket.add_trade(market, price, volume, ts_sec)
            await self._bucket.flush_completed(ts_sec)

    # ------------------------------------------------------------------
    # Orderbookdepth 처리 (메모리 캐시만)
    # ------------------------------------------------------------------

    def _handle_orderbookdepth(self, content: dict) -> None:
        """오더북 델타 → 메모리 캐시 병합."""
        ob_list = content.get("list", [])

        for entry in ob_list:
            symbol = entry.get("symbol", "")
            order_type = entry.get("orderType", "")  # "ask" / "bid"
            price_str = entry.get("price", "0")
            qty_str = entry.get("quantity", "0")

            try:
                price = float(price_str.replace(",", ""))
                qty = float(qty_str.replace(",", ""))
            except (ValueError, AttributeError):
                continue

            if not symbol:
                continue

            self._merge_orderbook_delta(symbol, order_type, price, qty)

    def _merge_orderbook_delta(
        self, symbol: str, side: str, price: float, qty: float
    ) -> None:
        """기존 캐시에 변경분 병합. qty=0이면 해당 가격 삭제.

        사이드별 최대 _MAX_OB_LEVELS 레벨 유지 (메모리 상한).
        """
        if symbol not in self._orderbook_cache:
            self._orderbook_cache[symbol] = {"asks": {}, "bids": {}}

        book = self._orderbook_cache[symbol]
        side_key = "asks" if side == "ask" else "bids"

        if qty == 0:
            book[side_key].pop(price, None)
        else:
            book[side_key][price] = qty

            # 레벨 수 초과 시 트림 (asks: 높은 가격 제거, bids: 낮은 가격 제거)
            levels = book[side_key]
            if len(levels) > _MAX_OB_LEVELS:
                sorted_prices = sorted(levels.keys(), reverse=(side_key == "bids"))
                for p in sorted_prices[_MAX_OB_LEVELS:]:
                    del levels[p]

    # ------------------------------------------------------------------
    # Phase 2: 동적 구독 + Shutdown flush
    # ------------------------------------------------------------------

    async def flush_pending(self) -> int:
        """Shutdown 시 미완료 SecondBucket 데이터 flush."""
        return await self._bucket.flush_all()

    async def add_market(self, market: str) -> None:
        """실행 중 마켓 동적 추가 — WS 재구독.

        MarketMonitor가 신규 상장 감지 시 호출.
        """
        if market in self.markets:
            return
        self.markets.append(market)
        logger.info("[BithumbCollector] 마켓 추가: %s (총 %d)", market, len(self.markets))
        await self.subscribe()

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    _KST = timezone(timedelta(hours=9))

    @staticmethod
    def _parse_ts(ts_str: Optional[str]) -> int:
        """빗썸 contDtm 문자열 → epoch 초.

        빗썸은 KST(UTC+9) 기준 시각을 반환.
        naive datetime에 KST tzinfo를 명시적으로 부여하여
        시스템 타임존에 무관하게 올바른 UTC epoch를 산출.
        """
        if not ts_str:
            return int(datetime.now(timezone.utc).timestamp())
        try:
            # "2024-01-15 12:34:56.123456" → KST 기준
            dt_naive = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
            dt_kst = dt_naive.replace(tzinfo=BithumbCollector._KST)
            return int(dt_kst.timestamp())
        except (ValueError, TypeError):
            return int(datetime.now(timezone.utc).timestamp())

    @staticmethod
    def _decode(data: bytes | str) -> Optional[dict]:
        """빗썸 WS 메시지 디코딩."""
        try:
            if isinstance(data, bytes):
                return json.loads(data.decode("utf-8"))
            return json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("메시지 디코딩 실패: %s", e)
            return None
