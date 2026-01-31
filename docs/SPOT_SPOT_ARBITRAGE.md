# Spot-Spot 아비트라지 개발 계획서

> 작성일: 2026-02-01
> 예상 개발 기간: 3-4일

---

## 1. 개요

### 1.1 정의
**Spot-Spot 아비트라지**: 해외 거래소 A에서 매수 → 해외 거래소 B로 전송 → 거래소 B에서 매도

### 1.2 기존 기능과의 차이

| 구분 | 현재 구현 | Spot-Spot |
|------|----------|-----------|
| 경로 | 해외 → 국내 | 해외 → 해외 |
| 목적 | 김프 차익 | 거래소 간 가격 괴리 |
| 제약 | KRW 환전 필요 | USDT로 완결 |
| 속도 | 입금 후 매도 | 전송 속도 의존 |

### 1.3 사용 케이스

1. **신규 상장 괴리**: Binance 상장 후 Bybit 미상장 → 가격 차이
2. **유동성 차이**: 소형 거래소 유동성 부족 → 일시적 프리미엄
3. **펀딩비 차익**: 현물 보유 + 선물 숏 포지션 이동
4. **지역별 가격 차이**: 특정 시간대 거래소별 수급 차이

---

## 2. 기술 설계

### 2.1 데이터 구조

```python
@dataclass
class SpotSpotOpportunity:
    """Spot-Spot 아비트라지 기회"""
    # 기본 정보
    symbol: str
    buy_exchange: str           # 매수 거래소
    sell_exchange: str          # 매도 거래소
    
    # 가격 정보
    buy_price: float            # 매수가 (Ask)
    sell_price: float           # 매도가 (Bid)
    premium_percent: float      # 프리미엄 (%)
    
    # 비용 정보
    withdraw_fee: float         # 출금 수수료 (코인 단위)
    withdraw_fee_usd: float     # 출금 수수료 (USD)
    trading_fee_buy: float      # 매수 수수료 (%)
    trading_fee_sell: float     # 매도 수수료 (%)
    total_fee_percent: float    # 총 수수료 (%)
    
    # 전송 정보
    network: str                # 전송 네트워크
    transfer_time: str          # 예상 전송 시간
    confirmations: int          # 필요 컨펌 수
    
    # 손익 계산
    net_premium: float          # 순 프리미엄 (수수료 차감)
    estimated_pnl_usd: float    # 예상 손익 (USD)
    min_amount_usd: float       # 최소 수익 발생 금액
    
    # 리스크
    risk_level: str             # LOW / MEDIUM / HIGH
    risk_factors: list[str]     # 리스크 요인 목록
    
    timestamp: float


@dataclass
class NetworkTransferInfo:
    """네트워크 전송 정보"""
    network: str                # ETH, BSC, SOL 등
    chain_id: str
    avg_time_seconds: int       # 평균 전송 시간
    confirmations: int          # 필요 컨펌 수
    congestion_level: str       # LOW / MEDIUM / HIGH
    gas_price_gwei: float       # 현재 가스비 (EVM)
```

### 2.2 핵심 계산 로직

