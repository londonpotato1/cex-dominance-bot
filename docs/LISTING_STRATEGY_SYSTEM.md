# 상장 공지 자동 분석 & 전략 추천 시스템

> 작성일: 2026-02-01
> 요청자: 런던감자
> 예상 개발 기간: 5-7일

---

## 1. 개요

### 1.1 목표
상장 공지가 뜨면 자동으로 코인을 분석하고, 최적의 전략(헷지, 론, 익절 타이밍)을 추천하는 시스템

### 1.2 핵심 플로우

```
📢 상장 공지 감지
       ↓
   코인 분석 (자동)
       ↓
   전략 추천 (론, 헷지, 리스크)
       ↓
   실시간 현선갭 알림
```

---

## 2. 상세 기능

### 2.1 상장 공지 감지 (기존 구현 활용)

```python
# listing_monitor.py - 이미 구현됨
# 업비트/빗썸 마켓 목록 비교로 신규 상장 감지
```

### 2.2 코인 분석 (자동)

상장 공지 감지 시 자동으로 수집하는 데이터:

| 항목 | 소스 | 현재 구현 |
|------|------|----------|
| 토크노믹스 (초기물량, 언락) | CoinGecko, 프로젝트 문서 | ⚠️ 부분 |
| VC/MM 정보 | vc_mm_collector.py | ✅ |
| DEX 유동성 | DexScreener API | ✅ |
| 핫월렛 물량 | Alchemy RPC | ✅ |
| 네트워크 속도 | network_speed.py | ✅ |
| **현선갭** | 거래소 API | ✅ |
| **론 가능 여부** | 거래소 Margin API | ❌ NEW |

#### 출력 예시:
```
📊 [NEWCOIN] 따리 분석 결과

🎯 GO Score: 78/100

📈 토크노믹스:
   초기 유통량: 15%
   TGE 언락: 10%
   → 물량 적음 ✅

💰 유동성:
   DEX: $450K (적당)
   핫월렛: 12억원 (보통)

⚡ 네트워크: Ethereum (36컨펌, ~7분)
   → 후따리 난이도 보통

📊 현선갭: 1.2% (Binance)
   → 헷지 진입 추천! 🟢
```

### 2.3 전략 추천

#### A. 론(Loan) 가능 거래소 스캔

```python
@dataclass
class LoanInfo:
    exchange: str           # 거래소명
    available: bool         # 론 가능 여부
    max_amount: float       # 최대 대출량
    hourly_rate: float      # 시간당 이자율 (%)
    daily_rate: float       # 일일 이자율 (%)

async def scan_loan_availability(symbol: str) -> list[LoanInfo]:
    """상장 공지 시 론 가능한 거래소 스캔"""
    exchanges = ["binance", "bybit", "okx", "gate", "bitget"]
    results = []
    
    for exchange in exchanges:
        try:
            info = await check_margin_loan(exchange, symbol)
            if info.available:
                results.append(info)
        except:
            continue
    
    # 이자율 낮은 순 정렬
    return sorted(results, key=lambda x: x.hourly_rate)
```

#### 거래소별 Margin API:

| 거래소 | API 엔드포인트 | 비고 |
|--------|---------------|------|
| Binance | `GET /sapi/v1/margin/isolated/pair` | Cross/Isolated 둘 다 |
| Bybit | `GET /v5/asset/coin/query-info` | borrowable 필드 |
| OKX | `GET /api/v5/account/max-loan` | 인증 필요 |
| Gate | `GET /api/v4/margin/cross/currencies` | 공개 API |
| Bitget | `GET /api/margin/v1/cross/public/currencies` | 문서 제한적 |

#### 출력 예시:
```
💰 론 가능 거래소:

1. Binance Cross Margin
   최대: 10,000 NEWCOIN
   이자: 0.02%/h (0.48%/일)
   
2. Bybit Spot Margin  
   최대: 5,000 NEWCOIN
   이자: 0.025%/h (0.6%/일)

3. Gate Cross Margin
   최대: 8,000 NEWCOIN
   이자: 0.03%/h (0.72%/일)

→ Binance 론 추천 (이자 최저)
```

#### B. 현선갭 분석 & 헷지 추천

