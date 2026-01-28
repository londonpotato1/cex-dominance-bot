# CEX Dominance Bot - 진행 상황 기록

**마지막 업데이트**: 2026-01-28 (Day 3)
**현재 단계**: Phase 3 구현 + 코드 리뷰 수정 + 통합 테스트 완료

---

## 1. 완료된 작업

### Phase 1: 기초 인프라 (완료)

| 파일 | 역할 |
|------|------|
| `store/database.py` | SQLite WAL 커넥션 + 마이그레이션 |
| `store/writer.py` | Single Writer Queue (thread-safe) |
| `store/token_registry.py` | 토큰 식별 기반 |
| `collectors/robust_ws.py` | WS 베이스 (재연결/핑/Gap Recovery) |
| `collectors/second_bucket.py` | 1초 OHLCV 인메모리 집계 |
| `collectors/upbit_ws.py` | 업비트 WS 수집기 |
| `collectors/bithumb_ws.py` | 빗썸 WS 수집기 |
| `migrations/001_initial.sql` | 초기 스키마 |
| `scripts/test_pipeline.py` | Phase 1 검증 스크립트 |

### Phase 2: 데이터 파이프라인 (완료)

| 파일 | 타입 | 역할 |
|------|------|------|
| `collectors/aggregator.py` | 신규 | 1s→1m 롤업 + self-healing + purge |
| `collectors/notice_parser.py` | 신규 | 빗썸 공지 파싱 (정규식) |
| `collectors/market_monitor.py` | 신규 | 상장 감지 (업비트 API Diff + 빗썸 공지 폴링) |
| `collector_daemon.py` | 신규 | 메인 데몬 프로세스 |
| `store/token_registry.py` | 수정 | Writer Queue 경유 + CoinGecko 부트스트랩 |
| `collectors/upbit_ws.py` | 수정 | flush_pending() + add_market() |
| `collectors/bithumb_ws.py` | 수정 | flush_pending() + add_market() |

### 코드 리뷰: CRITICAL 4건 (Day 1 수정 완료)

| # | 파일 | 수정 내용 |
|---|------|----------|
| C1 | `bithumb_ws.py` | KST tzinfo 명시 부여 (`dt_naive.replace(tzinfo=KST)`) |
| C2 | `aggregator.py` | FALSE POSITIVE — `datetime('now')`는 이미 UTC. 수정 불필요 |
| C3 | `collector_daemon.py` | `loop.call_soon_threadsafe(stop_event.set)` |
| C4 | `aggregator.py` | `INSERT OR REPLACE` + self_heal 항상 재롤업 |

### 코드 리뷰: IMPORTANT 7건 (Day 1 수정 완료)

| # | 파일 | 수정 내용 |
|---|------|----------|
| I1 | `robust_ws.py` | `asyncio.wait(FIRST_COMPLETED)` + pending 취소 |
| I2 | `writer.py` | 드롭 로깅 1, 10, 100, 1000, 매 1000건 |
| I3 | `token_registry.py` | Writer 필수 강제 + RuntimeError |
| I4 | `robust_ws.py` + `writer.py` + `collector_daemon.py` | public property 추가, private 접근 제거 |
| I5 | `writer.py` | 배치 롤백 → 건별 재시도 (`_commit_individually`) |
| I6 | `bithumb_ws.py` | 오더북 캐시 50레벨 제한 (`_MAX_OB_LEVELS`) |
| I7 | `token_registry.py` | CoinGecko sleep 1.0s → 2.0s |

### 코드 리뷰: MINOR 6건 (Day 2 수정 완료)

| # | 파일 | 결과 |
|---|------|------|
| M1 | `second_bucket.py` | 수정 불필요 — flush_all/flush_completed 리턴 이미 일관 |
| M2 | `notice_parser.py` | "추가" 단독 키워드 제거, "신규 상장" 추가 |
| M3 | `market_monitor.py` | `assert` → `RuntimeError` (프로덕션 안전) |
| M4 | `robust_ws.py` | 수정 불필요 — I1의 FIRST_COMPLETED로 이미 해결 |
| M5 | `collector_daemon.py` | 수정 불필요 — `writer.shutdown()`에서 conn.close() 호출 |
| M6 | `aggregator.py` | 수정 불필요 — open/close 서브쿼리 필수, 20마켓 수준 문제 없음 |

### 추가 버그 수정 (Day 2)

