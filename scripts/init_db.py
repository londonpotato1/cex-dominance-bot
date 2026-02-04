#!/usr/bin/env python3
"""
Initialize SQLite DB using docs/db_schema.sql
"""

import sqlite3
from pathlib import Path

ROOT = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot")
SCHEMA = ROOT / "docs" / "db_schema.sql"
DB_PATH = ROOT / "data" / "cex_listing.db"


def main():
    if not SCHEMA.exists():
        print(f"Schema missing: {SCHEMA}")
        return
    sql = SCHEMA.read_text(encoding="utf-8")
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(sql)
    conn.commit()
    conn.close()
    print(f"DB initialized: {DB_PATH}")


if __name__ == "__main__":
    main()
