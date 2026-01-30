-- 005_add_vcmm_columns.sql
-- Phase 7: VC/MM 정보 컬럼 추가 (Week 4 Day 25-28)

-- gate_analysis_log에 VC/MM 컬럼 추가
ALTER TABLE gate_analysis_log ADD COLUMN vc_tier1_investors TEXT;    -- JSON array of tier1 VC names
ALTER TABLE gate_analysis_log ADD COLUMN vc_tier2_investors TEXT;    -- JSON array of tier2 VC names
ALTER TABLE gate_analysis_log ADD COLUMN vc_total_funding_usd REAL;  -- 총 펀딩 금액
ALTER TABLE gate_analysis_log ADD COLUMN vc_risk_level TEXT;         -- "low", "medium", "high"
ALTER TABLE gate_analysis_log ADD COLUMN mm_name TEXT;               -- MM 이름
ALTER TABLE gate_analysis_log ADD COLUMN mm_risk_score REAL;         -- MM 리스크 점수 (0-10)
ALTER TABLE gate_analysis_log ADD COLUMN vcmm_data_source TEXT;      -- "coingecko", "yaml", "unknown"
