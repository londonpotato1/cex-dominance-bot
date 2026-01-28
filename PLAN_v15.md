# Ddari Info v15: 개발 보고서 + 구현 계획서 (통합본)

**프로젝트명**: Ddari Info v15
**목표**: 따리 정보 원스톱 + 공급 분류 기반 의사결정 프레임워크
**핵심 KPI**:
- **(갭 - 비용) = 순수익** (v5~)
- **Turnover Ratio = 거래량 / 입금액** = 손바뀜 횟수 (v6~)
**기준 코드베이스**: `cex_dominance_bot/` (기존 CEX Dominance Dashboard)
**기반 문서**: PLAN_v6.md (3,109줄) — 기술 상세/코드는 v6 참조
**스키마 정본**: v6 4.2절 CREATE TABLE. v10+ 추가 테이블: fx_snapshots, schema_version, alert_debounce. Retention 정책은 본 문서 A.3(6)절 우선.

> **v14 → v15 핵심 변경**: 이벤트 모니터 결합도 저감(EventSignal 중심 + event_history 별도 테이블 옵션), 헤징 계수 shrinkage 원칙 + hedge_venue/capacity 스키마 예약(Phase 5b~7), VASP 매트릭스 방향성 명시 + 대안경로 참고 note 추가

---

# Part A: v6 → v15 변경 사항 (피드백 반영)

## A.1 즉시 수정 4개

### (1) Turnover Ratio 정의 통일
- **문제**: v6 KPI 헤더 "입금액/거래량"와 본문 코드 "거래량/입금액"이 반대
- **수정**: **Turnover Ratio 하나로 통일** (v8 결정)
  - `turnover_ratio = volume / deposit` (손바뀜 횟수, 높을수록 흥따리)
  - ~~v7의 Deposit Pressure(역수) 제거~~ → Turnover Ratio가 낮으면 자동으로 입금 압력이 높다는 의미이므로 별도 지표 불필요
- **적용 위치**: `analysis/supply_classifier.py`, `analysis/gate.py`, `analysis/scenario.py`에서 `turnover_ratio` 단일 사용
- **임계값** (Phase 0에서 재보정):
  - `>= 10`: 극단적 흥따리 (거래량이 입금액의 10배+)
  - `>= 5`: 흥따리 유력
  - `>= 2`: 보통
  - `< 2`: 망따리 유력

- **None/저신뢰도 처리 규칙 (v9 추가)**:
  - `deposit_estimate_krw = None` → `turnover_ratio = None` → `supply_classification = "unknown"` → Gate는 경고만 (차단 안 함)
  - `deposit_estimate_krw < 1_000_000` (100만원 미만) → epsilon floor 적용: `turnover_ratio = volume / max(deposit, 1_000_000)` → 극단값 방지
  - **신뢰도 기반 가중치**:
    - 수동 입력: `confidence = 1.0` (사용자가 직접 확인)
    - 핫월렛 추정: `confidence = 0.5` (온체인 데이터 기반)
    - DEX outflow 추정: `confidence = 0.2` (가정이 약함)
  - SupplyClassifier에서 turnover_ratio 팩터 가중치에 confidence를 곱함:
    ```python
    # 예: turnover_score * confidence = 실제 반영 스코어
    turnover_weight = base_weight * data.turnover_confidence
    ```

### (2) DB 테이블 개수 정리
- **문제**: "6개 추가" vs 11개 나열
- **수정**: 실제 테이블 정리
  - Phase 5 CREATE TABLE: 7개 (listing_history, dex_liquidity, airdrop_claims, hot_wallet_balances, withdrawal_status, market_condition, listing_scenarios)
  - Phase 5 참조 테이블 (CREATE TABLE 미작성): 4개 (exchange_wallets, withdrawal_patterns, valuation_checklist, competitive_listings)
  - **총 11개 테이블**, Phase 5에서 7개 우선 생성, 나머지 4개는 Phase 6

### (3) Gate 실행 순서 명시
```
1단계: Hard Gate (v5) → 입출금/수익성/전송시간 Blocker 체크 → RED면 즉시 NO-GO
2단계: Supply Classification → 원활/미원활 판정
3단계: Listing Type → TGE/직상장/옆상장 분류
4단계: Strategy Determination → 공급+유형 조합별 전략 결정
5단계: Scenario Generation → 흥/망따리 카드 생성
```
- **적용 위치**: `analysis/gate.py` — GateChecker.full_check() 메서드로 구현

```python
# analysis/gate.py (v9 구조 — Graceful Degradation 포함)
class GateChecker:
    async def full_check(self, data: GateInput) -> GateResult:
        warnings = []

        # 1단계: Hard Blockers (v5) — 유일한 차단 권한
        hard = self._check_hard_blockers(data)
        if not hard.can_proceed:
            return hard  # 즉시 NO-GO
        warnings.extend(hard.warnings)

        # 2단계: Supply Classification (v6) — 실패 시 "unknown"
        try:
            supply = await self.supply_classifier.classify(data)
        except Exception as e:
            logger.warning(f"Supply 분류 실패, unknown 처리: {e}")
            supply = SupplyResult(classification="unknown", confidence=0.0)
            warnings.append("공급 분류 실패 — 수동 확인 필요")

        # 3단계: Listing Type (v6) — 실패 시 UNKNOWN (v12: DIRECT→UNKNOWN)
        try:
            listing_type = self.listing_classifier.classify(data)
        except Exception as e:
            logger.warning(f"상장유형 분류 실패, UNKNOWN 처리: {e}")
            listing_type = ListingType.UNKNOWN  # v12: DIRECT→UNKNOWN (WATCH_ONLY 강제)
            warnings.append("상장유형 분류 실패 — 유형 미확인, 관망 강제")

        # 4단계: Strategy (v6) — 실패 시 관망 전략
        try:
            # v12: UNKNOWN 유형이면 전략 결정 전에 관망 강제
            if listing_type == ListingType.UNKNOWN:
                strategy = StrategyCode.WATCH_ONLY
                warnings.append("상장유형 미확인 — 관망 강제 (v12)")
            else:
                strategy = self._determine_strategy(supply, listing_type, data)
        except Exception as e:
            logger.warning(f"전략 결정 실패, 관망 기본값: {e}")
            strategy = StrategyCode.WATCH_ONLY
            warnings.append("전략 결정 실패 — 관망 기본값")

        # 5단계: Scenario (v6) — 실패 시 최소 카드
        try:
            scenarios = self.scenario_planner.generate(data, supply, strategy)
        except Exception as e:
            logger.warning(f"시나리오 생성 실패: {e}")
            scenarios = [Scenario(label="정보 부족", description="시나리오 생성 불가", probability=None)]
            warnings.append("시나리오 생성 실패 — 정보 부족 카드")

        # v10: FX 소스가 hardcoded_fallback이면 WATCH_ONLY 강제
        fx_source = data.fx_source if hasattr(data, 'fx_source') else "unknown"
        if fx_source == "hardcoded_fallback":
            strategy = StrategyCode.WATCH_ONLY
            warnings.append("FX 기본값 사용 — 수익성 판단 불가, 관망 강제")

        result = GateResult(
            can_proceed=True, blockers=[], warnings=warnings,
            supply_classification=supply,
            listing_type=listing_type,
            recommended_strategy=strategy,
            scenarios=scenarios,
        )
        # v10: 알림 레벨 결정 (GateResult에 포함)
        result.alert_level = self._determine_alert_level(result, fx_source)
        return result

    # v10 신규: CRITICAL 알림 조건 정밀화
    def _determine_alert_level(self, result: GateResult, fx_source: str) -> AlertLevel:
        """GO + 행동가능 전략 + 신뢰 FX일 때만 CRITICAL"""
        if not result.can_proceed:
            return AlertLevel.HIGH  # NO-GO도 알려야 함
        if fx_source == "hardcoded_fallback":
            return AlertLevel.HIGH  # FX 신뢰 불가 → CRITICAL 불가
        if result.recommended_strategy == StrategyCode.WATCH_ONLY:
            return AlertLevel.HIGH  # GO지만 정보 부족 → CRITICAL 불가
        return AlertLevel.CRITICAL  # GO + 행동 가능 전략 + 신뢰 FX
```

**열화 규칙 요약 (v9 추가):**

| Stage | 실패 시 | 기본값 | 영향 |
|-------|--------|--------|------|
| 1 (Hard Gate) | 차단 | - | **유일한 NO-GO 권한** |
| 2 (Supply) | `unknown` (confidence=0.0) | 전략 축소, 시나리오 보수적 | 경고만 |
| 3 (ListingType) | `UNKNOWN` **(v12)** | `WATCH_ONLY` 강제 | 경고만 |
| 4 (Strategy) | `WATCH_ONLY` | 관망 (최소 위험) | 경고만 |
| 5 (Scenario) | "정보 부족" 카드 1장 | 사용자 수동 판단 | 경고만 |
| FX Source **(v10)** | `hardcoded_fallback` | `WATCH_ONLY` 강제 | **수익성 판단 불가, CRITICAL 알림 불가** |

**핵심 원칙**: Hard Gate(1단계)만 GO/NO-GO 의사결정 차단 권한 보유. 2~5단계는 정보 제공 목적이므로 실패해도 Gate 자체는 통과.
**알림 원칙 (v10)**: CRITICAL은 `GO + 행동가능 전략(!=WATCH_ONLY) + 신뢰 FX(!=hardcoded)` 조건을 모두 만족할 때만 발생. 그 외는 HIGH.

### (4) SupplyClassifier 이중 정의 통합
- **문제**: v6 5.2절(async, -1~+1 스코어)과 5.5절(동기, 0~1 스코어) 두 버전 존재
- **수정**: 5.2절 버전을 정본(canonical)으로 채택
  - async 메서드, SupplyFactor dataclass 사용
  - 스코어 범위: -1 (미원활) ~ 0 (중립) ~ +1 (원활)
  - 5.5절은 5.2절 참조로 변경 (코드 중복 삭제)

---

## A.2 Phase 0 추가: 라벨링 + 임계값 도출

**v6에서 누락된 핵심 단계**: 과거 데이터 분석 없이는 임계값/확률 조정값의 근거가 없음.

### Phase 0 작업 내용

#### 0-1. 데이터 수집 (최소 50건, 업비트 30건 + 빗썸 20건)

**데이터 소스:**
- 강의 자료 내 상장 사례 (Part 04/05 PDF) → 약 30건 추출 가능
- 카일 텔레그램 채널 (@info_Arbitrage) 상장 복기 데이터
- 업비트/빗썸 과거 공지사항 + 당시 차트 데이터
- 직접 참여한 상장 기록

**라벨링 스키마 (`data/labeling/listing_data.csv`):**
```csv
symbol,exchange,date,listing_type,market_cap_usd,top_exchange,top_exchange_tier,
deposit_krw,volume_5m_krw,volume_1m_krw,turnover_ratio,
max_premium_pct,premium_at_5m_pct,
supply_label,hedge_type,dex_liquidity_usd,hot_wallet_usd,
network_chain,network_speed_min,withdrawal_open,airdrop_claim_rate,
prev_listing_result,market_condition,
result_label,result_notes
```

#### 0-2. 흥/망따리 판정 기준 (v8 확정)

| 판정 | 기준 | 예시 |
|------|------|------|
| **대흥따리** | 최대 김프 ≥ 30% | CKB(300%), MINA(200%), MOCA빗썸(100%) |
| **흥따리** | 최대 김프 ≥ 8% AND 5분 이상 유지 | RED, API3, ERA |
| **보통** | 최대 김프 3~8% OR 피뢰침(순간 김프) | BONK(3%), WLFI(20%피뢰침) |
| **망따리** | 최대 김프 < 3% OR 역프 발생 | RAY, RVN, CYBER |

- **피뢰침 판정**: 김프가 1분 이내에 소멸 → result_label = "neutral" (흥도 망도 아님)
- **후펌핑 별도 기록**: 상장 직후 망따리여도 이후 드라이빙 발생 시 `result_notes`에 기록

#### 0-3. 임계값 도출 방법

1. Turnover Ratio 사분위수
   - 50건+ 데이터에서 P25/P50/P75/P90 계산
   - 흥따리 건만 추출하여 별도 분포 확인
2. 시나리오 확률 조건부 테이블
   - `P(흥따리 | supply=constrained)` = constrained 건 중 흥따리 비율
   - `P(흥따리 | prev_result=heung)` = 직전 흥따리 후 흥따리 비율
   - 교차 분석: `P(흥따리 | constrained AND prev_heung)` 등
3. SupplyClassifier 가중치 검증
   - 현재 하드코딩: hot_wallet(0.30), dex(0.25), withdrawal(0.20), airdrop(0.15), network(0.10)
   - Phase 0에서: 각 factor와 흥/망따리의 상관계수 계산 → 가중치 재조정

#### 0-4. 산출물
```yaml
# Phase 0 결과 → config/thresholds.yaml
turnover_ratio:
  extreme_high: 8.5   # 실제 데이터 P90
  high: 4.2            # P75
  normal: 2.1          # P50
  low: 1.0             # P25

supply_classifier_weights:  # Phase 0 검증 후 조정
  hot_wallet: 0.30
  dex_liquidity: 0.25
  withdrawal: 0.20
  airdrop: 0.15         # 데이터 없으면 가중치 재분배 (아래 fallback 참조)
  network: 0.10

  # airdrop 데이터 없을 때 fallback 가중치
  fallback_no_airdrop:
    hot_wallet: 0.35
    dex_liquidity: 0.30
    withdrawal: 0.23
    network: 0.12

scenario_coefficients:
  supply_constrained: 0.23   # 실제: constrained 건 중 흥따리 비율
  supply_smooth: -0.15
  market_bull: 0.12
  prev_heung: 0.08
  base_probability: 0.48
  # v14: 헤징 유형 3단계 계수 (hedging_possible bool → hedge_type enum)
  hedge_cex: 0.0             # CEX 선물 헤징 가능 → 기저(baseline)
  hedge_dex_only: 0.15       # DEX 선물만 가능 → 중간 시그널 (추정치, Phase 0 재검증)
  hedge_none: 0.37           # 헤징 불가 → 최강 시그널

# v15: 계수 신뢰성 관리 원칙
# 적용 범위: scenario_coefficients 내 **모든 계수**에 동일 적용
# (hedge_dex_only뿐 아니라 supply_constrained, market_bull, prev_heung 등 전체)
coefficient_governance:
  scope: "all_scenario_coefficients"  # 전체 시나리오 계수 대상
  min_sample_size: 10          # 이 미만이면 해당 계수를 baseline(0.0)으로 shrink
  shrinkage_formula: "coeff * min(1.0, sample_count / min_sample_size)"
  # 예: hedge_dex_only 사례가 4건이면 → 0.15 * (4/10) = 0.06으로 축소
  # 예: supply_constrained 사례가 7건이면 → 0.23 * (7/10) = 0.161로 축소
  # 예: market_bull 사례가 25건이면 → 0.12 * 1.0 = 0.12 (충분, 원본 유지)
  # 충분한 표본(10건+) 확보 후 계수 재산출
  review_cycle: "Phase 0 완료 후 분기 1회 재검증"

heung_definition:
  min_premium_pct: 8
  min_duration_sec: 300       # 5분 이상 유지
  lightning_rod_window_sec: 60  # 이 안에 소멸하면 피뢰침

# v9: Turnover Ratio None/저신뢰도 처리
turnover_none_handling:
  epsilon_floor_krw: 1_000_000   # deposit < 이 값이면 floor 적용
  confidence_levels:
    manual_input: 1.0            # 사용자 직접 입력
    hot_wallet_estimate: 0.5     # 온체인 핫월렛 추정
    dex_outflow_estimate: 0.2    # DEX 유출 기반 추정
  unknown_supply_action: "warn"  # warn (경고만) | block (차단)
```

---

## A.3 보완사항 5개

### (1) Token Identity 기준 — `store/token_registry.py` 신규
```python
@dataclass
class TokenIdentity:
    coingecko_id: str          # 유일 식별자
    symbol: str                # 표시용
    chains: list[ChainInfo]    # 멀티체인 지원

@dataclass
class ChainInfo:
    chain: str                 # ethereum/solana/bsc
    contract_address: str
    decimals: int
    hot_wallets: dict          # {exchange: [addresses]}
```
- **Phase 1**: TokenIdentity dataclass + 수동 INSERT 인터페이스만 구현 **(v10 변경)**
- RPC 엔드포인트, 탐색기 URL도 여기에 매핑

**부트스트랩 전략 (v8 추가, v10 Phase 2~3으로 이동):**

> **v10 변경**: 부트스트랩(대량 외부 API 호출)은 Phase 1 스코프 초과. Phase 1은 WS→DB 파이프 완성이 목표이므로, 외부 시딩은 Phase 2~3에서 market_monitor와 함께 구현.

