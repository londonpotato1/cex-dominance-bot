#!/usr/bin/env python3
"""텔레그램 파싱 데이터를 listing_data.csv 형식으로 변환.

백테스팅에 사용할 수 있는 형태로 변환.
"""

import json
import csv
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class BacktestEntry:
    """백테스트용 엔트리."""
    symbol: str
    exchange: str
    date: str
    listing_type: str  # TGE, 직상장, 옆상장
    deposit_krw: Optional[float] = None
    volume_5m_krw: Optional[float] = None
    turnover_ratio: Optional[float] = None
    max_premium_pct: Optional[float] = None
    supply_label: str = ""
    hedge_type: str = "cex_futures"
    market_condition: str = "neutral"
    result_label: str = ""
    result_notes: str = ""


def parse_korean_number(text: str) -> Optional[float]:
    """한국어 숫자 표현 파싱 (예: 3000억, 50억).
    
    Returns: 원화 금액 (억 단위로 반환)
    """
    # 억 패턴
    match = re.search(r'(\d+(?:\.\d+)?)\s*억', text)
    if match:
        return float(match.group(1)) * 100_000_000  # 억 -> 원
    
    # 조 패턴
    match = re.search(r'(\d+(?:\.\d+)?)\s*조', text)
    if match:
        return float(match.group(1)) * 1_000_000_000_000  # 조 -> 원
    
    return None


def extract_listing_type(text: str) -> str:
    """상장 유형 추출."""
    if 'TGE' in text.upper():
        return 'TGE'
    elif '직상장' in text:
        return '직상장'
    elif '옆상장' in text or '재상장' in text:
        return '옆상장'
    elif '신규' in text:
        return 'TGE'
    return ''


def extract_result_label(text: str) -> str:
    """결과 라벨 추출."""
    if '대흥' in text or '초대박' in text or '100%' in text or '200%' in text:
        return '대흥따리'
    elif '흥따리' in text or '괜찮' in text:
        return '흥따리'
    elif '망' in text or '실패' in text or '손실' in text:
        return '망따리'
    elif '보통' in text or '노잼' in text:
        return '보통'
    return ''


def extract_market_condition(text: str) -> str:
    """시장 상황 추출."""
    if '불장' in text or '상승장' in text:
        return 'bull'
    elif '하락장' in text or '베어' in text:
        return 'bear'
    return 'neutral'


def extract_supply_label(text: str) -> str:
    """공급 라벨 추출."""
    if '입금적' in text or '물량부족' in text or 'constrained' in text.lower():
        return 'constrained'
    elif '입금많' in text or '물량풍' in text or 'smooth' in text.lower():
        return 'smooth'
    return ''


def extract_deposit_volume(text: str) -> tuple:
    """입금액, 거래량 추출."""
    deposit = None
    volume = None
    
    # 입금액 패턴
    deposit_match = re.search(r'입금\s*(\d+(?:\.\d+)?)\s*억', text)
    if deposit_match:
        deposit = float(deposit_match.group(1)) * 100_000_000
    
    # 거래량 패턴
    volume_match = re.search(r'거래량\s*(\d+(?:\.\d+)?)\s*(억|조)', text)
    if volume_match:
        val = float(volume_match.group(1))
        unit = volume_match.group(2)
        volume = val * (100_000_000 if unit == '억' else 1_000_000_000_000)
    
    return deposit, volume


def extract_premium(text: str) -> Optional[float]:
    """김프 수치 추출."""
    # 김프 XX% 패턴
    match = re.search(r'김프\s*(\d+(?:\.\d+)?)\s*%', text)
    if match:
        return float(match.group(1))
    
    # XX% 김프 패턴
    match = re.search(r'(\d+(?:\.\d+)?)\s*%\s*김프', text)
    if match:
        return float(match.group(1))
    
    return None


