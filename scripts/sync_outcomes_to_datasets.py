#!/usr/bin/env python3
"""
Sync listing_outcomes -> listing_data.csv and guide_listing_cases.csv (fill empty fields only).
"""

import csv
import sqlite3
from pathlib import Path
from typing import Dict

ROOT = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot")
DB_PATH = ROOT / "data" / "cex_listing.db"
LISTING_CSV = ROOT / "data" / "labeling" / "listing_data.csv"
GUIDE_CSV = ROOT / "docs" / "guide_listing_cases.csv"


def _label_from_pump(pct: float) -> str:
    if pct >= 30:
        return "대흥따리"
    if pct >= 10:
        return "흥따리"
    if pct > 0:
        return "보통"
    return "망따리"


def _load_csv(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save_csv(path: Path, rows, fieldnames):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _load_outcomes() -> list[Dict]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT lo.pump_pct, lo.deposit_krw, lo.market_cap_usd,
               le.listing_ts, a.symbol, e.name
        FROM listing_outcomes lo
        JOIN listing_events le ON lo.listing_event_id = le.id
        JOIN assets a ON lo.asset_id = a.id
        JOIN exchanges e ON lo.exchange_id = e.id
        """
    ).fetchall()
    conn.close()
    results = []
    for pump_pct, deposit_krw, market_cap_usd, listing_ts, symbol, exchange in rows:
        date = listing_ts[:10] if listing_ts else ""
        results.append({
            "symbol": symbol,
            "exchange": exchange,
            "date": date,
            "pump_pct": pump_pct,
            "deposit_krw": deposit_krw,
            "market_cap_usd": market_cap_usd,
            "result_label": _label_from_pump(pump_pct) if pump_pct is not None else "",
        })
    return results


def sync_listing_data():
    outcomes = _load_outcomes()
    if not outcomes:
        return 0
    rows = _load_csv(LISTING_CSV)
    fieldnames = list(rows[0].keys()) if rows else []
    updated = 0
    for r in rows:
        for o in outcomes:
            if (
                r.get("symbol", "").upper() == o["symbol"].upper()
                and r.get("exchange", "").lower() == o["exchange"].lower()
                and r.get("date", "") == o["date"]
            ):
                if not r.get("deposit_krw") and o["deposit_krw"]:
                    r["deposit_krw"] = str(o["deposit_krw"])
                if not r.get("market_cap_usd") and o["market_cap_usd"]:
                    r["market_cap_usd"] = str(o["market_cap_usd"])
                if not r.get("result_label") and o["result_label"]:
                    r["result_label"] = o["result_label"]
                if not r.get("result_notes"):
                    r["result_notes"] = f"pump_pct={o['pump_pct']}"
                updated += 1
                break
    if updated and fieldnames:
        _save_csv(LISTING_CSV, rows, fieldnames)
    return updated


def sync_guide_cases():
    outcomes = _load_outcomes()
    if not outcomes:
        return 0
    rows = _load_csv(GUIDE_CSV)
    fieldnames = list(rows[0].keys()) if rows else []
    updated = 0
    for r in rows:
        date_raw = r.get("listing_date_raw", "")
        for o in outcomes:
            if r.get("ticker", "").upper() != o["symbol"].upper():
                continue
            if o["date"] and o["date"] in date_raw:
                if not r.get("deposit_krw") and o["deposit_krw"]:
                    r["deposit_krw"] = str(o["deposit_krw"])
                if not r.get("market_cap_usd") and o["market_cap_usd"]:
                    r["market_cap_usd"] = str(o["market_cap_usd"])
                if not r.get("profit_pct") and o["pump_pct"] is not None:
                    r["profit_pct"] = str(o["pump_pct"])
                if not r.get("result_label") and o["result_label"]:
                    r["result_label"] = o["result_label"]
                updated += 1
                break
    if updated and fieldnames:
        _save_csv(GUIDE_CSV, rows, fieldnames)
    return updated


def main():
    updated_listing = sync_listing_data()
    updated_guide = sync_guide_cases()
    print(f"sync listing_data: {updated_listing}")
    print(f"sync guide_listing_cases: {updated_guide}")


if __name__ == "__main__":
    main()