1. **초기 시딩 → Phase 2~3**: CoinGecko API `/coins/list?include_platform=true`에서 상위 500개 토큰 자동 fetch → chain+contract 매핑
2. **핫월렛 주소 시딩 → Phase 3**: Etherscan Labels API + Arkham 퍼블릭 라벨에서 주요 거래소(Upbit, Bithumb, Binance, Bybit, OKX, Bitget, Gate) 핫월렛 수집
3. **상장 감지 시 자동 등록 → Phase 2**: market_monitor가 신규 상장 감지 → CoinGecko에서 토큰 정보 fetch → token_registry에 자동 INSERT
4. **수동 보완 UI**: Streamlit에서 거래소+체인+주소 수동 입력 (Phase 1부터 가능)

### (2) DATABASE_URL 분기 (Postgres 전환 경로)
```python
# store/database.py (v9)
def get_connection():
    db_url = os.getenv("DATABASE_URL")
    if db_url and db_url.startswith("postgres"):
        raise NotImplementedError("Postgres support planned for Phase 5+")
    # SQLite 기본 (기존 WAL 설정)
    conn = sqlite3.connect("ddari.db", ...)
    ...
```
- MVP에서는 SQLite만 사용, 분리 배포 필요 시 Postgres 전환

### (3) DEX 유동성 신뢰도 레벨
- `_estimate_from_dex_outflow()`: DEX 유동성 감소 ≠ CEX 입금 (가정이 약함)
- **수정**: 이 추정치의 confidence = 0.2 (매우 낮음), "참고용" 태그
- UI에서도 "추정치 (신뢰도 낮음)" 표시

### (4) External API Rate Limit + Circuit Breaker 설정 파일
```yaml
# config/external_apis.yaml (v8 강화)
defaults:
  circuit_breaker:
    failure_threshold: 5        # 연속 5회 실패 시 차단
    recovery_timeout_sec: 300   # 5분 후 반개방
    half_open_max_calls: 2      # 반개방 시 테스트 호출 수

dexscreener:
  base_url: "https://api.dexscreener.com/latest"
  rate_limit_per_min: 300
  retry_after_sec: 60
  fallback: "gmgn"             # DexScreener 장애 시 GMGN으로 폴백

gmgn:
  base_url: "https://gmgn.ai/api"
  rate_limit_per_min: 100
  api_key_required: false
  fallback: null               # 최종 폴백 없음 → 캐시된 데이터 반환

etherscan:
  rate_limit_per_sec: 5
  api_key_env: "ETHERSCAN_API_KEY"
  fallback: "blockscout"       # Etherscan 장애 시 Blockscout

blockscout:
  rate_limit_per_sec: 3
  fallback: null

exchange_apis:                  # 거래소 출금 상태 API
  binance:
    rate_limit_per_min: 60
  bybit:
    rate_limit_per_min: 60
  okx:
    rate_limit_per_min: 60
```

**Circuit Breaker 구현** (`collectors/api_client.py` 신규):
```python
from enum import Enum

class CircuitState(Enum):
    """Circuit Breaker 상태 (Enum으로 오타 방지)"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreaker:
    """외부 API 장애 시 자동 차단 + 폴백"""

    def __init__(self, config: dict):
        self.failure_threshold = config.get("failure_threshold", 5)
        self.recovery_timeout = config.get("recovery_timeout_sec", 300)
        self.half_open_max_calls = config.get("half_open_max_calls", 2)
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.half_open_successes = 0  # v9: HALF_OPEN 성공 카운트
        self.last_failure_time = 0
        self._half_open_sem = asyncio.Semaphore(1)  # v10: HALF_OPEN 동시 호출 방지

    async def call(self, primary_fn, fallback_fn=None, **kwargs):
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_successes = 0
                logger.info("Circuit HALF_OPEN: 테스트 호출 시작")
            elif fallback_fn:
                return await fallback_fn(**kwargs)
            else:
                raise CircuitOpenError("Circuit open, no fallback")

        # v10: HALF_OPEN일 때 Semaphore로 동시 테스트 호출 1개로 제한
        if self.state == CircuitState.HALF_OPEN:
            if not self._half_open_sem.locked():
                async with self._half_open_sem:
                    try:
                        result = await primary_fn(**kwargs)
                        self._on_success()
                        return result
                    except Exception as e:
                        self._on_failure(e)
                        if fallback_fn:
                            return await fallback_fn(**kwargs)
                        raise
            else:
                # 이미 테스트 호출 진행 중 → 폴백
                if fallback_fn:
                    return await fallback_fn(**kwargs)
                raise CircuitOpenError("HALF_OPEN test in progress")

        try:
            result = await primary_fn(**kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            if fallback_fn:
                return await fallback_fn(**kwargs)
            raise

    def _on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_successes += 1
            if self.half_open_successes >= self.half_open_max_calls:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                logger.info("Circuit CLOSED: 복구 완료")
        else:
            self.failure_count = 0

    def _on_failure(self, error: Exception):
        self.failure_count += 1
        if self.state == CircuitState.HALF_OPEN:
            # HALF_OPEN에서 실패 → 즉시 OPEN 복귀
            self.state = CircuitState.OPEN
            self.last_failure_time = time.time()
            logger.warning(f"Circuit OPEN (HALF_OPEN 실패): {error}")
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.last_failure_time = time.time()
            logger.warning(f"Circuit OPEN: {self.failure_count}회 연속 실패")
```

**Phase 6 고도화 예정 (v9 로드맵)**:
- **Token Bucket Rate Limiter**: `external_apis.yaml`의 `rate_limit_per_min` 기반 호출 제한
- **Exponential Backoff + Jitter**: 반복 실패 시 `recovery_timeout` 을 2x 증가 + 랜덤 jitter
- **Short TTL Cache**: HALF_OPEN 성공 응답을 30초 캐시하여 복구 직후 요청 폭주 방지

### (5) 핫월렛 주소 갱신 전략
- 월 1회 자동 검증: 30일 이상 활동 없는 주소 비활성 처리
- Etherscan 라벨 서비스에서 신규 주소 발견
- `exchange_wallets` 테이블에 `confidence`, `last_verified` 컬럼 추가
- 수동 추가 UI (Streamlit에서 거래소+체인+주소 입력)

### (6) 데이터 보존 정책 (v8 신규)

| 테이블 | 폴링 주기 | 보존 기간 | 정리 방법 |
|--------|----------|----------|----------|
| `trade_snapshot_1s` | 실시간 | 10분 | 매분 DELETE |
| `trade_snapshot_1m` | 1분 | 영구 | - |
| `orderbook_snapshot` | 실시간 | 1시간 | 매시 DELETE **(v9 추가)** |
| `dex_liquidity` | 5분 | 7일 | 일별 배치 DELETE |
| `hot_wallet_balances` | 10분 | 30일 | 주간 배치 DELETE |
| `withdrawal_status` | 1분 | 7일 | 일별 배치 DELETE |
| `airdrop_claims` | 5분 | 상장 후 24시간 | **자동 정리 (v9 변경)** |
| `listing_history` | 이벤트 | 영구 | - |
| `market_condition` | 상장 시 | 영구 | - |
| `listing_scenarios` | 상장 시 | 영구 | - |
| `exchange_wallets` | 수동/월1 | 영구 | 비활성 처리만 |

**정리 구현**: `collector_daemon.py`에 `DataRetentionTask` 추가, 매시 00분에 실행
```python
class DataRetentionTask:
    # v10: (table, time_column, ttl) 명시 — 컬럼 불일치 런타임 에러 방지
    # v6 스키마 정본과 컬럼명 일치 필수
    RETENTION_POLICIES = [
        ("orderbook_snapshot", "ts", timedelta(hours=1)),
        ("fx_snapshots", "timestamp", timedelta(days=7)),
        ("dex_liquidity", "checked_at", timedelta(days=7)),
        ("hot_wallet_balances", "checked_at", timedelta(days=30)),
        ("withdrawal_status", "checked_at", timedelta(days=7)),
    ]

    def __init__(self, writer: 'DatabaseWriter'):
        """v13: DB 쓰기 원칙 통합 — DELETE도 Writer Queue 경유."""
        self._writer = writer

    async def cleanup(self):
        now = datetime.now()
        # 1. 시간 기반 정리 (v10: 테이블별 컬럼명 명시, v13: Writer Queue 경유)
        for table, time_col, ttl in self.RETENTION_POLICIES:
            cutoff = now - ttl
            await self._writer.enqueue(
                f"DELETE FROM {table} WHERE {time_col} < ?",
                (cutoff,),
                priority="normal"  # v13: 드롭돼도 다음 정시에 재실행
            )

        # 2. airdrop_claims: 상장 후 24시간 경과 시 자동 정리 (v9, v13: Writer Queue)
        await self._writer.enqueue(
            """DELETE FROM airdrop_claims
               WHERE symbol IN (
                   SELECT symbol FROM listing_history
                   WHERE listing_time < datetime('now', '-24 hours')
               )""",
            (),
            priority="normal"
        )

    # v10: 정시 스케줄러 (asyncio.sleep 드리프트 방지)
    async def run_scheduled(self):
        """매시 00분에 실행"""
        while True:
            now = datetime.now()
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            wait_seconds = (next_hour - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            try:
                await self.cleanup()
                logger.info(f"Data retention cleanup completed at {datetime.now()}")
            except Exception as e:
                logger.error(f"Data retention cleanup failed: {e}")
```

### (7) 알림 우선순위 체계 (v8 신규)

| 레벨 | 조건 | 알림 방식 |
|------|------|----------|
| 🔴 **CRITICAL** | 상장 감지 + Gate GO | 즉시 전송, 사운드 알림 |
| 🟠 **HIGH** | 공급 분류 변경 (smooth→constrained), 출금 오픈 감지 | 즉시 전송 |
| 🟡 **MEDIUM** | DEX 유동성 임계값 돌파, 핫월렛 급감, 시나리오 확률 변동 | 5분 Debounce |
| 🔵 **LOW** | 시황 사이클 변화, 정기 리포트 | 1시간 배치 |
| ⚪ **INFO** | 데이터 수집 상태, 헬스체크 | 로그만 (텔레그램 미전송) |

```python
# alerts/telegram.py (v8 확장)
class AlertLevel(Enum):
    CRITICAL = "critical"   # 즉시
    HIGH = "high"           # 즉시
    MEDIUM = "medium"       # 5분 debounce
    LOW = "low"             # 1시간 배치
    INFO = "info"           # 로그만

class TelegramAlert:
    def __init__(self, writer: 'DatabaseWriter', read_conn):
        """v12: DB 쓰기 원칙 통합 — 모든 write는 Writer Queue 경유.
        writer: 공유 Writer Queue (쓰기용)
        read_conn: 읽기 전용 커넥션 (debounce 조회, WAL에서 안전)

        원칙: "모든 DB 쓰기는 Writer Queue를 통해서만. 읽기는 아무 커넥션에서 자유롭게."
        v11의 별도 커넥션 직접 쓰기는 Single Writer 원칙과 충돌하므로 제거.
        """
        self.batch_buffer = {AlertLevel.LOW: []}
        self._writer = writer
        self._read_conn = read_conn
        # alert_debounce 테이블은 migrations/에서 생성 (v10)

    def _debounce_check(self, key: str, min_interval: int = 300) -> bool:
        """v12: 읽기는 read_conn, 쓰기는 Writer Queue 경유.

        v13 Known Behavior: enqueue_sync() 후 Writer 스레드가 커밋할 때까지
        read_conn에서 새 레코드가 보이지 않음. 따라서 동일 키에 대한 연속 호출이
        매우 짧은 간격(~수십ms)으로 발생하면 첫 몇 건이 debounce되지 않을 수 있음.
        → 아키텍처 일관성(Single Writer) vs debounce 정밀도 trade-off.
        → 실사용에서 상장 알림은 수 초 간격이므로 실질적 영향 없음.
        """
        now = time.time()
        # 읽기: 별도 커넥션 (WAL에서 비블로킹)
        row = self._read_conn.execute(
            "SELECT last_sent_at FROM alert_debounce WHERE key = ?", (key,)
        ).fetchone()
        if row and now - row[0] < min_interval:
            return False  # 아직 간격 부족
        # 쓰기: Writer Queue 경유 (Single Writer 원칙)
        self._writer.enqueue_sync(
            "INSERT OR REPLACE INTO alert_debounce (key, last_sent_at, expires_at) VALUES (?, ?, ?)",
            (key, now, now + min_interval * 2)
        )
        # 만료 키 정리도 Writer 경유
        self._writer.enqueue_sync(
            "DELETE FROM alert_debounce WHERE expires_at < ?",
            (now,)
        )
        return True

    async def send(self, level: AlertLevel, message: str, key: str = None):
        if level == AlertLevel.INFO:
            logger.info(message)
            return
        if level == AlertLevel.LOW:
            self.batch_buffer[level].append(message)
            return  # 1시간마다 flush
        if level == AlertLevel.MEDIUM and key:
            if not self._debounce_check(key, min_interval=300):
                return
        await self._send_telegram(f"{level.value.upper()}: {message}")
```

### (8) DEX 모니터 체인 커버리지 (v8 명시)

**Phase 5b 지원 체인:**
| 체인 | DEX | 우선순위 | 비고 |
|------|-----|---------|------|
| Ethereum | Uniswap V2/V3 | 🔴 필수 | 대부분의 TGE 토큰 |
| Solana | Raydium, Jupiter, Orca | 🔴 필수 | 솔라나 TGE 증가 추세 |
| BSC | PancakeSwap | 🔴 필수 | 바이낸스 알파 물량 |
| Base | Aerodrome, Uniswap | 🟡 권장 | Base 생태계 성장 |
| Arbitrum | Uniswap, Camelot | 🟡 권장 | L2 |
| Optimism | Velodrome, Uniswap | 🔵 선택 | L2 |

**체인 추가 방법**: `config/dex_chains.yaml`에 체인+DEX+API 엔드포인트 추가 → DexScreener가 대부분 커버하므로 별도 개발 최소화
```yaml
# config/dex_chains.yaml (v8 신규)
chains:
  ethereum:
    explorer: "https://etherscan.io"
    rpc: "${ETH_RPC_URL}"
    dexscreener_chain_id: "ethereum"
  solana:
    explorer: "https://solscan.io"
    rpc: "${SOL_RPC_URL}"
    dexscreener_chain_id: "solana"
  bsc:
    explorer: "https://bscscan.com"
    rpc: "${BSC_RPC_URL}"
    dexscreener_chain_id: "bsc"
  base:
    explorer: "https://basescan.org"
    dexscreener_chain_id: "base"
  arbitrum:
    explorer: "https://arbiscan.io"
    dexscreener_chain_id: "arbitrum"
```

### (9) Premium FX 폴백 체인 (v9 신규)

Implied FX(`R_FX = BTC_Upbit / BTC_Binance`)가 실패하는 경우의 폴백:

| 순서 | 방법 | 조건 |
|------|------|------|
| 1 | BTC Implied FX | 기본 (업비트+바이낸스 BTC 정상) |
| 2 | ETH Implied FX | BTC 거래 일시 중단 시 |
| 3 | USDT/KRW 직접 환율 | 업비트 `USDT/KRW` 티커 (이미 `dominance.py`에 존재) |
| 4 | 캐시된 FX값 | 최근 5분 이내 계산된 값 사용 + 경고 |
| 5 | 하드코딩 기본값 | 모든 소스 실패 시 (`1350.0`) + CRITICAL 경고 |

```python
# analysis/premium.py (v9 FX 폴백)
async def get_implied_fx(self) -> tuple[float, str]:
    """내재환율 조회 (폴백 체인 포함). Returns: (fx_rate, source)"""
    # 1. BTC Implied FX
    try:
        btc_krw = await self._fetch_price("upbit", "BTC/KRW")
        btc_usd = await self._fetch_vwap("BTC/USDT")
        return btc_krw / btc_usd, "btc_implied"
    except Exception:
        pass
    # 2. ETH Implied FX
    try:
        eth_krw = await self._fetch_price("upbit", "ETH/KRW")
        eth_usd = await self._fetch_vwap("ETH/USDT")
        return eth_krw / eth_usd, "eth_implied"
    except Exception:
        pass
    # 3. USDT/KRW 직접
    try:
        usdt_krw = await self._fetch_price("upbit", "USDT/KRW")
        return usdt_krw, "usdt_krw_direct"
    except Exception:
        pass
    # 4. 캐시
    if self._fx_cache and time.time() - self._fx_cache_time < 300:
        return self._fx_cache, "cached"
    # 5. 하드코딩
    logger.critical("모든 FX 소스 실패, 기본값 사용")
    return 1350.0, "hardcoded_fallback"
    # v10: hardcoded_fallback 반환 시 gate.py에서:
    #   - recommended_strategy → WATCH_ONLY 강제
    #   - alert_level → HIGH (CRITICAL 불가)
    #   - warnings에 "FX 기본값 사용 — 수익성 판단 불가" 추가
```

