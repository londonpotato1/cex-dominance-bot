#!/usr/bin/env python3
"""
Run NoticeFetcher and store listing events into SQLite DB.
"""

import argparse
import asyncio
import logging
from typing import Optional

import json

from collectors.notice_fetcher import NoticeFetcher
from collectors.notice_parser import NoticeParseResult
from collectors.storage import get_conn, insert_listing_event, insert_notice_event
from collectors.korean_notice import KoreanNoticeFetcher, NoticeType

logging.basicConfig(level=logging.INFO)


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
    raw = {
        "symbols": result.symbols,
        "listing_time": result.listing_time,
        "notice_type": result.notice_type,
        "exchange": result.exchange,
        "raw_title": result.raw_title,
        "notice_id": result.notice_id,
        "notice_url": result.notice_url,
        "event_severity": result.event_severity.value,
        "event_action": result.event_action.value,
        "event_details": result.event_details,
    }
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
            raw_json=raw,
        )
    finally:
        conn.close()


async def on_listing(result: NoticeParseResult) -> None:
    if result.notice_type != "listing":
        return
    if not result.symbols:
        return
    exchange = _exchange_name(result.exchange)
    listing_type = result.notice_type
    listing_ts = result.listing_time
    source = result.notice_url or result.notice_id or "notice"

    conn = get_conn()
    try:
        for sym in result.symbols:
            insert_listing_event(
                conn=conn,
                symbol=sym,
                exchange=exchange,
                listing_type=listing_type,
                listing_ts=listing_ts,
                source=source,
                status="parsed",
            )
    finally:
        conn.close()


async def run(duration: Optional[int]) -> None:
    stop_event = asyncio.Event()
    fetcher = NoticeFetcher(on_listing=on_listing, on_notice=on_notice)

    # one-shot korean notice fetch (listing only)
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
                    # store notice event for all actionable types
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
                        raw_json={
                            "title": n.title,
                            "symbols": n.symbols,
                            "networks": n.networks,
                            "notice_type": n.notice_type.value,
                        },
                    )

                    # store listing event if applicable
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
        except Exception as e:
            logging.warning("[notice_collector_runner] KoreanNotice prefetch failed: %s", e)
        finally:
            if knf is not None:
                try:
                    await knf.close()
                except Exception:
                    pass

    async def _stop_later():
        if duration is None:
            return
        await asyncio.sleep(duration)
        stop_event.set()

    await _prefetch_korean()

    if duration is not None:
        asyncio.create_task(_stop_later())

    await fetcher.run(stop_event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=0, help="Run duration in seconds (0 = forever)")
    args = parser.parse_args()
    duration = None if args.duration == 0 else args.duration
    asyncio.run(run(duration))


if __name__ == "__main__":
    main()
