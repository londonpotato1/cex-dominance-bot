# Phase 6 로드맵: 거래소 확장 & 아비트라지

> 작성일: 2026-02-01
> 예상 기간: 1-2주

---

## 📊 Phase 5 완료 현황

| 기능 | 상태 | 파일 |
|------|------|------|
| 오더북 기반 프리미엄 | ✅ | `exchange_service.py`, `gap_calculator.py` |
| DEX 심볼 자동 보정 | ✅ | `dex_liquidity.py` |
| 입금 가능 여부 확인 | ✅ | `deposit_status.py` |

---

## 🎯 Phase 6 목표

### 6.1 다중 거래소 확장

**현재 상태:**
- 현물: 업비트, 빗썸, 바이낸스, 바이비트
- 선물: 바이낸스, 바이비트, OKX, Gate, Bitget (일부)

**추가할 거래소:**

| 거래소 | 우선순위 | 이유 | API 복잡도 |
|--------|----------|------|-----------|
| **OKX** | 🔴 높음 | 한국 사용자 많음, 유동성 풍부 | 중간 |
| **Gate.io** | 🟡 중간 | 신규 코인 빠른 상장, 핫월렛 적음 | 낮음 |
| **Bitget** | 🟡 중간 | 카피트레이딩으로 유명, 핫월렛 적음 | 낮음 |
| **MEXC** | 🟢 낮음 | 초기 상장 많음 | 낮음 |
| **KuCoin** | 🟢 낮음 | 대형 거래소 | 중간 |

**구현 계획:**
```python
# exchange_service.py 확장
EXCHANGE_CONFIG = {
    'okx': {
        'spot_class': 'okx',
        'futures_class': 'okx',
        'spot_suffix': '/USDT',
        'futures_suffix': '/USDT:USDT',
    },
    # ... Gate, Bitget 이미 정의됨
}
```

**예상 작업량:** 2-3일

---

### 6.2 Spot-Spot 아비트라지

**개념:**
해외 거래소 A → 해외 거래소 B 간 가격 차이 포착

**사용 케이스:**
1. Binance에서 매수 → Bybit으로 전송 → Bybit에서 매도
2. 신규 상장 시 거래소별 가격 괴리 활용
3. 유동성 차이로 인한 일시적 프리미엄

**구현 계획:**

```python
@dataclass
class SpotSpotGapResult:
    """Spot-Spot 아비트라지 결과"""
    buy_exchange: str       # 매수 거래소
    sell_exchange: str      # 매도 거래소
    symbol: str
    buy_price: float
    sell_price: float
    premium_percent: float
    # 비용 정보
    withdraw_fee: float     # 출금 수수료
    network: str            # 전송 네트워크
    transfer_time: str      # 예상 전송 시간
    # 순익
    net_premium: float      # 수수료 차감 후 프리미엄
    estimated_pnl: float    # 예상 손익
```

**UI 표시:**
```
🔄 Spot-Spot 아비트라지
Binance → Bybit (ETH)
├── 프리미엄: +0.15%
├── 출금 수수료: 0.001 ETH (~$3)
├── 전송 시간: ~5분
└── 순익 (10K): $12.00
```

**예상 작업량:** 3-4일

---

### 6.3 다중 환율 소스

**현재 문제:**
- USDT/KRW 환율이 Fallback 1450원 사용 시 부정확
- 거래소별 환율 차이 미반영

**개선 방안:**

| 소스 | 방법 | 신뢰도 |
|------|------|--------|
| **업비트 USDT/KRW** | 직접 API | ⭐⭐⭐⭐⭐ |
| **빗썸 USDT/KRW** | 직접 API | ⭐⭐⭐⭐⭐ |
| **BTC Implied** | BTC 가격 역산 | ⭐⭐⭐⭐ |
| **ETH Implied** | ETH 가격 역산 | ⭐⭐⭐⭐ |
| **외부 API** | ExchangeRate-API | ⭐⭐⭐ |

**구현 계획:**
```python
async def get_best_krw_rate() -> tuple[float, str]:
    """최적 KRW 환율 조회.
    
    Returns:
        (환율, 소스명)
    """
    # 1. 업비트/빗썸 직접 조회
    # 2. BTC implied 계산
    # 3. Fallback
```

**예상 작업량:** 1-2일

---

## 🗓️ 구현 일정

| 주차 | 작업 | 담당 |
|------|------|------|
| Week 1 (Day 1-3) | 다중 거래소 확장 (OKX, Gate 우선) | - |
| Week 1 (Day 4-5) | Spot-Spot 아비트라지 기본 구현 | - |
| Week 2 (Day 1-2) | 다중 환율 소스 | - |
| Week 2 (Day 3-5) | UI 통합 & 테스트 | - |

---

## 📁 파일 구조 (예정)

```
collectors/
├── exchange_service.py     # 거래소 API (확장)
├── gap_calculator.py       # 갭 계산 (Spot-Spot 추가)
├── deposit_status.py       # 입출금 상태 ✅
├── fx_rate.py              # 환율 서비스 (NEW)
└── spot_spot_arb.py        # Spot-Spot 아비트라지 (NEW)
```

---

## 🔧 API 엔드포인트 정리

### OKX
```
현물 가격: GET /api/v5/market/ticker?instId=BTC-USDT
오더북: GET /api/v5/market/books?instId=BTC-USDT
입출금: GET /api/v5/asset/currencies (인증 필요)
```

### Gate.io
```
현물 가격: GET /api/v4/spot/tickers
오더북: GET /api/v4/spot/order_book?currency_pair=BTC_USDT
입출금: GET /api/v4/spot/currencies/{currency} ✅ (Public)
```

### Bitget
```
현물 가격: GET /api/v2/spot/market/tickers
오더북: GET /api/v2/spot/market/orderbook
입출금: GET /api/v2/spot/public/coins ✅ (Public)
```

---

## ⚠️ 주의사항

### Rate Limit
| 거래소 | 제한 | 권장 |
|--------|------|------|
| OKX | 20 req/2s | 0.5초 간격 |
| Gate | 900 req/min | 정상 사용 OK |
| Bitget | 20 req/s | 정상 사용 OK |

### 비용
- 모든 API 무료 (Public)
- 인증 필요 기능은 선택적 구현

---

## 📈 예상 효과

1. **거래소 커버리지**: 4개 → 7개+ (75% 증가)
2. **아비트라지 기회**: 해외↔한국 + 해외↔해외
3. **환율 정확도**: Fallback 의존도 감소
4. **GO/NO-GO 정확도**: 다중 소스로 신뢰도 향상

---

## 🚀 다음 단계 (Phase 7 예고)

- 입금량 실시간 추적 (핫월렛 모니터링)
- 손바뀜 비율 계산
- 후따리 알림 시스템

---

*본 문서는 Phase 6 개발 계획을 정리한 것입니다.*