**FX 스냅샷 DB 저장**: 디버깅/사후 분석용으로 `fx_snapshots` 테이블 추가
- 스키마: `(timestamp, fx_rate, source, btc_krw, btc_usd)`
- 보존 기간: 7일 (DataRetentionTask에 추가)

### (10) 파일 책임 분리 (v9 신규)

v8까지 SRP(단일 책임 원칙) 위반이 있는 두 모듈을 분리:

**① 빗썸 공지 파서 분리**
- AS-IS: `collectors/bithumb_ws.py` 안에 `BithumbNoticeParser` 클래스 포함
- TO-BE: `collectors/notice_parser.py`로 분리
- 이유: WS 메시지 처리와 공지 텍스트 파싱은 별개 관심사. 분리하면 파서 단위 테스트 용이

**② 토크노믹스 조회 위치 확정**
- AS-IS: `store/cache.py`에 CoinGecko 토크노믹스 fetch + 캐시 + 분석 로직 혼재
- TO-BE: 2-레이어 분리
  - `store/cache.py`: 순수 캐싱 레이어 (TTL, 429 Soft Fail, 캐시 적중/미스)
  - `analysis/tokenomics.py`: MC/FDV/유통량 조회 로직 (cache.py를 내부적으로 호출)
- Gate/SupplyClassifier에서는 `analysis/tokenomics.py`만 import

### (11) Arkham IN/OUT 구분 명확화 (v9 신규)

v8에서 Arkham이 OUT 테이블에 있으면서 부트스트랩에서 언급되는 불일치 해소:

| Arkham 기능 | 상태 | 이유 | 사용 Phase |
|------------|------|------|-----------|
| **자동 입금량 추적 API** | ❌ OUT | API 불안정, 비용 높음, 실시간 미지원 | - |
| **퍼블릭 라벨 (무료)** | ⚠️ Phase 6 Feature Flag | 무료 공개 데이터지만 스크래핑 필요 | 6 |
| **수동 입금량 입력** | ✅ IN (MVP) | Phase 3~4부터 사용자 직접 입력 | 3 |

- MVP (Phase 1~4): 입금량은 **수동 입력만** 지원
- Phase 5b: 핫월렛 추정 (Etherscan Labels API)
- Phase 6: Arkham 퍼블릭 라벨 스크래핑은 **feature flag** (`features.arkham_scraping: false`) 뒤에 배치

### (12) Feature Flag 체계 (v9 신규)

Phase 1-3을 MVP Core로, Phase 5/6 기능을 feature flag로 관리:

```yaml
# config.yaml 또는 config/features.yaml
features:
  # Phase 5a
  supply_classifier: false    # SupplyClassifier 5-factor 분류
  listing_type: false         # TGE/직상장/옆상장 자동 분류

  # Phase 5b
  dex_monitor: false          # DEX 유동성 실시간 모니터링
  hot_wallet_tracker: false   # 핫월렛 잔액 추적
  withdrawal_tracker: false   # 입출금 상태 자동 추적

  # Phase 6
  scenario_planner: false     # 흥/망따리 시나리오 카드
  arkham_scraping: false      # Arkham 퍼블릭 라벨 스크래핑
  competitive_listing: false  # 견제상장 자동 감지

  # Phase 7 (v14)
  event_arb_monitor: false    # 비상장 이벤트 아비트라지 (경고/장애/디페깅/마이그레이션)
```

```python
# analysis/gate.py — feature flag 분기
async def full_check(self, data: GateInput) -> GateResult:
    # 1단계: Hard Gate (항상 활성)
    hard = self._check_hard_blockers(data)
    if not hard.can_proceed:
        return hard

    supply = None
    listing_type = None
    strategy = None
    scenarios = []

    # 2~5단계: feature flag에 따라 활성/비활성
    if self.features.get("supply_classifier"):
        supply = await self._safe_classify_supply(data)
    if self.features.get("listing_type"):
        listing_type = self._safe_classify_listing(data)
    if supply and listing_type:
        strategy = self._safe_determine_strategy(supply, listing_type, data)
    if self.features.get("scenario_planner") and strategy:
        scenarios = self._safe_generate_scenarios(data, supply, strategy)

    return GateResult(...)
```

**장점**: 코드가 존재하지만 비활성 → 점진적 활성화 → 버그 시 flag만 끄면 롤백

### (13) 스키마 마이그레이션 체계 (v10 신규)

Phase 1부터 스키마 변경을 추적하는 최소 마이그레이션 체계 도입. v10/v11에서 ALTER TABLE 지옥 방지.

**디렉토리 구조:**
```
migrations/
  001_initial.sql           # Phase 1: 기본 테이블 (trade_snapshot_1s/1m, orderbook)
  002_add_fx_snapshots.sql  # Phase 3: FX 스냅샷 + alert_debounce
  003_phase5a_tables.sql    # Phase 5a: listing_history, market_condition 등
  ...
```

**버전 추적 테이블:**
```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    applied_at TEXT DEFAULT (datetime('now')),
    checksum TEXT
);
```

**자동 실행 (`store/database.py` startup):**
```python
from pathlib import Path
import hashlib

def apply_migrations(conn, migrations_dir="migrations"):
    """시작 시 미적용 마이그레이션 자동 실행 (v10)"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            applied_at TEXT DEFAULT (datetime('now')),
            checksum TEXT
        )
    """)
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_version")}

    for f in sorted(Path(migrations_dir).glob("*.sql")):
        version = int(f.name.split("_")[0])
        if version not in applied:
            logger.info(f"Applying migration: {f.name}")
            conn.executescript(f.read_text())
            conn.execute(
                "INSERT INTO schema_version (version, filename, checksum) VALUES (?, ?, ?)",
                (version, f.name, hashlib.md5(f.read_bytes()).hexdigest())
            )
    conn.commit()
```

**규칙:**
- 마이그레이션 파일은 한번 적용되면 **수정 금지** (새 파일로 추가)
- 롤백은 수동 (SQLite ALTER TABLE 제약)
- Phase 1에서 `001_initial.sql`부터 시작

**실행 순서 (v12 명문화, v13 DataRetentionTask 추가) — collector_daemon.py 시작 시퀀스:**
```python
# collector_daemon.py — 시작 순서 (v13 확정)
async def main():
    # 1. DB 커넥션 + 마이그레이션 (Writer 시작 전!)
    conn = get_connection()
    try:
        apply_migrations(conn)
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        logger.info(f"Schema version: {version}")
    except Exception as e:
        logger.critical(f"Migration failed — 즉시 종료: {e}")
        sys.exit(1)  # 부분 적용 스키마로 운영은 더 위험

    # 2. Writer 시작 (마이그레이션 성공 후)
    writer = DatabaseWriter()
    writer.start()

    # 3. 읽기 전용 커넥션 (TelegramAlert, Streamlit IPC 등)
    read_conn = get_connection()  # 별도 커넥션 (읽기만)

    # 4. 서비스 시작 (WS, monitor, alert 등)
    alert = TelegramAlert(writer=writer, read_conn=read_conn)
    retention = DataRetentionTask(writer=writer)  # v13: Writer Queue 경유
    ...
```

**핵심 원칙:**
1. 마이그레이션은 **Writer 시작 전에** 단독 커넥션으로 실행
2. 실패 시 **즉시 종료** (`sys.exit(1)`) — 부분 적용 상태로 운영 금지
3. Writer 시작 후에야 수집기/알림 등 서비스 활성화
4. schema_version 로그로 현재 스키마 버전 기록

### (14) Windows 호환성: 원자적 파일 교체 (v10 신규)

Health Check IPC에서 `os.rename()`은 Windows에서 대상 파일이 이미 존재하면 `FileExistsError` 발생.

```python
# AS-IS (Linux only)
os.rename("health.json.tmp", "health.json")

# TO-BE (v10: cross-platform)
os.replace("health.json.tmp", "health.json")  # Windows에서도 원자적 교체
```

`os.replace()`는 Python 3.3+에서 모든 플랫폼에서 대상 파일 덮어쓰기를 보장.
이 패턴은 프로젝트 전체에서 원자적 파일 교체가 필요한 모든 곳에 적용.

### (15) Writer 스레드 분리 (v10 신규)

`sqlite3`는 동기 I/O이므로 asyncio 이벤트루프에서 `conn.commit()` 시 WAL fsync로 루프가 블로킹됨. WS 수집 코루틴의 데이터 드롭 가능.

**v10 결정: Writer를 별도 스레드로 분리 (asyncio Queue → threading.Queue)**

```python
import threading
import queue as thread_queue

class DatabaseWriter:
    """v10: 별도 스레드에서 DB 쓰기 (이벤트루프 블로킹 방지)
    v12: backpressure 정책 + sentinel 내부→외부 탈출 수정 + enqueue_sync 추가
    """

    def __init__(self):
        self._queue = thread_queue.Queue(maxsize=50000)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._conn = get_connection()
        self.drop_count = 0  # v12: 드롭 메트릭 (health.json에 노출)

    def start(self):
        self._thread.start()

    async def enqueue(self, sql: str, params: tuple, priority: str = "normal"):
        """asyncio 코루틴에서 호출.
        priority: "critical" (listing/gate — 절대 드롭 금지) | "normal" (snapshot — 드롭 가능)
        """
        if priority == "critical":
            loop = asyncio.get_running_loop()  # v11
            await loop.run_in_executor(None, self._queue.put, (sql, params))  # 블로킹 OK
        else:
            try:
                self._queue.put_nowait((sql, params))
            except thread_queue.Full:
                self.drop_count += 1
                if self.drop_count % 100 == 1:
                    logger.warning(f"Writer queue full — dropped {self.drop_count} items total")

    def enqueue_sync(self, sql: str, params: tuple):
        """v12: 동기 호출용 (TelegramAlert 등 비-코루틴 컨텍스트)
        Single Writer 원칙: 모든 DB 쓰기는 이 큐를 통해서만.
        """
        try:
            self._queue.put_nowait((sql, params))
        except thread_queue.Full:
            self.drop_count += 1
            logger.warning(f"Writer queue full (sync) — dropped {self.drop_count}")

    def _run(self):
        """스레드 루프: 배치 수집 → 커밋"""
        while True:
            batch = []
            sentinel_received = False  # v12: 내부→외부 루프 탈출 플래그

            item = self._queue.get()  # 블로킹 대기
            if item is None:          # sentinel → 종료
                break
            batch.append(item)

            # 추가 아이템 비블로킹으로 수집
            while len(batch) < 100:
                try:
                    next_item = self._queue.get_nowait()
                    if next_item is None:  # v11: sentinel 내부 루프 체크
                        sentinel_received = True  # v12: 플래그만 세팅
                        break
                    batch.append(next_item)
                except thread_queue.Empty:
                    break

            # 잔여 배치 커밋 (sentinel 후에도 모은 건 커밋)
            if batch:
                try:
                    cursor = self._conn.cursor()
                    for sql, params in batch:
                        cursor.execute(sql, params)
                    self._conn.commit()
                except Exception as e:
                    logger.error(f"DB write failed: {e}")
                    self._conn.rollback()

            # v12: sentinel이 내부 루프에서 잡혔으면 외부 루프도 탈출
            if sentinel_received:
                break

    def shutdown(self):
        """Graceful Shutdown — sentinel으로 잔여 flush 후 종료"""
        self._queue.put(None)  # sentinel
        self._thread.join(timeout=10)
        self._conn.close()
```

**DB 쓰기 원칙 (v12 확정, v13 DataRetentionTask 통합):**
> **모든 DB 쓰기는 Writer Queue를 통해서만. 읽기는 아무 커넥션에서 자유롭게. (WAL 보장)**
> 예외 없음. TelegramAlert(`enqueue_sync`), DataRetentionTask(`enqueue` priority=normal) 등 모든 모듈이 이 원칙을 따름.

**Backpressure 정책 (v12 신규):**
| 우선순위 | 대상 | Queue full 시 동작 |
|----------|------|-------------------|
| `critical` | listing_events, gate_results | **블로킹 대기** (절대 드롭 금지) |
| `normal` | 1s snapshot, orderbook, debounce | **put_nowait + 드롭** (메트릭 카운트) |

- `drop_count`는 `health.json`에 포함되어 Streamlit에서 "데이터 드롭 발생" 경고 표시
- Queue full은 비정상 상태 → 50,000건 도달 전에 write lag 경고로 조기 감지

**장점:**
- asyncio 이벤트루프가 DB I/O에 **절대 블로킹되지 않음** (normal priority)
- 상장 이벤트/Gate 결과는 **절대 유실되지 않음** (critical priority)
- `threading.Queue`는 thread-safe이므로 `empty()` 레이스 **없음**
- sentinel(`None`) 패턴으로 Graceful Shutdown 보장 (내부→외부 루프 탈출 v12 수정)
- `aiosqlite` 의존성 **불필요** (제거)

**변경 이력:**
- v9→v10: asyncio.Queue → threading.Queue, sentinel 종료
- v10→v11: get_running_loop(), 내부 루프 sentinel 체크
- v11→v12: backpressure(priority+drop), enqueue_sync(), sentinel_received 플래그, DB 쓰기 원칙 확정
- v12→v13: DataRetentionTask도 Writer Queue 경유 (DB 쓰기 원칙 예외 없이 완전 적용)

### (16) 이벤트 아비트라지 모니터 (v14 신규)

**문제**: v13까지 봇은 "신규 상장" 이벤트(TGE/직상장/옆상장)만 감지. 비상장 이벤트에서도 상장 수준의 김프가 발생:

| 이벤트 유형 | 실제 사례 | 수익률 |
|------------|----------|--------|
| 경고 지정 (Warning) | RDNT 해킹 → 3시간 내 | 80% |
| 네트워크 장애 (Halt) | KSM 입금 중단 | 중~대 |
| 스테이블코인 디페깅 | sUSD/SNX → 업비트 110%, 빗썸 40% | 40~110% |
| 비인가 토큰 발행 | LEVER → 경고 지정 전 | 90% |
| 마이그레이션/리브랜딩 | MC→BEAMX 전환 차익 | 중 |

**해결**: `collectors/event_monitor.py` 신규 + `collectors/notice_parser.py` 정규식 확장

**notice_parser.py 정규식 추가**:
```python
# v14: 기존 상장 패턴에 추가
WARNING_PATTERNS = [r"투자유의\s*종목\s*지정", r"경고\s*종목", r"유의\s*지정"]
HALT_PATTERNS = [r"입금\s*일시\s*중단", r"네트워크\s*점검", r"입출금\s*중단"]
MIGRATION_PATTERNS = [r"마이그레이션", r"토큰\s*전환", r"리브랜딩", r"스왑\s*지원"]
DEPEG_PATTERNS = [r"디페깅", r"페깅\s*이탈"]
```

**적용**: Phase 7 (Feature Flag `event_arb_monitor: false`)
**이유**: 상장 아비트라지 인프라(Phase 1~6)가 먼저 완성돼야 이벤트 감지를 확장 가능. Gate/Premium/CostModel은 이벤트에도 동일 적용.

**v15: EventSignal 분리 + DB 결합도 저감**

이벤트 감지 결과를 `listing_history` 테이블에 재활용하면 쿼리/인덱스/정합성 규칙이 깨지기 쉬움 (경고지정/디페깅은 상장 따리와 pricing basis/리스크 모델/액션이 다름). 따라서 Phase 7은 **EventSignal 생성(감지→분류→알림)까지만 확정**, DB 저장은 아래 옵션 중 Phase 7 구현 시 결정:

| 옵션 | 설명 | 장단점 |
|------|------|--------|
| **(A) event_history 별도 테이블** | 이벤트 전용 테이블 신설 | 깔끔한 분리, listing과 혼재 없음 |
| **(B) 범용 이벤트 모델** | `events` 단일 테이블 + `event_kind` 컬럼 (`listing\|warning\|halt\|peg\|migration`) | 확장성 좋지만 초기 스키마 설계 필요 |

```python
# v15: EventSignal dataclass (DB 비종속 — 감지/분류/알림 파이프라인용)
@dataclass
class EventSignal:
    event_kind: str          # "warning" | "halt" | "depeg" | "migration"
    symbol: str
    exchange: str            # 감지된 거래소
    detected_at: datetime
    source: str              # "notice" | "price_deviation" | "ws_status"
    raw_text: str | None     # 공지 원문 (있으면)
    confidence: float        # 감지 신뢰도 (0.0~1.0)
```

