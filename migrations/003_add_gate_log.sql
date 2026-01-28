-- 003_add_gate_log.sql
-- Phase 4: Gate 분석 결과 로그 (관측성 + UI 조회)

-- gate_analysis_log: 모든 Gate 판정 결과 기록
CREATE TABLE IF NOT EXISTS gate_analysis_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL NOT NULL,
    symbol          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    can_proceed     INTEGER NOT NULL,       -- 0=NO-GO, 1=GO
    alert_level     TEXT NOT NULL,           -- CRITICAL/HIGH/MEDIUM/LOW/INFO
    premium_pct     REAL,
    net_profit_pct  REAL,
    total_cost_pct  REAL,
    fx_rate         REAL,
    fx_source       TEXT,
    blockers_json   TEXT,                   -- JSON array
    warnings_json   TEXT,                   -- JSON array
    hedge_type      TEXT,
    network         TEXT,
    global_volume_usd REAL,
    gate_duration_ms REAL                   -- analyze_listing 소요 시간
);
CREATE INDEX IF NOT EXISTS idx_gate_log_ts ON gate_analysis_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_gate_log_symbol ON gate_analysis_log(symbol, exchange);
