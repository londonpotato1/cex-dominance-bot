#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""상장 전략 분석 테스트"""
import asyncio
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from collectors.listing_strategy import analyze_listing, format_strategy_recommendation

async def main():
    print("=== Listing Strategy Analysis Test ===\n")
    
    rec = await analyze_listing("TESTCOIN")
    print(format_strategy_recommendation(rec))

if __name__ == "__main__":
    asyncio.run(main())
