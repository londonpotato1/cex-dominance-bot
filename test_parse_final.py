import asyncio
from collectors.binance_notice import BinanceNoticeFetcher

async def test():
    fetcher = BinanceNoticeFetcher()
    try:
        notices = await fetcher.fetch_all_listings(page_size=3)
        for n in notices[:1]:
            print(f'Title: {n.title}')
            print(f'Symbols: {n.symbols}')
            print(f'Before parse - listing_time: {n.listing_time}')
            
            content = await fetcher.fetch_article_content(n)
            print(f'Content length: {len(content)}')
            print(f'Content preview: {content[:300]}...')
            print()
            print(f'After parse - listing_time: {n.listing_time}')
            print(f'After parse - deposit_time: {n.deposit_time}')
            print(f'After parse - withdraw_time: {n.withdraw_time}')
    finally:
        await fetcher.close()

asyncio.run(test())
