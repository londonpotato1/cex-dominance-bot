import sqlite3
conn = sqlite3.connect('ddari.db')
conn.row_factory = sqlite3.Row

# 테이블 목록
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('Tables:', [t['name'] for t in tables])

# listing 관련 테이블 확인
for t in tables:
    name = t['name']
    if 'list' in name.lower() or 'history' in name.lower() or 'gate' in name.lower():
        count = conn.execute(f'SELECT COUNT(*) as cnt FROM {name}').fetchone()['cnt']
        print(f'{name}: {count} rows')
        
        # 샘플 데이터
        if count > 0:
            sample = conn.execute(f'SELECT * FROM {name} LIMIT 1').fetchone()
            print(f'  Columns: {list(sample.keys())}')