```python
def calculate_spot_spot_opportunity(
    symbol: str,
    buy_exchange: str,
    sell_exchange: str,
    buy_orderbook: OrderbookData,
    sell_orderbook: OrderbookData,
    amount_usd: float = 10000,
    network: str = None
) -> Optional[SpotSpotOpportunity]:
    """
    Spot-Spot 기회 계산
    
    1. 매수가: buy_orderbook의 Ask 가중평균 (amount_usd 기준)
    2. 매도가: sell_orderbook의 Bid 가중평균
    3. 수수료: 거래 수수료 + 출금 수수료
    4. 순익: (매도가 - 매수가) - 총 수수료
    """
    
    # 1. 가격 계산
    buy_price = buy_orderbook.get_executable_buy_price(amount_usd)
    sell_price = sell_orderbook.get_executable_sell_price(amount_usd)
    
    if not buy_price or not sell_price:
        return None
    
    # 2. 프리미엄 계산
    premium_percent = (sell_price - buy_price) / buy_price * 100
    
    # 3. 수수료 계산
    trading_fee_buy = EXCHANGE_FEES[buy_exchange]['taker']   # 0.1%
    trading_fee_sell = EXCHANGE_FEES[sell_exchange]['taker'] # 0.1%
    
    withdraw_info = get_withdraw_fee(buy_exchange, symbol, network)
    withdraw_fee = withdraw_info['fee']
    withdraw_fee_usd = withdraw_fee * buy_price
    withdraw_fee_percent = (withdraw_fee_usd / amount_usd) * 100
    
    total_fee_percent = trading_fee_buy + trading_fee_sell + withdraw_fee_percent
    
    # 4. 순 프리미엄
    net_premium = premium_percent - total_fee_percent
    
    # 5. 예상 손익
    estimated_pnl_usd = amount_usd * (net_premium / 100)
    
    # 6. 최소 수익 발생 금액 (수수료 > 프리미엄이 되는 지점)
    if premium_percent > 0:
        min_amount = withdraw_fee_usd / (premium_percent / 100 - trading_fee_buy - trading_fee_sell)
        min_amount = max(0, min_amount)
    else:
        min_amount = float('inf')
    
    # 7. 리스크 평가
    risk_level, risk_factors = assess_risk(
        premium_percent, net_premium, network, transfer_time
    )
    
    return SpotSpotOpportunity(...)
```

### 2.3 거래소 수수료 데이터베이스

```python
EXCHANGE_FEES = {
    'binance': {
        'maker': 0.10,      # 0.1%
        'taker': 0.10,
        'withdraw': {
            'BTC': {'BTC': 0.0001, 'Lightning': 0},
            'ETH': {'ETH': 0.001, 'Arbitrum': 0.0001},
            'USDT': {'TRC20': 1, 'ERC20': 15, 'BSC': 0.3},
        }
    },
    'bybit': {
        'maker': 0.10,
        'taker': 0.10,
        'withdraw': {...}
    },
    'okx': {
        'maker': 0.08,
        'taker': 0.10,
        'withdraw': {...}
    },
    # ... Gate, Bitget, MEXC, KuCoin
}
```

### 2.4 네트워크 선택 로직

```python
def select_best_network(
    symbol: str,
    from_exchange: str,
    to_exchange: str
) -> NetworkTransferInfo:
    """
    최적 전송 네트워크 선택
    
    우선순위:
    1. 양쪽 모두 지원하는 네트워크
    2. 수수료 최소
    3. 속도 최적
    """
    from_networks = get_supported_networks(from_exchange, symbol)
    to_networks = get_supported_networks(to_exchange, symbol)
    
    common = set(from_networks) & set(to_networks)
    
    if not common:
        return None  # 직접 전송 불가
    
    # 수수료 + 속도 기준 정렬
    scored = []
    for net in common:
        fee = get_withdraw_fee(from_exchange, symbol, net)
        time = get_transfer_time(net)
        score = fee * 0.7 + time * 0.3  # 수수료 70%, 속도 30%
        scored.append((net, score))
    
    best = min(scored, key=lambda x: x[1])
    return get_network_info(best[0])
```

---

## 3. API 설계

### 3.1 내부 API

```python
# collectors/spot_spot_arb.py

async def scan_all_opportunities(
    symbols: list[str] = None,
    min_premium: float = 0.1,
    amount_usd: float = 10000
) -> list[SpotSpotOpportunity]:
    """전체 Spot-Spot 기회 스캔"""

async def get_opportunity(
    symbol: str,
    buy_exchange: str,
    sell_exchange: str,
    amount_usd: float = 10000
) -> Optional[SpotSpotOpportunity]:
    """특정 경로 기회 조회"""

def get_best_opportunities(
    opportunities: list[SpotSpotOpportunity],
    min_net_premium: float = 0.05,
    max_risk: str = "MEDIUM",
    limit: int = 10
) -> list[SpotSpotOpportunity]:
    """최적 기회 필터링"""
```

### 3.2 UI 엔드포인트

```python
# 빠른 분석에 통합
results["spot_spot"] = await scan_symbol_opportunities(symbol)

# 별도 탭 (선택적)
def render_spot_spot_tab():
    """Spot-Spot 아비트라지 전용 탭"""
```

---