```python
@dataclass  
class GapAnalysis:
    exchange: str
    spot_price: float
    futures_price: float
    gap_percent: float
    recommendation: str
    risk_level: str  # LOW, MEDIUM, HIGH

async def analyze_spot_futures_gap(symbol: str) -> list[GapAnalysis]:
    """거래소별 현선갭 분석"""
    exchanges = ["binance", "bybit", "okx"]
    results = []
    
    for exchange in exchanges:
        spot = await get_spot_price(exchange, symbol)
        futures = await get_futures_price(exchange, symbol)
        
        gap = (futures - spot) / spot * 100
        
        # 리스크 레벨 & 추천
        if gap < 2:
            risk = "LOW"
            rec = "🟢 헷지 추천! 갭 낮음"
        elif gap < 4:
            risk = "MEDIUM"  
            rec = "🟡 헷지 가능, 비용 고려"
        else:
            risk = "HIGH"
            rec = "🔴 헷지 부담, 리스크 있음"
            
        results.append(GapAnalysis(
            exchange=exchange,
            spot_price=spot,
            futures_price=futures,
            gap_percent=gap,
            recommendation=rec,
            risk_level=risk
        ))
    
    return sorted(results, key=lambda x: x.gap_percent)
```

#### 출력 예시:
```
📈 현선갭 분석:

거래소     | 현물     | 선물     | 갭    | 추천
----------|----------|----------|-------|----------------
Binance   | $1.000   | $1.012   | 1.2%  | 🟢 헷지 추천!
Bybit     | $1.002   | $1.017   | 1.5%  | 🟢 헷지 추천!
OKX       | $0.998   | $1.038   | 4.0%  | 🔴 리스크 있음

💡 추천: Binance 현선 헷지 (갭 1.2% 최저)
```

#### C. 종합 전략 추천 (모든 요소 조합)

```python
@dataclass
class ComprehensiveStrategy:
    """모든 요소를 종합한 전략 추천"""
    go_score: int                    # 종합 점수 (0-100)
    strategy_type: str               # 전략 유형
    strategy_detail: str             # 상세 설명
    
    # 개별 분석 결과
    gap_analysis: GapAnalysis        # 현선갭 분석
    loan_info: list[LoanInfo]        # 론 가능 거래소
    dex_liquidity: float             # DEX 유동성 ($)
    hot_wallet: float                # 핫월렛 물량 (원)
    network_speed: str               # 네트워크 속도
    
    # 리스크/추천
    risk_level: str
    action_items: list[str]

async def get_comprehensive_strategy(symbol: str) -> ComprehensiveStrategy:
    """상장 공지 시 종합 전략 분석"""
    
    # 1. 모든 데이터 수집 (병렬)
    gap_result, loan_result, dex_result, wallet_result, network_result = await asyncio.gather(
        analyze_spot_futures_gap(symbol),
        scan_loan_availability(symbol),
        get_dex_liquidity(symbol),
        get_hot_wallet_balance(symbol),
        get_network_speed(symbol)
    )
    
    best_gap = min(gap_result, key=lambda x: x.gap_percent)
    best_loan = loan_result[0] if loan_result else None
    
    # 2. 종합 전략 결정
    strategy = determine_strategy(
        gap=best_gap.gap_percent,
        has_loan=bool(loan_result),
        dex_liquidity=dex_result,
        hot_wallet=wallet_result,
        network_speed=network_result
    )
    
    return strategy

def determine_strategy(gap, has_loan, dex_liquidity, hot_wallet, network_speed) -> dict:
    """
    모든 요소를 조합하여 최적 전략 결정
    
    조건 조합:
    - 갭 낮음(1-2%) + 론 가능 + 유동성 적음 → 헷지 갭익절 전략 🔥
    - 갭 낮음 + 론 불가 + 유동성 적음 → 현물만 선따리
    - 갭 높음(4%+) + 유동성 많음 → 후따리 대기
    - 역프 → 역따리 전략
    - 핫월렛 많음 + 네트워크 빠름 → 경쟁 치열, 리스크 ↑
    """
    
    actions = []
    
    # === 현선갭 기반 판단 ===
    if gap < 0:
        # 역프 상황
        return {
            "strategy_type": "🔄 역따리",
            "strategy_detail": "역프 발생! 국내 매수 + 해외 숏 전략",
            "risk_level": "MEDIUM",
            "actions": [
                "국내(업비트/빗썸) 현물 매수",
                "해외 선물 숏 헷지",
                "해외로 전송 후 청산"
            ]
        }
    
    elif gap < 2:
        # 갭 매우 낮음 - 헷지 최적 타이밍
        if has_loan:
            return {
                "strategy_type": "🎯 헷지 갭익절 전략",
                "strategy_detail": f"갭 {gap:.1f}% 매우 낮음! 론 가능! 헷지 잡고 갭 벌어지면 익절",
                "risk_level": "LOW",
                "actions": [
                    f"✅ 론 빌리기 (추천 거래소 확인)",
                    f"✅ 현물 매수 + 선물 숏 헷지 (갭 {gap:.1f}%)",
                    "✅ 국내 입금 대기",
                    "✅ 갭 벌어지면 단계별 익절 (5%/10%/20%/30%)"
                ]
            }
        else:
            return {
                "strategy_type": "📦 현물 선따리",
                "strategy_detail": f"갭 {gap:.1f}% 낮음! 론 불가 → 현물만 진행",
                "risk_level": "MEDIUM",
                "actions": [
                    "✅ 현물 매수 (헷지 없이)",
                    "✅ 국내 입금",
                    "⚠️ 가격 변동 리스크 있음"
                ]
            }
    
    elif gap < 4:
        # 갭 보통
        return {
            "strategy_type": "⚠️ 헷지 비용 고려",
            "strategy_detail": f"갭 {gap:.1f}% 보통, 헷지 비용이 수익 일부 차지",
            "risk_level": "MEDIUM",
            "actions": [
                f"🟡 헷지 시 비용 {gap:.1f}% 발생",
                "🟡 김프 예상치와 비교 필요",
                "🟡 물량 줄이거나 현물만 고려"
            ]
        }
    
    else:
        # 갭 높음 (4%+)
        if dex_liquidity > 500000:  # DEX 유동성 50만불 이상
            return {
                "strategy_type": "⏳ 후따리 대기",
                "strategy_detail": f"갭 {gap:.1f}% 높음 + DEX 유동성 충분 → 상장 후 후따리",
                "risk_level": "LOW",
                "actions": [
                    f"🔴 헷지 비용 {gap:.1f}% 너무 높음",
                    "✅ 상장 후 김프 확인",
                    "✅ 김프 유지되면 후따리 진입"
                ]
            }
        else:
            return {
                "strategy_type": "🚫 리스크 높음",
                "strategy_detail": f"갭 {gap:.1f}% 높음 + DEX 유동성 부족",
                "risk_level": "HIGH",
                "actions": [
                    f"🔴 헷지 비용 {gap:.1f}% 높음",
                    "🔴 후따리 유동성도 부족",
                    "⚠️ 패스 고려 또는 소량만"
                ]
            }

    # === 추가 리스크 요소 ===
    
    # 핫월렛 많으면 경쟁 치열
    if hot_wallet > 50_000_000_000:  # 500억 이상
        actions.append("⚠️ 핫월렛 물량 많음 - 입금 경쟁 치열 예상")
    
    # 네트워크 빠르면 후따리 쉬움 = 선따리 가치 ↓
    if network_speed == "very_fast":
        actions.append("⚠️ 네트워크 빠름 - 후따리 쉬움, 프리미엄 빨리 사라질 수 있음")
    
    return strategy
```

