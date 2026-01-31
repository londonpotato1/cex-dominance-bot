-- 008: 실전 수익 기록 테이블 (Phase 4.1)
-- GO 신호 → 실제 수익 추적

CREATE TABLE IF NOT EXISTS trade_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 신호 정보
    signal_id TEXT,                    -- gate_analysis_log.id 참조
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    signal_timestamp REAL NOT NULL,    -- 신호 발생 시간
    
    -- 예측 정보 (신호 시점)
    predicted_profit_pct REAL,         -- 예측 순수익
    predicted_premium_pct REAL,        -- 예측 김프
    
    -- 실제 결과
    actual_profit_pct REAL,            -- 실제 수익률
    entry_price_krw REAL,              -- 진입가 (국내)
    exit_price_krw REAL,               -- 청산가 (국내)
    entry_price_usd REAL,              -- 진입가 (해외)
    exit_price_usd REAL,               -- 청산가 (해외)
    
    -- 거래 정보
    trade_amount_krw REAL,             -- 거래 금액 (KRW)
    actual_cost_pct REAL,              -- 실제 비용
    holding_minutes INTEGER,           -- 보유 시간 (분)
    
    -- 메타
    result_label TEXT,                 -- "WIN", "LOSS", "BREAKEVEN", "SKIP"
    user_note TEXT,                    -- 사용자 메모
    recorded_at REAL NOT NULL,         -- 기록 시간
    
    -- 인덱스용
    created_at REAL DEFAULT (strftime('%s', 'now'))
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_trade_results_symbol ON trade_results(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_results_timestamp ON trade_results(signal_timestamp);
CREATE INDEX IF NOT EXISTS idx_trade_results_label ON trade_results(result_label);

-- 일별 성과 요약 뷰
CREATE VIEW IF NOT EXISTS daily_performance AS
SELECT 
    date(signal_timestamp, 'unixepoch', 'localtime') as trade_date,
    COUNT(*) as total_trades,
    SUM(CASE WHEN result_label = 'WIN' THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN result_label = 'LOSS' THEN 1 ELSE 0 END) as losses,
    SUM(CASE WHEN result_label = 'SKIP' THEN 1 ELSE 0 END) as skips,
    AVG(actual_profit_pct) as avg_profit_pct,
    SUM(actual_profit_pct) as total_profit_pct,
    AVG(predicted_profit_pct) as avg_predicted_pct,
    AVG(ABS(actual_profit_pct - predicted_profit_pct)) as avg_prediction_error
FROM trade_results
WHERE result_label IS NOT NULL
GROUP BY trade_date
ORDER BY trade_date DESC;
