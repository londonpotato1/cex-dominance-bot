# 다중 환율 소스 개발 계획서

> 작성일: 2026-02-01
> 예상 개발 기간: 1-2일

---

## 1. 개요

### 1.1 현재 문제점

```python
# 현재 구현 (exchange_service.py)
def _get_krw_rate(self, exchange: str) -> Optional[float]:
    # 업비트/빗썸 USDT/KRW 직접 조회
    # 실패 시 → Fallback 1450원 (하드코딩)
```

**문제점:**
1. 단일 소스 의존 → 장애 시 부정확
2. Fallback 1450원 → 실제 환율과 괴리
3. 거래소별 환율 차이 미반영
4. 정프(USDT 프리미엄) 미고려

### 1.2 목표

- **정확도**: 실제 환율 ±0.1% 이내
- **신뢰도**: 다중 소스로 검증
- **가용성**: 하나 실패해도 대안 확보
- **투명성**: 사용된 소스와 신뢰도 표시

---

## 2. 환율 소스 분석

### 2.1 직접 조회 소스 (Tier 1)

| 소스 | 방법 | 장점 | 단점 | 신뢰도 |
|------|------|------|------|--------|
| **업비트 USDT/KRW** | API | 실시간, 정확 | 업비트 장애 시 불가 | ⭐⭐⭐⭐⭐ |
| **빗썸 USDT/KRW** | API | 실시간, 정확 | 빗썸 장애 시 불가 | ⭐⭐⭐⭐⭐ |

```python
# 현재 구현됨
ticker = exchange.fetch_ticker('USDT/KRW')
rate = ticker['last']  # 예: 1465.5
```

### 2.2 암시적 환율 (Tier 2)

**개념**: 동일 자산의 KRW/USD 가격 비교로 역산

| 자산 | 계산 | 장점 | 단점 | 신뢰도 |
|------|------|------|------|--------|
| **BTC Implied** | 업비트BTC(KRW) ÷ 바이낸스BTC(USD) | 유동성 최고 | 김프 포함됨 | ⭐⭐⭐⭐ |
| **ETH Implied** | 업비트ETH(KRW) ÷ 바이낸스ETH(USD) | 유동성 높음 | 김프 포함됨 | ⭐⭐⭐⭐ |
| **XRP Implied** | 업비트XRP(KRW) ÷ 바이낸스XRP(USD) | 대안 | 변동성 높음 | ⭐⭐⭐ |

```python
def get_btc_implied_rate():
    """BTC 암시적 환율 계산"""
    upbit_btc_krw = upbit.fetch_ticker('BTC/KRW')['last']
    binance_btc_usd = binance.fetch_ticker('BTC/USDT')['last']
    
    implied_rate = upbit_btc_krw / binance_btc_usd
    # 예: 150,000,000 / 100,000 = 1500 KRW/USD
    
    return implied_rate
```

**주의**: 암시적 환율에는 **김프가 포함**되어 있음
- 실제 환율: 1450원
- 김프 3%: 암시적 환율 1493.5원
- 따라서 김프 계산 시 암시적 환율 사용하면 안 됨!

### 2.3 외부 API (Tier 3)

| 소스 | API | 장점 | 단점 | 신뢰도 |
|------|-----|------|------|--------|
| **ExchangeRate-API** | 무료 | 안정적 | 실시간 아님, Rate Limit | ⭐⭐⭐ |
| **Open Exchange Rates** | 무료/유료 | 정확 | API 키 필요 | ⭐⭐⭐ |
| **한국은행** | 공공데이터 | 공식 | 실시간 아님 | ⭐⭐ |

```python
async def get_external_fx_rate():
    """외부 API로 USD/KRW 조회"""
    url = "https://api.exchangerate-api.com/v4/latest/USD"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            return data['rates']['KRW']  # 예: 1445.23
```

---

## 3. 기술 설계

### 3.1 데이터 구조

