#!/usr/bin/env python3
"""
Insert manual listing events + notice events into SQLite DB (test data).
"""

import argparse
from datetime import datetime

from collectors.storage import get_conn, insert_listing_event, insert_notice_event


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--exchange", required=True, help="Upbit/Bithumb/etc")
    parser.add_argument("--listing-ts", required=True, help="YYYY-MM-DD HH:MM:SS (KST or UTC as you decide)")
    parser.add_argument("--source", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--notice-type", default="listing")
    parser.add_argument("--status", default="manual_test")
    args = parser.parse_args()

    conn = get_conn()
    try:
        insert_notice_event(
            conn=conn,
            exchange=args.exchange,
            notice_type=args.notice_type,
            title=args.title or f"{args.symbol} listing",
            symbols=[args.symbol],
            notice_ts=args.listing_ts,
            source=args.source,
            severity="",
            action="",
            raw_json={
                "symbol": args.symbol,
                "exchange": args.exchange,
                "listing_ts": args.listing_ts,
                "source": args.source,
                "inserted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

        insert_listing_event(
            conn=conn,
            symbol=args.symbol,
            exchange=args.exchange,
            listing_type="listing",
            listing_ts=args.listing_ts,
            source=args.source,
            status=args.status,
        )
    finally:
        conn.close()

    print(f"Inserted manual listing: {args.symbol} on {args.exchange} @ {args.listing_ts}")


if __name__ == "__main__":
    main()
