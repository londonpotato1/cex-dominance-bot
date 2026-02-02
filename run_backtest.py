#!/usr/bin/env python3
"""Run backtest script."""
import sys
import asyncio
sys.path.insert(0, '.')

from analysis.backtest import BacktestEngine

async def main():
    engine = BacktestEngine()
    print("Loading data...")
    summary = await engine.run_backtest()
    engine.print_report(summary)

if __name__ == "__main__":
    asyncio.run(main())
