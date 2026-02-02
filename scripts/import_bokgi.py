"""
김피카썬더볼트 복기 데이터 → learning_cases 테이블 import
"""

import json
import sqlite3
import time
from pathlib import Path

# 결과 라벨 분류
def classify_result(profit_pct: float) -> str:
    """수익률로 결과 라벨 자동 분류."""
    if profit_pct >= 5.0:
        return "heung_big"
    elif profit_pct >= 2.0:
        return "heung"
    elif profit_pct >= 0.0:
        return "neutral"
    else:
        return "mang"


def import_bokgi_data():
    """복기 데이터를 ddari.db에 import"""
    
    # 경로 설정
    bokgi_json = Path(r"C:\Users\user\clawd\data\bokgi_data.json")
    db_path = Path(__file__).parent.parent / "ddari.db"
    
    # JSON 로드
    with open(bokgi_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"[+] {len(data)}개 복기 데이터 로드")
    
    # DB 연결
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # learning_cases 테이블 존재 확인
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='learning_cases'"
    ).fetchone()
    
    if not tables:
        print("[X] learning_cases 테이블 없음. 마이그레이션 먼저 실행하세요.")
        return
    
    # 이미 있는 데이터 확인 (중복 방지)
    existing = set()
    for row in conn.execute("SELECT symbol, listing_date FROM learning_cases"):
        existing.add((row['symbol'], row['listing_date']))
    
    inserted = 0
    skipped = 0
    
    for entry in data:
        symbol = entry['symbol'].upper()
        listing_date = entry['date']
        
        # 중복 체크
        if (symbol, listing_date) in existing:
            print(f"[SKIP] {symbol} ({listing_date}) - already exists")
            skipped += 1
            continue
        
        # 분석 텍스트 조합
        analysis_parts = []
        if entry.get('best_play'):
            analysis_parts.append("【베스트 플레이】\n" + "\n".join(f"• {p}" for p in entry['best_play']))
        if entry.get('actual_play'):
            analysis_parts.append("【실제 플레이】\n" + "\n".join(f"• {p}" for p in entry['actual_play']))
        
        analysis_text = "\n\n".join(analysis_parts) if analysis_parts else None
        
        # key_factors 조합 (잘한 점)
        key_factors = entry.get('good_points', [])
        
        # lessons_learned 조합
        lessons_parts = []
        if entry.get('bad_points'):
            lessons_parts.extend(f"[BAD] {p}" for p in entry['bad_points'])
        if entry.get('lessons'):
            lessons_parts.extend(entry['lessons'])
        lessons_learned = "\n".join(lessons_parts) if lessons_parts else None
        
        # 수익률로 라벨 분류
        profit_pct = entry['profit_pct']
        result_label = classify_result(profit_pct)
        
        # 거래소 매핑
        exchange_map = {
            '업비트': 'upbit',
            '빗썸': 'bithumb', 
            '코인원': 'coinone',
            '업빗썸': 'upbit+bithumb',
            '미상': 'unknown',
        }
        exchange = exchange_map.get(entry['exchange'], entry['exchange'])
        
        # INSERT
        sql = """
        INSERT INTO learning_cases (
            symbol, exchange, listing_date,
            result_label, actual_profit_pct,
            source, analysis_text, key_factors, lessons_learned,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        params = (
            symbol,
            exchange,
            listing_date,
            result_label,
            profit_pct,
            'telegram:김피카썬더볼트',
            analysis_text,
            json.dumps(key_factors, ensure_ascii=False) if key_factors else None,
            lessons_learned,
            time.time(),
        )
        
        try:
            conn.execute(sql, params)
            print(f"[OK] {symbol} ({listing_date}): {profit_pct:+.2f}% -> {result_label}")
            inserted += 1
        except Exception as e:
            print(f"[FAIL] {symbol}: {e}")
    
    conn.commit()
    conn.close()
    
    print(f"\n[DONE] {inserted} inserted, {skipped} skipped")
    
    # 통계 출력
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    print("\n=== learning_cases 통계 ===")
    for row in conn.execute("""
        SELECT result_label, COUNT(*) as cnt, ROUND(AVG(actual_profit_pct), 2) as avg_pct
        FROM learning_cases
        GROUP BY result_label
    """):
        label = row['result_label'] or 'null'
        emoji = {'heung_big': '**', 'heung': '*', 'neutral': '-', 'mang': 'X'}.get(label, '?')
        print(f"  {emoji} {label}: {row['cnt']}건, 평균 {row['avg_pct']}%")
    
    conn.close()


if __name__ == "__main__":
    import_bokgi_data()