**핵심 원칙**: EventSignal → Gate 파이프라인(프리미엄/비용/GO-NOGO) 전달은 기존 `GateInput` 어댑터로 처리. 이벤트 유형별 Gate 분기가 필요하면 Phase 7 구현 시 `event_kind`별 전략 매핑 추가.

**confidence 필터링 (Phase 7 구현 시 결정)**: `EventSignal.confidence`가 임계값(예: 0.3) 이하이면 Gate에 전달하지 않고 로그만 기록. 임계값은 Phase 7 구현 시 과거 이벤트 파싱 정확도 기반으로 확정.

**Feature Flag 추가** (v13 features.yaml 확장):
```yaml
features:
  # 기존 8개 유지 ...
  # Phase 7 (v14)
  event_arb_monitor: false    # 비상장 이벤트 아비트라지 (경고/장애/디페깅/마이그레이션)
```

**산출물**:
- `collectors/event_monitor.py` (신규)
- `collectors/notice_parser.py` (정규식 확장)
- `tests/test_event_monitor.py` (신규)

### (17) 헤징 유형 3단계 세분화 (v14 신규)

**문제**: v13에서 `hedging_possible`은 `bool` (true/false). ZRO 사례에서 CEX 선물은 없지만 **Hyperliquid(DEX 무기한 선물)** 로 헤징 가능한 중간 단계가 존재.

**현재 데이터**: `hedging_impossible`은 시나리오 계수 **+0.37** (67건 분석 최강 시그널). 이 신호를 세분화하면 의사결정 품질 향상.

**수정**:
```yaml
# data/labeling/README.md 스키마 변경
# AS-IS: hedging_possible (bool) — true/false
# TO-BE: hedge_type (enum) — cex_futures / dex_futures / none

# config/thresholds.yaml 계수 세분화
scenario_coefficients:
  hedge_cex: 0.0          # CEX 선물 헤징 가능 → 기저(baseline)
  hedge_dex_only: 0.15    # DEX 선물만 가능 → 중간 시그널 (추정치, Phase 0 재검증 필요)
  hedge_none: 0.37        # 헤징 불가 → 최강 시그널 (기존 값 유지)
```

**cost_model.py 확장**:
```python
# DEX 무기한 선물 헤징 비용 모델 (v14)
class HedgeCost:
    CEX_PERP_FEE = 0.0006    # 0.06% (Binance/Bybit 메이커)
    DEX_PERP_FEE = 0.0020    # 0.20% (Hyperliquid 메이커)
    DEX_SLIPPAGE = 0.005     # 0.5% (DEX 유동성 부족)
```

**v15: 계수 shrinkage 원칙**

`dex_futures` 계수(+0.15)는 표본이 부족할 가능성이 높음 (Hyperliquid 보편화 = 2024년 이후). Phase 0에서 해당 조건의 사례가 `min_sample_size(10건)` 미만이면 계수를 baseline(0.0)에 수렴시킴. 이 원칙은 `dex_futures`뿐 아니라 **모든 시나리오 계수**(`supply_constrained`, `market_bull`, `prev_heung` 등)에 동일 적용 (thresholds.yaml `coefficient_governance.scope: all` 참조):

```python
# scripts/phase0_analysis.py — 계수 shrinkage 적용 (v15)
def apply_shrinkage(raw_coeff: float, sample_count: int, min_sample: int = 10) -> float:
    """표본 부족 시 계수를 baseline(0.0)으로 축소"""
    shrink_factor = min(1.0, sample_count / min_sample)
    return raw_coeff * shrink_factor
    # 예: raw=0.15, count=4 → 0.15 * 0.4 = 0.06
    # 예: raw=0.37, count=45 → 0.37 * 1.0 = 0.37 (충분)
```

**v15: 헤지 실행가능성 메타데이터 (스키마 예약, Phase 5b~7 구현)**

`hedge_type` 3단계만으로는 실행가능성을 충분히 판단하기 어려운 경우가 있음:
- 해당 토큰이 **실제로** DEX perp에 상장돼 있는가?
- 헤지 규모 대비 슬리피지/펀딩이 감당 가능한가? (OI/depth)

```python
# v15: GateInput 헤지 메타 확장 (Phase 5b~7 구현, 그전까진 None)
@dataclass
class HedgeMeta:
    hedge_type: str                  # "cex_futures" | "dex_futures" | "none" (v14)
    hedge_venue: str | None = None   # "binance" | "hyperliquid" | None (v15 예약)
    hedge_capacity_usd: float | None = None  # 헤지 가능 규모 추정 ($) (v15 예약)
    # hedge_venue/capacity는 Phase 5b~7에서 DEX/CEX 선물 데이터 수집 시 채움
    # 그 전까지는 None → 기존 hedge_type만으로 판정 (하위 호환)
```

**구현 로드맵 + 중간 상태 동작**:
- Phase 0~3: `hedge_type`만 사용 (v14와 동일). `hedge_venue`/`hedge_capacity_usd` = None
- Phase 5b: `hedge_venue` 채움 (DEX perp 상장 여부 조회). `hedge_capacity_usd` = None → **cost_model은 기존 고정 슬리피지(`HedgeCost.DEX_SLIPPAGE=0.5%`) 사용** (capacity 미확인 시 보수적 고정값 적용)
- Phase 7: `hedge_capacity_usd` 채움 (OI/depth 기반 규모 추정) → cost_model이 capacity 대비 동적 슬리피지로 전환

**적용 위치**: Phase 0 (재라벨링) + Phase 3 (cost_model) + Phase 5a (scenario 계수)
**Phase 0 영향**: 기존 67건 CSV의 `hedging_possible` → `hedge_type` 재라벨링 필요:
- `true` → 대부분 `cex_futures` (CEX 선물 있는 경우)
- `false` → `none` (기존 값)
- 일부 수동 확인 → `dex_futures` (DEX 선물만 가능)

### (18) Travel Rule / VASP 호환성 체크 (v14 신규)

**문제**: v13 Gate의 Hard Blocker에 Travel Rule/VASP 호환성 체크가 없음. 한국 거래소(업비트/빗썸)는 Travel Rule에 따라 **VASP 협약이 있는 거래소에서만** 입금 가능. 협약 없는 거래소에서 송금하면 자금이 동결됨.

**실제 영향**: 특정 토큰이 VASP 비호환 거래소에만 있으면 김프가 아무리 높아도 아비트라지 불가능. 이는 입출금 중단과 동일 수준의 Hard Blocker.

**설정 파일 신규**:
```yaml
# config/vasp_matrix.yaml (v14 신규, v15 보강)
# 방향: 해외 거래소 → 국내 거래소 입금 기준 (따리 전략 자금흐름 방향)
# O = 호환(송금 가능), X = 비호환
vasp_compatibility:
  upbit:
    binance:
      status: O
    bybit:
      status: O
    okx:
      status: O
    bitget:
      status: O
    gate:
      status: O
    coinbase:
      status: O
    kraken:
      status: X       # Travel Rule 미이행
      alt_note: "개인지갑 경유 시 사전 화이트리스트 등록 필요 (즉시 대응 불가)"
    mexc:
      status: X
      alt_note: "개인지갑 경유 가능하나 사전 등록 필수 + KYC 지연 위험"
    hyperliquid:
      status: X       # DEX (VASP 불가)
      alt_note: "DEX — 개인지갑으로만 출금, 국내 입금 시 화이트리스트 필요"
  bithumb:
    binance:
      status: O
    bybit:
      status: O
    okx:
      status: O
    bitget:
      status: O
    gate:
      status: O
    coinbase:
      status: O
    kraken:
      status: X
      alt_note: "개인지갑 경유 시 사전 화이트리스트 등록 필요"
    mexc:
      status: X
      alt_note: "개인지갑 경유 가능하나 사전 등록 필수"
    hyperliquid:
      status: X
      alt_note: "DEX — 개인지갑으로만 출금, 국내 입금 시 화이트리스트 필요"
last_updated: "2026-01-27"
# 갱신 주기: 분기 1회 수동 확인 (거래소 공지 기반)
```

**v15: VASP 매트릭스 보강 사항**

1. **방향성 명시**: 매트릭스 상단에 "해외→국내 입금 기준"을 주석으로 명시. 따리 전략의 자금 흐름은 대부분 해외→국내 단방향이므로 역방향 매트릭스는 불필요.
2. **대안 경로 참고 (`alt_note`)**: VASP 비호환 거래소에 대해 "개인지갑 경유" 등 대안 가능성을 **참고 정보**로 기록. 단, Gate 판정 로직에는 **반영하지 않음** (Hard Blocker `status: X` 유지). 이유:
   - 화이트리스트 사전 등록은 즉시 대응 불가 (따리는 속도 싸움)
   - Travel Rule 우회는 법적 그레이존 → 봇이 자동 안내하기 부적절
   - UI에서 `alt_note`를 "참고" 배지로 표시하여 사용자가 **사전 준비** 여부를 판단

**적용**: Phase 3 (gate.py Hard Blocker) — VASP는 GO/NO-GO 판단이므로 최초 Gate에 포함
**파일**: `config/vasp_matrix.yaml` (신규) + `analysis/gate.py` (수정)

---

## A.4 추가 발견 3개 (v7) + 2개 (v8) + 2개 (v9)

### (1) 전략 코드명 통일
- 내부: 영문 enum (`StrategyCode.LENDING_ARB`, `StrategyCode.DEX_SPLIT_BUY`)
- UI 표시: 한국어 (`"랜딩(차입) → 빌려서 참여"`)
- `analysis/scenario.py`에 매핑 dict 추가

### (2) Phase 5 범위 세분화
- Phase 5a: Core (supply_classifier, listing_type, token_registry, listing_history) — 3주
- Phase 5b: Data Collection (dex_monitor, hot_wallet_tracker, withdrawal_tracker) — 2주
- Phase 6: Strategy + Scenario (scenario.py, 후따리, 현선갭, UI 확장) — 2주

### (3) airdrop_monitor MVP 전략
- Phase 5b에서는 수동입력 UI만 제공
- 자동화는 주요 플랫폼(LayerZero, Jupiter, Wormhole) 템플릿만 Phase 6에서
- **(v8 보완)**: airdrop 데이터 없을 때 SupplyClassifier 가중치 자동 재분배
  - `airdrop_claim_rate = None` → airdrop 가중치(0.15)를 나머지 4개에 비례 분배
  - fallback 가중치는 `config/thresholds.yaml`의 `fallback_no_airdrop` 참조

### (4) 테스트 커버리지 강화 (v8→v10 확대)
- v7: 테스트 4개 → **v8: 8개** → **v10: 11개** → **v14: 12개**로 확대
- v8 추가 테스트:
  - `tests/test_listing_type.py` — TGE/직상장/옆상장 분류 정확도
  - `tests/test_scenario.py` — 시나리오 확률 계산 + thresholds.yaml 계수 반영
  - `tests/test_dex_monitor.py` — DexScreener 응답 파싱 + 임계값 판정
  - `tests/test_circuit_breaker.py` — Circuit Breaker 상태 전이 (Closed→Open→HalfOpen)
- v9 추가 테스트:
  - `tests/test_notice_parser.py` — 빗썸 공지 파서 단위 테스트 (분리된 모듈)
  - `tests/test_premium.py` — FX 폴백 체인 동작 검증
- 통합 테스트 1개: `tests/test_gate_integration.py` — Phase 0 라벨링 데이터 **50건**으로 Gate 5단계 파이프라인 end-to-end 검증 (열화 규칙 + v10 CRITICAL 조건 포함)

**총 12개 (단위 11개 + 통합 1개, v14)**: test_gate, test_cost_model, test_ws_parser, test_notice_parser, test_premium, test_supply_classifier, test_listing_type, test_scenario, test_dex_monitor, test_circuit_breaker, **test_event_monitor(v14)** + test_gate_integration

### (5) 견제상장 감지 시간 해상도 (v8 신규)
- 빗썸 공지 → 업비트 견제상장이 **최소 20분**만에 발생 가능
- `market_monitor.py` 폴링 주기: **업비트 market/all 30초, 빗썸 공지 API 60초**
- 빗썸 상장 감지 즉시 → "업비트 견제상장 가능성" 알림 (CRITICAL 레벨)
- `competitive_listings` 테이블에 자동 기록

### (6) Streamlit 캐싱 전략 (v8 신규)
```python
# app.py 캐싱 패턴
@st.cache_data(ttl=60)          # 1분 캐시: 시황 데이터, 리스팅 히스토리
def load_market_condition(): ...

@st.cache_data(ttl=10)          # 10초 캐시: 실시간 프리미엄, 오더북
def load_realtime_data(): ...

@st.cache_resource               # 앱 생명주기: DB 커넥션, 설정 파일
def get_db_connection(): ...
```
- 탭별 lazy loading: 선택한 탭만 데이터 조회
- 대시보드 자동 리프레시: `st.rerun()` 30초 간격 (실시간 탭만)

### (7) Gate 열화 시 UI 표시 (v9 신규)
- Gate 2~5단계 중 실패한 단계가 있으면 UI에 `⚠️ 정보 부족` 배지 표시
- 어떤 단계가 실패했는지 + 기본값으로 어떤 전략이 적용됐는지 명시
- 사용자가 수동으로 공급/유형/전략을 오버라이드할 수 있는 드롭다운 제공

### (8) FX 스냅샷 DB 저장 (v9 신규)
- `fx_snapshots` 테이블: `(timestamp, fx_rate, source, btc_krw, btc_usd)`
- 프리미엄 계산 시 사용된 FX 소스 추적 (디버깅/사후 분석)
- 보존 기간: 7일 (DataRetentionTask에 추가)

### (9) Phase 0 hedge_type 재라벨링 (v14 신규)
- `hedging_possible` (bool) → `hedge_type` (enum: `cex_futures`/`dex_futures`/`none`) 변환
- 기존 67건 CSV 재라벨링 필요:
  - `hedging_possible=true` → 대부분 `hedge_type=cex_futures`
  - `hedging_possible=false` → `hedge_type=none`
  - 일부 수동 확인 → `hedge_type=dex_futures` (DEX 선물만 가능했던 경우)
- `scripts/phase0_analysis.py`에 헤징 3분류 분석 함수 추가
- `config/thresholds.yaml` 헤징 계수 세분화: `hedge_cex(0.0)`, `hedge_dex_only(+0.15)`, `hedge_none(+0.37)` + **계수 shrinkage 원칙 (v15)**: 표본 < 10건 시 baseline 수렴

---

# Part B: v15 확정 로드맵

| Phase | 범위 | 산출물 |
|-------|------|--------|
| **0** | 라벨링 + 임계값 | **50건+** 라벨링(업비트30+빗썸20), thresholds.yaml, 조건부 확률 테이블, 흥/망따리 판정 기준, **hedge_type 재라벨링(67건, v14)**, **계수 shrinkage 적용(v15)** |
| **1** | Collector + Store 기반 | robust_ws, database(WAL), **writer(스레드 분리, v10)**, upbit_ws, bithumb_ws, token_registry(**수동 INSERT만, 부트스트랩 Phase 2 이동 v10**), **migrations/(v10)** |
| **2** | 데이터 파이프라인 | aggregator, market_monitor(**30초/60초 폴링**), **notice_parser(분리, v9)**, collector_daemon, **token_registry 부트스트랩(v10 이동)** |
| **3** | 분석 + Gate (v5) | premium(**FX 폴백 체인 + hardcoded→WATCH_ONLY, v10**), cost_model(**+ DEX 헤징 비용 모델, v14**), gate(**열화 규칙 + CRITICAL 조건 + UNKNOWN→WATCH_ONLY, v12** + **VASP Blocker + DEX-only Warning, v14**), **tokenomics.py(분리, v9)**, cache, telegram(**알림 레벨 + debounce Writer Queue 통합, v12**), **features.yaml(v9)**, **vasp_matrix.yaml(v14, v15: 방향성+alt_note 보강)** |
| **4** | UI + 안정화 | app.py 따리분석 탭(**캐싱 전략**), health IPC(**os.replace, v10**), 테스트(**11개, v10**), 메트릭 |
| **5a** | v6 Core Analysis (Feature Flag) | supply_classifier(**가중치 검증 + None처리, v9**), listing_type, listing_history, gate 5단계 확장, **scenario.py hedge_type 3단계 계수 + shrinkage(v14/v15)** |
| **5b** | v6 Data Collection (Feature Flag) | dex_monitor(**6체인**), hot_wallet_tracker, withdrawal_tracker, **api_client(CB Enum + HALF_OPEN Sem, v10)**, **DataRetentionTask(column명시 + 정시스케줄러 v10 + Writer Queue 통합 v13)**, **HedgeMeta.hedge_venue 채움(v15)** |
| **6** | v6 Strategy + UI (Feature Flag) | scenario.py, 후따리/현선갭, 시나리오 카드 UI, 텔레그램 확장, **견제상장 실시간 감지**, **Arkham 라벨 feature flag(v9)**, **CB 고도화(rate limiter/backoff)** |
| **7 (v14/v15)** | **이벤트 아비트라지 (Feature Flag: `event_arb_monitor`)** | **EventSignal 기반 감지/분류/알림(v15), event_monitor.py(신규), notice_parser.py(정규식 확장), test_event_monitor.py(신규), DB: event_history 별도 테이블 또는 범용 이벤트 모델(v15 옵션), HedgeMeta.hedge_capacity_usd 채움(v15)** |