| 파일 | 내용 |
|------|------|
| `token_registry.py` | UNIQUE(symbol, chain) NULL 중복 허용 → chain='' 사용 |
| `test_pipeline.py` | `writer._queue.qsize()` → `writer.queue_size` (I4 반영) |

### Phase 2 통합 테스트 (Day 2)

| 항목 | 결과 |
|------|------|
| DB 초기화 + 마이그레이션 | PASS |
| Writer 배치 커밋 | PASS |
| Writer queue_size property | PASS |
| SecondBucket flush | PASS |
| SecondBucket OHLCV 정확성 | PASS |
| SecondBucket flush_all | PASS |
| Aggregator 1s 데이터 준비 | PASS |
| Aggregator rollup_minute | PASS |
| Aggregator 1m OHLCV (O/H/L/C) | PASS |
| INSERT OR REPLACE 덮어쓰기 | PASS |
| TokenRegistry insert_async + 조회 | PASS |
| TokenRegistry 중복 방지 | PASS |
| NoticeParser 상장 감지 | PASS |
| NoticeParser 심볼 추출 | PASS |
| NoticeParser 비상장 공지 | PASS |
| NoticeParser '추가' 오탐 방지 (M2) | PASS |
| NoticeParser 시간 추출 | PASS |
| 배치 롤백 + 건별 재시도 (I5) | PASS |
| **총 결과** | **20/20 PASS** |

### Phase 3: 분석 + Gate 파이프라인 (완료)

| 파일 | 타입 | 역할 |
|------|------|------|
| `migrations/002_add_fx_snapshots.sql` | 신규 | fx_snapshots + alert_debounce 테이블 (스키마 v2) |
| `config/features.yaml` | 신규 | Feature Flag (Phase 5+ 기능 OFF) |
| `config/networks.yaml` | 신규 | 네트워크 전송 시간/P90/가스비 임계값 |
| `config/exchanges.yaml` | 신규 | 거래소 API/수수료 설정 |
| `config/fees.yaml` | 신규 | 거래 수수료 + 가스비 기준 |
| `config/vasp_matrix.yaml` | 신규 | VASP 호환성 매트릭스 (Travel Rule) |
| `store/cache.py` | 신규 | CoinGecko TTL 캐시 (3단계: 24h/1h/1min) |
| `analysis/__init__.py` | 신규 | 패키지 초기화 |
| `analysis/tokenomics.py` | 신규 | MC/FDV/유통량 조회 (cache.py 경유) |
| `analysis/premium.py` | 신규 | 김치프리미엄 + FX 5단계 폴백 + 글로벌 VWAP |
| `analysis/cost_model.py` | 신규 | 슬리피지 + HedgeCost + 총비용 계산 |
| `analysis/gate.py` | 신규 | Hard Gate 4 Blockers + 3 Warnings + AlertLevel |
| `alerts/__init__.py` | 신규 | 패키지 초기화 |
| `alerts/telegram.py` | 신규 | AlertLevel 5단계 + Debouncing + Writer Queue |
| `collectors/market_monitor.py` | 수정 | `_on_new_listing()` → Gate + Alert 연결 |
| `collector_daemon.py` | 수정 | Phase 3 컴포넌트 생성 + 주입 + Shutdown 6단계 |

### Phase 3 코드 리뷰: CRITICAL 5건 (Day 3 수정 완료)

| # | 파일 | 수정 내용 |
|---|------|----------|
| C1 | `premium.py` | FX 캐시 소스 보존 (`"cached"` → 원본 소스 유지) |
| C2 | `premium.py` + `gate.py` | `calculate_premium()` fx_source 파라미터 추가, dataclass 뮤테이션 제거 |
| C3 | `gate.py` | 국내 가격 실패 blocker에 거래소명 포함 |
| C4 | `gate.py` | `_is_watch_only()` WATCH_ONLY blocker 실제 연결 (hardcoded FX → NO-GO) |
| C5 | `collector_daemon.py` | `alert.flush_batch()` shutdown 추가 (5→6단계) |

### Phase 3 코드 리뷰: IMPORTANT 7건 (Day 3 수정 완료)

