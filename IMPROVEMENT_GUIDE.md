# Gate.py 개선 가이드: 10점 만점을 향해

**작성일**: 2026-01-29  
**대상 파일**: `analysis/gate.py`  
**현재 버전**: Phase 5 구현 완료  
**작성자**: 감비 🥔

---

## 목차

1. [현재 점수 요약](#1-현재-점수-요약)
2. [중복 방지 (9/10 → 10/10)](#2-중복-방지-910--1010)
3. [hedge_type 동적 결정 (8/10 → 10/10)](#3-hedge_type-동적-결정-810--1010)
4. [네트워크 동적 결정 (9/10 → 10/10)](#4-네트워크-동적-결정-910--1010)
5. [에러 핸들링 (9/10 → 10/10)](#5-에러-핸들링-910--1010)
6. [성능 최적화 (7/10 → 10/10)](#6-성능-최적화-710--1010)
7. [추가 개선 사항](#7-추가-개선-사항)
8. [구현 우선순위](#8-구현-우선순위)

---

## 1. 현재 점수 요약

| 항목 | 현재 점수 | 감점 요인 |
|------|----------|----------|
| 중복 방지 | 9/10 | 캐시 메모리 누수, 분산 환경 미지원 |
| hedge_type 동적 결정 | 8/10 | API 캐싱 없음, DEX 선물 미지원 |
| 네트워크 동적 결정 | 9/10 | 실시간 혼잡도 미반영 |
| 에러 핸들링 | 9/10 | 재시도 로직 부재, 메트릭 부족 |
| 성능 최적화 | 7/10 | 병렬 처리 없음, 캐싱 부족 |

---

## 2. 중복 방지 (9/10 → 10/10)

### 현재 구현
```python
self._analysis_cache: dict[str, tuple[float, GateResult]] = {}
self._cache_ttl = 300.0  # 5분
```

### 감점 요인

#### 2.1 캐시 메모리 누수 (-0.5점)
오래된 캐시 항목이 자동으로 정리되지 않음.

**개선 코드**:
```python
from collections import OrderedDict
import time

class LRUCache:
    """TTL + LRU 캐시 (메모리 누수 방지)."""
    
    def __init__(self, maxsize: int = 1000, ttl: float = 300.0):
        self._cache: OrderedDict[str, tuple[float, any]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl
    
    def get(self, key: str) -> tuple[bool, any]:
        """캐시 조회. Returns (hit, value)."""
        if key not in self._cache:
            return False, None
        
        timestamp, value = self._cache[key]
        if time.time() - timestamp > self._ttl:
            del self._cache[key]
            return False, None
        
        # LRU: 최근 사용 항목을 끝으로 이동
        self._cache.move_to_end(key)
        return True, value
    
    def set(self, key: str, value: any) -> None:
        """캐시 저장."""
        # maxsize 초과 시 가장 오래된 항목 제거
        while len(self._cache) >= self._maxsize:
            self._cache.popitem(last=False)
        
        self._cache[key] = (time.time(), value)
    
    def cleanup(self) -> int:
        """만료된 항목 정리. Returns 제거된 항목 수."""
        now = time.time()
        expired = [k for k, (t, _) in self._cache.items() if now - t > self._ttl]
        for k in expired:
            del self._cache[k]
        return len(expired)


# GateChecker에서 사용
class GateChecker:
    def __init__(self, ...):
        # 기존: self._analysis_cache: dict = {}
        # 개선:
        self._analysis_cache = LRUCache(maxsize=1000, ttl=300.0)
```

#### 2.2 분산 환경 미지원 (-0.5점)
여러 인스턴스 실행 시 캐시가 공유되지 않음.

**개선 방안** (선택적):
```python
# Option A: Redis 캐시 (분산 환경)
import redis

class RedisCache:
    def __init__(self, redis_url: str, ttl: int = 300):
        self._redis = redis.from_url(redis_url)
        self._ttl = ttl
    
    def get(self, key: str) -> tuple[bool, any]:
        data = self._redis.get(f"gate:{key}")
        if data:
            return True, pickle.loads(data)
        return False, None
    
    def set(self, key: str, value: any) -> None:
        self._redis.setex(f"gate:{key}", self._ttl, pickle.dumps(value))


# Option B: DB 기반 캐시 (단순)
# gate_analysis_log 테이블의 timestamp로 중복 체크
async def _check_recent_analysis(self, symbol: str, exchange: str) -> GateResult | None:
    """최근 5분 이내 분석 결과 조회."""
    row = self._read_conn.execute(
        """SELECT * FROM gate_analysis_log 
           WHERE symbol = ? AND exchange = ? 
           AND timestamp > datetime('now', '-5 minutes')
           ORDER BY timestamp DESC LIMIT 1""",
        (symbol, exchange)
    ).fetchone()
    if row:
        return self._row_to_gate_result(row)
    return None
```

### 10점 달성 체크리스트
- [ ] LRUCache 구현 (maxsize + TTL)
- [ ] 주기적 cleanup 호출 (매 분석 시 또는 백그라운드)
- [ ] (선택) 분산 캐시 지원 (Redis 또는 DB)

---

## 3. hedge_type 동적 결정 (8/10 → 10/10)

### 현재 구현
```python
async def _check_futures_market(self, symbol: str, session: aiohttp.ClientSession) -> str:
    """Bybit → Binance 순으로 선물 마켓 확인."""
    futures_symbol = f"{symbol}USDT"

    # 1. Bybit: 특정 심볼만 조회 (효율적)
    url = f"https://api.bybit.com/v5/market/instruments-info?category=linear&symbol={futures_symbol}"
    # ... retCode == 0 and list not empty → return "cex"

    # 2. Binance: 전체 exchangeInfo 조회 후 검색 (비효율적!)
    url = f"https://fapi.binance.com/fapi/v1/exchangeInfo"
    symbols = [s["symbol"] for s in data.get("symbols", [])]
    if futures_symbol in symbols:
        return "cex"

    return "none"
```

### 감점 요인

#### 3.1 Binance 전체 목록 매번 조회 (-1점)
Bybit은 단일 심볼 쿼리로 효율적이나, Binance `/fapi/v1/exchangeInfo`는 수백 개 심볼 반환 → 비효율적

**개선 코드**:
```python
class GateChecker:
    def __init__(self, ...):
        # 선물 마켓 캐시
        self._futures_cache: dict[str, set[str]] = {
            "binance": set(),
            "bybit": set(),
        }
        self._futures_cache_time: dict[str, float] = {
            "binance": 0,
            "bybit": 0,
        }
        self._futures_cache_ttl = 3600  # 1시간
    
    async def _refresh_futures_cache(
        self, exchange: str, session: aiohttp.ClientSession
    ) -> None:
        """선물 마켓 목록 캐시 갱신."""
        now = time.time()
        if now - self._futures_cache_time.get(exchange, 0) < self._futures_cache_ttl:
            return  # 캐시 유효
        
        symbols = set()
        
        if exchange == "binance":
            try:
                async with session.get(
                    "https://fapi.binance.com/fapi/v1/exchangeInfo",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        symbols = {s["symbol"] for s in data.get("symbols", [])}
            except Exception as e:
                logger.warning("[Gate] Binance 선물 목록 조회 실패: %s", e)
                return
        
        elif exchange == "bybit":
            try:
                async with session.get(
                    "https://api.bybit.com/v5/market/instruments-info?category=linear&limit=1000",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("retCode") == 0:
                            symbols = {
                                s["symbol"] 
                                for s in data.get("result", {}).get("list", [])
                            }
            except Exception as e:
                logger.warning("[Gate] Bybit 선물 목록 조회 실패: %s", e)
                return
        
        self._futures_cache[exchange] = symbols
        self._futures_cache_time[exchange] = now
        logger.info("[Gate] %s 선물 캐시 갱신: %d 심볼", exchange, len(symbols))
    
    async def _check_futures_market(
        self, symbol: str, session: aiohttp.ClientSession
    ) -> str:
        """선물 마켓 존재 여부 확인 (캐시 사용)."""
        futures_symbol = f"{symbol}USDT"
        
        # 캐시 갱신 (필요 시)
        await self._refresh_futures_cache("bybit", session)
        await self._refresh_futures_cache("binance", session)
        
        # Bybit 우선 확인
        if futures_symbol in self._futures_cache["bybit"]:
            logger.debug("[Gate] 선물 발견: %s@Bybit (캐시)", futures_symbol)
            return "cex"
        
        # Binance 확인
        if futures_symbol in self._futures_cache["binance"]:
            logger.debug("[Gate] 선물 발견: %s@Binance (캐시)", futures_symbol)
            return "cex"
        
        return "none"
```

#### 3.2 DEX 무기한 선물 미지원 (-1점)
Hyperliquid 등 DEX perp 지원 필요 (PLAN v14)

**개선 코드**:
```python
async def _check_futures_market(
    self, symbol: str, session: aiohttp.ClientSession
) -> str:
    """선물 마켓 확인 (CEX → DEX 순)."""
    futures_symbol = f"{symbol}USDT"
    
    # 1. CEX 선물 확인 (캐시)
    await self._refresh_futures_cache("bybit", session)
    await self._refresh_futures_cache("binance", session)
    
    if futures_symbol in self._futures_cache["bybit"]:
        return "cex"
    if futures_symbol in self._futures_cache["binance"]:
        return "cex"
    
    # 2. DEX 선물 확인 (Hyperliquid)
    if await self._check_hyperliquid_market(symbol, session):
        return "dex_only"
    
    return "none"

async def _check_hyperliquid_market(
    self, symbol: str, session: aiohttp.ClientSession
) -> bool:
    """Hyperliquid 무기한 선물 마켓 확인."""
    try:
        # Hyperliquid는 meta endpoint에서 전체 마켓 조회
        async with session.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "meta"},
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                # universe 배열에서 심볼 검색
                universe = data.get("universe", [])
                for asset in universe:
                    if asset.get("name", "").upper() == symbol.upper():
                        logger.debug("[Gate] DEX 선물 발견: %s@Hyperliquid", symbol)
                        return True
    except Exception as e:
        logger.debug("[Gate] Hyperliquid 조회 실패 (%s): %s", symbol, e)
    return False
```

### 10점 달성 체크리스트
- [ ] 선물 마켓 목록 캐싱 (1시간 TTL)
- [ ] 캐시 기반 O(1) 조회
- [ ] Hyperliquid DEX 선물 지원
- [ ] (선택) OKX, Bitget 추가

---

## 4. 네트워크 동적 결정 (9/10 → 10/10)

### 현재 구현
```python
# CoinGecko chain name → networks.yaml key 매핑
_CHAIN_NAME_MAP = {
    "ethereum": "ethereum",
    "solana": "solana",
    "binance-smart-chain": "bsc",
    "arbitrum-one": "arbitrum",
    "polygon-pos": "polygon",
    "avalanche": "avalanche",
    "tron": "tron",
    "base": "base",
    # ... 총 11개 매핑
}

def _determine_optimal_network(self, symbol: str) -> str:
    """TokenRegistry 기반 최적 네트워크 선택."""
    if self._registry is None:
        return "ethereum"  # fallback

    token = self._registry.get_by_symbol(symbol)
    if token is None or not token.chains:
        return "ethereum"  # fallback

    # networks.yaml에서 avg_transfer_min 비교
    best_network = "ethereum"
    best_time = float("inf")

    for chain_info in token.chains:
        chain_name = chain_info.chain.lower()
        network_key = self._CHAIN_NAME_MAP.get(chain_name)
        if network_key is None:
            continue

        net_config = networks_config.get(network_key)
        transfer_time = net_config.get("avg_transfer_min", float("inf"))
        if transfer_time < best_time:
            best_time = transfer_time
            best_network = network_key

    return best_network  # solana(0.5분) > bsc(1분) > ethereum(5분)
```

### 감점 요인

#### 4.1 실시간 네트워크 혼잡도 미반영 (-1점)
정적 avg_transfer_min만 사용 → 이더리움 가스비 폭등 시 반영 안 됨

**개선 코드**:
```python
class GateChecker:
    def __init__(self, ...):
        # 네트워크 혼잡도 캐시
        self._network_congestion: dict[str, float] = {}  # 0.0 (정상) ~ 1.0 (혼잡)
        self._congestion_cache_time: dict[str, float] = {}
        self._congestion_cache_ttl = 60  # 1분
    
    async def _get_network_congestion(
        self, network: str, session: aiohttp.ClientSession
    ) -> float:
        """네트워크 혼잡도 조회 (0.0~1.0)."""
        now = time.time()
        if now - self._congestion_cache_time.get(network, 0) < self._congestion_cache_ttl:
            return self._network_congestion.get(network, 0.0)
        
        congestion = 0.0
        
        if network == "ethereum":
            try:
                # Etherscan Gas Tracker API
                api_key = os.environ.get("ETHERSCAN_API_KEY", "")
                url = f"https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey={api_key}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "1":
                            fast_gas = float(data["result"].get("FastGasPrice", 30))
                            # 30 gwei = 정상, 100+ gwei = 혼잡
                            congestion = min(1.0, max(0.0, (fast_gas - 30) / 70))
            except Exception as e:
                logger.debug("[Gate] Ethereum 가스 조회 실패: %s", e)
        
        elif network == "solana":
            try:
                # Solana 최근 TPS로 혼잡도 추정
                async with session.post(
                    "https://api.mainnet-beta.solana.com",
                    json={"jsonrpc": "2.0", "id": 1, "method": "getRecentPerformanceSamples", "params": [1]},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        samples = data.get("result", [])
                        if samples:
                            tps = samples[0].get("numTransactions", 0) / samples[0].get("samplePeriodSecs", 1)
                            # 2000 TPS = 정상, 4000+ TPS = 혼잡
                            congestion = min(1.0, max(0.0, (tps - 2000) / 2000))
            except Exception as e:
                logger.debug("[Gate] Solana TPS 조회 실패: %s", e)
        
        self._network_congestion[network] = congestion
        self._congestion_cache_time[network] = now
        return congestion
    
    async def _determine_optimal_network_async(
        self, symbol: str, session: aiohttp.ClientSession
    ) -> str:
        """토큰의 최적 전송 네트워크 결정 (혼잡도 반영)."""
        if self._registry is None:
            return "ethereum"
        
        token = self._registry.get_by_symbol(symbol)
        if token is None or not token.chains:
            return "ethereum"
        
        networks_config = self._networks.get("networks", {})
        if not networks_config:
            return "ethereum"
        
        best_network = "ethereum"
        best_score = float("inf")  # 낮을수록 좋음
        
        for chain_info in token.chains:
            chain_name = chain_info.chain.lower()
            network_key = self._CHAIN_NAME_MAP.get(chain_name)
            if network_key is None:
                continue
            
            net_config = networks_config.get(network_key)
            if net_config is None:
                continue
            
            base_time = net_config.get("avg_transfer_min", float("inf"))
            congestion = await self._get_network_congestion(network_key, session)
            
            # 혼잡도에 따른 예상 전송 시간 조정
            # 혼잡도 1.0 → 전송 시간 3배
            adjusted_time = base_time * (1 + congestion * 2)
            
            if adjusted_time < best_score:
                best_score = adjusted_time
                best_network = network_key
        
        logger.info(
            "[Gate] 네트워크 결정: %s → %s (조정 시간 %.1f분)",
            symbol, best_network, best_score,
        )
        return best_network
```

### 10점 달성 체크리스트
- [ ] Ethereum 가스비 실시간 조회
- [ ] Solana TPS 기반 혼잡도
- [ ] 혼잡도 기반 전송 시간 조정
- [ ] 혼잡도 캐시 (1분 TTL)

---

## 5. 에러 핸들링 (9/10 → 10/10)

### 현재 구현
```python
try:
    async with session.get(url) as resp:
        ...
except Exception as e:
    logger.debug(...)
```

### 감점 요인

#### 5.1 재시도 로직 부재 (-0.5점)
일시적 네트워크 오류 시 바로 실패

**개선 코드**:
```python
import asyncio
from functools import wraps

def async_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    exponential: bool = True,
    exceptions: tuple = (aiohttp.ClientError, asyncio.TimeoutError),
):
    """비동기 함수 재시도 데코레이터."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt if exponential else 1)
                        # Jitter 추가 (thundering herd 방지)
                        delay *= (0.5 + random.random())
                        logger.warning(
                            "[Retry] %s 실패 (attempt %d/%d), %.1fs 후 재시도: %s",
                            func.__name__, attempt + 1, max_retries, delay, e,
                        )
                        await asyncio.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


# 사용 예시
class GateChecker:
    @async_retry(max_retries=3, base_delay=0.5)
    async def _fetch_bybit_futures(self, session: aiohttp.ClientSession) -> set[str]:
        async with session.get(
            "https://api.bybit.com/v5/market/instruments-info?category=linear&limit=1000",
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if data.get("retCode") != 0:
                raise ValueError(f"Bybit API error: {data.get('retMsg')}")
            return {s["symbol"] for s in data.get("result", {}).get("list", [])}
```

#### 5.2 에러 메트릭 부족 (-0.5점)
실패율, 지연 시간 등 모니터링 불가

**개선 코드**:
```python
from dataclasses import dataclass, field
from collections import defaultdict
import time

@dataclass
class APIMetrics:
    """API 호출 메트릭."""
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    @property
    def success_rate(self) -> float:
        return self.success_calls / self.total_calls if self.total_calls > 0 else 0.0
    
    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.success_calls if self.success_calls > 0 else 0.0
    
    def record_success(self, latency_ms: float) -> None:
        self.total_calls += 1
        self.success_calls += 1
        self.total_latency_ms += latency_ms
    
    def record_failure(self, error_type: str) -> None:
        self.total_calls += 1
        self.failed_calls += 1
        self.errors[error_type] += 1
    
    def to_dict(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "success_rate": f"{self.success_rate:.2%}",
            "avg_latency_ms": f"{self.avg_latency_ms:.1f}",
            "errors": dict(self.errors),
        }


class GateChecker:
    def __init__(self, ...):
        # API 메트릭
        self._metrics: dict[str, APIMetrics] = defaultdict(APIMetrics)
    
    async def _call_api_with_metrics(
        self,
        name: str,
        coro,
    ):
        """메트릭 수집과 함께 API 호출."""
        start = time.monotonic()
        try:
            result = await coro
            latency_ms = (time.monotonic() - start) * 1000
            self._metrics[name].record_success(latency_ms)
            return result
        except Exception as e:
            self._metrics[name].record_failure(type(e).__name__)
            raise
    
    def get_metrics(self) -> dict[str, dict]:
        """전체 메트릭 반환."""
        return {name: m.to_dict() for name, m in self._metrics.items()}
    
    # health.json에 메트릭 포함
    def export_health(self) -> dict:
        return {
            "status": "ok",
            "metrics": self.get_metrics(),
            "cache": {
                "analysis": len(self._analysis_cache._cache),
                "futures_binance": len(self._futures_cache.get("binance", set())),
                "futures_bybit": len(self._futures_cache.get("bybit", set())),
            },
        }
```

### 10점 달성 체크리스트
- [ ] 재시도 데코레이터 (exponential backoff + jitter)
- [ ] API별 메트릭 수집 (성공률, 지연 시간, 에러 유형)
- [ ] health.json에 메트릭 포함
- [ ] 실패율 임계값 알림 (선택)

---

## 6. 성능 최적화 (7/10 → 10/10)

### 현재 구현
```python
# 순차 실행
fx_rate, fx_source = await self._premium.get_implied_fx(session)
krw_price = await _fetch_upbit_price(krw_market, session)
vwap_result = await self._premium.get_global_vwap(symbol, session)
```

### 감점 요인

#### 6.1 병렬 처리 없음 (-2점)
독립적인 API 호출을 순차적으로 실행

**개선 코드**:
```python
async def analyze_listing(self, symbol: str, exchange: str, force: bool = False) -> GateResult:
    """상장 분석 (병렬 최적화)."""
    import time
    cache_key = f"{symbol}@{exchange}"
    now = time.time()
    
    # 캐시 확인
    hit, cached = self._analysis_cache.get(cache_key)
    if not force and hit:
        return cached
    
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=15)
    ) as session:
        # 1단계: 독립적인 API 호출 병렬 실행
        krw_market = self._make_domestic_market(symbol, exchange)
        
        fx_task = self._premium.get_implied_fx(session)
        krw_task = self._fetch_domestic_price_safe(symbol, exchange, session)
        vwap_task = self._premium.get_global_vwap(symbol, session)
        hedge_task = self._check_futures_market(symbol, session)
        
        # 병렬 실행 (asyncio.gather)
        results = await asyncio.gather(
            fx_task, krw_task, vwap_task, hedge_task,
            return_exceptions=True,
        )
        
        fx_result, krw_price, vwap_result, hedge_type = results
        
        # 에러 처리
        if isinstance(fx_result, Exception):
            logger.warning("[Gate] FX 조회 실패: %s", fx_result)
            fx_rate, fx_source = 1350.0, "hardcoded_fallback"
        else:
            fx_rate, fx_source = fx_result
        
        if isinstance(krw_price, Exception) or krw_price is None:
            return GateResult(
                can_proceed=False,
                blockers=["국내 가격 조회 실패"],
                symbol=symbol, exchange=exchange,
            )
        
        # ... 나머지 로직
```

#### 6.2 캐싱 부족 (-1점)
FX 환율, CoinGecko 데이터 등 반복 조회

**개선 코드**:
```python
class GateChecker:
    def __init__(self, ...):
        # 다양한 캐시
        self._fx_cache: tuple[float, str, float] | None = None  # (rate, source, timestamp)
        self._fx_cache_ttl = 30  # 30초
        
        self._token_info_cache: dict[str, tuple[any, float]] = {}  # symbol -> (info, timestamp)
        self._token_info_cache_ttl = 300  # 5분
    
    async def _get_fx_cached(self, session: aiohttp.ClientSession) -> tuple[float, str]:
        """FX 환율 캐시 조회."""
        now = time.time()
        if self._fx_cache and now - self._fx_cache[2] < self._fx_cache_ttl:
            return self._fx_cache[0], self._fx_cache[1]
        
        rate, source = await self._premium.get_implied_fx(session)
        self._fx_cache = (rate, source, now)
        return rate, source
    
    async def _get_vwap_cached(
        self, symbol: str, session: aiohttp.ClientSession
    ):
        """VWAP 캐시 조회 (30초)."""
        cache_key = f"vwap:{symbol}"
        now = time.time()
        
        if cache_key in self._token_info_cache:
            cached, ts = self._token_info_cache[cache_key]
            if now - ts < 30:
                return cached
        
        result = await self._premium.get_global_vwap(symbol, session)
        self._token_info_cache[cache_key] = (result, now)
        return result
```

#### 6.3 Connection Pool 미활용 (-0점, 이미 양호)
`aiohttp.ClientSession`을 함수 내에서 생성 → 재사용 권장

**개선 코드** (선택):
```python
class GateChecker:
    def __init__(self, ...):
        self._session: aiohttp.ClientSession | None = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """공유 세션 반환 (Connection Pool 재사용)."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=100,           # 최대 동시 연결
                limit_per_host=30,   # 호스트당 최대 연결
                ttl_dns_cache=300,   # DNS 캐시 5분
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session
    
    async def close(self) -> None:
        """세션 정리."""
        if self._session and not self._session.closed:
            await self._session.close()
```

### 10점 달성 체크리스트
- [ ] asyncio.gather로 독립 API 호출 병렬화
- [ ] FX 환율 캐시 (30초)
- [ ] VWAP 캐시 (30초)
- [ ] 공유 ClientSession (Connection Pool)
- [ ] 선물 마켓 목록 캐시 (1시간)

---

## 7. 추가 개선 사항

### 7.1 타입 힌트 강화
```python
# 현재
def _check_vasp(self, from_exchange: str, to_exchange: str) -> str:

# 개선: Literal 사용
from typing import Literal

VASPStatus = Literal["ok", "partial", "blocked", "unknown"]

def _check_vasp(self, from_exchange: str, to_exchange: str) -> VASPStatus:
```

### 7.2 설정 검증
```python
def _load_networks(self) -> dict:
    """Networks YAML 로드 + 검증."""
    path = self._config_dir / "networks.yaml"
    if not path.exists():
        logger.warning("networks.yaml 미발견 — 기본값 사용")
        return self._get_default_networks()
    
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    
    # 필수 필드 검증
    networks = config.get("networks", {})
    required_networks = ["ethereum", "solana", "bsc"]
    for net in required_networks:
        if net not in networks:
            logger.warning("networks.yaml에 %s 없음 — 기본값 추가", net)
            networks[net] = self._get_default_network_config(net)
    
    return {"networks": networks}

def _get_default_networks(self) -> dict:
    return {
        "networks": {
            "ethereum": {"avg_transfer_min": 5.0, "gas_warn_gwei": 50},
            "solana": {"avg_transfer_min": 0.5},
            "bsc": {"avg_transfer_min": 1.0},
            "arbitrum": {"avg_transfer_min": 1.0},
            "base": {"avg_transfer_min": 1.0},
        }
    }
```

### 7.3 단위 테스트 용이성
```python
# 의존성 주입으로 테스트 용이하게
class GateChecker:
    def __init__(
        self,
        premium: PremiumCalculator,
        cost_model: CostModel,
        writer: DatabaseWriter,
        # 테스트용 주입 가능
        futures_checker: FuturesChecker | None = None,
        network_selector: NetworkSelector | None = None,
    ):
        self._futures_checker = futures_checker or DefaultFuturesChecker()
        self._network_selector = network_selector or DefaultNetworkSelector()
```

---

## 8. 구현 우선순위

### 즉시 (1-2일)
| 작업 | 영향 점수 | 난이도 |
|------|----------|--------|
| 병렬 API 호출 (asyncio.gather) | +2 | 낮음 |
| 선물 마켓 캐싱 | +1 | 낮음 |
| LRU 캐시 구현 | +0.5 | 낮음 |

### 단기 (1주)
| 작업 | 영향 점수 | 난이도 |
|------|----------|--------|
| 재시도 데코레이터 | +0.5 | 중간 |
| API 메트릭 수집 | +0.5 | 중간 |
| Hyperliquid DEX 선물 | +1 | 중간 |

### 중기 (2주)
| 작업 | 영향 점수 | 난이도 |
|------|----------|--------|
| 네트워크 혼잡도 실시간 반영 | +1 | 높음 |
| 공유 ClientSession | +0 | 낮음 |
| 분산 캐시 (Redis) | +0.5 | 높음 |

---

## 체크리스트 요약

```
[ ] 성능: asyncio.gather 병렬화
[ ] 성능: FX/VWAP 캐시 (30초)
[ ] 성능: 선물 마켓 캐시 (1시간)
[ ] 중복방지: LRU 캐시 (maxsize + TTL + cleanup)
[ ] hedge: Binance/Bybit 목록 캐싱
[ ] hedge: Hyperliquid DEX 선물 지원
[ ] 네트워크: 실시간 혼잡도 반영
[ ] 에러: 재시도 데코레이터
[ ] 에러: API 메트릭 수집
[ ] 에러: health.json 메트릭 포함
```

---

*작성 완료: 감비 🥔*  
*2026-01-29 23:00 KST*
