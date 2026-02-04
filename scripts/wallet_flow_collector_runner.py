#!/usr/bin/env python3
"""
Run HotWalletTracker and persist deposit events to wallet_flows.
Requires ALCHEMY_API_KEY.
"""

import argparse
import asyncio
from datetime import datetime

from collectors.hot_wallet_tracker import HotWalletTracker, DepositEvent
from collectors.storage import get_conn, insert_wallet_flow


async def _on_deposit(event: DepositEvent) -> None:
    ts = event.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        insert_wallet_flow(
            conn=conn,
            exchange=event.exchange,
            symbol=event.token_symbol,
            chain=event.chain,
            direction="deposit",
            amount=event.amount_human,
            usd_value=event.amount_usd,
            tx_hash=None,
            ts=ts,
            source="hot_wallet_tracker",
        )
    finally:
        conn.close()


def _parse_chains(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [c.strip().lower() for c in raw.split(",") if c.strip()]


async def run(
    duration: int,
    interval_sec: int,
    min_deposit_usd: float,
    chains: list[str] | None,
) -> None:
    tracker = HotWalletTracker(alert_callback=_on_deposit, min_deposit_usd=min_deposit_usd)
    task = asyncio.create_task(
        tracker.start_monitoring(interval_sec=interval_sec, chains=chains)
    )

    if duration > 0:
        await asyncio.sleep(duration)
        tracker.stop_monitoring()
        await asyncio.sleep(1)
        task.cancel()
        await tracker.close()
    else:
        try:
            await task
        finally:
            await tracker.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=0, help="Run duration seconds (0=forever)")
    parser.add_argument("--interval", type=int, default=60, help="Polling interval seconds")
    parser.add_argument("--min-usd", type=float, default=100_000, help="Min deposit USD")
    parser.add_argument("--chains", type=str, default="", help="Comma-separated chains (e.g., ethereum)")
    args = parser.parse_args()

    asyncio.run(run(args.duration, args.interval, args.min_usd, _parse_chains(args.chains)))


if __name__ == "__main__":
    main()
