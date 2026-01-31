# 🔍 CEX Dominance Bot 코드 리뷰
**작성일:** 2026-01-30  
**리뷰어:** 감비 🥔

---

## 📊 전체 평가

| 파일 | 코드 품질 | 상태 |
|------|----------|------|
| `dominance.py` | B+ | ✅ 안정적 |
| `main.py` | B+ | ✅ 안정적 |
| `app.py` | B | ✅ 동작함 |

---

## ✅ 잘 된 부분

### dominance.py
- `dataclass` 활용으로 데이터 구조 명확
- ccxt 비동기 래핑 깔끔
- 한국/글로벌 거래소 분리 잘 됨
- 환율 조회 + 폴백 처리 있음
- OHLCV 기반 기간별 거래량 지원

### main.py
- argparse CLI 구조 깔끔
- 텔레그램 알림 쿨다운 로직 구현됨
- 로깅 설정 잘 되어 있음

### app.py
- 모던한 UI (Space Grotesk, 다크테마)
- Plotly 차트 깔끔 (도넛, 바)
- `@st.cache_data` 캐싱 활용
- Railway 데몬 자동 재시작 로직

---

## 🔧 개선 제안

### 1. 환율 기본값 하드코딩 (dominance.py)

**현재 코드 (Line ~53, ~60):**
```python
self._krw_rate = 1350.0
```

**개선안:**
```python
self._krw_rate = self.config.get("default_krw_rate", 1350.0)
```

**이유:** 환율 변동 시 config만 수정하면 됨

---

### 2. USD 환산 로직 중복 (dominance.py)

**현재:** `_fetch_volume`과 `_fetch_volume_ohlcv`에서 동일한 USD 환산 로직 반복

**개선안 - 헬퍼 메서드 추가:**
```python
def _to_usd(self, volume_quote: float, region: str) -> float:
    """KRW/USD 환산"""
    if region == "korean":
        return volume_quote / self._krw_rate if self._krw_rate else 0
    return volume_quote
```

그 후 두 메서드에서 호출:
```python
volume_usd = self._to_usd(volume_24h, region)
```

---

### 3. exchange_totals 개선 (dominance.py)

**현재 코드 (calculate_total_market 내):**
```python
exchange_totals: dict[str, ExchangeVolume] = {}
for v in all_volumes:
    key = v.exchange
    if key in exchange_totals:
        exchange_totals[key] = ExchangeVolume(
            exchange=v.exchange,
            ticker="TOTAL",
            volume_24h=exchange_totals[key].volume_24h + v.volume_24h,
            volume_usd=exchange_totals[key].volume_usd + v.volume_usd,
            price=0,
            region=v.region,
        )
    else:
        exchange_totals[key] = ExchangeVolume(...)
```

**개선안 - defaultdict 사용:**
```python
from collections import defaultdict

# 먼저 합산
totals = defaultdict(lambda: {"volume_24h": 0, "volume_usd": 0, "region": None})
for v in all_volumes:
    totals[v.exchange]["volume_24h"] += v.volume_24h
    totals[v.exchange]["volume_usd"] += v.volume_usd
    totals[v.exchange]["region"] = v.region

# ExchangeVolume 변환
exchange_totals = [
    ExchangeVolume(
        exchange=ex,
        ticker="TOTAL",
        volume_24h=data["volume_24h"],
        volume_usd=data["volume_usd"],
        price=0,
        region=data["region"],
    )
    for ex, data in totals.items()
]
```

---

### 4. asyncio.run() 반복 호출 (app.py)

**현재 코드:**
```python
@st.cache_data(ttl=60)
def fetch_all_data(_config, period: str = "24h"):
    async def _fetch():
        ...
    return asyncio.run(_fetch())
```

**잠재적 문제:** Streamlit 환경에서 이벤트 루프 충돌 가능성

**현재 상태:** `@st.cache_data(ttl=60)` 캐싱 덕분에 실제로는 60초마다 1회만 호출되어 당장 문제없음

**장기 개선안 (필요시):**
```python
import nest_asyncio
nest_asyncio.apply()  # 중첩 이벤트 루프 허용
```

또는 Streamlit의 `st.cache_resource`로 이벤트 루프 재사용

---

### 5. 선물 vs 현물 거래량 (중요!)

**현재:** 현물(spot) 거래량만 조회

**Cron 리포트에서:** "글로벌 선물 (24h)" 표시됨

**선물 거래량 추가하려면:**
```python
# 바이낸스 선물 예시
exchange = ccxt.binance({
    'options': {'defaultType': 'future'}
})
await exchange.load_markets()
ticker = await exchange.fetch_ticker("BTC/USDT")
```

**config.yaml 확장 예시:**
```yaml
exchanges:
  global_spot:
    - {name: binance, enabled: true}
  global_futures:
    - {name: binance, enabled: true, type: future}
```

---

### 6. CSS 분리 (app.py)

**현재:** 300줄+ CSS가 파이썬 코드 내 인라인

**개선안:**
1. `static/style.css` 파일로 분리
2. 또는 `ui/styles.py`에 상수로 분리

```python
# ui/styles.py
MAIN_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk...');
    ...
</style>
"""

# app.py
from ui.styles import MAIN_CSS
st.markdown(MAIN_CSS, unsafe_allow_html=True)
```

---

## 📋 우선순위 정리

| 순위 | 항목 | 난이도 | 영향도 |
|------|------|--------|--------|
| P1 | 환율 config 이동 | 쉬움 | 낮음 |
| P1 | USD 환산 헬퍼 | 쉬움 | 코드 품질 |
| P2 | 선물 거래량 추가 | 중간 | 기능 확장 |
| P3 | CSS 분리 | 쉬움 | 유지보수 |
| P3 | asyncio 개선 | 중간 | 안정성 |

---

## 🎯 결론

현재 코드는 **안정적으로 동작**하고 있음. 위 개선사항들은 "있으면 좋은" 수준이지 긴급한 버그 수정은 아님.

**당장 적용 추천:**
1. 환율 기본값 → config로 이동
2. `_to_usd()` 헬퍼 메서드 추가

**나중에 적용:**
- 선물 거래량 (기능 확장 시)
- CSS 분리 (UI 대규모 수정 시)

---

*리뷰 완료: 2026-01-30 21:15 KST*  
*감비 🥔*
