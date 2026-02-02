#!/usr/bin/env python3
"""상장/따리 복기글 상세 추출."""

import re
import json
from pathlib import Path
from bs4 import BeautifulSoup

chat_dir = Path(r'C:\Users\user\Downloads\Telegram Desktop\ChatExport_2026-02-02 (1)')
output_dir = Path(r'C:\Users\user\Documents\03_Claude\cex_dominance_bot\data\telegram_parsed')

keywords = ['따리', '상장', '김프', '역프', '선선', '현선', '입금']
reviews = []

for html_file in sorted(chat_dir.glob('messages*.html')):
    print(f'Processing: {html_file.name}')
    with open(html_file, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    
    for msg in soup.find_all('div', class_='text'):
        text = msg.get_text(strip=True)
        
        # 복기 + 상장/따리 관련
        if '복기' in text and any(k in text for k in keywords):
            parent = msg.find_parent('div', class_='message')
            date_div = parent.find('div', class_='date') if parent else None
            date_str = date_div.get('title', '')[:16] if date_div else ''
            
            # 심볼 추출
            symbols = re.findall(r'\$([A-Z]{2,10})\b', text)
            symbols += re.findall(r'\b([A-Z]{3,8})\s*(?:상장|복기|따리|김프)', text)
            
            # 거래소 추출
            exchange = ''
            if '업비트' in text or 'upbit' in text.lower():
                exchange = 'Upbit'
            elif '빗썸' in text or 'bithumb' in text.lower():
                exchange = 'Bithumb'
            
            # 결과 추출
            result = ''
            if '대흥' in text:
                result = '대흥따리'
            elif '흥따리' in text or '잘' in text:
                result = '흥따리'
            elif '망' in text or '실패' in text:
                result = '망따리'
            
            # 수익률 추출
            profit_match = re.search(r'(\d+(?:\.\d+)?)\s*%', text)
            profit = profit_match.group(1) if profit_match else ''
            
            reviews.append({
                'date': date_str,
                'symbols': list(set(symbols)),
                'exchange': exchange,
                'result': result,
                'profit_pct': profit,
                'text': text[:500],
            })

print(f'\nFound {len(reviews)} reviews')

# 저장
output_path = output_dir / 'detailed_reviews.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(reviews, f, ensure_ascii=False, indent=2)

print(f'Saved to: {output_path}')

# 상세 출력
print('\n=== 상장/따리 복기글 ===\n')
for r in reviews[:20]:
    print(f"[{r['date']}] {r['symbols']} {r['exchange']} {r['result']}")
    print(f"  {r['text'][:150]}...")
    print()
