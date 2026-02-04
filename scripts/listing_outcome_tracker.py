#!/usr/bin/env python3
"""
Track post-listing pump and store outcomes.
- Poll listing_events
- Collect market snapshots for a window
- Compute pump % and store listing_outcomes
"""

import argparse
import time
from datetime import datetime, timezone
import sqlite3

from collectors.exchange_service import ExchangeService
from collectors.storage import (
    get_conn,
    insert_market_snapshot,
    insert_listing_outcome,
)


def _parse_ts(ts: str | None) -> float | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            pass
    return None


def _exchange_id_to_ccxt(exchange_name: str) -> str:
    m = {
        "Upbit": "upbit",
        "Bithumb": "bithumb",
        "Coinone": "coinone",
    }
    return m.get(exchange_name, exchange_name.lower())


def _fetch_listing_events(conn: sqlite3.Connection):
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT le.id, le.asset_id, le.exchange_id, le.listing_ts, le.status,
               a.symbol, e.name
        FROM listing_events le
        JOIN assets a ON le.asset_id = a.id
        JOIN exchanges e ON le.exchange_id = e.id
        """
    ).fetchall()
    return rows


def _has_outcome(conn: sqlite3.Connection, listing_event_id: int) -> bool:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM listing_outcomes WHERE listing_event_id = ?",
        (listing_event_id,),
    ).fetchone()
    return row is not None


def _aggregate_snapshots(conn: sqlite3.Connection, asset_id: int, exchange_id: int, start_ts: float, end_ts: float):
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT ts, price
        FROM market_snapshots
        WHERE asset_id = ? AND exchange_id = ?
        """,
        (asset_id, exchange_id),
    ).fetchall()
    series = []
    for ts_str, price in rows:
        t = _parse_ts(ts_str)
        if t is None:
            continue
        if t < start_ts or t > end_ts:
            continue
        series.append((t, price))
    return series


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-min", type=int, default=60, help="Tracking window in minutes")
    parser.add_argument("--interval", type=int, default=20, help="Snapshot interval in seconds")
    parser.add_argument("--duration", type=int, default=120, help="Runner duration in seconds")
    args = parser.parse_args()

    window_sec = args.window_min * 60
    interval = args.interval
    duration = args.duration

    ex_service = ExchangeService()

    start_time = time.time()
    while time.time() - start_time < duration:
        conn = get_conn()
        try:
            events = _fetch_listing_events(conn)
            now = time.time()
            for (
                event_id, asset_id, exchange_id, listing_ts,
                status, symbol, exchange_name
            ) in events:
                if _has_outcome(conn, event_id):
                    continue
                listing_time = _parse_ts(listing_ts) or now
                end_time = listing_time + window_sec

                # collect snapshot if within window
                if now <= end_time:
                    ccxt_ex = _exchange_id_to_ccxt(exchange_name)
                    price_data = ex_service.get_spot_price(ccxt_ex, symbol)
                    if price_data and price_data.price:
                        ts_str = datetime.utcfromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
                        insert_market_snapshot(
                            conn=conn,
                            symbol=symbol,
                            exchange=exchange_name,
                            price=price_data.price,
                            ts=ts_str,
                        )
                # finalize when window elapsed
                if now >= end_time:
                    series = _aggregate_snapshots(conn, asset_id, exchange_id, listing_time, end_time)
                    if not series:
                        continue
                    series.sort(key=lambda x: x[0])
                    start_price = series[0][1]
                    peak_t, peak_price = max(series, key=lambda x: x[1])
                    pump_pct = ((peak_price - start_price) / start_price * 100.0) if start_price else 0.0
                    insert_listing_outcome(
                        conn=conn,
                        listing_event_id=event_id,
                        asset_id=asset_id,
                        exchange_id=exchange_id,
                        start_ts=datetime.utcfromtimestamp(series[0][0]).strftime("%Y-%m-%d %H:%M:%S"),
                        end_ts=datetime.utcfromtimestamp(end_time).strftime("%Y-%m-%d %H:%M:%S"),
                        start_price=start_price,
                        peak_price=peak_price,
                        peak_ts=datetime.utcfromtimestamp(peak_t).strftime("%Y-%m-%d %H:%M:%S"),
                        pump_pct=pump_pct,
                        notes=f"window={args.window_min}m",
                    )
        finally:
            conn.close()

        time.sleep(interval)

    print("listing_outcome_tracker finished")


if __name__ == "__main__":
    main()