| # | 파일 | 수정 내용 |
|---|------|----------|
| I1 | `premium.py` | `import asyncio` 모듈 레벨로 이동 |
| I2 | `telegram.py` | 디바운스 조회 실패 로그 debug → warning |
| I3 | `collector_daemon.py` | Phase 3 컴포넌트 초기화 try/except 추가 |
| I4 | `gate.py` | AlertLevel 판정 v10 정밀화 (trusted FX + actionable → CRITICAL) |
| I5 | `cost_model.py` | 가스비 1% 경고 플래그 gas_warn 추가 |
| I6 | `gate.py` | analyze_listing에서 FX 소스를 GateInput까지 전파 |
| I7 | `telegram.py` | batch flush 간격 1시간 조건 자동 체크 |

### Phase 3 통합 테스트 (Day 3)

| 항목 | 결과 |
|------|------|
| DB 마이그레이션 v2 | PASS |
| fx_snapshots 테이블 컬럼 확인 | PASS |
| alert_debounce 테이블 컬럼 확인 | PASS |
| features.yaml 로드 | PASS |
| networks.yaml 로드 | PASS |
| exchanges.yaml 로드 | PASS |
| fees.yaml 로드 | PASS |
| vasp_matrix.yaml 로드 | PASS |
| CoinGecko 캐시 set/get | PASS |
| 캐시 TTL 만료 | PASS |
| CostModel 인스턴스 생성 | PASS |
| 헤지 비용 계산 (CEX Perp) | PASS |
| 헤지 비용 계산 (DEX Perp) | PASS |
| 총비용 계산 (양수 프리미엄) | PASS |
| 총비용 계산 (음수 프리미엄) | PASS |
| 가스비 경고 플래그 | PASS |
| 슬리피지 추정 (빈 오더북) | PASS |
| PremiumResult 생성 | PASS |
| 프리미엄 계산 + fx_source 전달 | PASS |
| 프리미엄 0% (동일 가격) | PASS |
| VWAPResult 생성 | PASS |
| FX 스냅샷 DB 기록 | PASS |
| AlertLevel enum 순서 | PASS |
| GateInput 생성 | PASS |
| Gate: 모든 조건 충족 → GO | PASS |
| Gate: 입금 불가 → blocker | PASS |
| Gate: 출금 불가 → blocker | PASS |
| Gate: 수익성 부족 → blocker | PASS |
| Gate: 전송 시간 초과 → blocker | PASS |
| Gate: VASP 차단 → blocker | PASS |
| Gate: VASP 정상 → no blocker | PASS |
| Gate: 유동성 경고 (<$100K) | PASS |
| Gate: 가스비 경고 | PASS |
| Gate: WATCH_ONLY (hardcoded FX) | PASS |
| Gate: GO → CRITICAL (trusted FX) | PASS |
| Gate: GO → HIGH (untrusted FX) | PASS |
| Gate: NO-GO → MEDIUM | PASS |
| Gate: blocker 없음 + warning → LOW | PASS |
| TelegramAlert 생성 | PASS |
| is_configured = False (토큰 없음) | PASS |
| level prefix 매핑 | PASS |
| 디바운스: 초기 → 전송 허용 | PASS |
| 디바운스: 기록 후 → 전송 차단 | PASS |
| 디바운스: 만료 후 → 재전송 허용 | PASS |
| MarketMonitor gate_checker 파라미터 | PASS |
| collector_daemon import 검증 | PASS |
| Shutdown 함수 alert 파라미터 | PASS |
| 네트워크 가스비 조회 | PASS |
| 총비용에 가스비 반영 | PASS |
| CostResult net_profit_pct 정확성 | PASS |
| config 디렉토리 존재 확인 | PASS |
| analysis 패키지 import 확인 | PASS |
| alerts 패키지 import 확인 | PASS |
| Phase 2 회귀 검증 (20/20) | PASS |
| **총 결과** | **54/54 PASS** |

---

## 2. 다음 세션 작업

### 즉시 진행 가능
1. **라이브 WS 테스트** — `python scripts/test_pipeline.py --duration 30`으로 실제 업비트/빗썸 WS 연결 확인
2. **전체 데몬 테스트** — `python collector_daemon.py` 실행 (Phase 3 컴포넌트 포함)

### Phase 4 진행
- PLAN_v15.md 기준 다음 Phase 확인
- 현재 Phase 3까지 구현 + 리뷰 + 테스트 완료 상태

---

## 3. 현재 파일 구조

