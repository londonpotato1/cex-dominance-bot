"""1초 단위 OHLCV 인메모리 집계.

개별 체결(trade) → trade_snapshot_1s(1초 캔들) 사이의 집계 로직.
Phase 2에서 aggregator.py로 리팩터링 예정.
"""

import logging
from datetime import datetime, timezone

from store.writer import DatabaseWriter

logger = logging.getLogger(__name__)

_INSERT_TRADE_1S = """
    INSERT OR REPLACE INTO trade_snapshot_1s
        (market, ts, open, high, low, close, volume, volume_krw)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


class SecondBucket:
    """1초 단위 OHLCV 인메모리 집계 → 초 변경 시 flush.

    사용법:
        bucket = SecondBucket(writer)
        bucket.add_trade("UPBIT:KRW-BTC", 100_000, 0.5, 1706400000)
        await bucket.flush_completed(1706400001)
    """

    def __init__(self, writer: DatabaseWriter) -> None:
        self._writer = writer
        # (market, ts_sec) → {open, high, low, close, volume, volume_krw}
        self._buckets: dict[tuple[str, int], dict] = {}

    def add_trade(
        self,
        market: str,
        price: float,
        volume: float,
        ts_sec: int,
    ) -> None:
        """개별 체결을 1초 버킷에 집계."""
        volume_krw = price * volume
        key = (market, ts_sec)

        if key not in self._buckets:
            self._buckets[key] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume,
                "volume_krw": volume_krw,
            }
        else:
            b = self._buckets[key]
            b["high"] = max(b["high"], price)
            b["low"] = min(b["low"], price)
            b["close"] = price
            b["volume"] += volume
            b["volume_krw"] += volume_krw

    async def flush_completed(self, current_ts_sec: int) -> int:
        """현재 초보다 이전 버킷들을 DB에 flush.

        Returns:
            flush된 버킷 수.
        """
        completed_keys = [
            k for k in self._buckets if k[1] < current_ts_sec
        ]

        for key in completed_keys:
            market, ts_sec = key
            b = self._buckets.pop(key)
            ts_str = datetime.fromtimestamp(ts_sec, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            await self._writer.enqueue(
                _INSERT_TRADE_1S,
                (
                    market,
                    ts_str,
                    b["open"],
                    b["high"],
                    b["low"],
                    b["close"],
                    b["volume"],
                    b["volume_krw"],
                ),
            )

        return len(completed_keys)

    async def flush_all(self) -> int:
        """모든 버킷 강제 flush (shutdown 시)."""
        all_keys = list(self._buckets.keys())
        for key in all_keys:
            market, ts_sec = key
            b = self._buckets.pop(key)
            ts_str = datetime.fromtimestamp(ts_sec, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            await self._writer.enqueue(
                _INSERT_TRADE_1S,
                (
                    market,
                    ts_str,
                    b["open"],
                    b["high"],
                    b["low"],
                    b["close"],
                    b["volume"],
                    b["volume_krw"],
                ),
            )
        return len(all_keys)

    @property
    def pending_count(self) -> int:
        """아직 flush 안 된 버킷 수."""
        return len(self._buckets)
