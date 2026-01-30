-- Migration 007: gate_analysis_log에 가격 컬럼 추가
-- 국내/글로벌 실제 가격을 저장하여 직관적인 가격 비교 제공

ALTER TABLE gate_analysis_log ADD COLUMN domestic_price_krw REAL;
ALTER TABLE gate_analysis_log ADD COLUMN global_price_usd REAL;
