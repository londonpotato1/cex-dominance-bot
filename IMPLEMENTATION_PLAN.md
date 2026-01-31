# Gate.py 개선 구현 계획

**작성일**: 2026-01-29 23:30 KST
**기반 문서**: IMPROVEMENT_GUIDE.md
**목표**: 현재 점수 42/50 → 50/50

---

## 구현 순서 (우선순위별)

### Phase A: 즉시 구현 (영향도 높음, 난이도 낮음)

#### A1. asyncio.gather 병렬화 ⭐⭐⭐
**영향**: +2점 (성능)
**예상 시간**: 30분

```python
# Before: 순차 실행 (총 ~3초)
fx_rate, fx_source = await self._premium.get_implied_fx(session)
krw_price = await self._fetch_domestic_price(...)
vwap_result = await self._premium.get_global_vwap(symbol, session)
hedge_type = await self._check_futures_market(symbol, session)

# After: 병렬 실행 (총 ~1초)
results = await asyncio.gather(
    self._premium.get_implied_fx(session),
    self._fetch_domestic_price_safe(symbol, exchange, session),
    self._premium.get_global_vwap(symbol, session),
    self._check_futures_market(symbol, session),
    return_exceptions=True,
)
```

**수정 파일**: `analysis/gate.py`

---

#### A2. 선물 마켓 목록 캐싱 ⭐⭐
**영향**: +1점 (성능/hedge_type)
**예상 시간**: 1시간

```python
# 1시간 TTL로 Binance/Bybit 선물 목록 캐싱
self._futures_cache: dict[str, set[str]] = {"binance": set(), "bybit": set()}
self._futures_cache_time: dict[str, float] = {}
self._futures_cache_ttl = 3600  # 1시간
```

**수정 파일**: `analysis/gate.py`

---

#### A3. LRU 캐시 구현 ⭐
**영향**: +0.5점 (중복방지)
**예상 시간**: 30분

```python
from collections import OrderedDict

class LRUCache:
    def __init__(self, maxsize: int = 1000, ttl: float = 300.0):
        self._cache: OrderedDict = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl
```

**수정 파일**: `analysis/gate.py` 또는 `utils/cache.py` 신규

---

### Phase B: 단기 구현 (영향도 중간, 난이도 중간)

#### B1. 재시도 데코레이터 ⭐
**영향**: +0.5점 (에러 핸들링)
**예상 시간**: 1시간

```python
@async_retry(max_retries=3, base_delay=0.5, exponential=True)
async def _fetch_bybit_futures(self, session):
    ...
```

**수정 파일**: `utils/retry.py` 신규, `analysis/gate.py`

---

#### B2. API 메트릭 수집 ⭐
**영향**: +0.5점 (에러 핸들링)
**예상 시간**: 1시간

```python
@dataclass
class APIMetrics:
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
```

**수정 파일**: `analysis/gate.py`, `ui/health_display.py`

---

#### B3. Hyperliquid DEX 선물 지원 ⭐⭐
**영향**: +1점 (hedge_type)
**예상 시간**: 1시간

```python
async def _check_hyperliquid_market(self, symbol: str, session) -> bool:
    """Hyperliquid 무기한 선물 마켓 확인."""
    async with session.post(
        "https://api.hyperliquid.xyz/info",
        json={"type": "meta"},
    ) as resp:
        ...
```

**수정 파일**: `analysis/gate.py`

---

### Phase C: 중기 구현 (영향도 중간, 난이도 높음)

#### C1. 네트워크 혼잡도 실시간 반영 ⭐⭐
**영향**: +1점 (네트워크)
**예상 시간**: 2시간

```python
async def _get_network_congestion(self, network: str, session) -> float:
    """네트워크 혼잡도 조회 (0.0~1.0)."""
    if network == "ethereum":
        # Etherscan Gas Tracker API
        ...
    elif network == "solana":
        # Solana TPS 기반
        ...
```

**수정 파일**: `analysis/gate.py`
**필요**: `ETHERSCAN_API_KEY` 환경변수

---

#### C2. 공유 ClientSession
**영향**: 0점 (이미 양호하지만 개선 가능)
**예상 시간**: 30분

```python
async def _get_session(self) -> aiohttp.ClientSession:
    if self._session is None or self._session.closed:
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
        self._session = aiohttp.ClientSession(connector=connector)
    return self._session
```

---

## 체크리스트

### Phase A (즉시)
- [x] A1: asyncio.gather 병렬화 ✅ (4x 속도 향상)
- [x] A2: 선물 마켓 캐싱 ✅ (1시간 TTL, O(1) 조회)
- [x] A3: LRU 캐시 구현 ✅ (maxsize=1000, TTL=5분, 자동 cleanup)

### Phase B (단기)
- [x] B1: 재시도 데코레이터 ✅ (지수 백오프 + 지터, 3회 재시도)
- [x] B2: API 메트릭 수집 ✅ (성공률, 평균 레이턴시, 에러 유형별 카운트)
- [x] B3: Hyperliquid DEX 선물 ✅ (CEX 없을 때 DEX 헤지 가능 → "dex_only")

### Phase C (중기)
- [x] C1: 네트워크 혼잡도 ✅ (Ethereum 가스, Solana TPS, EVM 체인 지원)
- [x] C2: 공유 ClientSession ✅ (연결 풀 재사용, DNS 캐시, 리소스 정리)

---

## 점수 예상

| 항목 | 현재 | Phase A 후 | Phase B 후 | Phase C 후 |
|------|------|-----------|-----------|-----------|
| 중복 방지 | 9 | 9.5 | 9.5 | 9.5 |
| hedge_type | 8 | 9 | 10 | 10 |
| 네트워크 | 9 | 9 | 9 | 10 |
| 에러 핸들링 | 9 | 9 | 10 | 10 |
| 성능 최적화 | 7 | 10 | 10 | 10 |
| **합계** | **42** | **46.5** | **48.5** | **49.5** |

---

## 시작하기

```bash
# Phase A1부터 시작
# gate.py의 analyze_listing() 함수에서 asyncio.gather 적용
```

---

*계획 작성: 2026-01-29 23:30 KST*
