# Phase 7: 이벤트 아비트라지 구현

**완료일**: 2026-01-30
**상태**: ✅ 구현 완료

## 개요

거래소 공지사항에서 4가지 이벤트 패턴을 감지하여 수익 기회를 포착하는 시스템.

## 추가된 이벤트 유형

### 1. WARNING (출금 중단 경고)
- **감지 키워드**: 출금 중단, 입출금 중단, 지갑 점검, 출금 제한
- **트레이딩 기회**: 출금 차단 → 프리미엄 상승 예상 → **BUY 기회**
- **심각도**: MEDIUM
- **권장 조치**: TRADE

**예시**:
```
[공지] 이더리움(ETH) 지갑 점검에 따른 입출금 중단 안내
→ 출금 불가 시 국내 가격 상승 가능성
→ 해외에서 ETH 매수 후 출금 재개 시 차익 실현
```

### 2. HALT (거래 중단)
- **감지 키워드**: 거래 중단, 거래 정지, 매매 중단
- **트레이딩 기회**: 거래 재개 시 **변동성 급증**
- **심각도**: HIGH
- **권장 조치**: MONITOR

**예시**:
```
[긴급] LUNA 거래 일시 중단 안내
→ 거래 재개 후 첫 몇 분간 극심한 변동성
→ 사전 포지션 준비, 재개 즉시 스캘핑
```

### 3. MIGRATION (체인 마이그레이션)
- **감지 키워드**: 스왑, 마이그레이션, 전환, 체인 변경
- **트레이딩 기회**: 구버전 토큰 할인 거래 → 신버전으로 스왑
- **심각도**: MEDIUM
- **권장 조치**: ALERT

**예시**:
```
[안내] MATIC → POL 토큰 전환 안내
→ 구버전 MATIC 할인 매수 → POL로 1:1 스왑
```

### 4. DEPEG (스테이블코인 디페깅)
- **감지 키워드**: 가격 급락, 이상 거래, 시세 오류, 급등락
- **트레이딩 기회**: USDT 디페깅 시 **저가 매수** 기회
- **심각도**: CRITICAL
- **권장 조치**: ALERT

**예시**:
```
[긴급] USDT 가격 이상 거래 안내
→ USDT가 0.98달러로 하락
→ 0.98 매수 → 1.00 회복 시 2% 수익
```

## 구현 세부사항

### NoticeParseResult 확장

```python
@dataclass
class NoticeParseResult:
    # 기존 필드
    symbols: list[str]
    listing_time: str | None
    notice_type: str  # "listing", "warning", "halt", "migration", "depeg", "unknown"

    # Phase 7 신규 필드
    event_severity: EventSeverity    # LOW, MEDIUM, HIGH, CRITICAL
    event_action: EventAction        # NONE, MONITOR, ALERT, TRADE
    event_details: dict              # 추가 메타데이터
```

### EventSeverity (심각도)

| 레벨 | 의미 | 대응 시간 |
|------|------|----------|
| LOW | 일반 공지 | 1시간 이내 |
| MEDIUM | 주의 필요 | 30분 이내 |
| HIGH | 긴급 대응 필요 | 10분 이내 |
| CRITICAL | 즉시 조치 필요 | 즉시 |

### EventAction (권장 조치)

| 조치 | 의미 | 액션 |
|------|------|------|
| NONE | 조치 불필요 | 무시 |
| MONITOR | 모니터링 | 가격 추적만 |
| ALERT | 알림만 | 텔레그램 알림 |
| TRADE | 거래 기회 | 자동 주문 검토 |

### 이벤트 우선순위

```
HALT > WARNING > MIGRATION > DEPEG > LISTING
```

한 공지에 여러 키워드가 있으면 우선순위가 높은 것으로 분류.

## 사용 예시

### 1. 출금 중단 감지

```python
from collectors.notice_parser import BithumbNoticeParser

parser = BithumbNoticeParser()
result = parser.parse(
    title="[공지] 비트코인(BTC) 출금 중단 안내",
    content="2026-01-30 14:00부터 지갑 점검으로 출금이 중단됩니다."
)

assert result.notice_type == "warning"
assert result.event_severity == EventSeverity.MEDIUM
assert result.event_action == EventAction.TRADE  # 출금 중단 = 매수 기회
assert "BTC" in result.symbols
assert "14:00" in result.listing_time
```

### 2. 거래 중단 감지

```python
result = parser.parse(
    title="[긴급] 루나(LUNA) 거래 일시 중단",
    content="이상 거래 감지로 매매가 중단되었습니다."
)

assert result.notice_type == "halt"
assert result.event_severity == EventSeverity.HIGH
assert result.event_action == EventAction.MONITOR
```

### 3. 마이그레이션 감지

