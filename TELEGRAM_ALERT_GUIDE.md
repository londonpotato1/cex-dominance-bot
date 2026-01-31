# 텔레그램 알림 시스템 사용 가이드

**Phase 7a 구현 완료**: 이벤트 기반 자동 전략 알림

## 개요

CEX Dominance Bot은 5단계 레벨 기반 텔레그램 알림 시스템을 제공합니다:
- **CRITICAL**: 긴급 이벤트 (디페깅, 거래 중단 등)
- **HIGH**: 중요 이벤트 (상장, 출금 중단 등)
- **MEDIUM**: 일반 이벤트 (경고, 마이그레이션)
- **LOW**: 배치 알림 (1시간마다 모아서 전송)
- **INFO**: 로그만 (전송하지 않음)

## 설정 방법

### 1. 텔레그램 봇 생성

1. Telegram에서 @BotFather 검색
2. `/newbot` 명령어 실행
3. 봇 이름 및 사용자명 설정
4. **Bot Token** 저장 (예: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 2. Chat ID 확인

1. 생성한 봇에게 아무 메시지 전송 (예: "Hello")
2. 브라우저에서 다음 URL 접속:
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
3. JSON 응답에서 `chat.id` 찾기 (예: `123456789`)

### 3. 환경 변수 설정

`.env` 파일 또는 시스템 환경변수에 추가:

```bash
# 텔레그램 알림 설정
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=123456789
```

**주의**: `.env` 파일은 `.gitignore`에 추가하여 Git에 커밋되지 않도록 주의!

### 4. 설정 확인

봇 실행 후 로그에서 확인:

```
Phase 3+7a 컴포넌트 초기화 (텔레그램: 설정됨)
```

"미설정 (로그만)"이 표시되면 환경변수가 올바르지 않은 것입니다.

## 알림 유형

### 1. 상장 감지 알림 (LISTING)

**발생 조건**: 업비트/빗썸 신규 마켓 감지

**알림 레벨**: Gate 분석 결과에 따라 (LOW/MEDIUM/HIGH/CRITICAL)

**예시**:
```
📢 *공지 감지* | GO
심볼: SENT @ UPBIT
상장 시간: 2026-01-30 14:00
프리미엄: +3.50% | 순수익: +1.20%
FX: binance (1.80% 비용)

공지: https://upbit.com/service_center/notice?id=1234
```

### 2. WARNING 이벤트 알림

**발생 조건**: 출금/입금 중단, 지갑 점검

**알림 레벨**: MEDIUM

**자동 전략**: BUY 추천 (프리미엄 상승 예상)

**예시**:
```
⚠️ **이벤트 전략 알림**
━━━━━━━━━━━━━━━
💰 **조치**: BUY
🪙 **심볼**: BTC
🏢 **거래소**: upbit
📋 **이벤트**: WARNING
⚡ **심각도**: medium

💡 **사유**:
출금 중단으로 upbit 프리미엄 상승 예상

📈 **예상 수익**: +2.5%
⏰ **최대 보유**: 3시간
🎲 **신뢰도**: 70%
⚠️ **리스크**: medium
━━━━━━━━━━━━━━━
```

### 3. HALT 이벤트 알림

**발생 조건**: 거래 중단, 매매 정지

**알림 레벨**: HIGH

**자동 전략**: MONITOR (거래 재개 대기)

**예시**:
```
🚨 **이벤트 전략 알림**
━━━━━━━━━━━━━━━
🔍 **조치**: MONITOR
🪙 **심볼**: LUNA
🏢 **거래소**: bithumb
📋 **이벤트**: HALT
⚡ **심각도**: high

💡 **사유**:
거래 중단, 재개 모니터링

📈 **예상 수익**: 0.0%
⏰ **최대 보유**: 0시간
🎲 **신뢰도**: 50%
⚠️ **리스크**: high
━━━━━━━━━━━━━━━
```

### 4. DEPEG 이벤트 알림

**발생 조건**: 가격 급락, 스테이블코인 디페깅

**알림 레벨**: CRITICAL

**자동 전략**: SELL 추천 (긴급 청산)

**예시**:
```
🔴 **이벤트 전략 알림**
━━━━━━━━━━━━━━━
📉 **조치**: SELL
🪙 **심볼**: USDT
🏢 **거래소**: upbit
📋 **이벤트**: DEPEG
⚡ **심각도**: critical

💡 **사유**:
스테이블코인 디페깅 감지, 즉시 청산 권장

📈 **예상 수익**: -5.0%
⏰ **최대 보유**: 0시간
🎲 **신뢰도**: 90%
⚠️ **리스크**: critical
🔊 **소리**: 활성화
━━━━━━━━━━━━━━━
```

### 5. MIGRATION 이벤트 알림

**발생 조건**: 토큰 스왑, 체인 변경, 컨트랙트 변경

**알림 레벨**: MEDIUM

**자동 전략**: HOLD (스왑 대기)

**예시**:
```
⚠️ **이벤트 전략 알림**
━━━━━━━━━━━━━━━
⏸️ **조치**: HOLD
🪙 **심볼**: MATIC
🏢 **거래소**: bithumb
📋 **이벤트**: MIGRATION
⚡ **심각도**: medium

💡 **사유**:
POL 토큰 전환, 1:1 스왑 대기

📈 **예상 수익**: 0.0%
⏰ **최대 보유**: 24시간
🎲 **신뢰도**: 80%
⚠️ **리스크**: medium
━━━━━━━━━━━━━━━
```

## 디바운스 (중복 알림 방지)

### MEDIUM 레벨 디바운스

MEDIUM 레벨 알림은 5분 간격으로 제한됩니다:

```python
await alert.send(
    AlertLevel.MEDIUM,
    "프리미엄 3% 돌파",
    key="premium:BTC"  # 5분 내 동일 key는 차단
)
```

### 이벤트 알림 디바운스

이벤트 전략 알림도 자동으로 디바운스 적용:

```python
key=f"event:{event_type}:{symbol}"
# 예: "event:warning:BTC"
# 동일 심볼+이벤트는 5분 간격으로 제한
```

## 배치 알림 (LOW 레벨)

LOW 레벨 알림은 버퍼에 쌓였다가 1시간마다 모아서 전송:

```python
await alert.send(AlertLevel.LOW, "일반 정보")
await alert.send(AlertLevel.LOW, "또 다른 정보")

# 1시간 후 자동으로:
await alert.flush_batch()
```

강제 flush:

```python
await alert.flush_batch()
```

## 알림 미설정 시 동작

Bot Token 또는 Chat ID가 설정되지 않은 경우:
- 실제 전송 없이 **로그만 출력**
- 시스템은 정상 동작
- 테스트 환경에서 유용

로그 예시:

```
[Telegram/dry-run] [CRITICAL] 긴급 알림 테스트
```

## 인터랙티브 봇 (Phase 4)

텔레그램에서 봇에게 명령어를 보내 수동 분석 가능:

### 활성화 방법

`config/features.yaml`:

```yaml
features:
  telegram_interactive: true
```

### 사용 가능 명령어

| 명령어 | 기능 | 예시 |
|--------|------|------|
| `/status` | 시스템 상태 확인 | `/status` |
| `/recent` | 최근 Gate 분석 5건 | `/recent` |
| `/gate <SYMBOL>` | 수동 Gate 분석 (업비트) | `/gate BTC` |
| `/analyze <SYMBOL> <EXCHANGE>` | 거래소 지정 분석 | `/analyze SENT bithumb` |
| `/notice <URL>` | 공지 URL 자동 파싱/분석 | `/notice https://...` |
| `/help` | 도움말 | `/help` |

## 고급 설정

### 알림 필터링 (향후 구현)

`config/features.yaml`:

```yaml
telegram:
  filters:
    # 심각도별 on/off
    severity:
      critical: true
      high: true
      medium: true
      low: false
      info: false

    # 거래소별 필터
    exchanges:
      - upbit
      - bithumb

    # 조용한 시간대 (Do Not Disturb)
    dnd:
      enabled: true
      start: "23:00"
      end: "07:00"

  # Rate limiting
  rate_limit:
    enabled: true
    max_per_hour: 20
```

### 커스텀 알림 포맷

`analysis/event_strategy.py`의 `format_strategy_alert()` 함수 수정:

```python
def format_strategy_alert(recommendation: StrategyRecommendation) -> str:
    """전략 추천 알림 포맷."""
    # 커스텀 포맷 구현
    ...
```

## 트러블슈팅

### 알림이 오지 않을 때

1. **환경변수 확인**:
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```

2. **봇 설정 확인**:
   - 로그에서 "설정됨" 확인
   - "미설정 (로그만)" → 환경변수 미설정

3. **Bot Token 유효성 확인**:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_TOKEN>/getMe"
   ```

4. **Chat ID 유효성 확인**:
   - 봇에게 메시지 보낸 후 `/getUpdates` 확인

### 알림이 너무 많을 때

1. **디바운스 키 사용**:
   ```python
   await alert.send(level, message, key="unique_key")
   ```

2. **알림 레벨 조정**:
   - HIGH/CRITICAL만 받고 싶으면 MEDIUM을 LOW로 변경

3. **Rate Limit 설정** (향후 구현):
   - 시간당 최대 알림 수 제한

## 테스트

### 단위 테스트

```bash
pytest tests/test_telegram_alert.py -v
```

### 통합 테스트

```bash
pytest tests/test_market_monitor_events.py -v
```

### 수동 테스트

Python 스크립트로 테스트:

```python
import asyncio
import sqlite3
from alerts.telegram import TelegramAlert
from analysis.gate import AlertLevel
from store.writer import DatabaseWriter

async def test_alert():
    conn = sqlite3.connect(":memory:")
    writer = DatabaseWriter(conn)
    alert = TelegramAlert(
        writer=writer,
        read_conn=conn,
        bot_token="YOUR_TOKEN",
        chat_id="YOUR_CHAT_ID"
    )

    await alert.send(AlertLevel.CRITICAL, "테스트 알림")
    await asyncio.sleep(1)

asyncio.run(test_alert())
```

## 참고 자료

- [Telegram Bot API 문서](https://core.telegram.org/bots/api)
- `INTEGRATION_EVENT_STRATEGY.md`: MarketMonitor 통합 가이드
- `PHASE7_EVENT_ARBITRAGE.md`: Phase 7 이벤트 아비트라지 상세
- `tests/test_telegram_alert.py`: 알림 시스템 테스트 코드

---

**구현 완료**: 2026-01-30
**Phase**: 7a (이벤트 전략 알림)
**다음 단계**: Phase 7b (이벤트 히스토리 분석)
