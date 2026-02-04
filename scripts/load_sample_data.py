#!/usr/bin/env python3
"""
Load sample data into SQLite DB from docs/guide_listing_cases.csv
"""

import csv
import sqlite3
import re
from pathlib import Path
from typing import Optional

ROOT = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot")
DB_PATH = ROOT / "data" / "cex_listing.db"
GUIDE_CSV = ROOT / "docs" / "guide_listing_cases.csv"


def parse_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    # direct yyyy-mm-dd
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # yy.mm.dd
    m2 = re.search(r"(\d{2})\.(\d{1,2})\.(\d{1,2})", raw)
    if m2:
        yy = int(m2.group(1)) + 2000
        return f"{yy:04d}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
    # yy년 mm월 dd일
    m3 = re.search(r"(\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일", raw)
    if m3:
        yy = int(m3.group(1)) + 2000
        return f"{yy:04d}-{int(m3.group(2)):02d}-{int(m3.group(3)):02d}"
    return None


def parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _normalize_exchange(name: str) -> str:
    if not name:
        return "Unknown"
    # normalize simple variants
    name = name.strip()
    if name.lower() in ["업비트", "upbit"]:
        return "Upbit"
    if name.lower() in ["빗썸", "bithumb"]:
        return "Bithumb"
    if name.lower() in ["코인원", "coinone"]:
        return "Coinone"
    return name


def get_or_create_exchange(cur, name: str) -> int:
    name = _normalize_exchange(name)
    row = cur.execute("SELECT id FROM exchanges WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO exchanges (name) VALUES (?)", (name,))
    return cur.lastrowid


def get_or_create_asset(cur, symbol: str, chain: Optional[str]) -> int:
    chain_val = chain if chain else None
    symbol = symbol.strip().upper()
    # prefer exact match
    if chain_val is None:
        row = cur.execute("SELECT id FROM assets WHERE symbol = ? AND chain IS NULL", (symbol,)).fetchone()
        if row:
            return row[0]
        # fallback: any chain same symbol
        row = cur.execute("SELECT id FROM assets WHERE symbol = ? LIMIT 1", (symbol,)).fetchone()
        if row:
            return row[0]
    else:
        row = cur.execute("SELECT id FROM assets WHERE symbol = ? AND chain = ?", (symbol, chain_val)).fetchone()
        if row:
            return row[0]
        # fallback to null chain
        row = cur.execute("SELECT id FROM assets WHERE symbol = ? AND chain IS NULL", (symbol,)).fetchone()
        if row:
            return row[0]
        # fallback: any chain same symbol
        row = cur.execute("SELECT id FROM assets WHERE symbol = ? LIMIT 1", (symbol,)).fetchone()
        if row:
            return row[0]
    cur.execute("INSERT INTO assets (symbol, chain) VALUES (?, ?)", (symbol, chain_val))
    return cur.lastrowid


def _extract_kv(text: str, key: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(rf"{key}\s*=\s*([^;\\s]+)", text, re.I)
    if m:
        return m.group(1)
    return None


def _case_exists(cur, asset_id: int, exchange_id: int, case_date: Optional[str], source: str, listing_type: str) -> bool:
    # primary duplicate check: asset + exchange + case_date (+ listing_type)
    if case_date:
        row = cur.execute(
            "SELECT id FROM listing_cases WHERE asset_id=? AND exchange_id=? AND case_date=? AND listing_type IS ?",
            (asset_id, exchange_id, case_date, listing_type),
        ).fetchone()
        if row:
            return True
    # fallback check: asset + exchange + source
    row = cur.execute(
        "SELECT id FROM listing_cases WHERE asset_id=? AND exchange_id=? AND source=?",
        (asset_id, exchange_id, source),
    ).fetchone()
    return row is not None


def main():
    if not DB_PATH.exists():
        print(f"DB not found. Run init_db.py first: {DB_PATH}")
        return
    if not GUIDE_CSV.exists():
        print(f"Missing guide CSV: {GUIDE_CSV}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    added = 0
    with open(GUIDE_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row.get("ticker", "")
            if not symbol:
                continue
            exchange = row.get("exchange", "")
            if not exchange:
                exchange = _extract_kv(row.get("descriptors_raw", ""), "exchange") or ""
            chain = row.get("network_chain", "")
            if not chain:
                chain = _extract_kv(row.get("descriptors_raw", ""), "chain") or ""
            listing_type = row.get("listing_type", "")
            result_label = row.get("result_label", "")
            profit_pct = parse_float(row.get("profit_pct", ""))
            market_cap_usd = parse_float(row.get("market_cap_usd", ""))
            deposit_krw = parse_float(row.get("deposit_krw", ""))
            max_premium_pct = parse_float(row.get("max_premium_pct", ""))
            hedge_type = row.get("hedge_type", "")
            hot_wallet_usd = parse_float(row.get("hot_wallet_usd", ""))
            withdrawal_open = row.get("withdrawal_open", "")
            notes = row.get("notes_norm", "") or row.get("context_raw", "")
            source = row.get("source_file", "")
            case_date = parse_date(row.get("listing_date_raw", ""))

            ex_id = get_or_create_exchange(cur, exchange)
            asset_id = get_or_create_asset(cur, symbol, chain)

            if _case_exists(cur, asset_id, ex_id, case_date, source, listing_type):
                continue

            cur.execute(
                """
                INSERT INTO listing_cases (
                  asset_id, exchange_id, case_date, listing_type, result_label,
                  profit_pct, market_cap_usd, deposit_krw, max_premium_pct,
                  hedge_type, hot_wallet_usd, network_chain, withdrawal_open,
                  notes, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id, ex_id, case_date, listing_type, result_label,
                    profit_pct, market_cap_usd, deposit_krw, max_premium_pct,
                    hedge_type, hot_wallet_usd, chain, withdrawal_open,
                    notes[:1000], source
                ),
            )
            added += 1

    conn.commit()
    conn.close()
    print(f"Loaded listing_cases: {added}")


if __name__ == "__main__":
    main()