---

# Part C: v5 기반 기술 상세 (요약 참조)

> 아래 내용은 기존 v5/v6 계획서의 기술 상세를 요약합니다.
> 전체 코드 스니펫과 DB 스키마는 `PLAN_v6.md` (3,109줄) 참조.

## C.1 원래 요청 vs v15 반영 현황

| # | 사용자 원래 요청 | v15 반영 | 구현 위치 |
|---|-----------------|---------|----------|
| 1 | 코인 백서/토크노믹스 분석 | **O** | `analysis/tokenomics.py` + `store/cache.py` **(v9 분리)** |
| 2 | MC, FDV, 유통량 표시 | **O** | `analysis/tokenomics.py` + `store/cache.py` **(v9 분리)** |
| 3 | 상장 거래소 24h 거래량 | **O** | `collectors/` + `dominance.py` |
| 4 | 업비트/빗썸 실시간 입금량 | **O (수동 + 핫월렛 추정)** | `app.py` + `collectors/hot_wallet_tracker.py` |
| 5 | 상장 후 5분 거래량 모니터링 | **O** | `collectors/aggregator.py` |
| 6 | 전략 추천 + 흥/망따리 | **O (공급 분류 기반)** | `analysis/gate.py` + `supply_classifier.py` |
| 7 | DEX 유동성 모니터링 | **O (v6)** | `collectors/dex_monitor.py` |
| 8 | 상장유형별 전략 분기 | **O (v6)** | `analysis/listing_type.py` |
| 9 | 시나리오 기반 의사결정 | **O (v6)** | `analysis/scenario.py` |

---

## C.2 버전별 진화 요약

### v1 (초안) → 평가: B+ 75/100

**포함됐던 기능:**
- CoinGecko 토크노믹스 조회
- 단순 스코어링 (가중치 합산)
- Arkham API 입금량 추적
- 흥/망따리 확률 점수

**피드백으로 지적된 문제:**
- 가중치 합계가 80%밖에 안 됨 (20% 누락)
- 입금량 자동화는 현실적으로 불가능
- 네트워크 전송시간 DB 없음
- 브릿지 리스크 매트릭스 없음
- 전략 분류가 너무 단순 (생따리/헷징 2가지만)
- 청산 시뮬레이터 없음

### v2 (정보 대시보드로 전환)

**v1 대비 추가된 것:**
- 네트워크 DB (전송시간, 컨펌수, P90)
- 브릿지 리스크 매트릭스
- 청산 시뮬레이터
- 상장 모니터링 (업비트/빗썸)
- 전략 세분화 (생따리/헷징/론/관망)

**v1에서 변경된 것:**
- "예측기" → "정보 대시보드"로 재포지셔닝
- 확률 스코어 → Go/No-Go 게이트로 전환

### v3 (아키텍처 강화) → 평가: A- 88/100

**v2 대비 추가된 것:**
- Collector/Streamlit 프로세스 분리 개념 도입
- 거래소별 상장 감지 분리 (업비트: Diff, 빗썸: 공지)
- Gate 라벨 정의 (흥따리 = 프리미엄 > 비용+버퍼, 5분 이상 유지)
- 비용 모델 (갭 - 비용 = 순수익)
- 마이크로스트럭처 지표
- 거래소 입출금 상태 플래그

**v2에서 변경된 것:**
- 단일 프로세스 → 이중 프로세스 모델 방향 설정
- 원시 데이터 저장 → 집계 전용 저장으로 변경

### v4 (운영 안정성)

**v3 대비 추가된 것:**
- Arkham API 폴백 체인 (Arkham → Explorer → Manual)
- WS 안정성 강화 (재연결, 핑퐁, 버퍼)
- 동시 상장 시나리오 핸들링
- 에러 핸들링 레이어 (Circuit Breaker)
- 최소 테스트 전략
- Config 분리 (networks.yaml, exchanges.yaml, fees.yaml)
- 관측성 메트릭

**v3에서 변경된 것:**
- 타임라인 현실화

### v5 (최종 - 기술 심화)

**v4 대비 추가된 것:**
- SQLite WAL 모드 + PRAGMA 최적화
- Single Writer Queue 패턴 (DB 락 원천 차단)
- 5단계 데이터 흐름 파이프라인
- 거래소별 오더북 처리 분리 (스냅샷 vs 델타)
- REST Gap Recovery (WS 끊김 후 데이터 복구)
- 내재환율(Implied FX) 프리미엄 계산
- 동적 슬리피지 (오더북 시뮬레이션)
- 1초/1분 이중 테이블 + 롤업 Self-Healing
- Graceful Shutdown (SIGTERM)
- Health Check IPC (health.json 원자적 교체)
- 텔레그램 Debouncing (5분/1% 임계값)
- CoinGecko 3단계 TTL 캐시 (정적/준정적/동적)
- 빗썸 정규식 다중패턴 파싱 엔진

**v4에서 변경된 것:**
- 프리미엄: 단순 (국내/해외)-1 → Implied FX VWAP
- 슬리피지: 고정 0.2% → 오더북 시뮬레이션
- 프로세스 종료: 강제 → Graceful Shutdown

---

## C.3 기능 인벤토리: v5 IN vs OUT

### v5에 포함된 기능 (IN)

| 카테고리 | 기능 | 최초 도입 | 구현 파일 |
|----------|------|----------|----------|
| **수집** | 업비트 WS 체결/호가 | v3 | `collectors/upbit_ws.py` |
| **수집** | 빗썸 WS 체결/호가 | v3 | `collectors/bithumb_ws.py` |
| **수집** | WS 재연결/핑퐁/버퍼 | v4 | `collectors/robust_ws.py` |
| **수집** | REST Gap Recovery | v5 | `collectors/robust_ws.py` |
| **감지** | 업비트 상장 감지 (market/all Diff) | v3 | `collectors/market_monitor.py` |
| **감지** | 빗썸 상장 감지 (공지 정규식 파싱) | v3→v5 강화 | `collectors/bithumb_ws.py` |
| **저장** | SQLite WAL 모드 | v5 | `store/database.py` |
| **저장** | Single Writer Queue | v5 | `store/writer.py` |
| **저장** | 1초/1분 이중 테이블 | v5 | `collectors/aggregator.py` |
| **저장** | 롤업 + Self-Healing | v5 | `collectors/aggregator.py` |
| **분석** | CoinGecko 토크노믹스 (MC/FDV/유통량) | v1 | `store/cache.py` |
| **분석** | 내재환율(Implied FX) 프리미엄 | v5 | `analysis/premium.py` |
| **분석** | 글로벌 VWAP (Binance+OKX+Bybit) | v5 | `analysis/premium.py` |
| **분석** | 동적 슬리피지 (오더북 시뮬) | v5 | `analysis/cost_model.py` |
| **분석** | Go/No-Go Gate 매트릭스 | v2→v5 확정 | `analysis/gate.py` |
| **분석** | 비용 모델 (갭-비용=순수익) | v3→v5 동적화 | `analysis/cost_model.py` |
| **설정** | networks.yaml (전송시간/P90) | v4 | `config/networks.yaml` |
| **설정** | exchanges.yaml (API URL/파싱) | v4 | `config/exchanges.yaml` |
| **설정** | fees.yaml (수수료/가스비) | v4 | `config/fees.yaml` |
| **알림** | 텔레그램 Debouncing 알림 | v1→v5 강화 | `alerts/telegram.py` |
| **운영** | Graceful Shutdown (SIGTERM) | v5 | `collector_daemon.py` |
| **운영** | Health Check IPC (health.json) | v5 | `collector_daemon.py` + `app.py` |
| **운영** | CoinGecko TTL 캐시 (3단계) | v5 | `store/cache.py` |
| **UI** | Streamlit 따리분석 탭 | v1 | `app.py` (수정) |
| **UI** | 수동 입금량 입력 | v2 | `app.py` (수정) |

### 검토 후 제외된 기능 (OUT)

| 기능 | 최초 등장 | 제외 이유 |
|------|----------|----------|
| 흥/망따리 확률 스코어 | v1 | 과적합 위험, 예측보다 정보 제공이 실용적 |
| 가중치 기반 점수 합산 | v1 | 주관적 가중치 문제, Gate 매트릭스로 대체 |
| Arkham API 자동 입금량 | v1 | API 불안정 + 비용 문제, 수동입력으로 변경 |
| 원시 체결 데이터 저장 | v3 초안 | DB 용량 폭발, 집계 전용으로 변경 |
| 단순 환율 프리미엄 계산 | v1~v4 | 은행환율 주말/야간 미반영, Implied FX로 대체 |
| 고정 슬리피지 (0.2%) | v1~v4 | 현실과 괴리, 오더북 시뮬레이션으로 대체 |
| 공통 오더북 처리 로직 | v1~v4 | 거래소별 차이 무시 문제, 스냅샷/델타 분리 |
| 단순 WS 재연결 | v1~v4 | 데이터 누락 불가피, Gap Recovery 추가 |
| 키워드 기반 빗썸 공지 감지 | v1~v3 | 오탐 위험, 정규식 다중패턴으로 대체 |
| 마이크로스트럭처 지표 | v3 | Phase 1~3 범위 외, 향후 확장 가능 |
| 브릿지 리스크 매트릭스 | v2 | 복잡도 대비 실용성 낮음, networks.yaml로 단순화 |
| 청산 시뮬레이터 | v2 | 따리분석 핵심 기능 아님, 별도 모듈로 분리 가능 |

---

## C.4 핵심 기술 결정 진화 추적

### 프리미엄 계산
```
v1~v4: Premium = (국내가 / 해외가) - 1  (은행환율 사용)
v5:    Premium = (P_KRW / (P_Global_USD × R_FX)) - 1
       R_FX = BTC_Upbit / BTC_Binance (내재환율)
       P_Global = Top3 VWAP (펌핑 필터)
```
변경 이유: 은행환율은 주말/야간에 고정. 내재환율이 실제 자금흐름 반영.

### 비용 모델
```
v1:    없음 (갭만 표시)
v3:    고정 비용 (수수료 0.1% + 슬리피지 0.2% + 가스비)
v5:    동적 비용 = 거래소수수료 + 오더북시뮬슬리피지 + 실시간가스비 + 전송비용
```
변경 이유: 핵심 KPI가 "갭"이 아닌 "(갭 - 비용) = 순수익"이므로 비용 정밀도가 곧 의사결정 품질.

### DB 동시성
```
v1~v4: 기본 SQLite (락 충돌 가능)
v5:    WAL 모드 + Single Writer Queue
       → 읽기(Streamlit)와 쓰기(Collector)가 서로 차단하지 않음
       → 모든 쓰기를 단일 태스크로 직렬화, "database is locked" 원천 차단
```

### 상장 감지
```
v1:    없음
v3:    공통 "공지 키워드 검색"
v5:    거래소별 분리
       - 업비트: /v1/market/all API 주기적 Diff (새 마켓 = 신규 상장)
       - 빗썸: 공지사항 API + 정규식 다중패턴 (심볼 + 시간 파싱)
```
변경 이유: 업비트는 공지 API가 없고, 빗썸은 마켓 목록 변경이 느림.

### WS 안정성
```
v1~v3: 단순 재연결
v4:    재연결 + 핑퐁 + 버퍼
v5:    + REST Gap Recovery + Self-Healing 롤업
       → WS 끊김 5초 이상 시 REST로 누락 데이터 보충
       → 재시작 시 최근 15분 스캔하여 누락 롤업 자동 수행
```

---

## C.5 기존 코드 vs v15 신규 코드

### 유지되는 기존 코드

| 파일 | 현재 역할 | v13 변경사항 |
|------|----------|-----------|
| `dominance.py` (310줄) | 거래소 거래량 지배력 계산 | **유지** - 기존 기능 그대로 |
| `main.py` (약 200줄) | CLI 모니터링 봇 | **유지** - 기존 기능 그대로 |
| `app.py` (2,169줄) | Streamlit 대시보드 | **수정** - 따리분석 탭 + health.json IPC(**os.replace**) + v6 시나리오 카드 UI + 캐싱 전략 + Gate 열화 UI + **VASP 상태+alt_note 표시 (v14/v15)** |
| `Procfile` | 배포 설정 | **수정** - collector_daemon worker 추가 |
| `requirements.txt` | 의존성 | **수정** - websockets 추가 (aiosqlite 제거) |

### 신규 생성 파일 (v15 기준: 45개 파일 + 2개 디렉토리)

**Phase 1~4 (25개 파일 + 1개 디렉토리)**

| 파일 | 역할 | Phase |
|------|------|-------|
| `collector_daemon.py` | 수집기 메인 프로세스 | 2 |
| `collectors/robust_ws.py` | WS 래퍼 (재연결/핑퐁/Gap Recovery) | 1 |
| `collectors/upbit_ws.py` | 업비트 WS 핸들러 (스냅샷 교체) | 1 |
| `collectors/bithumb_ws.py` | 빗썸 WS + 공지 파싱 엔진 | 1 |
| `collectors/market_monitor.py` | 상장 감지 (Diff + 공지) | 2 |
| `collectors/aggregator.py` | 1s/1m 집계 + 롤업 + Self-Healing | 2 |
| `store/database.py` | SQLite WAL 설정 | 1 |
| `store/writer.py` | Single Writer Queue **(v10: 스레드 분리)** | 1 |
| `store/cache.py` | CoinGecko TTL 캐시 (3단계) | 3 |
| `store/token_registry.py` | 토큰 식별 + 체인/주소 매핑 (부트스트랩 **v10: Phase 2~3 이동**) | 1 |
| `migrations/` | **스키마 마이그레이션 (v10)** | 1 |
| `analysis/premium.py` | 내재환율(Implied FX) 프리미엄 | 3 |
| `analysis/cost_model.py` | 동적 비용 모델 (오더북 시뮬) | 3 |
| `analysis/gate.py` | Go/No-Go 매트릭스 + **열화 규칙 (v9)** | 3 |
| `analysis/tokenomics.py` | MC/FDV/유통량 조회 **(v9 분리)** | 3 |
| `alerts/telegram.py` | Debouncing 알림 | 3 |
| `config/networks.yaml` | 네트워크 전송시간/P90 | 3 |
| `config/exchanges.yaml` | 거래소 API 설정 | 3 |
| `config/fees.yaml` | 수수료/가스비 임계값 | 3 |
| `config/features.yaml` | Feature Flag 설정 **(v9)** | 3 |
| `collectors/notice_parser.py` | 빗썸 공지 파싱 엔진 **(v9 분리)** | 2 |
| `tests/` (5개 파일) | Gate, CostModel, WS 파서, **NoticeParser, Premium** 테스트 | 4 |

**Phase 5~7 (20개 파일 + 1개 디렉토리)**

| 파일 | 역할 | Phase |
|------|------|-------|
| `analysis/supply_classifier.py` | 공급 원활/미원활 분류 (5-factor) | 5a |
| `analysis/listing_type.py` | TGE/직상장/옆상장 분류 | 5a |
| `analysis/scenario.py` | 흥/망따리 시나리오 카드 생성 | 6 |
| `collectors/dex_monitor.py` | DEX 유동성 모니터링 (DexScreener, 6체인) | 5b |
| `collectors/hot_wallet_tracker.py` | 거래소 핫월렛 잔액 추적 | 5b |
| `collectors/withdrawal_tracker.py` | 입출금 상태 추적 | 5b |
| `collectors/api_client.py` | 외부 API Circuit Breaker **(v8)** | 5b |
| `config/thresholds.yaml` | Phase 0 도출 임계값/확률 계수 **(v7)** | 0 |
| `config/external_apis.yaml` | 외부 API Rate Limit + Circuit Breaker **(v8 강화)** | 5b |
| `config/strategies.yaml` | 전략 코드명 ↔ 한국어 매핑 **(v7)** | 6 |
| `config/dex_chains.yaml` | DEX 체인별 설정 **(v8)** | 5b |
| `data/labeling/` | Phase 0 라벨링 데이터 (50건+) **(v8 확대)** | 0 |
| `tests/test_supply_classifier.py` | SupplyClassifier 테스트 | 5a |
| `tests/test_listing_type.py` | 상장유형 분류 테스트 **(v8)** | 5a |
| `tests/test_scenario.py` | 시나리오 확률 테스트 **(v8)** | 6 |
| `tests/test_dex_monitor.py` | DEX 모니터 테스트 **(v8)** | 5b |
| `tests/test_circuit_breaker.py` | Circuit Breaker 테스트 **(v8)** | 5b |
| `tests/test_gate_integration.py` | Gate 5단계 통합 테스트 **(v8)** | 5a |
| `collectors/event_monitor.py` | **비상장 이벤트 아비트라지 감지 (v14)** | **7** |
| `config/vasp_matrix.yaml` | **VASP 호환성 매트릭스 (v14)** | **3** |
| `tests/test_event_monitor.py` | **이벤트 모니터 테스트 (v14)** | **7** |

