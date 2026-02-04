#!/usr/bin/env python3
"""
Insert a manual wallet flow (deposit/withdraw) into DB for testing.
"""

import argparse
from collectors.storage import get_conn, insert_wallet_flow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--chain", default="")
    parser.add_argument("--direction", default="deposit")
    parser.add_argument("--amount", type=float, default=0.0)
    parser.add_argument("--usd", type=float, default=0.0)
    parser.add_argument("--ts", required=True, help="YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--tx", default="")
    args = parser.parse_args()

    conn = get_conn()
    try:
        insert_wallet_flow(
            conn=conn,
            exchange=args.exchange,
            symbol=args.symbol,
            chain=args.chain or None,
            direction=args.direction,
            amount=args.amount,
            usd_value=args.usd,
            tx_hash=args.tx or None,
            ts=args.ts,
            source="manual",
        )
    finally:
        conn.close()

    print(f"Inserted wallet flow: {args.exchange} {args.symbol} {args.direction} ${args.usd}")


if __name__ == "__main__":
    main()
