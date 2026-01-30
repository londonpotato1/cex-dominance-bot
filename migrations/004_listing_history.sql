-- 004_listing_history.sql
-- Phase 5a: 상장 히스토리 + 결과 라벨링

-- listing_history: 과거 상장 기록 + 결과 라벨
CREATE TABLE IF NOT EXISTS listing_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    exchange            TEXT NOT NULL,
    listing_time        TEXT,               -- ISO8601 (상장 시각)
    listing_type        TEXT,               -- 'TGE' | 'DIRECT' | 'SIDE' | 'UNKNOWN'

    -- 시장 데이터 (상장 시점)
    market_cap_usd      REAL,
    fdv_usd             REAL,
    top_exchange        TEXT,               -- 글로벌 주요 거래소
    top_exchange_tier   INTEGER,            -- 1=대형, 2=중형, 3=소형
    global_volume_usd   REAL,               -- 글로벌 24h 거래량

    -- Gate 분석 결과
    gate_can_proceed    INTEGER,            -- 0=NO-GO, 1=GO
    premium_pct         REAL,               -- 분석 시점 프리미엄 (%)
    net_profit_pct      REAL,               -- 순이익 (%)
    hedge_type          TEXT,               -- 'cex' | 'dex_only' | 'none'
    network             TEXT,               -- 전송 네트워크

    -- 결과 데이터 (상장 후 수집)
    max_premium_pct     REAL,               -- 최대 프리미엄 (%)
    premium_at_5m_pct   REAL,               -- 5분 후 프리미엄 (%)
    premium_at_30m_pct  REAL,               -- 30분 후 프리미엄 (%)
    duration_above_8pct_sec INTEGER,        -- 8% 이상 유지 시간 (초)

    -- 라벨 (수동/자동)
    result_label        TEXT,               -- 'heung_big' | 'heung' | 'neutral' | 'mang'
    result_notes        TEXT,               -- 비고
    labeled_by          TEXT,               -- 'auto' | 'manual'
    labeled_at          TEXT,               -- 라벨링 시각

    -- 메타
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),

    UNIQUE(symbol, exchange, listing_time)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_listing_history_time ON listing_history(listing_time DESC);
CREATE INDEX IF NOT EXISTS idx_listing_history_symbol ON listing_history(symbol, exchange);
CREATE INDEX IF NOT EXISTS idx_listing_history_label ON listing_history(result_label);
