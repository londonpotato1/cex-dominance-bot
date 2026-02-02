import cloudscraper
import re

scraper = cloudscraper.create_scraper()
url = 'https://www.binance.com/en/support/announcement/c411646abd94488bba084537c5563beb'

resp = scraper.get(url)
print(f'Status: {resp.status_code}')

html = resp.text

# UTC 시간 패턴 찾기
matches = re.findall(r'202\d-\d{2}-\d{2}\s+\d{1,2}:\d{2}[^"<]*(?:UTC|\(UTC\))', html)
print(f'UTC matches: {matches[:10]}')

# open trading 찾기
trading_match = re.search(r'open trading[^\d]*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})[^"]*\(?UTC\)?', html, re.IGNORECASE)
if trading_match:
    print(f'Trading time: {trading_match.group(1)} {trading_match.group(2)}:{trading_match.group(3)} UTC')

# 출금 시간 찾기
withdraw_match = re.search(r'[Ww]ithdrawal[s]?\s+will\s+open[^\d]*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})[^"]*\(?UTC\)?', html)
if withdraw_match:
    print(f'Withdraw time: {withdraw_match.group(1)} {withdraw_match.group(2)}:{withdraw_match.group(3)} UTC')

# 입금 관련 찾기  
deposit_match = re.search(r'start depositing.*?one hour', html, re.IGNORECASE | re.DOTALL)
if deposit_match:
    print(f'Deposit: one hour before trading')
