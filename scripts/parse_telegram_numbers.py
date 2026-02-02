#!/usr/bin/env python3
"""
텔레그램 복기글에서 숫자 데이터 자동 추출

패턴:
- 입금액: "입금 205억", "입금액 약 21억", "입금량 5억"
- 거래량: "5분 910억", "거래량 5억", "1분 350억"
- 프리미엄: "김프 90%", "30퍼", "10퍼대"
- turnover_ratio: 거래량/입금액 계산
"""

import csv
import re
from pathlib import Path


def parse_korean_number(text: str) -> float | None:
    """한글 숫자 파싱 (억, 만 단위)
    
    Returns:
        KRW 단위 숫자 (예: 21억 -> 21000000000.0)
    """
    if not text:
        return None
    
    # 숫자 추출
    text = text.replace(",", "").replace(" ", "")
    
    # 억 단위
    match = re.search(r'(\d+(?:\.\d+)?)\s*억', text)
    if match:
        return float(match.group(1)) * 100_000_000
    
    # 만 단위
    match = re.search(r'(\d+(?:\.\d+)?)\s*만', text)
    if match:
        return float(match.group(1)) * 10_000
    
    # 그냥 숫자
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if match:
        return float(match.group(1))
    
    return None


def extract_deposit(notes: str) -> float | None:
    """입금액 추출"""
    patterns = [
        r'입금(?:액|량)?[^\d]*?약?\s*(\d+(?:\.\d+)?)\s*억',
        r'입금(?:액|량)?\s*(\d+(?:\.\d+)?)\s*억',
        r'실제\s*입금(?:액|량)?\s*약?\s*(\d+(?:\.\d+)?)\s*억',
        r'입금\s*(\d+)\s*억',
        r'입금(?:액|량)?\s*(\d+)~\d+\s*억',  # "입금액 15~16억" -> 15억
        r'(\d+(?:\.\d+)?)\s*억\s*(?:가량|규모|수준)',  # "21억 규모"
        r'입금\s*완료.{0,20}(\d+)\s*억',  # "입금 완료... 21억"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, notes)
        if match:
            return float(match.group(1)) * 100_000_000
    
    return None


def extract_volume_5m(notes: str) -> float | None:
    """5분 거래량 추출"""
    patterns = [
        r'5분\s*(\d+(?:\.\d+)?)\s*억',
        r'거래량\s*(\d+(?:\.\d+)?)\s*억',
        r'(\d+(?:\.\d+)?)\s*억\s*거래량',
        r'거래\s*시작\s*후[^\d]*(\d+(?:\.\d+)?)\s*억',
        r'1분.{0,10}(\d+(?:\.\d+)?)\s*억',  # "1분 350억"
        r'거래\s*(\d+(?:\.\d+)?)\s*억',  # "거래 5억"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, notes)
        if match:
            return float(match.group(1)) * 100_000_000
    
    return None


def extract_premium(notes: str) -> float | None:
    """최대 프리미엄 추출"""
    patterns = [
        r'김프\s*(\d+(?:\.\d+)?)\s*%?',
        r'(\d+(?:\.\d+)?)\s*퍼\s*(?:대|%|프리미엄|갭)',
        r'갭\s*(\d+(?:\.\d+)?)\s*퍼',
        r'(\d+(?:\.\d+)?)\s*%?\s*갭',
        r'현선\s*(\d+(?:\.\d+)?)\s*퍼',
        r'(\d+(?:\.\d+)?)\s*퍼대\s*현선',
        r'(\d+(?:\.\d+)?)\s*퍼대\s*(?:까지|수익|이득)',
        r'고점\s*(\d+(?:\.\d+)?)\s*%',
        r'~(\d+(?:\.\d+)?)\s*퍼',  # "~10퍼대"
        r'(\d+)~(\d+)\s*퍼',  # "4~6퍼" -> 6 (max)
        r'(\d+(?:\.\d+)?)\s*%\s*(?:수익|이득|갭)',
        r'(\d+(?:\.\d+)?)\s*퍼\s*(?:수익|이득|띠기)',
        r'(\d+(?:\.\d+)?)\s*퍼\s*정도',
    ]
    
    max_premium = None
    for pattern in patterns:
        matches = re.findall(pattern, notes)
        for match in matches:
            # 튜플인 경우 (4~6퍼 같은 패턴)
            if isinstance(match, tuple):
                vals = [float(m) for m in match if m]
                val = max(vals) if vals else 0
            else:
                val = float(match)
            
            if val > 0 and val < 500:  # 합리적인 범위
                if max_premium is None or val > max_premium:
                    max_premium = val
    
    return max_premium


def process_csv(input_path: Path, output_path: Path):
    """CSV 파일 처리"""
    
    rows = []
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        
        for row in reader:
            notes = row.get('result_notes', '')
            
            # 기존 값이 없으면 추출 시도
            if not row.get('deposit_krw') or row['deposit_krw'] == '':
                deposit = extract_deposit(notes)
                if deposit:
                    row['deposit_krw'] = deposit
            
            if not row.get('volume_5m_krw') or row['volume_5m_krw'] == '':
                volume = extract_volume_5m(notes)
                if volume:
                    row['volume_5m_krw'] = volume
            
            if not row.get('max_premium_pct') or row['max_premium_pct'] == '':
                premium = extract_premium(notes)
                if premium:
                    row['max_premium_pct'] = premium
            
            # turnover_ratio 계산
            deposit = row.get('deposit_krw')
            volume = row.get('volume_5m_krw')
            if deposit and volume:
                try:
                    d = float(deposit)
                    v = float(volume)
                    if d > 0:
                        row['turnover_ratio'] = round(v / d, 2)
                except (ValueError, TypeError):
                    pass
            
            rows.append(row)
    
    # 결과 저장
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    return rows


def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    base_dir = Path(__file__).parent.parent / 'data' / 'labeling'
    input_file = base_dir / 'telegram_extracted.csv'
    output_file = base_dir / 'telegram_extracted_enriched.csv'
    
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    
    rows = process_csv(input_file, output_file)
    
    # 통계 출력
    total = len(rows)
    has_deposit = sum(1 for r in rows if r.get('deposit_krw'))
    has_volume = sum(1 for r in rows if r.get('volume_5m_krw'))
    has_premium = sum(1 for r in rows if r.get('max_premium_pct'))
    has_turnover = sum(1 for r in rows if r.get('turnover_ratio'))
    
    print(f"\n[Result]")
    print(f"  Total: {total}")
    print(f"  - deposit_krw: {has_deposit} ({has_deposit/total*100:.1f}%)")
    print(f"  - volume_5m_krw: {has_volume} ({has_volume/total*100:.1f}%)")
    print(f"  - max_premium_pct: {has_premium} ({has_premium/total*100:.1f}%)")
    print(f"  - turnover_ratio: {has_turnover} ({has_turnover/total*100:.1f}%)")
    
    # 샘플 출력
    print(f"\n[Sample - first 5]")
    for row in rows[:5]:
        print(f"  {row['symbol']}/{row['exchange']}: deposit={row.get('deposit_krw', '-')}, volume={row.get('volume_5m_krw', '-')}, premium={row.get('max_premium_pct', '-')}%, turnover={row.get('turnover_ratio', '-')}")


if __name__ == '__main__':
    main()
