#!/usr/bin/env python3
"""
Run report queries from docs/report_queries.sql and export CSVs to data/reports
"""

import csv
import sqlite3
from pathlib import Path

ROOT = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot")
DB_PATH = ROOT / "data" / "cex_listing.db"
SQL_PATH = ROOT / "docs" / "report_queries.sql"
OUT_DIR = ROOT / "data" / "reports"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_queries(sql_text: str):
    queries = []
    current_name = None
    current_sql = []
    for line in sql_text.splitlines():
        if line.strip().startswith("-- name:"):
            if current_name and current_sql:
                queries.append((current_name, "\n".join(current_sql).strip()))
            current_name = line.split(":", 1)[1].strip()
            current_sql = []
            continue
        if current_name is not None:
            current_sql.append(line)
    if current_name and current_sql:
        queries.append((current_name, "\n".join(current_sql).strip()))
    return queries


def main():
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return
    if not SQL_PATH.exists():
        print(f"SQL not found: {SQL_PATH}")
        return

    sql_text = SQL_PATH.read_text(encoding="utf-8")
    queries = parse_queries(sql_text)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for name, sql in queries:
        rows = cur.execute(sql).fetchall()
        cols = [d[0] for d in cur.description]
        out_path = OUT_DIR / f"{name}.csv"
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            writer.writerows(rows)
        print(f"Saved: {out_path} ({len(rows)} rows)")

    conn.close()


if __name__ == "__main__":
    main()
