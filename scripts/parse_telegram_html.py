#!/usr/bin/env python3
"""
텔레그램 HTML 채팅 파일 파싱 → CEX Dominance Bot 데이터 형식으로 변환
"""

import json
import re
import os
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

# 경로 설정
INPUT_HTML = r"C:\Users\user\Downloads\Telegram Desktop\ChatExport_2026-02-02 (3)\messages.html"
OUTPUT_DIR = r"C:\Users\user\Documents\03_Claude\cex_dominance_bot\data\telegram_parsed"

# 플레이 타입 키워드
PLAY_TYPES = {
    "상장따리": ["상장", "따리", "원상", "업빗", "빗썸", "업비트", "bithumb", "upbit", "코인원"],
    "김프": ["김프", "김치프리미엄", "김치 프리미엄", "아비트리지", "arbitrage"],
    "선선갭": ["선선갭", "선선", "선물갭", "바낸", "바이낸스", "바이빗", "bybit", "bitget", "okx"],
    "현선갭": ["현선갭", "현선", "펀비", "펀딩비", "funding"],
    "브릿지": ["브릿지", "bridge", "체인간", "크로스체인"],
    "에드작": ["에드", "에어드랍", "airdrop", "에드작"],
    "덱스": ["덱스", "dex", "유니스왑", "레이디움", "주피터"],
}

# 거래소 키워드
EXCHANGES = {
    "Upbit": ["업비트", "upbit", "업빗"],
    "Bithumb": ["빗썸", "bithumb", "빗"],
    "Binance": ["바이낸스", "binance", "바낸"],
    "Bybit": ["바이빗", "bybit"],
    "OKX": ["okx", "오케이엑스"],
    "Bitget": ["bitget", "비트겟"],
    "Gate.io": ["gate", "gate.io", "게이트"],
    "KuCoin": ["쿠코인", "kucoin"],
    "MEXC": ["mexc", "엠이엑스씨"],
    "Hyperliquid": ["하이퍼리퀴드", "hyperliquid", "하리"],
}

# 결과 키워드
RESULTS = {
    "흥따리": ["흥따리", "성공", "수익", "익절"],
    "망따리": ["망따리", "실패", "손실", "손절"],
}

# 코인 심볼 패턴
SYMBOL_PATTERN = re.compile(r'\$([A-Z]{2,10})\b|(?<![a-zA-Z])([A-Z]{2,6})(?=/|\s|$|상장|따리)')

def extract_symbols(text):
    """텍스트에서 코인 심볼 추출"""
    symbols = set()
    # $XXX 패턴
    matches = re.findall(r'\$([A-Z]{2,10})\b', text.upper())
    symbols.update(matches)
    
    # 특정 코인 이름 직접 매칭
    known_coins = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'PEPE', 'WIF', 'BONK', 'ONDO', 
                   'NXPC', 'WLFI', 'XPL', 'SUPER', 'FLUID', 'FF', 'MIRA', 'CUDIS',
                   'GMX', 'ARB', 'OP', 'FLOKI', 'GRASS', 'XYO', 'PUMP', 'TOWNS', 'DOUBLEZER0']
    for coin in known_coins:
        if coin in text.upper():
            symbols.add(coin)
    
    # 필터링: 일반 단어 제외
    excluded = {'THE', 'AND', 'FOR', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HER', 'WAS', 
                'ONE', 'OUR', 'OUT', 'DAY', 'GET', 'HAS', 'HIM', 'HIS', 'HOW', 'MAN',
                'NEW', 'NOW', 'OLD', 'SEE', 'WAY', 'WHO', 'BOY', 'DID', 'ITS', 'LET',
                'PUT', 'SAY', 'SHE', 'TOO', 'USE', 'FAQ', 'UTC', 'EXP', 'CEX', 'DEX',
                'PRE', 'OTC', 'TVL', 'APY', 'APR', 'SBF', 'FTX', 'WEN', 'EVM'}
    symbols = {s for s in symbols if s not in excluded}
    
    return list(symbols)

def detect_play_type(text):
    """텍스트에서 플레이 타입 감지"""
    text_lower = text.lower()
    for play_type, keywords in PLAY_TYPES.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                return play_type
    return "기타"

def detect_exchange(text):
    """텍스트에서 거래소 감지"""
    text_lower = text.lower()
    for exchange, keywords in EXCHANGES.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                return exchange
    return ""

def detect_result(text):
    """텍스트에서 결과 감지"""
    text_lower = text.lower()
    for result, keywords in RESULTS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                return result
    return ""

