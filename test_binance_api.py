import asyncio
import aiohttp

async def test():
    code = 'c411646abd94488bba084537c5563beb'
    
    # 여러 API 엔드포인트 시도
    urls = [
        f'https://www.binance.com/bapi/composite/v1/public/cms/article/detail?articleCode={code}',
        f'https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode={code}',
        f'https://www.binance.com/bapi/composite/v1/friendly/cms/article/detail/{code}',
        f'https://www.binance.com/bapi/apex/v1/friendly/cms/article/{code}',
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
        'lang': 'en',
    }
    
    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    print(f'{url[-50:]}: {resp.status}')
                    if resp.status == 200:
                        data = await resp.json()
                        print(f'  Success! Keys: {data.keys() if isinstance(data, dict) else "not dict"}')
                        if 'data' in data:
                            print(f'  Data keys: {data["data"].keys() if isinstance(data["data"], dict) else data["data"]}')
            except Exception as e:
                print(f'{url[-50:]}: Error - {e}')

asyncio.run(test())
