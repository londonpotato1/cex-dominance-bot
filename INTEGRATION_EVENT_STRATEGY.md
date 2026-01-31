# EventStrategy MarketMonitor 통합 가이드

**Phase 7a 구현**: 이벤트 기반 자동 전략을 MarketMonitor에 통합

## 개요

`analysis/event_strategy.py`의 `EventStrategyExecutor`를 `collectors/market_monitor.py`에 통합하여 공지사항 감지 시 자동으로 트레이딩 전략을 생성하고 알림을 발송합니다.

## 통합 단계

### 1. MarketMonitor.__init__() 수정

```python
# collectors/market_monitor.py

from analysis.event_strategy import EventStrategyExecutor

class MarketMonitor:
    def __init__(
        self,
        writer: DatabaseWriter,
        token_registry: TokenRegistry,
        upbit_collector: Optional[UpbitCollector] = None,
        bithumb_collector: Optional[BithumbCollector] = None,
        *,
        gate_checker: Optional[GateChecker] = None,
        alert: Optional[TelegramAlert] = None,
        event_strategy: Optional[EventStrategyExecutor] = None,  # 🆕 추가
        upbit_interval: float = 30.0,
        bithumb_interval: float = 60.0,
        notice_polling: bool = True,
        notice_interval: float = 30.0,
    ) -> None:
        self._writer = writer
        self._registry = token_registry
        self._upbit_collector = upbit_collector
        self._bithumb_collector = bithumb_collector
        self._gate_checker = gate_checker
        self._alert = alert
        self._event_strategy = event_strategy  # 🆕 추가
        # ... 나머지 초기화 코드
```

### 2. _on_notice_listing() 메서드 확장

```python
# collectors/market_monitor.py (line 437)

async def _on_notice_listing(self, result: NoticeParseResult) -> None:
    """공지에서 상장 감지 시 콜백 (Phase 7 확장)."""
    exchange = result.exchange
    symbols = result.symbols

    # Phase 7: 비상장 이벤트 처리 (WARNING/HALT/MIGRATION/DEPEG)
    if result.notice_type != "listing" and self._event_strategy:
        await self._handle_non_listing_event(result)
        return

    # 기존 상장 처리 로직
    for symbol in symbols:
        key = f"{symbol}@{exchange}"
        if key in self._notice_detected_symbols:
            logger.debug("[MarketMonitor] 이미 공지로 처리됨: %s", key)
            continue

        self._notice_detected_symbols.add(key)

        logger.critical(
            "[MarketMonitor] 📢 공지 상장 감지: %s @ %s (시간: %s)",
            symbol, exchange, result.listing_time or "미정",
        )

        # 1. token_registry 자동 등록
        await self._auto_register_token(symbol)

        # 2. Gate 파이프라인
        if self._gate_checker:
            try:
                t0 = time.monotonic()
                gate_result = await self._gate_checker.analyze_listing(
                    symbol, exchange
                )
                duration_ms = (time.monotonic() - t0) * 1000

                # Gate 분석 로그 DB 기록
                try:
                    from metrics.observability import log_gate_analysis
                    await log_gate_analysis(self._writer, gate_result, duration_ms)
                except Exception as e:
                    logger.warning(
                        "[MarketMonitor] Gate 로그 기록 실패 (%s@%s): %s",
                        symbol, exchange, e,
                    )

                # Listing History 기록
                try:
                    from metrics.observability import record_listing_history
                    await record_listing_history(
                        self._writer,
                        gate_result,
                        listing_time=result.listing_time,
                    )
                except Exception as e:
                    logger.warning(
                        "[MarketMonitor] Listing history 기록 실패 (%s@%s): %s",
                        symbol, exchange, e,
                    )

                # 🆕 Phase 7: 이벤트 전략 생성 (상장도 TRADE 기회)
                if self._event_strategy:
                    try:
                        strategy = await self._event_strategy.process_event(result)
                        if strategy and self._alert:
                            from analysis.event_strategy import format_strategy_alert
                            strategy_msg = format_strategy_alert(strategy)
                            await self._alert.send(
                                "high",  # 전략 알림은 항상 high
                                strategy_msg,
                                key=f"strategy:{symbol}",
                            )
                    except Exception as e:
                        logger.warning(
                            "[MarketMonitor] 이벤트 전략 생성 실패 (%s@%s): %s",
                            symbol, exchange, e,
                        )

                # 3. 텔레그램 알림 (기존)
                if self._alert:
                    alert_msg = self._format_notice_alert(
                        symbol, exchange, gate_result, result
                    )
                    await self._alert.send(
                        gate_result.alert_level,
                        alert_msg,
                        key=f"notice_listing:{symbol}",
                    )
            except Exception as e:
                logger.error(
                    "[MarketMonitor] Gate 파이프라인 에러 (%s@%s): %s",
                    symbol, exchange, e,
                )
```