```
cex_dominance_bot/
├── collector_daemon.py          # 메인 데몬 (Phase 2+3)
├── PROGRESS.md                  # ← 이 파일
│
├── collectors/
│   ├── __init__.py
│   ├── robust_ws.py             # WS 베이스
│   ├── second_bucket.py         # 1s OHLCV 집계
│   ├── upbit_ws.py              # 업비트 수집기
│   ├── bithumb_ws.py            # 빗썸 수집기
│   ├── aggregator.py            # 1s→1m 롤업
│   ├── notice_parser.py         # 빗썸 공지 파싱
│   └── market_monitor.py        # 상장 감지 + Gate/Alert 연결
│
├── analysis/                    # Phase 3: 분석 파이프라인
│   ├── __init__.py
│   ├── premium.py               # 김치프리미엄 + FX 5단계 폴백 + VWAP
│   ├── cost_model.py            # 슬리피지 + 헤지비용 + 총비용
│   ├── gate.py                  # Hard Gate 4 Blockers + 3 Warnings
│   └── tokenomics.py            # MC/FDV/유통량 조회
│
├── alerts/                      # Phase 3: 알림 시스템
│   ├── __init__.py
│   └── telegram.py              # AlertLevel 5단계 + Debounce
│
├── store/
│   ├── __init__.py
│   ├── database.py              # SQLite WAL
│   ├── writer.py                # Single Writer Queue
│   ├── token_registry.py        # 토큰 레지스트리
│   └── cache.py                 # CoinGecko TTL 캐시
│
├── config/                      # Phase 3: 설정 파일
│   ├── features.yaml            # Feature Flags
│   ├── networks.yaml            # 블록체인 네트워크 설정
│   ├── exchanges.yaml           # 거래소 API 설정
│   ├── fees.yaml                # 수수료 설정
│   └── vasp_matrix.yaml         # VASP 호환성 매트릭스
│
├── migrations/
│   ├── 001_initial.sql          # 초기 스키마
│   └── 002_add_fx_snapshots.sql # FX 스냅샷 + 디바운스 (v2)
│
├── scripts/
│   ├── test_pipeline.py         # Phase 1 검증 (라이브 WS)
│   ├── test_phase2.py           # Phase 2 통합 테스트 (오프라인)
│   ├── test_phase3.py           # Phase 3 통합 테스트 (54건)
│   └── phase0_analysis.py       # Phase 0 분석
│
├── data/                        # SQLite DB 파일
├── requirements.txt             # 의존성 목록
├── main.py, dominance.py, app.py  # 기존 파일
└── PLAN_v15.md                  # 최신 계획서
```

---

## 4. 핵심 아키텍처 요약

```
[업비트 WS] ──┐
              ├──→ SecondBucket ──→ Writer Queue ──→ SQLite (1s)
[빗썸 WS] ───┘                                        │
                                                        ↓
                                          Aggregator (매분 롤업) → SQLite (1m)
                                                        │
                                          Purge (10분 초과 1s 삭제)

[MarketMonitor] ──→ 업비트 API Diff (30초) ──→ 신규 상장 감지
                ──→ 빗썸 공지 폴링 (60초)  ──→ → 토큰 자동 등록
                                                → WS 동적 구독 추가
                                                → Gate 파이프라인 (Phase 3)

[Gate 파이프라인] (Phase 3)
  MarketMonitor._on_new_listing(exchange, symbol)
    → GateChecker.analyze_listing(symbol, exchange)
      ├─ PremiumCalculator.get_implied_fx()     [REST: Upbit/Binance]
      │    └─ 5단계 폴백: BTC → ETH → USDT → 캐시 → 하드코딩
      ├─ PremiumCalculator.get_global_vwap()    [REST: Binance+OKX+Bybit]
      ├─ PremiumCalculator.calculate_premium()
      ├─ CostModel.calculate_total_cost()       [fees.yaml + networks.yaml]
      ├─ VASP 매트릭스 조회                      [vasp_matrix.yaml]
      └─ check_hard_blockers()                  → GateResult
    → TelegramAlert.send(level, message, key)
      ├─ CRITICAL/HIGH → 즉시 전송
      ├─ MEDIUM → 5분 debounce
      ├─ LOW → batch (1시간 flush)
      └─ INFO → 로그만

[Health Loop] ──→ health.json (30초마다 갱신)
```

**Single Writer 원칙**: 모든 DB 쓰기는 `DatabaseWriter` 큐 경유 (thread-safe).
**Graceful Shutdown**: stop_event → WS close → flush → force rollup → alert flush → task cancel → Writer shutdown (6단계).