#### D. 리스크 시그널 (갭 기준)

```python
def get_gap_risk_signal(gap_percent: float) -> dict:
    """현선갭 기반 리스크 시그널"""
    
    if gap_percent < 2:
        return {
            "signal": "🟢 GO",
            "message": "갭 낮음! 헷지 진입 추천",
            "action": "현물 매수 + 선물 숏 헷지"
        }
    elif gap_percent < 4:
        return {
            "signal": "🟡 CAUTION",
            "message": "갭 보통, 헷지 비용 고려 필요",
            "action": "상황 봐서 판단"
        }
    else:
        return {
            "signal": "🔴 RISK",
            "message": f"갭 {gap_percent:.1f}% 높음! 리스크 있음",
            "action": "헷지 부담 큼, 후따리 or 현물만 고려"
        }
```

### 2.4 실시간 현선갭 알림

헷지 진입 후 갭 변화에 따른 익절 알림:

```python
class GapAlertMonitor:
    """현선갭 실시간 모니터링 & 알림"""
    
    def __init__(self, symbol: str, entry_gap: float):
        self.symbol = symbol
        self.entry_gap = entry_gap  # 진입 시 갭
        self.alert_levels = [5, 10, 15, 20, 25, 30]  # 알림 레벨
        self.alerted = set()  # 이미 알림 보낸 레벨
    
    async def check_and_alert(self):
        current_gap = await get_current_gap(self.symbol)
        
        for level in self.alert_levels:
            if current_gap >= level and level not in self.alerted:
                await self.send_alert(level, current_gap)
                self.alerted.add(level)
    
    async def send_alert(self, level: int, current_gap: float):
        profit = current_gap - self.entry_gap
        
        messages = {
            5: f"📊 현선갭 5% 돌파!\n진입: {self.entry_gap:.1f}% → 현재: {current_gap:.1f}%\n예상 수익: +{profit:.1f}%",
            10: f"📈 현선갭 10% 돌파!\n1/3 익절 고려\n예상 수익: +{profit:.1f}%",
            15: f"🔥 현선갭 15% 돌파!\n절반 익절 고려\n예상 수익: +{profit:.1f}%",
            20: f"💰 현선갭 20% 돌파!\n2/3 익절 강력 추천\n예상 수익: +{profit:.1f}%",
            25: f"🚀 현선갭 25% 돌파!\n대부분 익절 추천\n예상 수익: +{profit:.1f}%",
            30: f"🎯 현선갭 30%+ 돌파!\n전량 익절 강력 추천!\n예상 수익: +{profit:.1f}%"
        }
        
        await send_telegram_alert(messages[level])
```

