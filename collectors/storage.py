"""
DB storage helpers for collectors (SQLite).
"""

import sqlite3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot")
DB_PATH = ROOT / "data" / "cex_listing.db"

KST = timezone(timedelta(hours=9))


def _now_kst_str() -> str:
    return datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def get_or_create_exchange(conn: sqlite3.Connection, name: str) -> int:
    if not name:
        name = "Unknown"
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM exchanges WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO exchanges (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def get_or_create_asset(conn: sqlite3.Connection, symbol: str, chain: Optional[str]) -> int:
    cur = conn.cursor()
    sym = symbol.strip().upper()
    chain_val = chain if chain else None
    if chain_val:
        row = cur.execute(
            "SELECT id FROM assets WHERE symbol = ? AND chain = ?",
            (sym, chain_val),
        ).fetchone()
        if row:
            return row[0]
    row = cur.execute(
        "SELECT id FROM assets WHERE symbol = ? AND chain IS NULL",
        (sym,),
    ).fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO assets (symbol, chain) VALUES (?, ?)", (sym, chain_val))
    conn.commit()
    return cur.lastrowid


def insert_listing_event(
    conn: sqlite3.Connection,
    symbol: str,
    exchange: str,
    listing_type: str,
    listing_ts: Optional[str],
    source: str,
    status: str = "new",
) -> None:
    cur = conn.cursor()
    exchange_id = get_or_create_exchange(conn, exchange)
    asset_id = get_or_create_asset(conn, symbol, None)

    # duplicate check
    row = cur.execute(
        """
        SELECT id FROM listing_events
        WHERE asset_id = ? AND exchange_id = ? AND listing_ts IS ? AND source = ?
        """,
        (asset_id, exchange_id, listing_ts, source),
    ).fetchone()
    if row:
        return

    cur.execute(
        """
        INSERT INTO listing_events (
            asset_id, exchange_id, listing_type,
            announce_ts, listing_ts, source, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            exchange_id,
            listing_type,
            _now_kst_str(),
            listing_ts,
            source,
            status,
        ),
    )
    conn.commit()


def insert_notice_event(
    conn: sqlite3.Connection,
    exchange: str,
    notice_type: str,
    title: str,
    symbols: list[str],
    notice_ts: str | None,
    source: str,
    severity: str = "",
    action: str = "",
    raw_json: dict | None = None,
) -> None:
    cur = conn.cursor()
    exchange_id = get_or_create_exchange(conn, exchange)
    symbols_json = json.dumps(symbols, ensure_ascii=False)
    raw_json_str = json.dumps(raw_json or {}, ensure_ascii=False)

    # duplicate check
    # Dedup policy:
    # 1) If source looks unique (URL/ID), use (exchange_id, notice_type, source)
    # 2) Else fallback to (exchange_id, notice_type, title, notice_ts)
    source_val = (source or "").strip()
    if source_val and source_val != "notice":
        row = cur.execute(
            """
            SELECT id FROM notice_events
            WHERE exchange_id = ?
              AND notice_type = ?
              AND source = ?
            """,
            (exchange_id, notice_type, source_val),
        ).fetchone()
        if row:
            return
    row = cur.execute(
        """
        SELECT id FROM notice_events
        WHERE exchange_id = ?
          AND notice_type = ?
          AND title = ?
          AND notice_ts IS ?
        """,
        (exchange_id, notice_type, title, notice_ts),
    ).fetchone()
    if row:
        return

    cur.execute(
        """
        INSERT INTO notice_events (
            exchange_id, notice_type, title, symbols, notice_ts,
            source, severity, action, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            exchange_id,
            notice_type,
            title,
            symbols_json,
            notice_ts,
            source,
            severity,
            action,
            raw_json_str,
        ),
    )
    conn.commit()


def insert_market_snapshot(
    conn: sqlite3.Connection,
    symbol: str,
    exchange: str,
    price: float,
    ts: str,
    volume_1m_krw: float | None = None,
    volume_5m_krw: float | None = None,
    premium_pct: float | None = None,
) -> None:
    exchange_id = get_or_create_exchange(conn, exchange)
    asset_id = get_or_create_asset(conn, symbol, None)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO market_snapshots (
          asset_id, exchange_id, ts, price,
          volume_1m_krw, volume_5m_krw, premium_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (asset_id, exchange_id, ts, price, volume_1m_krw, volume_5m_krw, premium_pct),
    )
    conn.commit()


def insert_listing_outcome(
    conn: sqlite3.Connection,
    listing_event_id: int,
    asset_id: int,
    exchange_id: int,
    start_ts: str,
    end_ts: str,
    start_price: float,
    peak_price: float,
    peak_ts: str,
    pump_pct: float,
    deposit_usd: float | None = None,
    deposit_krw: float | None = None,
    market_cap_usd: float | None = None,
    notes: str | None = None,
) -> None:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM listing_outcomes WHERE listing_event_id = ?",
        (listing_event_id,),
    ).fetchone()
    if row:
        return
    cur.execute(
        """
        INSERT INTO listing_outcomes (
          listing_event_id, asset_id, exchange_id,
          start_ts, end_ts, start_price, peak_price, peak_ts, pump_pct,
          deposit_usd, deposit_krw, market_cap_usd, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            listing_event_id, asset_id, exchange_id,
            start_ts, end_ts, start_price, peak_price, peak_ts, pump_pct,
            deposit_usd, deposit_krw, market_cap_usd, notes,
        ),
    )
    conn.commit()


def insert_wallet_flow(
    conn: sqlite3.Connection,
    exchange: str,
    symbol: str,
    chain: str | None,
    direction: str,
    amount: float,
    usd_value: float | None,
    tx_hash: str | None,
    ts: str,
    source: str = "manual",
) -> None:
    exchange_id = get_or_create_exchange(conn, exchange)
    asset_id = get_or_create_asset(conn, symbol, chain)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO wallet_flows (
          exchange_id, asset_id, chain, address, direction,
          amount, usd_value, tx_hash, ts, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            exchange_id, asset_id, chain, None, direction,
            amount, usd_value, tx_hash, ts, source,
        ),
    )
    conn.commit()
