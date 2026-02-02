import asyncio
from collectors.binance_notice import BinanceNoticeFetcher

async def test():
    fetcher = BinanceNoticeFetcher()
    try:
        notices = await fetcher.fetch_all_listings(page_size=1)
        n = notices[0]
        content = await fetcher.fetch_article_content(n)
        
        # 시간 관련 텍스트 찾기
        import re
        
        print("=== Content (relevant parts) ===")
        # open trading
        match1 = re.search(r'open trading.{0,50}\d{4}-\d{2}-\d{2}.{0,30}', content, re.IGNORECASE)
        if match1:
            print(f'Trading: {match1.group()}')
        
        # deposit
        match2 = re.search(r'deposit.{0,100}', content, re.IGNORECASE)
        if match2:
            print(f'Deposit: {match2.group()}')
        
        # withdraw
        match3 = re.search(r'withdraw.{0,100}', content, re.IGNORECASE)
        if match3:
            print(f'Withdraw: {match3.group()}')
        
        print()
        print(f"Parsed listing_time: {n.listing_time}")
        print(f"Parsed deposit_time: {n.deposit_time}")  
        print(f"Parsed withdraw_time: {n.withdraw_time}")
            
    finally:
        await fetcher.close()

asyncio.run(test())