---

# Part D: v5 기술 상세 설계 (참고용)

> 아래 내용은 v5 기술 상세입니다. v6/v7 확장 기능의 코드 상세는 `PLAN_v6.md` 참조.

## D.1 아키텍처: 이중 프로세스 모델

**핵심 원칙:**
- GIL 문제 해결: Streamlit 렌더링이 WS 수집을 차단하지 않도록 OS 프로세스 분리
- SQLite WAL 모드로 읽기/쓰기 동시 가능
- Single Writer Queue로 DB 락 충돌 원천 차단

**데이터 흐름 5단계:**
```
1.수집(Ingestion) → 2.버퍼링(Queue) → 3.집계(1s/1m) → 4.적재(SQLite) → 5.소비(Streamlit)
```

### 프로세스 구조
```
┌───────────────────────────────────┐    ┌──────────────────────┐
│ Collector Daemon (항시 실행)       │    │ Streamlit (조회 전용) │
│                                   │    │                      │
│ market_monitor ─→ 상장 감지       │    │ DB 조회 + 시각화     │
│ upbit_ws ──────→ 체결/호가 수집   │    │ 수동 입력 UI         │
│ bithumb_ws ────→ 체결/호가 수집   │    │                      │
│ aggregator ────→ 1s/1m 집계      │    └──────────┬───────────┘
│ db_writer ─────→ Single Writer   │               │ 읽기
│                  Thread (v10+)   │               │
│ health_writer ─→ health.json     │               │
│ telegram_alert → 알림 전송       │    ┌──────────▼───────────┐
│                                   │    │ SQLite (WAL 모드)    │
│        threading.Queue (v10+)     │    │ ddari.db             │
│        (maxsize=50,000)           ├───►│ + health.json (IPC)  │
└───────────────────────────────────┘    └──────────────────────┘
```

---

## D.2 디렉토리 구조 (v15 확정)

```
cex_dominance_bot/
├── collector_daemon.py       # [Entry] 수집기 데몬
├── app.py                    # [Entry] Streamlit 대시보드
├── health.json               # [IPC] 상태 모니터링 (v10: os.replace)
├── ddari.db                  # SQLite DB (WAL 모드)
│
├── migrations/               # [v10] 스키마 마이그레이션
│   ├── 001_initial.sql       # Phase 1: 기본 테이블
│   ├── 002_add_fx_snapshots.sql  # Phase 3
│   └── ...
│
├── config/
│   ├── networks.yaml         # 네트워크 전송시간/컨펌 (P90 포함)
│   ├── exchanges.yaml        # 거래소 API URL, 파싱 정규식
│   ├── fees.yaml             # 수수료, 가스비 임계값
│   ├── features.yaml         # [v9] Feature Flag (Phase 5/6/7 기능 토글, v14: event_arb_monitor 추가)
│   ├── thresholds.yaml       # [v7] Phase 0 도출 임계값/확률 계수 (+fallback 가중치, v14: hedge_type 3단계 계수, v15: shrinkage 원칙)
│   ├── external_apis.yaml    # [v8] 외부 API Rate Limit + Circuit Breaker + Fallback
│   ├── dex_chains.yaml       # [v8] DEX 체인별 설정 (6체인)
│   ├── strategies.yaml       # [v7] 전략 코드명 ↔ 한국어 매핑
│   └── vasp_matrix.yaml      # [v14] VASP 호환성 매트릭스 (v15: 방향성+alt_note 보강)
│
├── data/
│   └── labeling/             # [v7] Phase 0 라벨링 데이터
│
├── collectors/
│   ├── robust_ws.py          # 웹소켓 래퍼 (재연결/핑퐁/버퍼/REST폴백)
│   ├── upbit_ws.py           # 업비트 핸들러 (스냅샷 교체 방식)
│   ├── bithumb_ws.py         # 빗썸 핸들러 (WS 메시지 처리만)
│   ├── notice_parser.py      # [v9] 빗썸 공지 파싱 엔진 (bithumb_ws에서 분리)
│   ├── market_monitor.py     # 마켓 목록 Diff (업비트 30초) + 공지 (빗썸 60초)
│   ├── aggregator.py         # 1s/1m 집계 + 롤업 + Self-healing
│   ├── api_client.py         # [v8] 외부 API Circuit Breaker (v9: Enum 전환)
│   ├── dex_monitor.py        # [v6] DEX 유동성 모니터링 (6체인)
│   ├── hot_wallet_tracker.py # [v6] 거래소 핫월렛 잔액 추적
│   ├── withdrawal_tracker.py # [v6] 입출금 상태 추적
│   └── event_monitor.py      # [v14] 비상장 이벤트 아비트라지 감지 (Phase 7 Feature Flag)
│
├── store/
│   ├── database.py           # SQLite WAL 연결 설정 + 마이그레이션 자동 실행 (v10)
│   ├── writer.py             # Single Writer — 스레드 분리 (v10)
│   ├── cache.py              # CoinGecko TTL 캐시 (순수 캐싱 레이어, v9 분리)
│   └── token_registry.py     # [v7] 토큰 식별 + 체인/주소 매핑
│
├── analysis/
│   ├── premium.py            # 크로스 프리미엄 (Implied FX + v9 폴백 체인)
│   ├── tokenomics.py         # [v9] MC/FDV/유통량 조회 (cache.py에서 분리)
│   ├── cost_model.py         # 동적 비용 (슬리피지 = 오더북 시뮬레이션)
│   ├── gate.py               # Go/No-Go 판단 + 5단계 파이프라인 + v9 열화 규칙
│   ├── supply_classifier.py  # [v6] 공급 원활/미원활 분류 (5-factor + v9 None처리)
│   ├── listing_type.py       # [v6] TGE/직상장/옆상장 분류
│   └── scenario.py           # [v6] 흥/망따리 시나리오 카드 생성
│
├── alerts/
│   └── telegram.py           # 통합 알림 (Debouncing 내장)
│
└── tests/
    ├── test_gate.py
    ├── test_gate_integration.py   # [v8] Gate 5단계 통합 테스트 (v9: 열화 규칙 포함)
    ├── test_cost_model.py
    ├── test_ws_parser.py
    ├── test_notice_parser.py      # [v9] 빗썸 공지 파서 단위 테스트
    ├── test_premium.py            # [v9] FX 폴백 체인 테스트
    ├── test_supply_classifier.py  # [v6]
    ├── test_listing_type.py       # [v8]
    ├── test_scenario.py           # [v8]
    ├── test_dex_monitor.py        # [v8]
    ├── test_circuit_breaker.py    # [v8]
    └── test_event_monitor.py     # [v14] 이벤트 아비트라지 감지 테스트
```

---

## D.3 SQLite WAL + Single Writer Queue

### WAL 모드 설정 (store/database.py)
```python
def get_connection(db_path="ddari.db"):
    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level="DEFERRED")
    conn.execute("PRAGMA journal_mode=WAL")       # 읽기/쓰기 비차단
    conn.execute("PRAGMA synchronous=NORMAL")      # 안전성/속도 타협
    conn.execute("PRAGMA busy_timeout=30000")       # 락 대기 30초
    conn.execute("PRAGMA temp_store=MEMORY")        # 임시 테이블 메모리
    conn.row_factory = sqlite3.Row
    return conn
```

### Single Writer Queue (store/writer.py) — v10: 스레드 분리, v11: sentinel 보강, v12: backpressure + DB쓰기원칙, v13: DataRetentionTask 통합
```python
# v12 전체 코드는 A.3(15)절 참조. 아래는 핵심 구조만 요약.
# 변경 이력: v10(스레드분리) → v11(get_running_loop, sentinel내부체크) → v12(backpressure, enqueue_sync, sentinel_received) → v13(DataRetentionTask Writer Queue 통합)

class DatabaseWriter:
    # threading.Queue(maxsize=50000) + 별도 스레드
    # enqueue(sql, params, priority="normal") — async, critical은 블로킹 허용
    # enqueue_sync(sql, params) — 동기, TelegramAlert 등 비-코루틴용
    # _run() — 배치 수집 + sentinel_received 플래그로 내부→외부 루프 탈출
    # shutdown() — sentinel(None) 주입 → join(10s) → conn.close()
    # drop_count — health.json에 노출
```

---

## D.4 WebSocket 래퍼 상세

### 스냅샷/델타 처리 (거래소별 분리)

| 거래소 | 오더북 처리 방식 | 재연결 시 동작 |
|--------|----------------|-------------|
| **업비트** | 수신 패킷 = 최신 상태 (스냅샷 교체) | 바로 수신 시작 |
| **빗썸** | 초기 스냅샷 + 델타 업데이트 | 오더북 캐시 Flush → 새 스냅샷 대기 |

### REST Gap Recovery
```python
async def _gap_recovery(self, market: str, disconnect_time: float):
    """WS 끊긴 동안 REST로 누락 데이터 보충"""
    gap_seconds = time.time() - disconnect_time
    if gap_seconds < 5:
        return  # 짧은 끊김은 무시

    logger.info(f"Gap Recovery: {market} {gap_seconds:.0f}초 누락 복구")

    # 업비트: /v1/trades/ticks
    # 빗썸: /public/transaction_history
    trades = await self.rest_api.fetch_recent_trades(market, limit=200)
    for trade in trades:
        if trade.timestamp > disconnect_time:
            await self.buffer.put(trade)
```

### 업비트 Idle 타임아웃 대응
- 업비트: 120초 무데이터 시 서버가 연결 종료
- Ping Loop: 30초마다 핑 프레임 전송

---

## D.5 크로스 프리미엄 정밀 산출 (analysis/premium.py)

### 기존 문제점
- 단순 (국내가 / 해외가) - 1 공식은 왜곡 가능
- 은행 환율은 주말/야간에 변하지 않음

### v5 개선: 내재환율(Implied FX) 사용
```
Premium = (P_KRW / (P_Global_USD * R_FX)) - 1

P_Global_USD = 상위 3개 거래소(Binance, OKX, Bybit) VWAP
R_FX = BTC_Upbit_KRW / BTC_Binance_USDT  (내재환율)
```

- VWAP: 특정 거래소 입출금 중단으로 인한 가격 펌핑 필터링
- 내재환율: 실제 자금 흐름 반영, 시장 전체 김프를 베이스라인으로 삼음

---

## D.6 동적 비용 모델링 (analysis/cost_model.py)

### 슬리피지: 오더북 시뮬레이션
```python
def estimate_slippage(orderbook: dict, amount_krw: float) -> float:
    """오더북에서 실제 평균 매입단가를 시뮬레이션"""
    remaining = amount_krw
    total_qty = 0
    for price, qty in orderbook["asks"]:
        fill = min(remaining, price * qty)
        total_qty += fill / price
        remaining -= fill
        if remaining <= 0:
            break

    avg_price = amount_krw / total_qty if total_qty > 0 else 0
    best_ask = orderbook["asks"][0][0]
    slippage = (avg_price - best_ask) / best_ask
    return slippage
```

### 가스비 경고
- networks.yaml의 가스비 임계값과 현재 Gwei 비교
- 예상 가스비가 원금의 1% 초과 시 경고

---

## D.7 빗썸 공지 파싱 엔진 (collectors/notice_parser.py, v9 분리)

### 정규 표현식 기반 다중 패턴 매칭
```python
class BithumbNoticeParser:
    def parse(self, title: str, content: str) -> dict:
        result = {"symbol": None, "listing_time": None}

        # 1. 심볼 추출 (제목 우선)
        # 패턴1: [신규] 비트코인(BTC) 원화 마켓 추가
        m = re.search(r"\(([A-Z]{2,6})\)", title)
        if not m:
            # 패턴2: BTC/KRW
            m = re.search(r"([A-Z]{2,6})/KRW", title)
        if m:
            result["symbol"] = m.group(1)

        # 2. 시간 추출
        # 패턴: "14:00", "오후 2시"
        time_m = re.search(r"(\d{1,2}):(\d{2})", content)
        if time_m:
            hour, minute = int(time_m.group(1)), int(time_m.group(2))
            if "오후" in content and hour < 12:
                hour += 12
            # datetime 객체 생성...

        # 3. 파싱 실패 시 → listing_time=None → "즉시 감지" 모드
        return result
```

---

## D.8 데이터 집계 + 롤업 + Self-Healing

### 이중 테이블 전략
- **trade_snapshot_1s**: 1초 집계, 10분만 보관 (상장 직후 분석용)
- **trade_snapshot_1m**: 1분 집계, 영구 보관 (백테스팅용)

### 롤업 로직 (매분 00초 트리거)
1. 조회: 직전 1분간 1초 데이터
2. 재집계: High=max, Low=min, Volume=sum
3. 삽입: INSERT OR IGNORE (UNIQUE(market, timestamp))
4. 정리: 10분 초과 1초 데이터 DELETE

### Self-Healing (시스템 재시작 시)
- 최근 15분간 데이터 스캔
- 누락된 롤업 자동 수행

---

## D.9 Gate Logic: Go/No-Go 결정 매트릭스

| 구분 | 체크 항목 | 판정 기준 | 결과 |
|------|----------|----------|------|
| **필수(Blocker)** | 입출금 상태 | 입금/출금 중단 | RED |
| **필수(Blocker)** | 수익성 | 프리미엄 < (총비용 + 최소마진 1%) | RED |
| **필수(Blocker)** | 전송 속도 | P90 전송시간 > 30분 | RED |
| **필수(Blocker) (v14)** | **VASP 호환성** | **top_exchange가 한국 거래소와 VASP 비호환** | **RED** **(v15: alt_note는 UI 참고만, Gate 미반영)** |
| **경고(Warning)** | 유동성 | 글로벌 5분 거래량 < $100k | YELLOW |
| **경고(Warning)** | 네트워크 | 가스비 > 100 Gwei | YELLOW |
| **경고(Warning) (v14)** | **DEX-only 헤징** | **CEX 선물 없음, DEX 선물만 가능** | **YELLOW** |

→ 모든 필수 통과 + 경고 없음 = **GO (GREEN)** → 텔레그램 즉시 전송
> **v15 참고**: VASP 비호환(RED) 시 `vasp_matrix.yaml`의 `alt_note`에 대안경로 참고 정보가 있으면 UI에 "참고" 배지로 표시. 단, Gate 판정은 항상 RED 유지 (사전 준비 여부는 사용자 판단).

---

## D.10 운영 안정성

### Graceful Shutdown (SIGTERM) — v10+: sentinel 패턴
1. 수집 중단: WS 메시지 수신 멈춤
2. **Writer 종료**: `writer.shutdown()` 호출 → sentinel(`None`) 주입 → 잔여 배치 flush → 스레드 join **(v10)**
3. 강제 롤업: 진행 중인 분(minute) 데이터 즉시 롤업
4. 연결 종료: DB/파일 핸들 안전 종료 + 종료 로그

### Health Check IPC (health.json) — v12: 판정 기준 확정
```python
# Daemon: 30초마다 갱신 (원자적 교체)
health_data = {
    "heartbeat_timestamp": time.time(),
    "schema_version": 3,                     # v12: 현재 마이그레이션 버전
    "ws_connected": {"upbit": True, "bithumb": False},
    "last_msg_time": {                       # v12: 거래소별 마지막 메시지 시각
        "upbit": 1706234567,
        "bithumb": 1706234500
    },
    "queue_size": 42,
    "queue_drops": 0,                        # v12: Writer 드롭 카운트
    "last_trade_time": 1706234567
}
# tmp에 쓰고 os.replace로 원자적 교체 (v10: Windows 호환)
with open("health.json.tmp", "w") as f:
    json.dump(health_data, f)
os.replace("health.json.tmp", "health.json")  # v10: os.rename → os.replace
```

