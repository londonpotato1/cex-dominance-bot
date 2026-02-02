#!/usr/bin/env python3
"""
Claude API를 사용해서 텔레그램 복기글에서 상장 데이터 추출

추출 필드:
- deposit_krw: 입금액 (원)
- volume_5m_krw: 5분 거래량 (원)
- turnover_ratio: 거래량/입금액
- max_premium_pct: 최대 프리미엄 (%)
- supply_label: 공급 상황 (constrained/smooth)
- market_condition: 시장 상황 (bull/bear/neutral)
- listing_type: 상장 유형 (TGE/DIRECT/SIDE)
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

# Anthropic SDK
try:
    import anthropic
except ImportError:
    print("anthropic 패키지 필요: pip install anthropic")
    sys.exit(1)


EXTRACTION_PROMPT = '''당신은 암호화폐 상장(리스팅) 복기글을 분석하는 전문가입니다.
주어진 복기글에서 다음 정보를 추출해주세요.

## 추출할 필드

1. **deposit_krw**: 입금액 (원화, 숫자만)
   - "입금 21억" → 2100000000
   - "입금액 15~16억" → 1500000000 (최소값)
   - 정보 없으면 null

2. **volume_5m_krw**: 5분 거래량 (원화, 숫자만)  
   - "5분 910억" → 91000000000
   - "거래량 5억" → 500000000
   - 정보 없으면 null

3. **max_premium_pct**: 최대 프리미엄/김프/갭 (%, 숫자만)
   - "김프 90%" → 90
   - "30퍼대 갭" → 30
   - "현선 6퍼" → 6
   - 정보 없으면 null

4. **supply_label**: 공급 상황
   - "constrained": 공급 제한 (입금 적음, 네트워크 혼잡, 출금 막힘)
   - "smooth": 공급 원활 (입금 많음, 출금 열림)
   - 정보 없으면 null

5. **market_condition**: 시장 상황
   - "bull": 상승장, 불장
   - "bear": 하락장
   - "neutral": 보통
   - 정보 없으면 "neutral"

6. **listing_type**: 상장 유형
   - "TGE": 토큰 첫 발행 상장 (TGE, 신규)
   - "DIRECT": 직상장 (김치코인, 재상장)
   - "SIDE": 옆상장 (이미 다른 거래소에 있는 코인)
   - 정보 없으면 null

7. **hedge_type**: 헷징 방법
   - "cex_futures": 선물 헷징 가능 (바이낸스 등)
   - "none": 헷징 불가
   - 정보 없으면 "cex_futures"

## 복기글 정보
- 코인: {symbol}
- 거래소: {exchange}
- 날짜: {date}
- 결과: {result_label}

## 복기글 원문
{notes}

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요. 설명 없이 JSON만:

{{
  "deposit_krw": <숫자 또는 null>,
  "volume_5m_krw": <숫자 또는 null>,
  "max_premium_pct": <숫자 또는 null>,
  "supply_label": "<constrained|smooth 또는 null>",
  "market_condition": "<bull|bear|neutral>",
  "listing_type": "<TGE|DIRECT|SIDE 또는 null>",
  "hedge_type": "<cex_futures|none>",
  "reasoning": "<추출 근거 한 줄>"
}}
'''


def extract_with_claude(client: anthropic.Anthropic, row: dict) -> dict:
    """Claude API로 복기글에서 데이터 추출"""
    
    prompt = EXTRACTION_PROMPT.format(
        symbol=row.get('symbol', ''),
        exchange=row.get('exchange', ''),
        date=row.get('date', ''),
        result_label=row.get('result_label', ''),
        notes=row.get('result_notes', '')
    )
    
    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",  # 빠르고 저렴
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # 응답 파싱
        text = response.content[0].text.strip()
        
        # JSON 추출 (코드블록 제거)
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        
        data = json.loads(text)
        return data
        
    except json.JSONDecodeError as e:
        print(f"  [WARN] JSON 파싱 실패: {e}")
        return {}
    except Exception as e:
        print(f"  [ERROR] API 호출 실패: {e}")
        return {}


def process_csv(input_path: Path, output_path: Path):
    """CSV 파일 처리"""
    
    # API 클라이언트
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY 환경변수 필요")
        sys.exit(1)
    
    client = anthropic.Anthropic(api_key=api_key)
    
    # 입력 파일 로드
    rows = []
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    
    print(f"Total rows: {len(rows)}")
    
    # 각 row 처리
    enriched_rows = []
    for i, row in enumerate(rows):
        symbol = row.get('symbol', '')
        exchange = row.get('exchange', '')
        notes = row.get('result_notes', '')
        
        # 복기글이 너무 짧으면 스킵
        if len(notes) < 50:
            print(f"[{i+1}/{len(rows)}] {symbol}/{exchange}: SKIP (too short)")
            enriched_rows.append(row)
            continue
        
        print(f"[{i+1}/{len(rows)}] {symbol}/{exchange}: Extracting...", end=" ")
        
        # Claude API 호출
        extracted = extract_with_claude(client, row)
        
        if extracted:
            # 추출된 데이터 병합 (기존 값이 없을 때만)
            for field in ['deposit_krw', 'volume_5m_krw', 'max_premium_pct', 
                         'supply_label', 'market_condition', 'listing_type', 'hedge_type']:
                if extracted.get(field) and not row.get(field):
                    row[field] = extracted[field]
            
            # turnover_ratio 계산
            if row.get('deposit_krw') and row.get('volume_5m_krw'):
                try:
                    d = float(row['deposit_krw'])
                    v = float(row['volume_5m_krw'])
                    if d > 0:
                        row['turnover_ratio'] = round(v / d, 2)
                except (ValueError, TypeError):
                    pass
            
            reasoning = extracted.get('reasoning', '')[:50]
            print(f"OK - {reasoning}")
        else:
            print("FAIL")
        
        enriched_rows.append(row)
        
        # Rate limit 방지
        time.sleep(0.5)
    
    # 결과 저장
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched_rows)
    
    print(f"\nOutput saved: {output_path}")
    
    # 통계
    has_deposit = sum(1 for r in enriched_rows if r.get('deposit_krw'))
    has_volume = sum(1 for r in enriched_rows if r.get('volume_5m_krw'))
    has_premium = sum(1 for r in enriched_rows if r.get('max_premium_pct'))
    has_supply = sum(1 for r in enriched_rows if r.get('supply_label'))
    
    print(f"\n[Stats]")
    print(f"  deposit_krw: {has_deposit}/{len(enriched_rows)}")
    print(f"  volume_5m_krw: {has_volume}/{len(enriched_rows)}")
    print(f"  max_premium_pct: {has_premium}/{len(enriched_rows)}")
    print(f"  supply_label: {has_supply}/{len(enriched_rows)}")


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    
    base_dir = Path(__file__).parent.parent / 'data' / 'labeling'
    input_file = base_dir / 'telegram_extracted.csv'
    output_file = base_dir / 'telegram_extracted_ai.csv'
    
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print()
    
    process_csv(input_file, output_file)


if __name__ == '__main__':
    main()
