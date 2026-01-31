#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""마진 론 스캔 테스트"""
import asyncio
import sys

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from collectors.margin_loan import scan_loan_availability, LoanScanResult

def format_simple(result: LoanScanResult) -> str:
    """간단한 포맷 (이모지 없음)"""
    lines = [
        f"[{result.symbol}] Loan Available: {result.available_count} exchanges",
        "-" * 40,
    ]
    
    for info in result.results:
        status = "OK" if info.available else "NO"
        rate = f"{info.hourly_rate:.4f}%/h" if info.hourly_rate else "N/A"
        error = f" ({info.error})" if info.error else ""
        lines.append(f"  [{status}] {info.exchange}: {rate}{error}")
    
    if result.best_exchange:
        lines.append(f"\nBest: {result.best_exchange} ({result.best_rate:.4f}%/h)")
    
    return "\n".join(lines)

async def main():
    print("=== Margin Loan Scan Test ===\n")
    
    # BTC 테스트
    print("Scanning BTC...")
    result = await scan_loan_availability("BTC")
    print(format_simple(result))
    print()
    
    # ETH 테스트
    print("Scanning ETH...")
    result = await scan_loan_availability("ETH")
    print(format_simple(result))

if __name__ == "__main__":
    asyncio.run(main())
