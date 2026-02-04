#!/usr/bin/env python3
"""
Test notice + listing insertion pipeline without real network.
"""

from datetime import datetime
from collectors.notice_parser import NoticeParseResult, EventSeverity, EventAction
from collectors.storage import get_conn, insert_listing_event, insert_notice_event


def main():
    conn = get_conn()
    cur = conn.cursor()
    before_notice = cur.execute("SELECT COUNT(*) FROM notice_events").fetchone()[0]
    before_listing = cur.execute("SELECT COUNT(*) FROM listing_events").fetchone()[0]

    # fake notice
    result = NoticeParseResult(
        symbols=["TEST"],
        listing_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        notice_type="listing",
        exchange="upbit",
        raw_title="[TEST] TEST 상장",
        notice_id="test_notice_001",
        notice_url="https://example.com/notice/test_notice_001",
        event_severity=EventSeverity.HIGH,
        event_action=EventAction.TRADE,
        event_details={"test": True},
    )

    insert_notice_event(
        conn=conn,
        exchange="Upbit",
        notice_type=result.notice_type,
        title=result.raw_title,
        symbols=result.symbols,
        notice_ts=result.listing_time,
        source=result.notice_url,
        severity=result.event_severity.value,
        action=result.event_action.value,
        raw_json={
            "symbols": result.symbols,
            "notice_id": result.notice_id,
        },
    )

    for sym in result.symbols:
        insert_listing_event(
            conn=conn,
            symbol=sym,
            exchange="Upbit",
            listing_type="listing",
            listing_ts=result.listing_time,
            source=result.notice_url,
            status="test",
        )

    after_notice = cur.execute("SELECT COUNT(*) FROM notice_events").fetchone()[0]
    after_listing = cur.execute("SELECT COUNT(*) FROM listing_events").fetchone()[0]
    conn.close()

    print(f"notice_events: {before_notice} -> {after_notice}")
    print(f"listing_events: {before_listing} -> {after_listing}")


if __name__ == "__main__":
    main()
