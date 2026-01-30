-- 006_phase8_tables.sql
-- Phase 8: 후따리 전략 (2차 펌핑 분석, 현선갭, 매도 타이밍)

-- post_listing_analysis: 후따리 분석 결과
CREATE TABLE IF NOT EXISTS post_listing_analysis (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    exchange            TEXT NOT NULL,
    listing_time        TEXT,               -- ISO8601 (상장 시각)

    -- 분석 결과
    phase               TEXT,               -- 'initial_pump' | 'first_dump' | 'consolidation' | 'second_pump' | 'fade_out'
    signal              TEXT,               -- 'strong_buy' | 'buy' | 'hold' | 'avoid'

    -- 개별 점수 (0-10)
    time_score          REAL,               -- 시간 점수
    price_score         REAL,               -- 가격 점수
    volume_score        REAL,               -- 거래량 점수
    premium_score       REAL,               -- 프리미엄 점수
    total_score         REAL,               -- 종합 점수

    -- 메타
    confidence          REAL,               -- 신뢰도 (0-1)
    reason              TEXT,               -- 설명
    analyzed_at         TEXT DEFAULT (datetime('now')),

    UNIQUE(symbol, exchange, analyzed_at)
);

-- spot_futures_gap: 현선갭 모니터링
CREATE TABLE IF NOT EXISTS spot_futures_gap (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,

    -- 거래소 정보
    domestic_exchange   TEXT,               -- 'upbit' | 'bithumb'
    global_exchange     TEXT,               -- 'binance' | 'bybit'

    -- 가격
    domestic_price_krw  REAL,               -- 국내 현물가 (KRW)
    global_price_usd    REAL,               -- 해외 가격 (USD)
    fx_rate             REAL,               -- 환율 (KRW/USD)

    -- 갭 정보
    gap_pct             REAL,               -- 갭 (%)
    hedge_strategy      TEXT,               -- 'long_global_short_domestic' | 'short_global_long_domestic' | 'no_hedge'
    is_profitable       INTEGER,            -- 0 | 1
    estimated_profit_pct REAL,              -- 예상 수익 (%)

    -- 메타
    created_at          TEXT DEFAULT (datetime('now')),  -- ISO8601 (일관성)

    UNIQUE(symbol, domestic_exchange, global_exchange, created_at)
);

-- exit_timing: 매도 타이밍 분석
CREATE TABLE IF NOT EXISTS exit_timing (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    exchange            TEXT NOT NULL,

    -- Exit 판단
    should_exit         INTEGER,            -- 0 | 1
    trigger_type        TEXT,               -- 'premium_target' | 'premium_floor' | 'time_limit' | 'volume_spike' | 'premium_reversal' | 'trailing_stop' | 'manual' | 'none'
    urgency             TEXT,               -- 'critical' | 'high' | 'medium' | 'low'
    reason              TEXT,               -- 설명

    -- 프리미엄 추적
    current_premium_pct REAL,               -- 현재 프리미엄
    entry_premium_pct   REAL,               -- 진입 시 프리미엄
    peak_premium_pct    REAL,               -- 최고 프리미엄

    -- 시간 추적
    position_duration_min INTEGER,          -- 포지션 유지 시간 (분)

    -- 메타
    created_at          TEXT DEFAULT (datetime('now')),  -- ISO8601 (일관성)

    UNIQUE(symbol, exchange, created_at)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_post_listing_analyzed_at ON post_listing_analysis(analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_post_listing_symbol ON post_listing_analysis(symbol, exchange);
CREATE INDEX IF NOT EXISTS idx_post_listing_signal ON post_listing_analysis(signal);

CREATE INDEX IF NOT EXISTS idx_spot_futures_gap_time ON spot_futures_gap(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_spot_futures_gap_symbol ON spot_futures_gap(symbol);

CREATE INDEX IF NOT EXISTS idx_exit_timing_time ON exit_timing(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exit_timing_symbol ON exit_timing(symbol, exchange);
CREATE INDEX IF NOT EXISTS idx_exit_timing_should_exit ON exit_timing(should_exit, urgency);
