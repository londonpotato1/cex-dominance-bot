#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""상장 알림 핸들러 테스트"""
import asyncio
import sys
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(message)s')

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from collectors.listing_monitor import ListingNotice
from collectors.listing_alert_handler import ListingAlertHandler

async def main():
    print("=== Listing Alert Handler Test ===\n")
    
    # 테스트용 공지 생성
    notice = ListingNotice(
        notice_id="test123",
        title="[마켓 추가] NEWCOIN(NEW) 원화 마켓 추가",
        url="https://example.com/notice",
        exchange="upbit",
        symbols=["NEW"],
        listing_time="2026-02-01 14:00:00",
    )
    
    # 핸들러 생성 (콘솔 출력 모드)
    handler = ListingAlertHandler()
    
    # 핸들러 테스트
    print("Testing handler with mock notice...\n")
    await handler.handle_listing(notice)
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(main())