**v12 판정 기준 (app.py에서 사용):**
```python
# Streamlit health 판정 룰 (v12 확정)
HEALTH_RULES = {
    # RED — 서비스 불능
    "collector_down":   lambda h: time.time() - h["heartbeat_timestamp"] > 60,
    # YELLOW — 경고
    "upbit_ws_stale":   lambda h: time.time() - h["last_msg_time"]["upbit"] > 30,
    "bithumb_ws_stale": lambda h: time.time() - h["last_msg_time"]["bithumb"] > 120,
    "write_lag":        lambda h: h["queue_size"] > 10000,
    "data_dropping":    lambda h: h["queue_drops"] > 0,
}

def evaluate_health(health_data: dict) -> tuple[str, list[str]]:
    """Returns: (status, warnings) where status = "RED"|"YELLOW"|"GREEN" """
    issues = [name for name, check in HEALTH_RULES.items() if check(health_data)]
    if "collector_down" in issues:
        return "RED", issues
    if issues:
        return "YELLOW", issues
    return "GREEN", []
```

| 판정 | 조건 | UI 표시 |
|------|------|---------|
| 🔴 RED | `heartbeat > 60초 지연` | "⚠️ 수집기 응답 없음" 배너 |
| 🟡 YELLOW | `upbit_ws > 30초 무응답` | "업비트 WS 재연결 중" |
| 🟡 YELLOW | `bithumb_ws > 120초 무응답` | "빗썸 WS 재연결 중" (빗썸은 메시지 간격 김) |
| 🟡 YELLOW | `queue_size > 10,000` | "DB 쓰기 지연" |
| 🟡 YELLOW | `queue_drops > 0` | "데이터 드롭 발생" |
| 🟢 GREEN | 전부 통과 | 정상 |

### 텔레그램 Debouncing
- 동일 코인 알림: 5분간 변동폭 1% 이상일 때만 추가 알림
- 알림에 Gate 통과 여부 + 핵심 지표(예상 순수익, 전송시간) 포함

---

## D.11 CoinGecko TTL 캐시 전략

| 데이터 유형 | TTL | 예시 |
|------------|-----|------|
| 정적 | 24시간 | 코인 목록, 심볼 |
| 준정적 | 1시간 | 시가총액, 유통량 |
| 동적 | 1분 | 글로벌 가격 |

- **Soft Fail**: 429 에러 시 만료된 캐시 데이터 반환 (서비스 중단 방지)

---

# Part E: v15 구현 로드맵 상세 + 검증

> 로드맵 요약은 Part B 참조. 아래는 Phase별 상세 체크리스트.

## E.0 Phase 0: 라벨링 + 임계값 도출
- [ ] 과거 상장 **50건+** 수집 (업비트 30건 + 빗썸 20건)
- [ ] 데이터 소스 확보: 강의 사례(~30건) + 카일 채널 + 거래소 공지
- [ ] 수동 라벨링 (`data/labeling/listing_data.csv`): 23개 필드 (A.2 스키마 참조)
- [ ] **흥/망따리 판정 기준** 적용: 김프 ≥8% + 5분 유지 = 흥따리 (A.2 참조)
- [ ] Turnover Ratio 사분위수 도출 (P25/P50/P75/P90)
- [ ] 시나리오 확률 조건부 테이블 생성 (constrained, prev_heung 등)
- [ ] **SupplyClassifier 가중치 검증**: 각 factor와 흥/망의 상관계수
- [ ] `config/thresholds.yaml` 생성 (임계값 + 가중치 + fallback 가중치)
- [ ] `data/labeling/` 초기 데이터 적재
- [ ] **(v14)** `hedging_possible` (bool) → `hedge_type` (enum: cex_futures/dex_futures/none) 재라벨링 (67건)
- [ ] **(v14)** `scripts/phase0_analysis.py` 헤징 3분류 분석 함수 추가 및 재실행
- [ ] **(v14)** `config/thresholds.yaml` 헤징 계수 세분화 반영 (`hedge_cex: 0.0`, `hedge_dex_only: 0.15`, `hedge_none: 0.37`)
- [ ] **(v15)** 계수 shrinkage 적용: `scripts/phase0_analysis.py`에 `apply_shrinkage()` 함수 추가, 표본 < 10건인 계수 자동 축소
- [ ] **(v15)** `config/thresholds.yaml`에 `coefficient_governance` 섹션 추가 (min_sample_size, shrinkage_formula, review_cycle)
- **검증**: 50건 이상 라벨링 완료, 임계값 분포 합리성 검토, 가중치 합 = 1.0 확인, **hedge_type 3분류 후 계수 재산출 + 67건 재라벨링 완료 (v14)**, **표본 부족 계수에 shrinkage 적용 확인 (v15)**

## E.1 Phase 1: 기반 구축
- [ ] `collectors/robust_ws.py` - 견고한 WS (재연결/핑퐁/Gap Recovery)
- [ ] `store/database.py` - SQLite WAL 설정 + DATABASE_URL 분기 + **스키마 마이그레이션 자동 실행 (v10)**
- [ ] `store/writer.py` - **Writer 스레드 분리 (v10)**: threading.Queue + sentinel + **backpressure(priority+drop) + enqueue_sync + sentinel_received (v12)**
- [ ] `collectors/upbit_ws.py` - 업비트 수집 (스냅샷 교체)
- [ ] `collectors/bithumb_ws.py` - 빗썸 수집 (델타 동기화)
- [ ] `store/token_registry.py` - 토큰 식별 기반 (**수동 INSERT만, 부트스트랩은 Phase 2 — v10**)
- [ ] `migrations/001_initial.sql` - **초기 스키마 마이그레이션 (v10)**
- **검증**: 24시간 끊김 없는 연결 유지, Writer 스레드 분리 후 이벤트루프 블로킹 없음 확인, 마이그레이션 자동 적용 확인(**실패 시 즉시 종료 v12**), sentinel 내부→외부 루프 탈출 검증(v12), **backpressure 드롭 메트릭 확인(v12)**

## E.2 Phase 2: 데이터 파이프라인
- [ ] `collectors/aggregator.py` - 1s→1m 롤업 + Self-healing
- [ ] `collectors/market_monitor.py` - 상장 감지 (업비트 Diff + 빗썸 공지)
- [ ] `collectors/notice_parser.py` - 빗썸 공지 파싱 엔진 **(v9: bithumb_ws에서 분리)**
- [ ] `collector_daemon.py` - 메인 프로세스 + **Graceful Shutdown (sentinel 패턴, v10)**
- [ ] `store/token_registry.py` - **CoinGecko 부트스트랩 + 상장 감지 시 자동 등록 (v10: Phase 1에서 이동)**
- **검증**: 데이터 적재 신뢰성, 롤업 정확도, token_registry 상위 500개 시딩 확인

## E.3 Phase 3: 분석 + Gate (v5)
- [ ] `analysis/premium.py` - 내재환율 기반 프리미엄 + **FX 폴백 체인 (v9)** + **hardcoded→WATCH_ONLY 연동 (v10)**
- [ ] `analysis/tokenomics.py` - MC/FDV/유통량 조회 **(v9: cache.py에서 분리)**
- [ ] `analysis/cost_model.py` - 동적 슬리피지 (오더북 시뮬레이션)
- [ ] `analysis/gate.py` - Go/No-Go 매트릭스 (Hard Gate만) + **열화 규칙 (v9)** + **CRITICAL 알림 조건 정밀화 (v10)**
- [ ] `store/cache.py` - CoinGecko TTL 캐시 (순수 캐싱 레이어)
- [ ] `alerts/telegram.py` - Debouncing 알림 + **AlertLevel 체계** (v8) + **debounce Writer Queue 통합 + 읽기 전용 커넥션 (v12)**
- [ ] `config/features.yaml` - **Feature Flag 설정 (v9)**
- [ ] `config/` - YAML 설정 파일 (networks, exchanges, fees)
- [ ] `migrations/002_add_fx_snapshots.sql` - **fx_snapshots + alert_debounce 테이블 (v10)**
- [ ] **(v14)** `config/vasp_matrix.yaml` — VASP 호환성 매트릭스 생성 (업비트/빗썸 ↔ 글로벌 거래소)
- [ ] **(v15)** `config/vasp_matrix.yaml` — 방향성 주석("해외→국내 입금 기준") + 비호환 거래소 `alt_note` 참고 정보 추가
- [ ] **(v14)** `analysis/gate.py` — VASP Blocker (4번째 Hard Blocker) + DEX-only 헤징 Warning (3번째) 추가
- [ ] **(v15)** `app.py` — VASP 비호환 시 `alt_note`를 UI "참고" 배지로 표시 (Gate 로직 미반영, 참고 정보만)
- [ ] **(v14)** `analysis/cost_model.py` — DEX 무기한 선물 헤징 비용 모델 추가 (HedgeCost 클래스)

## E.4 Phase 4: UI + 안정화
- [ ] `app.py` - Streamlit 따리분석 탭 + health.json IPC(**os.replace, v10**) + 캐싱 전략 + **Gate 열화 UI (v9)**
- [ ] 과거 상장 데이터 Replay 테스트
- [ ] 엣지 케이스 테스트 (동시 상장, 네트워크 단절)
- [ ] 테스트 세트: Gate, CostModel, WS 파서 + **NoticeParser, Premium, listing_type, scenario 등 11개 (v10 정정)**
- [ ] 관측성 메트릭 로깅

## E.5a Phase 5a: v6 Core Analysis (Feature Flag: `supply_classifier`, `listing_type`)
- [ ] `analysis/supply_classifier.py` - 5-factor 공급 분류 (정본: async, -1~+1)
- [ ] **Turnover Ratio None/저신뢰도 처리 로직** (v9): None→unknown→경고만, epsilon floor, confidence 가중치
- [ ] **airdrop 데이터 없을 시 가중치 fallback 로직** (v8)
- [ ] `analysis/listing_type.py` - TGE/직상장/옆상장 분류
- [ ] `analysis/gate.py` 확장 - 5단계 파이프라인 통합 (full_check) + **feature flag 분기 (v9)**
- [ ] DB: listing_history, market_condition, **fx_snapshots (v9)** 테이블
- [ ] `tests/test_supply_classifier.py` + `tests/test_listing_type.py` + `tests/test_gate_integration.py` (v8, **열화 규칙 검증 추가 v9**)
- [ ] **(v14)** `analysis/scenario.py` — hedge_type 3단계 계수 적용: `cex_futures(0.0)`, `dex_futures(+0.15)`, `none(+0.37)`
- [ ] **(v15)** `analysis/scenario.py` — shrinkage 적용: Phase 0 산출 계수에 `apply_shrinkage()` 반영, 표본 부족 계수는 baseline 수렴
- **검증**: 라벨링 50건 데이터로 분류 정확도 검증, Gate 통합 테스트 통과 (열화 시나리오 포함), **hedge_type 3단계 계수 시나리오 반영 확인 (v14)**, **shrinkage 적용 시 계수 변동 범위 합리성 확인 (v15)**

## E.5b Phase 5b: v6 Data Collection (Feature Flag: `dex_monitor`, `hot_wallet_tracker`, `withdrawal_tracker`)
- [ ] `collectors/dex_monitor.py` - DEX 유동성 (DexScreener, **6체인 커버**) (v8)
- [ ] `collectors/hot_wallet_tracker.py` - 핫월렛 잔액 추적
- [ ] `collectors/withdrawal_tracker.py` - 입출금 상태
- [ ] `collectors/api_client.py` - **Circuit Breaker (v9: CircuitState Enum + half_open_max_calls)** + **HALF_OPEN Semaphore (v10)**
- [ ] `config/external_apis.yaml` - Rate Limit + **Circuit Breaker + Fallback** (v8)
- [ ] `config/dex_chains.yaml` - **체인별 DEX 설정** (v8)
- [ ] **DataRetentionTask** - 보존 정책 자동 정리 + **airdrop_claims 자동 정리 (v9)** + **(table, column, ttl) 명시 + 정시 스케줄러 (v10)** + **Writer Queue 경유 (v13)**
- [ ] DB: dex_liquidity, hot_wallet_balances, withdrawal_status, airdrop_claims 테이블
- [ ] 나머지 참조 테이블: exchange_wallets, withdrawal_patterns
- [ ] `tests/test_dex_monitor.py` + `tests/test_circuit_breaker.py` (v8, **v9: Enum 상태 전이 검증**)
- [ ] **(v15)** `HedgeMeta.hedge_venue` 채움 — DEX perp 상장 여부 조회 로직 (DexScreener/Hyperliquid API)
- **검증**: DEX 신뢰도 레벨 태깅, Circuit Breaker Enum 상태 전이 + half_open 카운트 + **HALF_OPEN Semaphore 동시성 검증 (v10)**, 보존 정책 삭제 동작 + airdrop 자동 정리 + **컬럼명 일치 확인 (v10)** + **DataRetentionTask DELETE가 Writer Queue 경유 확인 (v13)** + **hedge_venue 정상 채움 확인 (v15)**

## E.6 Phase 6: Strategy + Scenario + UI (Feature Flag: `scenario_planner`, `competitive_listing`, `arkham_scraping`)
- [ ] `analysis/scenario.py` - 흥/망따리 시나리오 카드 생성
- [ ] `config/strategies.yaml` - 전략 코드명 매핑 (영문 enum ↔ 한국어)
- [ ] 후따리/현선갭 분석 UI
- [ ] 시나리오 카드 UI (Streamlit)
- [ ] 텔레그램 알림 확장 (시나리오 + **알림 레벨**) (v8)
- [ ] **견제상장 실시간 감지** (market_monitor 30초/60초 폴링) (v8)
- [ ] **Arkham 퍼블릭 라벨 스크래핑** — feature flag `arkham_scraping` 뒤에 배치 **(v9)**
- [ ] **Circuit Breaker 고도화** — Token Bucket Rate Limiter, Exponential Backoff + Jitter **(v9)**
- [ ] DB: listing_scenarios, valuation_checklist, competitive_listings 테이블
- [ ] airdrop_monitor 수동입력 UI
- [ ] `tests/test_scenario.py` (v8)
- **검증**: 시나리오 확률이 thresholds.yaml 계수 기반, 견제상장 20분 이내 감지, **Arkham flag OFF 시 스크래핑 비활성 확인**

## E.7 Phase 7: 이벤트 아비트라지 모니터 (v14 신규, v15 보강, Feature Flag: `event_arb_monitor`)
- [ ] `collectors/event_monitor.py` — 비상장 이벤트 감지 (경고지정, 네트워크장애, 디페깅, 마이그레이션)
- [ ] **(v15)** `EventSignal` dataclass 구현 — DB 비종속 감지/분류/알림 파이프라인 핵심 단위
- [ ] `collectors/notice_parser.py` 확장 — 경고/장애/마이그레이션/디페깅 정규식 패턴 추가 (WARNING_PATTERNS, HALT_PATTERNS, MIGRATION_PATTERNS, DEPEG_PATTERNS)
- [ ] 이벤트 감지 시 기존 Gate 파이프라인 적용 (EventSignal → GateInput 어댑터 → 프리미엄/비용/GO-NOGO)
- [ ] **(v15)** DB 저장 전략 결정: (A) `event_history` 별도 테이블 or (B) `events` 범용 테이블 + `event_kind` 컬럼 — `listing_history` 재활용 금지 (정합성/인덱스 충돌 방지)
- [ ] `alerts/telegram.py` 확장 — 이벤트별 CRITICAL/HIGH 알림 템플릿
- [ ] **(v15)** `HedgeMeta.hedge_capacity_usd` 채움 — DEX/CEX OI·depth 기반 헤지 가능 규모 추정
- [ ] `tests/test_event_monitor.py` — 이벤트 유형별 감지 + 알림 테스트
- **검증**: 과거 경고지정 공지 10건+ 파싱 정확도, feature flag OFF 시 비활성, 이벤트 감지 → Gate 파이프라인 정상 연동, **EventSignal→GateInput 어댑터 정상 변환 확인 (v15)**, **event_history 테이블이 listing_history와 분리 확인 (v15)**

---

## E.8 검증 방법

