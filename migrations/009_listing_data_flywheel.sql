-- 009: 데이터 플라이휠 확장 (Phase 4.1+)
-- 토크노믹스, VC/MM, 학습 데이터 강화

-- listing_history 테이블 확장
ALTER TABLE listing_history ADD COLUMN total_supply REAL;           -- 총 발행량
ALTER TABLE listing_history ADD COLUMN circulating_supply REAL;     -- 유통량
ALTER TABLE listing_history ADD COLUMN circulating_ratio REAL;      -- 유통비율 (%)

ALTER TABLE listing_history ADD COLUMN vc_tier TEXT;                -- VC 티어 (T1/T2/T3)
ALTER TABLE listing_history ADD COLUMN vc_names TEXT;               -- 주요 VC 이름 (JSON array)
ALTER TABLE listing_history ADD COLUMN total_funding_usd REAL;      -- 총 펀딩 금액

ALTER TABLE listing_history ADD COLUMN mm_name TEXT;                -- 마켓메이커 이름
ALTER TABLE listing_history ADD COLUMN mm_tier TEXT;                -- MM 티어 (T1/T2/T3)

ALTER TABLE listing_history ADD COLUMN supply_classification TEXT;  -- smooth/moderate/tight
ALTER TABLE listing_history ADD COLUMN turnover_ratio REAL;         -- 거래량/입금액

ALTER TABLE listing_history ADD COLUMN ai_risk_level TEXT;          -- AI 분석 리스크
ALTER TABLE listing_history ADD COLUMN ai_summary TEXT;             -- AI 요약

-- 학습 데이터 테이블 (고수 복기 글, 외부 케이스)
CREATE TABLE IF NOT EXISTS learning_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 기본 정보
    symbol TEXT NOT NULL,
    exchange TEXT,
    listing_date TEXT,                      -- YYYY-MM-DD
    
    -- 시장 데이터
    market_cap_usd REAL,
    fdv_usd REAL,
    circulating_ratio REAL,
    
    -- 토크노믹스
    total_supply REAL,
    circulating_supply REAL,
    unlock_schedule TEXT,                   -- 간단한 설명
    
    -- VC/MM
    vc_tier TEXT,
    vc_names TEXT,
    mm_name TEXT,
    
    -- 상장 유형
    listing_type TEXT,                      -- TGE/DIRECT/SIDE
    
    -- 결과
    result_label TEXT NOT NULL,             -- heung_big/heung/neutral/mang
    max_profit_pct REAL,                    -- 최대 수익률
    actual_profit_pct REAL,                 -- 실제 달성 수익률
    
    -- 복기 내용
    source TEXT,                            -- 출처 (telegram/twitter/manual)
    source_url TEXT,                        -- 원본 URL
    analysis_text TEXT,                     -- 복기 분석 내용
    key_factors TEXT,                       -- 핵심 요인 (JSON array)
    lessons_learned TEXT,                   -- 교훈
    
    -- 메타
    added_by TEXT DEFAULT 'manual',
    created_at REAL DEFAULT (strftime('%s', 'now'))
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_learning_cases_symbol ON learning_cases(symbol);
CREATE INDEX IF NOT EXISTS idx_learning_cases_label ON learning_cases(result_label);
CREATE INDEX IF NOT EXISTS idx_learning_cases_date ON learning_cases(listing_date);

-- 결과 라벨 통계 뷰
CREATE VIEW IF NOT EXISTS label_statistics AS
SELECT 
    result_label,
    COUNT(*) as count,
    AVG(market_cap_usd) as avg_mc,
    AVG(fdv_usd) as avg_fdv,
    AVG(circulating_ratio) as avg_circ_ratio,
    AVG(max_profit_pct) as avg_max_profit,
    AVG(actual_profit_pct) as avg_actual_profit
FROM (
    SELECT result_label, market_cap_usd, fdv_usd, 
           circulating_ratio, max_premium_pct as max_profit_pct, 
           net_profit_pct as actual_profit_pct
    FROM listing_history
    WHERE result_label IS NOT NULL
    UNION ALL
    SELECT result_label, market_cap_usd, fdv_usd,
           circulating_ratio, max_profit_pct, actual_profit_pct
    FROM learning_cases
    WHERE result_label IS NOT NULL
)
GROUP BY result_label;
