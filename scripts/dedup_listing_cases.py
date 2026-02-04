#!/usr/bin/env python3
"""
Deduplicate listing_cases in SQLite DB.
Keeps the lowest id for duplicate keys.
"""

import shutil
import sqlite3
from pathlib import Path

ROOT = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot")
DB_PATH = ROOT / "data" / "cex_listing.db"
BACKUP_PATH = ROOT / "data" / "cex_listing_before_dedup.db"


def main():
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return

    # backup once
    if not BACKUP_PATH.exists():
        shutil.copyfile(DB_PATH, BACKUP_PATH)
        print(f"Backup created: {BACKUP_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # count duplicates by key
    dup_rows = cur.execute(
        """
        SELECT asset_id, exchange_id, case_date, listing_type, source, COUNT(*) AS cnt
        FROM listing_cases
        GROUP BY asset_id, exchange_id, case_date, listing_type, source
        HAVING cnt > 1
        """
    ).fetchall()

    print(f"Duplicate groups: {len(dup_rows)}")

    # delete duplicates keeping smallest id
    cur.execute(
        """
        DELETE FROM listing_cases
        WHERE id NOT IN (
          SELECT MIN(id)
          FROM listing_cases
          GROUP BY asset_id, exchange_id, case_date, listing_type, source
        )
        """
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()

    print(f"Deleted rows: {deleted}")


if __name__ == "__main__":
    main()