## 4. UI 설계

### 4.1 빠른 분석 통합

```
┌─────────────────────────────────────────────────┐
│ 🔍 빠른 분석: BTC                                │
├─────────────────────────────────────────────────┤
│ [현선갭] [DEX] [네트워크]                         │
│ [오더북프리미엄] [입출금]                          │
├─────────────────────────────────────────────────┤
│ 🔄 Spot-Spot 기회                    ← NEW!     │
│ ┌─────────────────────────────────────────────┐ │
│ │ Binance → Bybit     +0.15%                 │ │
│ │ 수수료: 0.08%  순익: +0.07%  예상: +$7     │ │
│ │ 네트워크: Arbitrum (~5분)                   │ │
│ ├─────────────────────────────────────────────┤ │
│ │ OKX → Gate          +0.12%                 │ │
│ │ 수수료: 0.05%  순익: +0.07%  예상: +$7     │ │
│ │ 네트워크: BSC (~3분)                        │ │
│ └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### 4.2 상세 뷰 (별도 탭)

```
┌─────────────────────────────────────────────────┐
│ 🔄 Spot-Spot 아비트라지 스캐너                    │
├─────────────────────────────────────────────────┤
│ 필터: [최소 순익 0.05%] [최대 리스크 MEDIUM]     │
├─────────────────────────────────────────────────┤
│ #  | 심볼 | 경로          | 순익  | 예상   | ⚠️  │
│ 1  | ETH  | Binance→Bybit | +0.12%| +$12  | 🟢  │
│ 2  | SOL  | OKX→Gate      | +0.08%| +$8   | 🟡  │
│ 3  | BTC  | Bybit→OKX     | +0.05%| +$5   | 🟢  │
└─────────────────────────────────────────────────┘
```

---

## 5. 구현 단계

### Phase 1: 기본 구조 (Day 1)
- [ ] `SpotSpotOpportunity` 데이터 클래스
- [ ] `EXCHANGE_FEES` 데이터베이스
- [ ] 기본 계산 로직

### Phase 2: API 통합 (Day 2)
- [ ] 오더북 조회 통합
- [ ] 네트워크 선택 로직
- [ ] 전체 스캔 함수

### Phase 3: UI 연동 (Day 3)
- [ ] 빠른 분석에 통합
- [ ] 결과 렌더링
- [ ] 필터 옵션

### Phase 4: 고도화 (Day 4)
- [ ] 실시간 모니터링
- [ ] 알림 시스템 연동
- [ ] 리스크 평가 고도화

---

## 6. 리스크 관리

### 6.1 리스크 요인

| 요인 | 설명 | 대응 |
|------|------|------|
| **가격 변동** | 전송 중 가격 변동 | 전송 시간 짧은 네트워크 선택 |
| **네트워크 지연** | 예상보다 느린 전송 | 혼잡도 모니터링 |
| **출금 제한** | 거래소 출금 중단 | 입출금 상태 확인 |
| **슬리피지** | 큰 물량 시 가격 변동 | 오더북 깊이 확인 |

### 6.2 리스크 레벨 정의

```python
def assess_risk(opportunity) -> tuple[str, list[str]]:
    factors = []
    
    # 순익 대비 리스크
    if opportunity.net_premium < 0.05:
        factors.append("순익 매우 낮음")
    
    # 전송 시간
    if opportunity.transfer_time_seconds > 600:
        factors.append("전송 시간 10분 초과")
    
    # 호가 깊이
    if opportunity.min_depth_usd < opportunity.amount_usd * 2:
        factors.append("호가 깊이 부족")
    
    # 레벨 결정
    if len(factors) >= 3:
        return "HIGH", factors
    elif len(factors) >= 1:
        return "MEDIUM", factors
    else:
        return "LOW", factors
```

---

## 7. 예상 효과

1. **새로운 수익 기회**: 김프 외 추가 아비트라지 경로
2. **USDT 순환**: KRW 환전 없이 수익 실현
3. **리스크 분산**: 국내 거래소 의존도 감소
4. **자동화 기반**: 실시간 기회 포착 가능

---

*다음 문서: [다중 환율 소스 개발 계획서](./FX_RATE_SOURCES.md)*