```python
@dataclass
class FxRate:
    """환율 정보"""
    rate: float                 # 환율 (KRW per USD)
    source: str                 # 소스명
    source_type: str            # "direct" | "implied" | "external"
    confidence: float           # 신뢰도 (0-1)
    timestamp: datetime
    raw_data: dict              # 원본 데이터

    @property
    def confidence_label(self) -> str:
        if self.confidence >= 0.95:
            return "EXCELLENT"
        elif self.confidence >= 0.85:
            return "GOOD"
        elif self.confidence >= 0.70:
            return "FAIR"
        else:
            return "POOR"


@dataclass
class FxRateResult:
    """환율 조회 결과 (다중 소스 통합)"""
    best_rate: float            # 최적 환율
    best_source: str            # 최적 소스
    confidence: float           # 종합 신뢰도
    
    all_rates: list[FxRate]     # 모든 소스 결과
    spread: float               # 소스 간 스프레드 (%)
    
    # 암시적 환율 (참고용)
    btc_implied: Optional[float]
    eth_implied: Optional[float]
    implied_premium: float      # 정프 (%)
    
    timestamp: datetime
    
    @property
    def is_reliable(self) -> bool:
        """신뢰 가능 여부"""
        return self.confidence >= 0.85 and self.spread < 1.0
```

### 3.2 환율 조회 로직

```python
class FxRateService:
    """다중 소스 환율 서비스"""
    
    # 캐시 설정
    CACHE_TTL = 30  # 30초
    
    # 가중치 설정
    SOURCE_WEIGHTS = {
        'upbit_direct': 1.0,
        'bithumb_direct': 0.95,
        'btc_implied': 0.7,    # 김프 포함 가능성
        'eth_implied': 0.65,
        'external_api': 0.5,
    }
    
    async def get_best_rate(self) -> FxRateResult:
        """최적 환율 조회 (다중 소스 통합)"""
        
        # 1. 모든 소스 병렬 조회
        tasks = [
            self._get_upbit_direct(),
            self._get_bithumb_direct(),
            self._get_btc_implied(),
            self._get_eth_implied(),
            self._get_external_api(),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 2. 유효한 결과만 필터링
        valid_rates = [r for r in results if isinstance(r, FxRate)]
        
        if not valid_rates:
            # Fallback
            return self._get_fallback_rate()
        
        # 3. 가중 평균 계산
        weighted_sum = 0
        weight_sum = 0
        
        for rate in valid_rates:
            weight = self.SOURCE_WEIGHTS.get(rate.source, 0.5)
            adjusted_weight = weight * rate.confidence
            weighted_sum += rate.rate * adjusted_weight
            weight_sum += adjusted_weight
        
        best_rate = weighted_sum / weight_sum
        
        # 4. 스프레드 계산 (직접 소스만)
        direct_rates = [r.rate for r in valid_rates if r.source_type == 'direct']
        if len(direct_rates) >= 2:
            spread = (max(direct_rates) - min(direct_rates)) / min(direct_rates) * 100
        else:
            spread = 0
        
        # 5. 신뢰도 계산
        direct_count = sum(1 for r in valid_rates if r.source_type == 'direct')
        confidence = min(1.0, 0.5 + direct_count * 0.25)
        
        # 6. 암시적 환율 (정프 계산용)
        btc_implied = next((r.rate for r in valid_rates if 'btc' in r.source), None)
        eth_implied = next((r.rate for r in valid_rates if 'eth' in r.source), None)
        
        implied_premium = 0
        if btc_implied and best_rate:
            implied_premium = (btc_implied - best_rate) / best_rate * 100
        
        return FxRateResult(
            best_rate=best_rate,
            best_source=valid_rates[0].source,  # 가장 신뢰도 높은 것
            confidence=confidence,
            all_rates=valid_rates,
            spread=spread,
            btc_implied=btc_implied,
            eth_implied=eth_implied,
            implied_premium=implied_premium,
            timestamp=datetime.now(),
        )
    
    async def _get_upbit_direct(self) -> FxRate:
        """업비트 직접 조회"""
        try:
            ticker = self.upbit.fetch_ticker('USDT/KRW')
            return FxRate(
                rate=ticker['last'],
                source='upbit_direct',
                source_type='direct',
                confidence=1.0,
                timestamp=datetime.now(),
                raw_data=ticker,
            )
        except Exception as e:
            raise e
    
    async def _get_btc_implied(self) -> FxRate:
        """BTC 암시적 환율"""
        try:
            upbit_btc = self.upbit.fetch_ticker('BTC/KRW')['last']
            binance_btc = self.binance.fetch_ticker('BTC/USDT')['last']
            
            rate = upbit_btc / binance_btc
            
            return FxRate(
                rate=rate,
                source='btc_implied',
                source_type='implied',
                confidence=0.8,  # 김프 포함 가능성으로 낮춤
                timestamp=datetime.now(),
                raw_data={'upbit_btc': upbit_btc, 'binance_btc': binance_btc},
            )
        except Exception as e:
            raise e
```

