#!/usr/bin/env python3
"""
Run live listing pipeline:
- NoticeFetcher (listing + notice)
- HotWalletTracker (wallet_flows)
- Listing outcome tracker (pump/deposit/market cap)
"""

import argparse
import asyncio
import logging

from collectors.notice_fetcher import NoticeFetcher
from collectors.notice_parser import NoticeParseResult
from collectors.korean_notice import KoreanNoticeFetcher, NoticeType
from collectors.storage import get_conn, insert_listing_event, insert_notice_event
from collectors.hot_wallet_tracker import HotWalletTracker, DepositEvent
from scripts.listing_outcome_tracker import run_tracker


logging.basicConfig(level=logging.INFO)


def _parse_chains(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [c.strip().lower() for c in raw.split(",") if c.strip()]


def _exchange_name(raw: str) -> str:
    if raw.lower() == "upbit":
        return "Upbit"
    if raw.lower() == "bithumb":
        return "Bithumb"
    return raw


async def on_notice(result: NoticeParseResult) -> None:
    exchange = _exchange_name(result.exchange)
    notice_ts = result.listing_time
    source = result.notice_url or result.notice_id or "notice"
    conn = get_conn()
    try:
        insert_notice_event(
            conn=conn,
            exchange=exchange,
            notice_type=result.notice_type,
            title=result.raw_title or "",
            symbols=result.symbols,
            notice_ts=notice_ts,
            source=source,
            severity=result.event_severity.value,
            action=result.event_action.value,
            raw_json=result.event_details,
        )
    finally:
        conn.close()


async def on_listing(result: NoticeParseResult) -> None:
    if result.notice_type != "listing":
        return
    if not result.symbols:
        return
    exchange = _exchange_name(result.exchange)
    listing_ts = result.listing_time
    source = result.notice_url or result.notice_id or "notice"
    conn = get_conn()
    try:
        for sym in result.symbols:
            insert_listing_event(
                conn=conn,
                symbol=sym,
                exchange=exchange,
                listing_type="listing",
                listing_ts=listing_ts,
                source=source,
                status="parsed",
            )
    finally:
        conn.close()


async def _prefetch_korean():
    knf = None
    try:
        knf = KoreanNoticeFetcher()
        notices = await knf.fetch_actionable_notices(limit=20)
        for n in notices:
            if not n.symbols:
                continue
            conn = get_conn()
            try:
                insert_notice_event(
                    conn=conn,
                    exchange=_exchange_name(n.exchange.value),
                    notice_type=n.notice_type.value,
                    title=n.title,
                    symbols=n.symbols,
                    notice_ts=n.published_at.strftime("%Y-%m-%d %H:%M:%S"),
                    source=n.url,
                    severity="",
                    action="",
                    raw_json={"title": n.title, "symbols": n.symbols},
                )
                if n.notice_type == NoticeType.LISTING:
                    listing_ts = n.effective_time.strftime("%Y-%m-%d %H:%M:%S") if n.effective_time else None
                    for sym in n.symbols:
                        insert_listing_event(
                            conn=conn,
                            symbol=sym,
                            exchange=_exchange_name(n.exchange.value),
                            listing_type=n.notice_type.value,
                            listing_ts=listing_ts,
                            source=n.url,
                            status="prefetch",
                        )
            finally:
                conn.close()
    finally:
        if knf:
            await knf.close()


async def _wallet_callback(event: DepositEvent) -> None:
    from collectors.storage import insert_wallet_flow
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
            ts=event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            source="hot_wallet_tracker",
        )
    finally:
        conn.close()


async def run(
    duration: int,
    wallet_interval: int,
    wallet_min_usd: float,
    outcome_window: int,
    wallet_chains: list[str] | None,
):
    stop_event = asyncio.Event()
    fetcher = NoticeFetcher(on_listing=on_listing, on_notice=on_notice)
    wallet = HotWalletTracker(alert_callback=_wallet_callback, min_deposit_usd=wallet_min_usd)

    async def _stop_later():
        if duration <= 0:
            return
        await asyncio.sleep(duration)
        stop_event.set()
        wallet.stop_monitoring()

    await _prefetch_korean()

    outcome_duration = duration if duration > 0 else 3600

    tasks = [
        asyncio.create_task(fetcher.run(stop_event), name="notice_fetcher"),
        asyncio.create_task(
            wallet.start_monitoring(interval_sec=wallet_interval, chains=wallet_chains),
            name="wallet_tracker",
        ),
        asyncio.create_task(_stop_later(), name="stopper"),
        asyncio.to_thread(run_tracker, outcome_window, 20, outcome_duration),
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
    await wallet.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=0, help="Seconds (0=forever)")
    parser.add_argument("--wallet-interval", type=int, default=60)
    parser.add_argument("--wallet-min-usd", type=float, default=100_000)
    parser.add_argument("--outcome-window", type=int, default=60)
    parser.add_argument("--wallet-chains", type=str, default="", help="Comma-separated chains")
    args = parser.parse_args()

    asyncio.run(
        run(
            args.duration,
            args.wallet_interval,
            args.wallet_min_usd,
            args.outcome_window,
            _parse_chains(args.wallet_chains),
        )
    )


if __name__ == "__main__":
    main()
