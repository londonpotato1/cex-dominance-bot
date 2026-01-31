import sqlite3
import time
import random
from pathlib import Path

db_path = Path('data/ddari.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# gate_analysis_log 테이블 생성 (없으면)
cursor.execute('''
CREATE TABLE IF NOT EXISTS gate_analysis_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT,
    premium_pct REAL,
    can_proceed INTEGER DEFAULT 0,
    alert_level TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')
conn.commit()
print('gate_analysis_log 테이블 준비 완료')

# 샘플 데이터 삽입
now = int(time.time())
symbols = [('TESTCOIN', 'upbit'), ('SAMPLE', 'bithumb')]

for symbol, exchange in symbols:
    base_premium = random.uniform(5, 15)
    
    for i in range(96):  # 24시간, 15분 간격
        ts = now - (96 - i) * 900
        
        # 피뢰침 패턴
        if i < 10:
            premium = base_premium + random.uniform(20, 50)
        elif i < 30:
            premium = base_premium + random.uniform(5, 20)
        else:
            premium = base_premium + random.uniform(-2, 5)
        
        can_proceed = 1 if premium > 10 else 0
        alert_level = 'high' if premium > 30 else 'medium' if premium > 15 else 'low'
        
        cursor.execute('''
            INSERT INTO gate_analysis_log (timestamp, symbol, exchange, premium_pct, can_proceed, alert_level)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (ts, symbol, exchange, premium, can_proceed, alert_level))

conn.commit()
print(f'샘플 데이터 삽입 완료: {[s[0] for s in symbols]}')

# 확인
cursor.execute('SELECT symbol, COUNT(*), MIN(premium_pct), MAX(premium_pct) FROM gate_analysis_log GROUP BY symbol')
for row in cursor.fetchall():
    print(f'{row[0]}: {row[1]}건, {row[2]:.1f}% ~ {row[3]:.1f}%')

conn.close()
