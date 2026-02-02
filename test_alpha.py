import asyncio
from collectors.binance_notice import BinanceNoticeFetcher

async def test():
    fetcher = BinanceNoticeFetcher()
    try:
        notices = await fetcher.fetch_all_listings(page_size=5)
        for n in notices[:3]:
            print(f'Title: {n.title}')
            print(f'Type: {n.listing_type}')
            print(f'Seed Tag: {n.seed_tag}')
            
            content = await fetcher.fetch_article_content(n)
            
            # Alpha 관련 텍스트 찾기
            import re
            alpha_matches = re.findall(r'[Aa]lpha[^.]*\.', content)
            if alpha_matches:
                print(f'Alpha mentions: {alpha_matches[:3]}')
            
            # Binance Alpha 상장 정보 찾기
            alpha_listing = re.search(r'[Bb]inance\s+[Aa]lpha[^.]*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})', content)
            if alpha_listing:
                print(f'Alpha listing time: {alpha_listing.group()}')
            
            print('---')
    finally:
        await fetcher.close()

asyncio.run(test())