#### 알림 예시:
```
🔔 [NEWCOIN] 현선갭 알림

📈 현선갭 10% 돌파!

진입 시: 1.2%
현재: 10.5%
예상 수익: +9.3%

💡 1/3 익절 고려 시점입니다.
   - 현물 1/3 매도
   - 선물 숏 1/3 청산
```

---

## 3. UI 설계

### 3.1 상장 알림 메시지 (텔레그램)

#### 예시 1: 갭 낮음 + 론 가능 (최적 상황)
```
🚀 [신규 상장 감지] NEWCOIN

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 종합 분석
━━━━━━━━━━━━━━━━━━━━━━━━━━━
GO Score: 85/100 🟢

📈 토크노믹스: 양호 (초기물량 15%)
💧 DEX 유동성: $450K (적당)
🔥 핫월렛: 12억 (보통)
⚡ 네트워크: ETH 36컨펌 (~7분)
👥 VC: Paradigm, a16z (Tier 1)

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 현선갭 현황
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Binance: 1.2% 🟢 최저!
Bybit:   1.5% 🟢
OKX:     4.0% 🔴

━━━━━━━━━━━━━━━━━━━━━━━━━━━
💰 론 가능 거래소
━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Binance (0.02%/h) ✅ 추천
2. Bybit (0.025%/h)
3. Gate (0.03%/h)

━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 전략 추천: 헷지 갭익절 전략
━━━━━━━━━━━━━━━━━━━━━━━━━━━
갭 1.2% 매우 낮음! 론 가능!
헷지 잡고 갭 벌어지면 익절 전략 GO 🔥

📋 액션 플랜:
1. ✅ Binance 론 빌리기 (0.02%/h)
2. ✅ Binance 현물 매수 + 선물 숏 (갭 1.2%)
3. ✅ 업비트/빗썸 입금 대기
4. ✅ 갭 벌어지면 단계별 익절
   • 5% → 모니터링
   • 10% → 1/3 익절 고려
   • 20% → 2/3 익절
   • 30%+ → 전량 익절

[📊 실시간 갭 모니터링 시작]
```

#### 예시 2: 갭 높음 + DEX 유동성 충분 (후따리)
```
🚀 [신규 상장 감지] ANOTHERCOIN

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 종합 분석
━━━━━━━━━━━━━━━━━━━━━━━━━━━
GO Score: 62/100 🟡

📈 토크노믹스: 보통 (초기물량 25%)
💧 DEX 유동성: $1.2M (충분)
🔥 핫월렛: 45억 (많음)
⚡ 네트워크: Solana (~30초)

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 현선갭 현황
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Binance: 5.2% 🔴
Bybit:   4.8% 🔴
OKX:     6.1% 🔴

━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 전략 추천: 후따리 대기
━━━━━━━━━━━━━━━━━━━━━━━━━━━
갭 5%+ 높음! 헷지 부담 큼

⚠️ 리스크 요소:
• 현선갭 5%+ → 헷지 비용 높음
• 핫월렛 많음 → 입금 경쟁 치열
• 솔라나 → 후따리 쉬움

📋 액션 플랜:
1. ⏳ 상장 후 김프 확인
2. ⏳ 김프 유지되면 후따리 진입
3. ⚠️ 선따리는 패스 권장

[대기 모드]
```

