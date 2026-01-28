-- 002_add_fx_snapshots.sql
-- Phase 3: FX 환율 스냅샷 + 알림 중복 방지 테이블

-- FX 환율 스냅샷 (7일 보존, 주기적 purge)
CREATE TABLE IF NOT EXISTS fx_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  REAL NOT NULL,
    fx_rate    REAL NOT NULL,
    source     TEXT NOT NULL,      -- 'btc_implied', 'eth_implied', 'usdt_krw_direct', 'cached', 'hardcoded_fallback'
    btc_krw    REAL,
    btc_usd    REAL
);
CREATE INDEX IF NOT EXISTS idx_fx_snapshots_ts ON fx_snapshots(timestamp);

-- 알림 중복 방지 (debounce)
CREATE TABLE IF NOT EXISTS alert_debounce (
    key          TEXT PRIMARY KEY,
    last_sent_at REAL NOT NULL,
    expires_at   REAL NOT NULL
);