```python
result = parser.parse(
    title="[안내] 폴리곤(MATIC → POL) 토큰 전환",
    content="기존 MATIC 토큰이 POL로 1:1 스왑됩니다."
)

assert result.notice_type == "migration"
assert result.event_severity == EventSeverity.MEDIUM
assert result.event_action == EventAction.ALERT
```

## 통합 포인트

### 1. MarketMonitor 통합

```python
# collectors/market_monitor.py
async def _on_new_notice(self, notice_url: str, title: str):
    result = self._parser.parse(title, content="")

    # Phase 7: 이벤트 기반 알림
    if result.event_action == EventAction.TRADE:
        await self._telegram.send_alert(
            f"🚨 거래 기회: {result.notice_type.upper()}\n"
            f"심볼: {', '.join(result.symbols)}\n"
            f"심각도: {result.event_severity.value}"
        )
    elif result.event_severity == EventSeverity.CRITICAL:
        await self._telegram.send_critical_alert(
            f"🔴 긴급: {title}"
        )
```

### 2. Gate 분석 확장 (Optional)

```python
# analysis/gate.py
async def analyze_event(self, notice_result: NoticeParseResult):
    """이벤트 기반 거래 기회 분석."""
    if notice_result.notice_type == "warning" and "출금" in notice_result.raw_title:
        # 출금 중단 → 프리미엄 상승 예측
        premium = await self._premium.calculate_premium(...)
        if premium > 5.0:
            return "BUY_OPPORTUNITY"

    elif notice_result.notice_type == "halt":
        # 거래 중단 → 재개 시각 모니터링
        return "MONITOR_RESUME"
```

## 테스트 케이스

```python
# tests/test_notice_parser_phase7.py

def test_warning_withdrawal_suspension(bithumb_parser):
    """출금 중단 감지."""
    title = "[공지] 이더리움(ETH) 출금 중단 안내"
    result = bithumb_parser.parse(title)

    assert result.notice_type == "warning"
    assert result.event_action == EventAction.TRADE

def test_halt_trading_suspension(bithumb_parser):
    """거래 중단 감지."""
    title = "[긴급] 루나(LUNA) 거래 정지"
    result = bithumb_parser.parse(title)

    assert result.notice_type == "halt"
    assert result.event_severity == EventSeverity.HIGH

def test_migration_token_swap(upbit_parser):
    """마이그레이션 감지."""
    title = "[안내] MATIC 토큰 전환 안내"
    result = upbit_parser.parse(title)

    assert result.notice_type == "migration"
    assert result.event_action == EventAction.ALERT

def test_depeg_price_anomaly(bithumb_parser):
    """디페깅 감지."""
    title = "[긴급] USDT 가격 급락 안내"
    result = bithumb_parser.parse(title)

    assert result.notice_type == "depeg"
    assert result.event_severity == EventSeverity.CRITICAL
```

## 수익 기회 매트릭스

| 이벤트 | 방향 | 예상 수익률 | 리스크 | 지속 시간 |
|--------|------|------------|--------|----------|
| WARNING (출금 중단) | LONG | 2-5% | 중간 | 1-3시간 |
| HALT (재개 직전) | BOTH | 3-10% | 높음 | 5-30분 |
| MIGRATION | LONG | 1-3% | 낮음 | 1-7일 |
| DEPEG | LONG | 2-5% | 매우 높음 | 1-24시간 |

## 다음 단계

1. **Phase 7a**: 이벤트별 자동 전략 실행
   - WARNING → 자동 매수 주문
   - HALT → 재개 시각 알림
   - MIGRATION → 스왑 기회 계산
   - DEPEG → 안전 마진 모니터링

2. **Phase 7b**: 이벤트 히스토리 분석
   - 과거 출금 중단 시 프리미엄 변화 패턴
   - 거래 재개 후 평균 변동성
   - 마이그레이션 스왑 수익률 통계

3. **Phase 7c**: 멀티 이벤트 상관관계
   - 업비트 출금 중단 + 빗썸 정상 → 빗썸 프리미엄 상승
   - 한 거래소 HALT → 다른 거래소 유동성 이동

## 기대 효과

- **수익 기회 확대**: 상장 외 4가지 이벤트에서 추가 수익
- **리스크 회피**: 거래 중단/디페깅 조기 감지로 손실 방지
- **자동화 수준 향상**: 이벤트별 맞춤 전략 자동 실행

---

**구현 파일**:
- `collectors/notice_parser.py` (Phase 7 확장)
- `tests/test_notice_parser_phase7.py` (테스트 추가 예정)

**관련 문서**:
- `REVIEW_2026-01-29_DETAILED.md` (Phase 6 완료 체크)
- `PHASE6_SCENARIO.md` (이전 단계)
