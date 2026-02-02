#!/usr/bin/env python3
"""텔레그램 채팅 HTML 파싱 스크립트.

복기글, 상장 분석, 김프/역프, 선선/현선 갭 분석 등 추출.
"""

import re
import json
import csv
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List
from bs4 import BeautifulSoup
from datetime import datetime


@dataclass
class TradingCase:
    """거래 사례 데이터."""
    date: str
    symbol: str
    exchange: str  # 업비트, 빗썸, 바이낸스 등
    play_type: str  # 상장따리, 선선갭, 김프, 현선, 에드작 등
    entry_condition: str
    exit_condition: str
    result_pct: Optional[float]
    result_label: str  # 대흥따리, 흥따리, 보통, 망따리
    notes: str
    raw_text: str


# 키워드 패턴
KEYWORDS = {
    'review': ['복기', '플레이 복기', '상장 복기', '매매 복기', '따리 복기'],
    'listing': ['상장', '신규상장', '상장예정', '상장공시', '거래지원'],
    'kimp': ['김프', '역프', '김치프리미엄', '한국프리미엄'],
    'gap': ['선선', '현선', '갭', '펀비', '펀딩비'],
    'airdrop': ['에드작', '에어드랍', '에드', 'airdrop'],
    'exchange': ['업비트', '빗썸', '바이낸스', '코인베이스', 'upbit', 'bithumb', 'binance'],
}

# 종목 심볼 패턴 (대문자 알파벳 2-10자)
SYMBOL_PATTERN = re.compile(r'\b([A-Z]{2,10})\b')

# 수익률 패턴
PROFIT_PATTERN = re.compile(r'([+-]?\d+(?:\.\d+)?)\s*%')


def parse_html_file(filepath: Path) -> List[dict]:
    """HTML 파일에서 메시지 추출."""
    messages = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    
    # 메시지 div 찾기
    for msg_div in soup.find_all('div', class_='message'):
        if 'service' in msg_div.get('class', []):
            continue
            
        msg_data = {}
        
        # 날짜/시간 추출
        date_span = msg_div.find('div', class_='date')
        if date_span and date_span.get('title'):
            msg_data['datetime'] = date_span['title']
        else:
            msg_data['datetime'] = ''
        
        # 발신자 추출
        from_name = msg_div.find('div', class_='from_name')
        if from_name:
            msg_data['from'] = from_name.get_text(strip=True)
        else:
            msg_data['from'] = ''
        
        # 텍스트 내용 추출
        text_div = msg_div.find('div', class_='text')
        if text_div:
            # HTML 태그 제거하고 텍스트만 추출
            text = text_div.get_text(separator=' ', strip=True)
            msg_data['text'] = text
        else:
            msg_data['text'] = ''
        
        if msg_data['text']:
            messages.append(msg_data)
    
    return messages


def classify_message(text: str) -> dict:
    """메시지 분류."""
    categories = {}
    text_lower = text.lower()
    
    for category, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                categories[category] = True
                break
    
    return categories


def extract_symbols(text: str) -> List[str]:
    """종목 심볼 추출."""
    # 일반적인 단어 제외
    exclude = {'BTC', 'ETH', 'USD', 'USDT', 'KRW', 'THE', 'AND', 'FOR', 'BUY', 'SELL', 
               'LONG', 'SHORT', 'UTC', 'PDF', 'URL', 'API', 'CEX', 'DEX', 'TGE', 'OTC'}
    
    symbols = SYMBOL_PATTERN.findall(text)
    return [s for s in symbols if s not in exclude]


def extract_exchange(text: str) -> str:
    """거래소 추출."""
    text_lower = text.lower()
    
    if '업비트' in text or 'upbit' in text_lower:
        return 'Upbit'
    elif '빗썸' in text or 'bithumb' in text_lower:
        return 'Bithumb'
    elif '바이낸스' in text or 'binance' in text_lower:
        return 'Binance'
    elif '바이빗' in text or 'bybit' in text_lower:
        return 'Bybit'
    elif '게이트' in text or 'gate' in text_lower:
        return 'Gate'
    
    return ''


def extract_play_type(text: str, categories: dict) -> str:
    """플레이 유형 추출."""
    if '선선' in text:
        return '선선갭'
    elif '현선' in text:
        return '현선갭'
    elif categories.get('kimp'):
        return '김프'
    elif '상장따리' in text or '따리' in text:
        return '상장따리'
    elif categories.get('airdrop'):
        return '에드작'
    elif categories.get('listing'):
        return '상장분석'
    
    return '기타'


def extract_profit(text: str) -> Optional[float]:
    """수익률 추출."""
    matches = PROFIT_PATTERN.findall(text)
    if matches:
        try:
            return float(matches[0])
        except ValueError:
            pass
    return None