### 3. 비상장 이벤트 처리 메서드 추가

```python
# collectors/market_monitor.py (새 메서드 추가)

async def _handle_non_listing_event(self, result: NoticeParseResult) -> None:
    """Phase 7: 비상장 이벤트 처리 (WARNING/HALT/MIGRATION/DEPEG).

    Args:
        result: NoticeParseResult (notice_type != "listing")
    """
    logger.critical(
        "[MarketMonitor] 🚨 이벤트 감지: %s @ %s (%s)",
        result.symbols or "N/A",
        result.exchange,
        result.notice_type.upper(),
    )

    if not self._event_strategy:
        logger.warning("[MarketMonitor] EventStrategy 미설정")
        return

    try:
        # 이벤트 전략 생성
        strategy = await self._event_strategy.process_event(result)

        if strategy is None:
            logger.debug("[MarketMonitor] 조치 불필요 이벤트: %s", result.notice_type)
            return

        logger.info(
            "[MarketMonitor] 전략 생성: %s (%s) → %s",
            strategy.symbol,
            strategy.event_type,
            strategy.recommended_action,
        )

        # 텔레그램 알림 발송
        if self._alert:
            from analysis.event_strategy import format_strategy_alert
            alert_msg = format_strategy_alert(strategy)

            # 심각도에 따라 알림 레벨 결정
            severity_to_level = {
                "low": "low",
                "medium": "medium",
                "high": "high",
                "critical": "critical",
            }
            alert_level = severity_to_level.get(
                strategy.severity.value, "medium"
            )

            await self._alert.send(
                alert_level,
                alert_msg,
                key=f"event:{strategy.event_type}:{strategy.symbol}",
                sound=strategy.alert_sound,  # 긴급 알림 시 소리
            )

            logger.info(
                "[MarketMonitor] 이벤트 알림 발송 완료: %s (%s)",
                strategy.symbol,
                strategy.event_type,
            )

    except Exception as e:
        logger.error(
            "[MarketMonitor] 이벤트 전략 처리 실패: %s",
            e,
            exc_info=True,
        )
```

## main.py 통합

### EventStrategyExecutor 초기화

```python
# main.py

from analysis.event_strategy import EventStrategyExecutor
from analysis.premium import PremiumCalculator
from analysis.cost_model import CostModel

async def main():
    # ... 기존 초기화 코드 ...

    # PremiumCalculator, CostModel 초기화
    premium = PremiumCalculator(config_dir=config_dir)
    cost_model = CostModel(config_dir=config_dir)

    # 🆕 EventStrategyExecutor 초기화
    event_strategy = EventStrategyExecutor(
        premium_calculator=premium,
        cost_model=cost_model,
        enable_auto_trade=False,  # 자동 주문은 비활성화 (추천만)
    )

    # MarketMonitor 생성 시 event_strategy 전달
    monitor = MarketMonitor(
        writer=writer,
        token_registry=registry,
        upbit_collector=upbit_collector,
        bithumb_collector=bithumb_collector,
        gate_checker=gate_checker,
        alert=telegram_alert,
        event_strategy=event_strategy,  # 🆕 전달
        notice_polling=True,
    )

    # ... 실행 코드 ...
```

## 테스트 시나리오

### 1. WARNING 이벤트 (출금 중단)

**시나리오**: 업비트에서 BTC 출금 중단 공지

```
[공지] 비트코인(BTC) 지갑 점검에 따른 출금 중단 안내
```