def extract_profit_pct(text):
    """텍스트에서 수익률 추출"""
    # 패턴: 10%, 10퍼, 10프로, 약 10%
    patterns = [
        r'(\d+(?:\.\d+)?)\s*[%퍼프]',
        r'약\s*(\d+(?:\.\d+)?)\s*[%퍼프]',
        r'(\d+(?:\.\d+)?)\s*배',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None

def is_trading_case(text):
    """거래 사례/복기글인지 판단"""
    keywords = ['복기', '상장', '따리', '선선', '현선', '김프', '아비트리지', 
                '수익', '손실', '익절', '손절', '매수', '매도', '롱', '숏',
                '펀비', '갭', '브릿지', '입금', '출금']
    text_lower = text.lower()
    count = sum(1 for kw in keywords if kw in text_lower)
    return count >= 2  # 2개 이상 키워드 포함시 거래 사례로 판단

def parse_html_messages(html_path):
    """HTML 파일에서 메시지 파싱"""
    print(f"Reading HTML file: {html_path}")
    
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    
    messages = []
    current_date = None
    
    # 모든 메시지 div 찾기
    for div in soup.find_all('div', class_='message'):
        # 날짜 서비스 메시지
        if 'service' in div.get('class', []):
            date_div = div.find('div', class_='body')
            if date_div:
                date_text = date_div.get_text(strip=True)
                # "25 January 2025" 형식 파싱
                try:
                    current_date = datetime.strptime(date_text, '%d %B %Y').strftime('%Y-%m-%d')
                except:
                    pass
            continue
        
        # 일반 메시지
        text_div = div.find('div', class_='text')
        if text_div:
            # HTML 태그 제거하고 텍스트 추출
            text = text_div.get_text('\n', strip=True)
            
            # 날짜/시간 추출
            date_div = div.find('div', class_='date')
            time_str = ""
            full_date = current_date
            if date_div:
                title = date_div.get('title', '')
                # "25.01.2025 13:54:33 UTC+09:00" 형식
                match = re.search(r'(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})', title)
                if match:
                    try:
                        full_date = datetime.strptime(match.group(1), '%d.%m.%Y').strftime('%Y-%m-%d')
                        time_str = match.group(2)
                    except:
                        pass
            
            if text and len(text) > 20:  # 최소 길이 필터
                messages.append({
                    'date': full_date,
                    'time': time_str,
                    'text': text
                })
    
    print(f"Parsed {len(messages)} messages")
    return messages

def extract_trading_cases(messages):
    """메시지에서 거래 사례 추출"""
    all_cases = []
    detailed_reviews = []
    
    for msg in messages:
        text = msg['text']
        
        if not is_trading_case(text):
            continue
        
        # all_cases 형식
        case = {
            'date': msg['date'],
            'symbol': ', '.join(extract_symbols(text)[:3]),  # 최대 3개
            'exchange': detect_exchange(text),
            'play_type': detect_play_type(text),
            'entry_condition': '',
            'exit_condition': '',
            'result_pct': extract_profit_pct(text),
            'result_label': detect_result(text),
            'notes': '',
            'raw_text': text[:500]  # 최대 500자
        }
        all_cases.append(case)
        
        # detailed_reviews 형식 (복기 키워드 포함시)
        if '복기' in text.lower():
            review = {
                'date': f"{msg['date']} {msg['time']}".strip() if msg['time'] else msg['date'],
                'symbols': extract_symbols(text),
                'exchange': detect_exchange(text),
                'result': detect_result(text),
                'profit_pct': str(extract_profit_pct(text)) if extract_profit_pct(text) else '',
                'text': text[:1000]
            }
            detailed_reviews.append(review)
    
    print(f"Extracted {len(all_cases)} trading cases")
    print(f"Extracted {len(detailed_reviews)} detailed reviews")
    
    return all_cases, detailed_reviews

def merge_with_existing(new_data, existing_path, key_func):
    """기존 데이터와 병합 (중복 제거)"""
    existing_data = []
    if os.path.exists(existing_path):
        with open(existing_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
    
    # 기존 데이터 키 집합
    existing_keys = set()
    for item in existing_data:
        existing_keys.add(key_func(item))
    
    # 새 데이터 중 중복 아닌 것만 추가
    added = 0
    for item in new_data:
        key = key_func(item)
        if key not in existing_keys:
            existing_data.append(item)
            existing_keys.add(key)
            added += 1
    
    print(f"Added {added} new items (total: {len(existing_data)})")
    return existing_data

def main():
    # 출력 디렉토리 생성
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # HTML 파싱
    messages = parse_html_messages(INPUT_HTML)
    
    # 거래 사례 추출
    all_cases, detailed_reviews = extract_trading_cases(messages)
    
    # 기존 데이터와 병합
    all_cases_path = os.path.join(OUTPUT_DIR, 'all_cases.json')
    detailed_reviews_path = os.path.join(OUTPUT_DIR, 'detailed_reviews.json')
    
    # 키 함수: 날짜 + 텍스트 일부로 중복 체크
    def case_key(item):
        return f"{item.get('date', '')}_{item.get('raw_text', '')[:50]}"
    
    def review_key(item):
        return f"{item.get('date', '')}_{item.get('text', '')[:50]}"
    
    merged_cases = merge_with_existing(all_cases, all_cases_path, case_key)
    merged_reviews = merge_with_existing(detailed_reviews, detailed_reviews_path, review_key)
    
    # 저장
    with open(all_cases_path, 'w', encoding='utf-8') as f:
        json.dump(merged_cases, f, ensure_ascii=False, indent=2)
    
    with open(detailed_reviews_path, 'w', encoding='utf-8') as f:
        json.dump(merged_reviews, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== 결과 ===")
    print(f"파싱된 총 메시지: {len(messages)}")
    print(f"추출된 거래 사례: {len(all_cases)}")
    print(f"추출된 복기글: {len(detailed_reviews)}")
    print(f"저장 위치: {OUTPUT_DIR}")
    
    # 요약 통계
    play_type_counts = {}
    for case in all_cases:
        pt = case.get('play_type', '기타')
        play_type_counts[pt] = play_type_counts.get(pt, 0) + 1
    
    print(f"\n플레이 타입별 분포:")
    for pt, cnt in sorted(play_type_counts.items(), key=lambda x: -x[1]):
        print(f"  {pt}: {cnt}")
    
    return {
        'total_messages': len(messages),
        'trading_cases': len(all_cases),
        'detailed_reviews': len(detailed_reviews),
        'play_type_distribution': play_type_counts
    }

if __name__ == '__main__':
    main()