1. **WS 안정성**: 24시간 연속 운영 → 재연결 횟수, 드롭률
2. **Gap Recovery**: 의도적 WS 끊김 후 REST 복구 데이터 검증
3. **롤업 정확도**: REST API 캔들 vs 자체 집계 비교
4. **프리미엄 정확도**: 수동 계산 vs Implied FX 기반 계산 비교
5. **Gate 정확도**: Phase 0 라벨링 **50건**으로 Gate 결과 vs 실제 결과
6. **Supply 분류**: 라벨링 데이터의 흥/망 결과와 분류 일치율 (**목표: 70%+**)
7. **시나리오 확률**: thresholds.yaml 계수 적용 후 실제 결과와 비교
8. **Circuit Breaker (v8→v9)**: DexScreener 의도적 차단 → GMGN 폴백 동작, **half_open_max_calls 카운트 정상 전이 확인**
9. **데이터 보존 (v8→v9)**: 7일 경과 후 dex_liquidity 자동 삭제, **airdrop_claims 상장 24h 후 자동 삭제, orderbook 1시간 보존 확인**
10. **견제상장 감지 (v8)**: 빗썸 공지 → 20분 이내 업비트 견제 알림 도달 확인
11. **Gate 열화 (v9)**: SupplyClassifier 의도적 예외 → `unknown` 기본값 반환, Gate 통과 확인
12. **FX 폴백 (v9)**: BTC 가격 API 차단 → ETH→USDT/KRW→캐시→기본값 순차 폴백 확인
13. **Feature Flag (v9)**: flag OFF 시 해당 기능 비활성, flag ON 시 정상 동작 확인
14. **공지 파서 분리 (v9)**: notice_parser.py 단독 테스트 — 빗썸 공지 10건+ 파싱 정확도
15. **스키마 마이그레이션 (v10)**: 빈 DB에서 시작 → migrations/ 순차 적용 → 전체 스키마 정상 생성 확인
16. **Writer 스레드 (v10)**: WS 수신 중 DB 대량 커밋 → 이벤트루프 블로킹 없음 확인 (asyncio debug mode)
17. **Debounce DB (v10)**: 프로세스 재시작 후 동일 키 알림 중복 미발생 확인
18. **CRITICAL 알림 조건 (v10)**: FX hardcoded 시 CRITICAL 미발생 + WATCH_ONLY 시 CRITICAL 미발생 + 정상 시 CRITICAL 발생
19. **Windows 호환 (v10)**: health.json 반복 갱신 시 FileExistsError 미발생 (os.replace)
20. **Writer sentinel 내부→외부 탈출 (v12)**: shutdown() 직후 get_nowait()로 sentinel 수신 → sentinel_received 플래그 → 잔여 배치 커밋 후 외부 루프 탈출 확인
21. **DB 쓰기 원칙 (v12)**: TelegramAlert이 Writer Queue 경유로만 쓰기, 읽기만 별도 커넥션, 동시 write 충돌 없음 확인
22. **Queue backpressure (v12)**: Queue full 상태에서 priority=normal → 드롭 + 메트릭 카운트, priority=critical → 블로킹 대기 후 정상 적재
23. **ListingType.UNKNOWN (v12)**: listing_type 분류 실패 → UNKNOWN 반환 → 전략 WATCH_ONLY 강제 확인
24. **마이그레이션 실행 순서 (v12)**: 마이그레이션 실패 시 collector_daemon 즉시 종료, Writer 미시작 확인
25. **health.json 판정 (v12)**: heartbeat > 60초 → RED, ws_stale → YELLOW, queue_drops > 0 → YELLOW 판정 확인
26. **DataRetentionTask Writer Queue (v13)**: DataRetentionTask의 DELETE가 Writer Queue(`enqueue` priority="normal") 경유 확인, `self.db.execute()` 직접 호출 없음 확인
27. **Debounce 쓰기 지연 (v13)**: enqueue_sync() 직후 동일 키 _debounce_check() 재호출 시 — Writer 커밋 전이면 debounce 미적용 가능 (known behavior, 수 초 간격에서는 영향 없음 확인)
28. **VASP 체크 (v14)**: VASP 비호환 거래소(MEXC, Kraken) 소스 시 Gate RED 반환 확인, VASP 호환 거래소(Binance, Bybit) 소스 시 정상 통과 확인
29. **헤징 유형 (v14)**: hedge_type=dex_futures 시 비용 모델에 DEX 수수료(0.20%)+슬리피지(0.5%) 반영 확인, 시나리오 계수 중간값(+0.15) 적용 확인, hedge_type=none 시 기존 +0.37 유지 확인
30. **이벤트 모니터 (v14, Phase 7)**: 경고지정/네트워크장애 공지 파싱 → CRITICAL 알림 발송 확인, feature flag `event_arb_monitor: false` 시 비활성 확인, 이벤트 감지 후 Gate 파이프라인 정상 연동 확인
31. **계수 shrinkage (v15)**: Phase 0에서 `dex_futures` 사례가 10건 미만일 때 `apply_shrinkage()` 적용 → 계수가 baseline(0.0) 방향으로 축소 확인, 10건+ 시 원본 계수 유지 확인. **전체 시나리오 계수**(supply_constrained, market_bull, prev_heung 등)에도 동일 shrinkage 적용 확인
32. **EventSignal 분리 (v15)**: event_monitor.py가 EventSignal dataclass를 생성 → GateInput 어댑터로 변환 → Gate 파이프라인 정상 실행 확인, listing_history 테이블에 이벤트 데이터 미유입 확인, **confidence ≤ 임계값(예: 0.3) 시 Gate 미전달 + 로그만 기록 확인**
33. **VASP alt_note (v15)**: vasp_matrix.yaml의 `alt_note` 필드가 UI에 "참고" 배지로 표시 확인, Gate 판정 로직(`status: X → RED`)에는 alt_note가 영향 없음 확인
34. **HedgeMeta 스키마 (v15)**: hedge_venue/hedge_capacity_usd가 None일 때 기존 hedge_type만으로 정상 판정 (하위 호환), Phase 5b에서 hedge_venue만 채워지고 capacity=None일 때 **cost_model이 고정 슬리피지(DEX_SLIPPAGE=0.5%) 사용** 확인, Phase 7에서 capacity 채움 시 동적 슬리피지 전환 확인

---

# Part F: 부록

## F.1 버전별 핵심 변경 요약

| 항목 | v5 | v6/v7 | v8 | v9 | v10 | v11 | v12 | v13 | v14 | **v15** |
|------|----|-------|----|----|-----|-----|-----|-----|------|------|
| DB 동시성 | WAL + Single Writer Queue | 동일 | + DataRetentionTask | + orderbook 보존, airdrop 자동정리 | + Writer 스레드 분리, sentinel 종료, 스키마 마이그레이션 | + sentinel 내부 루프 체크, get_running_loop() | + DB쓰기원칙 확정, backpressure, enqueue_sync, sentinel_received, 마이그레이션 순서 | + DataRetentionTask Writer Queue 통합 | 동일 | 동일 |
| Gate | Hard Gate (Blocker 3개) | **5단계 파이프라인** | + Turnover Ratio 통합 | + 2~5단계 Graceful Degradation | + CRITICAL 조건 정밀화, FX hardcoded→WATCH_ONLY | 동일 | + ListingType.UNKNOWN→WATCH_ONLY | 동일 | + VASP Blocker(4번째), DEX헤징 Warning(3번째) | + **VASP alt_note(참고, Gate 미반영)** |
| 공급 분류 | 없음 | **SupplyClassifier** (5-factor) | + 가중치 검증 + fallback | + None/저신뢰도 처리, confidence 가중치 | 동일 | 동일 | 동일 | 동일 | 동일 | 동일 |
| 상장 유형 | 없음 | **ListingType** (TGE/직상장/옆상장) | 동일 | 동일 | 동일 | 동일 | + UNKNOWN 추가 (분류실패 기본값) | 동일 | 동일 | 동일 |
| 시나리오 | 없음 | **ScenarioPlanner** | 동일 | 동일 | 동일 | 동일 | 동일 | 동일 | + hedge_type 3단계 계수 | + **계수 shrinkage 원칙** |
| KPI | 갭 - 비용 = 순수익 | + Turnover Ratio | DP 제거, TR 통일 | 동일 | 동일 | 동일 | 동일 | 동일 | 동일 | 동일 |
| 토큰 식별 | 없음 | **TokenRegistry** | + 부트스트랩 전략 | 동일 | 부트스트랩 Phase 2~3 이동 | 동일 | 동일 | 동일 | 동일 | 동일 |
| 임계값 | 하드코딩 | **Phase 0 데이터 기반** | + 50건+, 판정 기준 확정 | 동일 | 동일 | 동일 | 동일 | 동일 | + hedge_type 3분류 계수 세분화 | + **coefficient_governance(shrinkage)** |
| 외부 API | - | Rate Limit | + Circuit Breaker + Fallback | + Enum 전환, half_open 로직 | + HALF_OPEN Semaphore | 동일 | 동일 | 동일 | 동일 | 동일 |
| 프리미엄 FX | Implied FX | 동일 | 동일 | + 5단계 폴백 체인 + fx_snapshots DB | + hardcoded→WATCH_ONLY 연동 | 동일 | 동일 | 동일 | 동일 | 동일 |
| 알림 | Debouncing | 동일 | + 5단계 AlertLevel | 동일 | + CRITICAL 조건 정밀화, debounce DB 저장 | + 별도 DB 커넥션 명시 | Writer Queue 통합 (직접쓰기 제거) | + debounce 쓰기 지연 known behavior 문서화 | + 이벤트별 CRITICAL/HIGH 알림 템플릿 | 동일 |
| 데이터 보존 | 1s(10분), 1m(영구) | 미정의 | 14테이블 보존 정책 | + orderbook 1h, airdrop 자동, fx_snapshots 7d | + (table,column,ttl) 명시, 정시 스케줄러 | 동일 | 동일 | + DELETE도 Writer Queue 경유 | 동일 | 동일 |
| DEX 체인 | - | 미명시 | 6체인 + dex_chains.yaml | 동일 | 동일 | 동일 | 동일 | 동일 | 동일 | 동일 |
| 견제상장 | - | 패턴 감지 | + 30초/60초 폴링 | 동일 | 동일 | 동일 | 동일 | 동일 | 동일 | 동일 |
| 이벤트 감지 | - | - | - | - | - | - | - | - | + 경고지정/장애/디페깅/마이그레이션 (Phase 7 FF) | + **EventSignal 분리, event_history 별도 테이블 옵션** |
| 파일 구조 | - | - | - | notice_parser 분리, tokenomics 분리 | + migrations/ 디렉토리 | 파일 개수 재정리 (42+2) | 동일 | 동일 | + event_monitor.py, vasp_matrix.yaml | 동일 (45+2) |
| Feature Flag | - | - | - | config/features.yaml + gate.py 분기 | 동일 | 동일 | 동일 | 동일 (8개) | + event_arb_monitor (9개) | 동일 (9개) |
| Arkham | OUT (자동) | 동일 | 동일 | IN/OUT 구분 | 동일 | 동일 | 동일 | 동일 | 동일 | 동일 |
| 테스트 | 3개 | 4개 | 8개 + 통합 1개 | ~~10개~~ | 11개 (정정) + 통합 1개 | 동일 | 동일 | 동일 | + test_event_monitor (12+1) | 동일 (12+1) |
| Streamlit | 기본 | 탭 추가 | + 캐싱 전략 | + Gate 열화 UI | 동일 | 동일 | + health 판정 룰(RED/YELLOW/GREEN) | 동일 | 동일 | + **VASP alt_note 배지** |
| Windows 호환 | - | - | - | - | os.replace 적용 | 동일 | 동일 | 동일 | 동일 | 동일 |
| 다이어그램 | - | - | - | - | - | threading.Queue 반영 | 동일 | 동일 | 동일 | 동일 |
| health.json | 있다 수준 | - | - | - | - | - | 판정 기준 확정 (RED/YELLOW/GREEN) | 동일 | 동일 | 동일 |
| 헤징 분류 | - | - | - | - | - | - | - | bool (가능/불가) | 3단계: cex_futures/dex_futures/none | + **HedgeMeta(venue/capacity 스키마 예약)** |
| VASP 호환 | - | - | - | - | - | - | - | - | vasp_matrix.yaml + Gate Blocker | + **방향성 주석 + alt_note 참고** |
| 검증 | - | - | - | - | - | - | - | 27개 | 30개 | **34개** |

## F.2 의존성 변경

### 기존 (유지)
```
ccxt>=4.0.0, pyyaml>=6.0, aiohttp>=3.9.0
streamlit>=1.30.0, plotly>=5.18.0, pandas>=2.0.0
```

### 신규 추가
```
websockets>=12.0       # WS 연결
# aiosqlite 제거 (v10): Writer 스레드 분리로 불필요
```

### 참고: 의존성 최소화 원칙 (v7~v13)
- httpx/requests 등 추가 HTTP 라이브러리 불필요 (aiohttp로 통일)
- DEX/온체인 API는 aiohttp 직접 호출 (별도 SDK 없음)
- **v10**: `aiosqlite` 제거 — Writer 스레드 분리로 비동기 SQLite 래퍼 불필요

## F.3 배포 변경

### 현재 Procfile
```
web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0
```

### v15 Procfile (변경 필요)
```
web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0
worker: python collector_daemon.py
```

## F.4 DB 테이블 총 정리 (v15 확정)

### Phase 1~4 테이블 (v5 기반 + v9~v13)
| 테이블 | 용도 | Phase | 보존 |
|--------|------|-------|------|
| `trade_snapshot_1s` | 1초 집계 | 2 | 10분 |
| `trade_snapshot_1m` | 1분 집계 | 2 | 영구 |
| `orderbook_snapshot` | 오더북 스냅샷 | 2 | **1시간 (v9)** |
| `fx_snapshots` | FX 환율 스냅샷 **(v9)** | 3 | **7일 (v9)** |
| `schema_version` | 마이그레이션 버전 추적 **(v10)** | 1 | 영구 |
| `alert_debounce` | 알림 debounce 이력 **(v10)** | 3 | 자동 만료 |

### Phase 5~6 테이블 (v6/v7 확장)
| 테이블 | 용도 | Phase | CREATE TABLE |
|--------|------|-------|-------------|
| `listing_history` | 과거 상장 기록 + 라벨 | 5a | O |
| `market_condition` | 상장 시점 시장 상태 | 5a | O |
| `dex_liquidity` | DEX 유동성 스냅샷 | 5b | O |
| `hot_wallet_balances` | 핫월렛 잔액 | 5b | O |
| `withdrawal_status` | 입출금 상태 | 5b | O |
| `airdrop_claims` | 에어드랍 클레임 현황 | 5b | O |
| `listing_scenarios` | 시나리오 카드 저장 | 6 | O |
| `exchange_wallets` | 거래소 핫월렛 주소 | 6 | Phase 6 |
| `withdrawal_patterns` | 출금 패턴 분석 | 6 | Phase 6 |
| `valuation_checklist` | 밸류에이션 체크리스트 | 6 | Phase 6 |
| `competitive_listings` | 경쟁 상장 이력 | 6 | Phase 6 |

**총 17개 테이블** (v5 3개 + v9 1개 + v10 2개 + v6/v7 11개)

> **v15 변경**: 이벤트 아비트라지 데이터(Phase 7)는 `listing_history` 재활용 **금지** (v15). `event_history` 별도 테이블 또는 `events` 범용 테이블(event_kind 컬럼) 중 Phase 7 구현 시 결정. 따라서 Phase 7에서 **테이블 1개 추가 예정**.

## F.5 참조 문서

| 문서 | 위치 | 내용 |
|------|------|------|
| PLAN_v5.md | `cex_dominance_bot/` | v5 계획서 (653줄) |
| PLAN_v6.md | `cex_dominance_bot/` | v6 기술 상세 (3,109줄) — 코드 스니펫, DB 스키마 정본 |
| PLAN_v7.md | `cex_dominance_bot/` | v7 통합 계획서 (969줄) |
| PLAN_v8.md | `cex_dominance_bot/` | v8 계획서 (v7 리뷰 피드백 반영) |
| PLAN_v9.md | `cex_dominance_bot/` | v9 계획서 (v8 리뷰 피드백 반영) |
| PLAN_v10.md | `cex_dominance_bot/` | v10 계획서 (v9 리뷰 피드백 반영) |
| PLAN_v11.md | `cex_dominance_bot/` | v11 계획서 (v10 리뷰 반영) |
| PLAN_v12.md | `cex_dominance_bot/` | v12 계획서 (v11 리뷰 반영) |
| PLAN_v13.md | `cex_dominance_bot/` | v13 계획서 (v12 리뷰 P1/P2 반영) |
| PLAN_v14.md | `cex_dominance_bot/` | v14 계획서 (이벤트 아비트라지 + 헤징 3단계 + VASP) |
| PLAN_v15.md | `cex_dominance_bot/` | **본 문서** — v15 최종 계획서 (EventSignal 분리 + shrinkage + HedgeMeta + VASP alt_note) |

---

*보고서 작성일: 2026-01-28*
*버전: v15 Final*
*v14 → v15 변경: 이벤트 모니터 결합도 저감(EventSignal dataclass 도입 + confidence 필터링 원칙, listing_history 재활용 금지 → event_history 별도 테이블 옵션), 헤징 계수 shrinkage 원칙 추가(전체 시나리오 계수 대상, 표본 < 10건 시 baseline 수렴, coefficient_governance 섹션), HedgeMeta 스키마 예약(hedge_venue/hedge_capacity_usd Phase 5b~7 채움, 중간 상태 시 고정 슬리피지 fallback 명시, 하위 호환), VASP 매트릭스 보강(방향성 "해외→국내" 명시 + alt_note 대안경로 참고 정보, Gate 로직 미반영), 검증 34개로 확대*
