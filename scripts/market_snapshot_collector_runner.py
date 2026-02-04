#!/usr/bin/env python3
"""
Collect premium, funding, and DEX liquidity snapshots.
"""

import argparse
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Iterable

from collectors.exchange_service import ExchangeService
from collectors.fx_rate import get_best_rate
from collectors.funding_rate import fetch_binance_funding, fetch_bybit_funding
from collectors.dex_liquidity import get_dex_liquidity
from collectors.storage import (
    get_conn,
    insert_market_snapshot,
    insert_funding_rate,
    insert_dex_liquidity_snapshot,
)

KST = timezone(timedelta(hours=9))


def _now_kst_str() -> str:
    return datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M:%S")


def _parse_symbols(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _fetch_symbols(limit: int) -> list[str]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT a.symbol
            FROM listing_events le
            JOIN assets a ON le.asset_id = a.id
            ORDER BY le.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def _calc_premium_pct(krw_price: float, usd_price: float, fx_rate: float) -> float:
    if usd_price <= 0:
        return 0.0
    usd_krw = usd_price * fx_rate
    return (krw_price - usd_krw) / usd_krw * 100.0


async def _collect_for_symbol(symbol: str, fx_rate: float, ex_service: ExchangeService, dex_chain: str | None) -> None:
    ts = _now_kst_str()

    upbit = ex_service.get_spot_price("upbit", symbol)
    binance = ex_service.get_spot_price("binance", symbol)

    conn = get_conn()
    try:
        premium_pct = None
        if upbit and binance and upbit.price and binance.price:
            premium_pct = _calc_premium_pct(upbit.price, binance.price, fx_rate)

        if upbit and upbit.price:
            insert_market_snapshot(
                conn=conn,
                symbol=symbol,
                exchange="Upbit",
                price=upbit.price,
                ts=ts,
                premium_pct=premium_pct,
            )

        if binance and binance.price:
            insert_market_snapshot(
                conn=conn,
                symbol=symbol,
                exchange="Binance",
                price=binance.price,
                ts=ts,
            )
    finally:
        conn.close()

    # funding rates
    binance_symbol = f"{symbol}USDT"
    fr_binance = await fetch_binance_funding(binance_symbol)
    if fr_binance:
        conn = get_conn()
        try:
            insert_funding_rate(
                conn=conn,
                symbol=symbol,
                exchange="Binance",
                ts=fr_binance.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                funding_rate=fr_binance.funding_rate,
                open_interest=None,
            )
        finally:
            conn.close()

    fr_bybit = await fetch_bybit_funding(binance_symbol)
    if fr_bybit:
        conn = get_conn()
        try:
            insert_funding_rate(
                conn=conn,
                symbol=symbol,
                exchange="Bybit",
                ts=fr_bybit.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                funding_rate=fr_bybit.funding_rate,
                open_interest=None,
            )
        finally:
            conn.close()

    # dex liquidity
    dex_result = await get_dex_liquidity(symbol, chain=dex_chain)
    if dex_result:
        best = dex_result.best_pair
        conn = get_conn()
        try:
            insert_dex_liquidity_snapshot(
                conn=conn,
                symbol=symbol,
                chain=best.chain if best else dex_chain,
                dex_name=best.dex if best else None,
                ts=dex_result.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                liquidity_usd=dex_result.total_liquidity_usd,
                volume_24h_usd=dex_result.total_volume_24h,
                pool_count=dex_result.pair_count,
            )
        finally:
            conn.close()


async def run(symbols: Iterable[str], dex_chain: str | None) -> None:
    result = await get_best_rate()
    fx_rate = result.best_rate if result and result.best_rate else 1450.0
    ex_service = ExchangeService()
    for sym in symbols:
        await _collect_for_symbol(sym, fx_rate, ex_service, dex_chain)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols")
    parser.add_argument("--limit", type=int, default=20, help="Max symbols from listing_events")
    parser.add_argument("--dex-chain", type=str, default="", help="Dex chain (e.g., ethereum)")
    args = parser.parse_args()

    symbols = _parse_symbols(args.symbols)
    if not symbols:
        symbols = _fetch_symbols(args.limit)

    if not symbols:
        print("No symbols to collect")
        return

    dex_chain = args.dex_chain.strip().lower() if args.dex_chain else None
    asyncio.run(run(symbols, dex_chain))


if __name__ == "__main__":
    main()
