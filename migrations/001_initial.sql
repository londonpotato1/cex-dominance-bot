-- 001_initial.sql
-- Phase 1: trade snapshot + token registry 기본 테이블

-- 1초 집계 스냅샷 (10분 보관, 주기적 purge)
CREATE TABLE IF NOT EXISTS trade_snapshot_1s (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    market     TEXT NOT NULL,        -- 'UPBIT:BTC-KRW'
    ts         DATETIME NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    volume     REAL,
    volume_krw REAL,
    UNIQUE(market, ts)
);

-- 1분 집계 스냅샷 (영구 보관)
CREATE TABLE IF NOT EXISTS trade_snapshot_1m (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    market     TEXT NOT NULL,
    ts         DATETIME NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    volume     REAL,
    volume_krw REAL,
    UNIQUE(market, ts)
);

-- 토큰 식별 기반 (Phase 1: 수동 INSERT만)
CREATE TABLE IF NOT EXISTS token_registry (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT NOT NULL,
    coingecko_id     TEXT,
    name             TEXT,
    chain            TEXT,              -- 'ethereum', 'solana', 'bsc'
    contract_address TEXT,
    decimals         INTEGER DEFAULT 18,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, chain)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_trade_1s_market_ts ON trade_snapshot_1s(market, ts);
CREATE INDEX IF NOT EXISTS idx_trade_1m_market_ts ON trade_snapshot_1m(market, ts);
CREATE INDEX IF NOT EXISTS idx_token_registry_symbol ON token_registry(symbol);
