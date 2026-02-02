#!/usr/bin/env python3
"""
telegram_extracted_enriched.csv를 listing_data.csv에 병합

규칙:
1. result_label이 있는 row만 병합 (대흥따리/흥따리/보통/망따리)
2. 중복 체크: symbol + exchange + date가 같으면 스킵
3. 새 데이터는 listing_data.csv 끝에 추가
"""

import csv
import sys
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    
    base_dir = Path(__file__).parent.parent / 'data' / 'labeling'
    enriched_file = base_dir / 'telegram_extracted_ai.csv'
    listing_file = base_dir / 'listing_data.csv'
    output_file = base_dir / 'listing_data_merged.csv'
    
    # 기존 listing_data 로드
    existing_keys = set()
    existing_rows = []
    
    with open(listing_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        listing_fieldnames = reader.fieldnames
        for row in reader:
            key = (row['symbol'], row['exchange'], row.get('date', ''))
            existing_keys.add(key)
            existing_rows.append(row)
    
    print(f"Existing listing_data.csv: {len(existing_rows)} rows")
    
    # enriched 데이터 로드 및 병합
    new_rows = []
    skipped = 0
    no_label = 0
    
    with open(enriched_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # result_label이 없으면 스킵
            label = row.get('result_label', '').strip()
            if label not in ['대흥따리', '흥따리', '보통', '망따리']:
                no_label += 1
                continue
            
            key = (row['symbol'], row['exchange'], row.get('date', ''))
            
            # 중복 체크
            if key in existing_keys:
                skipped += 1
                continue
            
            # 새 row를 listing_data 형식에 맞게 변환
            new_row = {field: row.get(field, '') for field in listing_fieldnames}
            new_rows.append(new_row)
            existing_keys.add(key)
    
    print(f"New rows to add: {len(new_rows)}")
    print(f"Skipped (duplicate): {skipped}")
    print(f"Skipped (no label): {no_label}")
    
    # 병합 파일 저장
    all_rows = existing_rows + new_rows
    
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=listing_fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    
    print(f"\nMerged file saved: {output_file}")
    print(f"Total rows: {len(all_rows)}")
    
    # 샘플 출력
    if new_rows:
        print(f"\n[New rows sample]")
        for row in new_rows[:5]:
            print(f"  {row['symbol']}/{row['exchange']}: {row['result_label']} (deposit={row.get('deposit_krw', '-')}, premium={row.get('max_premium_pct', '-')})")


if __name__ == '__main__':
    main()