def extract_trading_case(msg: dict) -> Optional[TradingCase]:
    """메시지에서 거래 사례 추출."""
    text = msg.get('text', '')
    if not text:
        return None
    
    categories = classify_message(text)
    
    # 관련 키워드가 하나도 없으면 스킵
    if not any(categories.values()):
        return None
    
    # 날짜 파싱
    dt_str = msg.get('datetime', '')
    try:
        # 형식: 25.05.2022 19:52:23 UTC+09:00
        if dt_str:
            dt_match = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', dt_str)
            if dt_match:
                date = f"{dt_match.group(3)}-{dt_match.group(2)}-{dt_match.group(1)}"
            else:
                date = dt_str[:10]
        else:
            date = ''
    except:
        date = ''
    
    symbols = extract_symbols(text)
    exchange = extract_exchange(text)
    play_type = extract_play_type(text, categories)
    profit = extract_profit(text)
    
    # 결과 라벨 추출
    result_label = ''
    if '대흥' in text:
        result_label = '대흥따리'
    elif '흥따리' in text:
        result_label = '흥따리'
    elif '망따리' in text:
        result_label = '망따리'
    elif '보통' in text:
        result_label = '보통'
    
    return TradingCase(
        date=date,
        symbol=symbols[0] if symbols else '',
        exchange=exchange,
        play_type=play_type,
        entry_condition='',  # 수동 분석 필요
        exit_condition='',
        result_pct=profit,
        result_label=result_label,
        notes='',
        raw_text=text[:500],  # 원본 텍스트 (500자 제한)
    )


def main():
    """메인 실행."""
    chat_dir = Path(r"C:\Users\user\Downloads\Telegram Desktop\ChatExport_2026-02-02 (1)")
    output_dir = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot\data\telegram_parsed")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    all_messages = []
    all_cases = []
    
    # HTML 파일들 파싱
    html_files = list(chat_dir.glob("messages*.html"))
    print(f"발견된 HTML 파일: {len(html_files)}개")
    
    for html_file in html_files:
        print(f"파싱 중: {html_file.name}")
        messages = parse_html_file(html_file)
        print(f"  - 추출된 메시지: {len(messages)}개")
        all_messages.extend(messages)
    
    print(f"\n총 메시지: {len(all_messages)}개")
    
    # 거래 사례 추출
    for msg in all_messages:
        case = extract_trading_case(msg)
        if case:
            all_cases.append(case)
    
    print(f"추출된 거래 사례: {len(all_cases)}개")
    
    # 카테고리별 분류
    categories_count = {}
    for case in all_cases:
        pt = case.play_type
        categories_count[pt] = categories_count.get(pt, 0) + 1
    
    print("\n카테고리별 분류:")
    for cat, count in sorted(categories_count.items(), key=lambda x: -x[1]):
        print(f"  - {cat}: {count}개")
    
    # JSON 저장 (전체)
    json_path = output_dir / "all_cases.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump([asdict(c) for c in all_cases], f, ensure_ascii=False, indent=2)
    print(f"\nJSON 저장: {json_path}")
    
    # CSV 저장 (listing_data.csv 형식 호환)
    csv_path = output_dir / "trading_cases.csv"
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'date', 'symbol', 'exchange', 'play_type', 
            'entry_condition', 'exit_condition', 'result_pct', 
            'result_label', 'notes', 'raw_text'
        ])
        for case in all_cases:
            writer.writerow([
                case.date, case.symbol, case.exchange, case.play_type,
                case.entry_condition, case.exit_condition, case.result_pct,
                case.result_label, case.notes, case.raw_text[:200]
            ])
    print(f"CSV 저장: {csv_path}")
    
    # 복기글만 별도 저장
    reviews = [c for c in all_cases if '복기' in c.raw_text]
    if reviews:
        reviews_path = output_dir / "reviews.json"
        with open(reviews_path, 'w', encoding='utf-8') as f:
            json.dump([asdict(c) for c in reviews], f, ensure_ascii=False, indent=2)
        print(f"복기글 저장: {reviews_path} ({len(reviews)}개)")
    
    # 상장 관련만 별도 저장
    listings = [c for c in all_cases if c.play_type in ['상장따리', '상장분석']]
    if listings:
        listings_path = output_dir / "listings.json"
        with open(listings_path, 'w', encoding='utf-8') as f:
            json.dump([asdict(c) for c in listings], f, ensure_ascii=False, indent=2)
        print(f"상장 관련 저장: {listings_path} ({len(listings)}개)")
    
    return all_cases


if __name__ == "__main__":
    main()