**예상 동작**:
1. NoticeFetcher가 공지 감지
2. NoticeParseResult 생성 (notice_type="warning")
3. EventStrategyExecutor가 매수 기회 전략 생성
4. 텔레그램 알림 발송:

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

### 2. HALT 이벤트 (거래 중단)

**시나리오**: 빗썸에서 LUNA 거래 중단

```
[긴급] 루나(LUNA) 거래 일시 중단
```

**예상 동작**:
1. 공지 감지 → notice_type="halt"
2. 재개 모니터링 전략 생성
3. 텔레그램 긴급 알림 (소리 포함)

### 3. MIGRATION 이벤트 (마이그레이션)

**시나리오**: 업비트에서 MATIC → POL 전환 안내

```
[안내] 폴리곤(MATIC) POL 토큰 전환
```

**예상 동작**:
1. 공지 감지 → notice_type="migration"
2. 스왑 기회 전략 생성
3. 텔레그램 알림 (HOLD 권장)

### 4. DEPEG 이벤트 (디페깅)

**시나리오**: 업비트에서 USDT 가격 급락

```
[긴급] USDT 가격 이상 거래 안내
```

**예상 동작**:
1. 공지 감지 → notice_type="depeg"
2. 안전성 체크 전략 생성 (SELL 권장)
3. 텔레그램 긴급 알림 (소리 포함)

## 설정 파일 (config.yaml)

```yaml
# config/config.yaml

# Phase 7a: 이벤트 전략 설정
event_strategy:
  enabled: true
  auto_trade: false  # true면 자동 주문 실행 (위험!)

  # 이벤트별 활성화
  events:
    warning: true   # 출금 중단
    halt: true      # 거래 중단
    migration: true # 마이그레이션
    depeg: true     # 디페깅

  # 리스크 관리
  risk:
    max_position_size: 0.01  # 최대 포지션 크기 (BTC 기준)
    max_hold_time: 180       # 최대 보유 시간 (분)
    stop_loss_pct: -10.0     # 손절률 (%)
    take_profit_pct: 5.0     # 익절률 (%)

  # 알림 설정
  alerts:
    telegram: true
    sound_for_critical: true  # CRITICAL 이벤트 시 소리
```

## 로그 예시

```
2026-01-30 14:00:00 | CRITICAL | MarketMonitor | 🚨 이벤트 감지: ['BTC'] @ upbit (WARNING)
2026-01-30 14:00:00 | INFO     | EventStrategy | 전략 생성: BTC (warning) → BUY
2026-01-30 14:00:00 | INFO     | MarketMonitor | 이벤트 알림 발송 완료: BTC (warning)
```

## 데이터베이스 스키마 (Optional)

Phase 7b에서 이벤트 히스토리 분석을 위한 테이블:

```sql
CREATE TABLE event_strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- "warning", "halt", "migration", "depeg"
    severity TEXT NOT NULL,    -- "low", "medium", "high", "critical"
    recommended_action TEXT,   -- "BUY", "SELL", "HOLD", "MONITOR"
    expected_roi REAL,
    confidence REAL,
    risk_level TEXT,
    reason TEXT,
    raw_notice TEXT  -- JSON 형식
);

CREATE INDEX idx_event_strategies_symbol ON event_strategies(symbol);
CREATE INDEX idx_event_strategies_type ON event_strategies(event_type);
CREATE INDEX idx_event_strategies_timestamp ON event_strategies(timestamp);
```

## 다음 단계 (Phase 7b, 7c)

1. **Phase 7b: 이벤트 히스토리 분석**
   - 과거 이벤트 데이터 분석
   - 패턴 학습 (출금 중단 → 평균 프리미엄 변화율)
   - 예상 수익률 정확도 개선

2. **Phase 7c: 멀티 이벤트 상관관계**
   - 여러 거래소 간 이벤트 상관관계
   - 업비트 출금 중단 + 빗썸 정상 → 빗썸 프리미엄 상승 예측

---

**구현 상태**: Phase 7a 완료 ✅
**테스트 파일**: `tests/test_event_strategy.py` (22개 테스트)
**관련 문서**: `PHASE7_EVENT_ARBITRAGE.md`