#### 예시 3: 역프 상황
```
🚀 [신규 상장 감지] REVERSECOIN

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 종합 분석
━━━━━━━━━━━━━━━━━━━━━━━━━━━
GO Score: 70/100 🟢

📈 프리미엄: -8.5% (역프!)
💧 DEX 유동성: $300K
🔥 핫월렛: 8억

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 현선갭 현황
━━━━━━━━━━━━━━━━━━━━━━━━━━━
역프 상황 - 국내 < 해외

━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 전략 추천: 역따리 전략
━━━━━━━━━━━━━━━━━━━━━━━━━━━
역프 -8.5% 발생! 역따리 기회 🔄

📋 액션 플랜:
1. ✅ 국내(업비트/빗썸) 현물 매수
2. ✅ 해외 선물 숏 헷지
3. ✅ 해외로 코인 전송
4. ✅ 해외 현물 매도 + 숏 청산
5. 💰 예상 수익: 역프% - 수수료

[역프 모니터링 시작]
```

### 3.2 대시보드 통합

```
┌─────────────────────────────────────────────┐
│ 🔥 실시간 탭                                 │
├─────────────────────────────────────────────┤
│ [기존 GO 카드들...]                          │
├─────────────────────────────────────────────┤
│ 📈 현선갭 모니터링 (NEW)                     │
│ ┌─────────────────────────────────────────┐ │
│ │ NEWCOIN                                 │ │
│ │ 진입: 1.2% → 현재: 8.5% (+7.3%)        │ │
│ │ [■■■■■■■□□□] 다음 알림: 10%            │ │
│ │ [익절 기록] [모니터링 중지]              │ │
│ └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## 4. 구현 계획

### Phase 1: 론 가능 거래소 스캔 (2일)
- [ ] Binance Margin API 연동
- [ ] Bybit Margin API 연동  
- [ ] OKX Margin API 연동
- [ ] Gate Margin API 연동
- [ ] 결과 통합 및 정렬

### Phase 2: 현선갭 분석 강화 (1일)
- [ ] 거래소별 현선갭 비교
- [ ] 리스크 시그널 로직
- [ ] 헷지 추천 로직

### Phase 3: 상장 공지 통합 (1일)
- [ ] 상장 감지 시 자동 분석 트리거
- [ ] 전략 추천 메시지 생성
- [ ] 텔레그램 알림 발송

### Phase 4: 실시간 갭 알림 (2일)
- [ ] GapAlertMonitor 클래스
- [ ] 백그라운드 모니터링
- [ ] 단계별 익절 알림
- [ ] 모니터링 시작/중지 UI

### Phase 5: UI 통합 (1일)
- [ ] 대시보드에 갭 모니터링 카드
- [ ] 알림 히스토리
- [ ] 수익 계산기

---

## 5. 데이터 구조

### 5.1 DB 스키마 추가

```sql
-- 론 정보 캐시
CREATE TABLE margin_loan_cache (
    id INTEGER PRIMARY KEY,
    symbol TEXT,
    exchange TEXT,
    available BOOLEAN,
    max_amount REAL,
    hourly_rate REAL,
    updated_at TIMESTAMP,
    UNIQUE(symbol, exchange)
);

-- 갭 모니터링 세션
CREATE TABLE gap_monitor_sessions (
    id INTEGER PRIMARY KEY,
    symbol TEXT,
    entry_gap REAL,
    entry_time TIMESTAMP,
    entry_exchange TEXT,
    current_gap REAL,
    last_alert_level INTEGER,
    is_active BOOLEAN,
    closed_at TIMESTAMP,
    final_profit REAL
);

-- 갭 알림 히스토리
CREATE TABLE gap_alerts (
    id INTEGER PRIMARY KEY,
    session_id INTEGER,
    gap_level INTEGER,
    gap_value REAL,
    profit_percent REAL,
    alerted_at TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES gap_monitor_sessions(id)
);
```

---

## 6. 예상 결과

1. **상장 공지 즉시** → 자동 분석 + 전략 추천
2. **론 어디서 빌릴지** → 거래소별 이자율 비교
3. **현선 몇 %인지** → 거래소별 갭 비교 + 추천
4. **1-2% → GO, 4%+ → 리스크** → 시그널 제공
5. **갭 증가 시** → 실시간 익절 알림

---

## 참고

- 기존 문서: `REVERSE_ARB_FROM_GUIDE.md`, `DDARI_FUNDAMENTALS.md`
- 관련 코드: `gap_calculator.py`, `listing_monitor.py`
- Spot-Spot 계획: `SPOT_SPOT_ARBITRAGE.md`

---

*본 문서는 런던감자님 요청으로 작성된 개발 계획서입니다.*
