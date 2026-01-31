-- 010_alert_latency.sql
-- Phase 4.2: 알림 속도 측정 테이블
-- 상장 감지 → 분석 → 알림 전송까지의 지연 시간 기록

CREATE TABLE IF NOT EXISTS alert_latency_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,              -- Unix timestamp (기록 시점)
    symbol TEXT NOT NULL,                 -- 토큰 심볼
    exchange TEXT NOT NULL,               -- 거래소 (upbit/bithumb)
    event_type TEXT DEFAULT 'listing',    -- 이벤트 유형 (listing/event/notice)
    
    -- 타임스탬프 (monotonic, 초 단위) - 상대 시간
    detect_ts REAL,                       -- 감지 시점
    analyze_start_ts REAL,                -- 분석 시작 시점
    analyze_end_ts REAL,                  -- 분석 완료 시점
    alert_sent_ts REAL,                   -- 알림 전송 완료 시점
    
    -- 계산된 지연 시간 (밀리초)
    detect_to_alert_ms REAL,              -- 감지 → 알림 (E2E)
    analyze_duration_ms REAL,             -- 분석 소요 시간
    total_duration_ms REAL,               -- 총 소요 시간
    
    -- 메타데이터
    alert_level TEXT,                     -- 알림 레벨 (CRITICAL/HIGH/...)
    can_proceed INTEGER                   -- GO/NO-GO (1/0)
);

-- 인덱스: 시간 범위 조회용
CREATE INDEX IF NOT EXISTS idx_alert_latency_timestamp 
    ON alert_latency_log(timestamp);

-- 인덱스: 심볼+거래소 조회용
CREATE INDEX IF NOT EXISTS idx_alert_latency_symbol_exchange 
    ON alert_latency_log(symbol, exchange);
