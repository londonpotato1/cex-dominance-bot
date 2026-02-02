-- 011: fx_snapshots 테이블에 테더 가격 및 실제 환율 컬럼 추가
-- 김프 계산 개선: 실제 환율 + 테더 가격 분리 저장

-- 업비트 USDT 가격 (테더 프리미엄 계산용)
ALTER TABLE fx_snapshots ADD COLUMN upbit_usdt_krw REAL;

-- 빗썸 USDT 가격 (테더 프리미엄 계산용)
ALTER TABLE fx_snapshots ADD COLUMN bithumb_usdt_krw REAL;

-- 실제 환율 (네이버/API 기준, implied와 구분)
ALTER TABLE fx_snapshots ADD COLUMN real_fx_rate REAL;