def process_cases(cases: List[dict]) -> List[BacktestEntry]:
    """케이스 목록을 백테스트 엔트리로 변환."""
    entries = []
    
    for case in cases:
        text = case.get('raw_text', '')
        symbol = case.get('symbol', '')
        exchange = case.get('exchange', '')
        date = case.get('date', '')
        
        # 심볼이 없거나 너무 짧으면 스킵
        if not symbol or len(symbol) < 2:
            continue
        
        # 거래소가 업비트/빗썸이 아니면 스킵 (국내 따리 위주)
        if exchange not in ['Upbit', 'Bithumb', '']:
            continue
        
        listing_type = extract_listing_type(text)
        result_label = extract_result_label(text)
        market_condition = extract_market_condition(text)
        supply_label = extract_supply_label(text)
        deposit, volume = extract_deposit_volume(text)
        premium = extract_premium(text)
        
        # 최소한의 정보가 있어야 추가
        if exchange and (result_label or premium or deposit):
            entry = BacktestEntry(
                symbol=symbol,
                exchange=exchange,
                date=date,
                listing_type=listing_type,
                deposit_krw=deposit,
                volume_5m_krw=volume,
                max_premium_pct=premium,
                supply_label=supply_label,
                market_condition=market_condition,
                result_label=result_label,
                result_notes=text[:200],
            )
            entries.append(entry)
    
    return entries


def main():
    """메인 실행."""
    data_dir = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot\data\telegram_parsed")
    output_dir = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot\data\labeling")
    
    # 모든 케이스 로드
    all_cases_path = data_dir / "all_cases.json"
    with open(all_cases_path, 'r', encoding='utf-8') as f:
        all_cases = json.load(f)
    
    print(f"로드된 케이스: {len(all_cases)}개")
    
    # 변환
    entries = process_cases(all_cases)
    print(f"변환된 엔트리: {len(entries)}개")
    
    # 기존 데이터와 병합
    existing_path = output_dir / "listing_data.csv"
    existing_symbols = set()
    
    if existing_path.exists():
        with open(existing_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = f"{row['symbol']}_{row['exchange']}_{row['date']}"
                existing_symbols.add(key)
        print(f"기존 데이터: {len(existing_symbols)}개 심볼")
    
    # 새 데이터만 추가
    new_entries = []
    for entry in entries:
        key = f"{entry.symbol}_{entry.exchange}_{entry.date}"
        if key not in existing_symbols:
            new_entries.append(entry)
    
    print(f"새로 추가할 엔트리: {len(new_entries)}개")
    
    # CSV로 저장 (새 데이터만)
    if new_entries:
        new_csv_path = output_dir / "telegram_extracted.csv"
        with open(new_csv_path, 'w', encoding='utf-8', newline='') as f:
            fieldnames = [
                'symbol', 'exchange', 'date', 'listing_type',
                'deposit_krw', 'volume_5m_krw', 'turnover_ratio',
                'max_premium_pct', 'supply_label', 'hedge_type',
                'market_condition', 'result_label', 'result_notes'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for entry in new_entries:
                writer.writerow({
                    'symbol': entry.symbol,
                    'exchange': entry.exchange,
                    'date': entry.date,
                    'listing_type': entry.listing_type,
                    'deposit_krw': entry.deposit_krw or '',
                    'volume_5m_krw': entry.volume_5m_krw or '',
                    'turnover_ratio': entry.turnover_ratio or '',
                    'max_premium_pct': entry.max_premium_pct or '',
                    'supply_label': entry.supply_label,
                    'hedge_type': entry.hedge_type,
                    'market_condition': entry.market_condition,
                    'result_label': entry.result_label,
                    'result_notes': entry.result_notes,
                })
        
        print(f"\n저장됨: {new_csv_path}")
    
    # 상세 분석 출력
    print("\n=== 추출된 상장 사례 분석 ===")
    
    # 거래소별 분류
    by_exchange = {}
    for entry in entries:
        ex = entry.exchange
        if ex not in by_exchange:
            by_exchange[ex] = []
        by_exchange[ex].append(entry)
    
    for ex, items in by_exchange.items():
        print(f"\n{ex}: {len(items)}개")
        for item in items[:5]:
            print(f"  - {item.symbol} ({item.date}): {item.result_label or '라벨없음'}")
    
    # 결과 라벨별 분류
    by_label = {}
    for entry in entries:
        label = entry.result_label or '미분류'
        if label not in by_label:
            by_label[label] = []
        by_label[label].append(entry)
    
    print("\n=== 결과 라벨별 분류 ===")
    for label, items in sorted(by_label.items(), key=lambda x: -len(x[1])):
        print(f"  {label}: {len(items)}개")
    
    return entries


if __name__ == "__main__":
    main()