### 3.3 정프(USDT 프리미엄) 계산

```python
def calculate_usdt_premium(fx_result: FxRateResult) -> float:
    """정프 계산
    
    정프 = (암시적 환율 - 직접 환율) / 직접 환율 * 100
    
    예: 
    - 직접 환율: 1450원
    - BTC 암시적: 1493.5원
    - 정프: (1493.5 - 1450) / 1450 * 100 = 3%
    
    의미: 현재 한국 시장에 3% 김프가 있음
    """
    return fx_result.implied_premium
```

---

## 4. 통합 계획

### 4.1 exchange_service.py 수정

```python
# Before
def _get_krw_rate(self, exchange: str) -> Optional[float]:
    # 단일 소스 조회
    ...
    return self._krw_rates.get(exchange)  # Fallback 없음

# After
async def _get_krw_rate(self, exchange: str) -> tuple[float, str, float]:
    """
    Returns:
        (환율, 소스, 신뢰도)
    """
    fx_service = FxRateService()
    result = await fx_service.get_best_rate()
    
    return (result.best_rate, result.best_source, result.confidence)
```

### 4.2 UI 표시

```python
# 현재: 환율만 표시
# 개선: 환율 + 소스 + 신뢰도 표시

"""
💱 환율: ₩1,465.5
├── 소스: 업비트 (직접)
├── 신뢰도: ⭐⭐⭐⭐⭐ EXCELLENT
├── 스프레드: 0.02%
└── 정프: +2.8%
"""
```

---

## 5. 구현 단계

### Phase 1: 기본 구조 (Day 1 AM)
- [ ] `FxRate`, `FxRateResult` 데이터 클래스
- [ ] `FxRateService` 기본 구조
- [ ] 업비트/빗썸 직접 조회

### Phase 2: 다중 소스 (Day 1 PM)
- [ ] BTC/ETH 암시적 환율
- [ ] 외부 API 연동
- [ ] 가중 평균 계산

### Phase 3: 통합 (Day 2 AM)
- [ ] `exchange_service.py` 수정
- [ ] 캐싱 로직
- [ ] 에러 처리

### Phase 4: UI (Day 2 PM)
- [ ] 환율 정보 표시 개선
- [ ] 정프 표시
- [ ] 신뢰도 배지

---

## 6. API 설계

### 6.1 파일 구조

```
collectors/
└── fx_rate.py          # NEW: 환율 서비스
    ├── FxRate          # 단일 환율 데이터
    ├── FxRateResult    # 통합 결과
    ├── FxRateService   # 메인 서비스
    └── get_best_rate() # 헬퍼 함수
```

### 6.2 사용 예시

```python
from collectors.fx_rate import get_best_rate

# 간단한 사용
rate, source, confidence = await get_best_rate()
print(f"환율: {rate}, 소스: {source}, 신뢰도: {confidence}")

# 상세 정보
result = await FxRateService().get_best_rate()
print(f"정프: {result.implied_premium}%")
```

---

## 7. 테스트 계획

### 7.1 단위 테스트

```python
async def test_upbit_direct():
    rate = await fx_service._get_upbit_direct()
    assert 1300 < rate.rate < 1600  # 합리적 범위
    assert rate.confidence == 1.0

async def test_fallback():
    # 모든 소스 실패 시
    result = await fx_service.get_best_rate()
    assert result.best_rate == 1450  # Fallback
    assert result.confidence < 0.5
```

### 7.2 통합 테스트

```python
async def test_full_flow():
    result = await get_best_rate()
    assert result.is_reliable
    assert result.spread < 0.5  # 소스 간 차이 0.5% 미만
```

---

## 8. 예상 효과

| 지표 | Before | After |
|------|--------|-------|
| 환율 정확도 | ±2% | ±0.1% |
| 장애 대응 | 단일 소스 | 5개 소스 |
| 신뢰도 표시 | ❌ | ✅ |
| 정프 표시 | ❌ | ✅ |
| 환율 갱신 | 30초 | 30초 (동일) |

---

## 9. 부록: 환율 참고 사이트

- **업비트**: https://upbit.com/exchange?code=CRIX.UPBIT.KRW-USDT
- **빗썸**: https://www.bithumb.com/trade/order/USDT_KRW
- **ExchangeRate-API**: https://www.exchangerate-api.com/
- **한국은행**: https://www.bok.or.kr/portal/main/contents.do?menuNo=200091

---

*본 문서는 다중 환율 소스 개발 계획을 정리한 것입니다.*
