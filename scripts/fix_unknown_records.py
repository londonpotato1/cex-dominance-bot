#!/usr/bin/env python3
"""기존 unknown symbol/exchange 레코드 수정.

blockers_json에서 "국내 가격 조회 실패: SYMBOL@EXCHANGE" 패턴을 파싱하여
symbol/exchange 컬럼 업데이트.

사용법:
    python scripts/fix_unknown_records.py           # 로컬 DB
    DATABASE_URL=/data/ddari.db python scripts/fix_unknown_records.py  # Railway

--dry-run으로 변경사항 미리 확인 가능.
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# DB 경로: 환경변수 우선, 없으면 로컬
_DEFAULT_DB = _ROOT / "ddari.db"
_DB_PATH = Path(os.environ.get("DATABASE_URL", str(_DEFAULT_DB)))

# 패턴: "국내 가격 조회 실패: SYMBOL@EXCHANGE"
_PATTERN = re.compile(r"국내 가격 조회 실패:\s*([A-Z0-9]+)@([a-z]+)")


def fix_unknown_records(dry_run: bool = False) -> int:
    """unknown 레코드 수정.

    Returns:
        수정된 레코드 수.
    """
    print(f"DB 경로: {_DB_PATH}")

    if not _DB_PATH.exists():
        print(f"DB 파일 없음: {_DB_PATH}")
        return 0

    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row

    # unknown 레코드 조회
    rows = conn.execute(
        "SELECT rowid, symbol, exchange, blockers_json FROM gate_analysis_log "
        "WHERE symbol = 'unknown' OR exchange = 'unknown'"
    ).fetchall()

    print(f"unknown 레코드 수: {len(rows)}")

    fixed = 0
    for row in rows:
        rowid = row["rowid"]
        blockers_json = row["blockers_json"] or "[]"

        try:
            blockers = json.loads(blockers_json)
        except json.JSONDecodeError:
            continue

        # blockers에서 symbol@exchange 추출
        new_symbol = None
        new_exchange = None

        for blocker in blockers:
            match = _PATTERN.search(blocker)
            if match:
                new_symbol = match.group(1)
                new_exchange = match.group(2)
                break

        if not new_symbol or not new_exchange:
            print(f"  rowid={rowid}: 파싱 실패 (blockers: {blockers})")
            continue

        print(f"  rowid={rowid}: unknown → {new_symbol}@{new_exchange}")

        if not dry_run:
            conn.execute(
                "UPDATE gate_analysis_log SET symbol = ?, exchange = ? WHERE rowid = ?",
                (new_symbol, new_exchange, rowid),
            )
            fixed += 1

    if not dry_run:
        conn.commit()
        print(f"\n수정 완료: {fixed}건")
    else:
        print(f"\n[DRY-RUN] 수정 예정: {fixed}건 (실제 변경 없음)")

    conn.close()
    return fixed


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY-RUN 모드 ===\n")

    fix_unknown_records(dry_run=dry_run)


if __name__ == "__main__":
    main()
