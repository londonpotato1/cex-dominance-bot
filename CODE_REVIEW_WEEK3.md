# Phase 7 Week 1-3 코드 리뷰 보고서

**작성일:** 2026-01-30  
**검토 범위:** Phase 7 Week 1-3 (Quick Wins + 백테스트 + VC/MM)  
**검토자:** 감비 (AI Assistant)  
**전체 평가:** ⭐⭐⭐⭐ (8.75/10) - 우수

---

## 📋 Executive Summary

Week 1-3 개발 완료 상태이며, 전반적으로 코드 품질이 우수함.  
핵심 기능(시나리오 예측, 백테스트, VC/MM 수집)이 잘 구현되었고,  
백테스트 정확도 **73.1%** 달성으로 목표(70%) 초과.

**주요 성과:**
- 6단계 Reference Price 폴백 체인 구현
- 다중 시나리오 생성 (BEST/LIKELY/WORST)
- 백테스트 프레임워크 + 73.1% 정확도 달성
- VC 33개 + MM 6개 티어 DB 구축

---

## 🔴 즉시 개선 필요 (High Priority)

### 1. UI 하드코딩 문제

**파일:** `ui/ddari_tab.py` (Line 396-430)

**문제:**
```python
# 현재 코드 - 하드코딩됨
tier1_vcs = [
    {"name": "Binance Labs", "roi": 85.3, "portfolio": 200},
    {"name": "a16z", "roi": 92.1, "portfolio": 150},
    ...
]
```

**위험:**
- `vc_tiers.yaml` 수정해도 UI에 반영 안 됨
- 데이터 불일치 발생 가능
- 유지보수 어려움

**해결책:**
```python
def _load_vc_tiers_cached() -> dict:
    """VC 티어 YAML 로드 (1시간 캐시)."""
    import streamlit as st
    
    @st.cache_data(ttl=3600)
    def _inner():
        vc_path = Path(__file__).parent.parent / "data" / "vc_mm_info" / "vc_tiers.yaml"
        with open(vc_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return _inner()

def _render_vc_mm_section() -> None:
    data = _load_vc_tiers_cached()
    tier1_vcs = data.get("tier1", [])
    # ... 동적으로 렌더링
```

**예상 소요:** 30분  
**담당:** Week 4 시작 전 수정 권장

---

### 2. VC/MM 수집기 테스트 부재

**현재 상태:**
```
tests/
├── test_phase7_integration.py  ✅ 있음
├── test_vc_mm_collector.py     ❌ 없음
```

**필요한 테스트:**
```python
# tests/test_vc_mm_collector.py

import pytest
from collectors.vc_mm_collector import VCMMCollector, VCTierClassifier

class TestVCTierClassifier:
    def test_exact_match(self):
        """정확한 VC 이름 매칭."""
        classifier = VCTierClassifier()
        assert classifier.classify("Binance Labs") == 1
        assert classifier.classify("Hashed") == 2
        assert classifier.classify("Unknown VC") == 3
    
    def test_partial_match(self):
        """부분 매칭 (a16z Crypto → a16z)."""
        classifier = VCTierClassifier()
        assert classifier.classify("a16z Crypto") == 1
        assert classifier.classify("Polychain Capital Partners") == 1
    
    def test_classify_all(self):
        """투자자 리스트 티어별 분류."""
        classifier = VCTierClassifier()
        investors = ["Binance Labs", "Hashed", "Unknown"]
        t1, t2, t3 = classifier.classify_all(investors)
        assert "Binance Labs" in t1
        assert "Hashed" in t2
        assert "Unknown" in t3

@pytest.mark.asyncio
async def test_manual_db_fallback():
    """수동 DB에서 정보 로드 테스트."""
    collector = VCMMCollector()
    info = await collector.collect("SENT")
    assert info.data_source == "manual"
    assert info.confidence >= 0.9
    assert "Binance Labs" in info.tier1_investors
    await collector.close()
```

**예상 소요:** 1시간  
**담당:** Week 4

---

## 🟡 중기 개선 권장 (Medium Priority)

### 3. CoinGecko ID 매핑 하드코딩

**파일:** `analysis/reference_price.py` (Line 270-295)

**현재:**
```python
def _symbol_to_coingecko_id(symbol: str) -> str | None:
    mapping = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        # ... 20개 하드코딩
    }
    return mapping.get(symbol.upper())
```

**문제:**
- 신규 토큰 추가 시 코드 수정 필요
- TGE 상장 토큰은 매핑 없음 → CoinGecko 폴백 실패

**해결책 (2가지 옵션):**

**Option A: YAML 외부화**
```yaml
# data/coingecko_mapping.yaml
mappings:
  BTC: bitcoin
  ETH: ethereum
  MOCA: moca-network
  # ... 확장 가능
```

**Option B: CoinGecko API 동적 조회**
```python
async def _fetch_coingecko_id(self, symbol: str) -> str | None:
    """CoinGecko /coins/list API로 동적 매핑."""
    # 캐시 확인
    if symbol in self._id_cache:
        return self._id_cache[symbol]
    
    # API 조회 (rate limit 주의)
    url = "https://api.coingecko.com/api/v3/coins/list"
    async with self._session.get(url) as resp:
        coins = await resp.json()
        for coin in coins:
            if coin["symbol"].upper() == symbol.upper():
                self._id_cache[symbol] = coin["id"]
                return coin["id"]
    return None
```

**권장:** Option A (YAML) 먼저 → 나중에 Option B 추가

**예상 소요:** 2시간  
**담당:** Phase 8 또는 Week 5

---

### 4. Rootdata API 실제 연동

**파일:** `collectors/vc_mm_collector.py` (Line 300-360)

**현재:**
```python
async def _fetch_rootdata(self, symbol: str) -> Optional[ProjectVCInfo]:
    """Rootdata API에서 펀딩 정보 조회.
    
    Note: Rootdata API는 실제 엔드포인트 문서 확인 필요.
    여기서는 예상 구조로 구현.
    """
    url = "https://api.rootdata.com/v1/project/search"  # 예상 URL
```

**문제:**
- 실제 Rootdata API 문서 확인 안 됨
- 응답 구조가 다를 수 있음
- API 키 없으면 테스트 불가

**해결책:**
1. Rootdata API 공식 문서 확인
2. API 키 발급 (필요시)
3. 실제 응답 구조에 맞게 파서 수정
4. 테스트 추가

**예상 소요:** 3시간 (API 문서 확인 포함)  
**담당:** Phase 9 (VC/MM 완성 단계)

---

### 5. Premium Velocity 설정 외부화

**파일:** `analysis/premium_velocity.py` (Line 95-98)

**현재:**
```python
class PremiumVelocityTracker:
    _COLLAPSE_THRESHOLD_1M = -2.0  # 하드코딩
    _SURGE_THRESHOLD_1M = 3.0
    _CONVERGENCE_THRESHOLD_15M = 0.5
```

**해결책:**
```yaml
# config/thresholds.yaml에 추가
premium_velocity:
  collapse_threshold_1m: -2.0
  surge_threshold_1m: 3.0
  convergence_threshold_15m: 0.5
  alert_cooldown_sec: 60
```

```python
def __init__(self, config: dict = None):
    config = config or self._load_config()
    self._collapse_threshold = config.get("collapse_threshold_1m", -2.0)
    # ...
```

**예상 소요:** 30분  
**담당:** Week 4 또는 5

---

## 🟢 장기 개선 권장 (Low Priority)

### 6. 백테스트 "보통" 카테고리 정확도

**현재:** 46.2% (다른 카테고리 대비 낮음)

| 카테고리 | 정확도 | 건수 |
|----------|--------|------|
| 대흥따리 | 90.5% | 21건 |
| 흥따리 | 76.9% | 13건 |
| **보통** | **46.2%** | 13건 |
| 망따리 | 70.0% | 20건 |

**원인 분석:**
- "보통" 경계가 애매함 (40-50% 범위)
- 데이터 자체가 양극화 (대흥/망따리가 많음)

**가능한 개선:**
1. "보통" 범주 세분화 (흥따리-보통 / 보통-망따리)
2. 추가 Feature 도입 (과거 유사 상장 패턴)
3. 데이터 라벨링 재검토

**예상 소요:** 1-2일  
**담당:** Phase 9 (최적화 단계)

---

### 7. 에러 로깅 표준화

**현재:** 일부 파일에서 로깅 포맷 불일치

```python
# 파일마다 다름
logger.warning("[VCCollector] CoinGecko API 실패: %s - %s", cg_id, e)
logger.debug("[RefPrice] Binance Futures 에러 (%s): %s", symbol, e)
```

**권장 포맷:**
```python
# 표준화
logger.warning(
    "[%s] %s failed: symbol=%s, error=%s",
    self.__class__.__name__,
    "CoinGecko API",
    cg_id,
    str(e),
)
```

**예상 소요:** 1시간  
**담당:** 코드 정리 시

---

## 📊 파일별 점수

| 파일 | 점수 | 주요 이슈 |
|------|------|-----------|
| `reference_price.py` | 9/10 | CoinGecko ID 매핑 하드코딩 |
| `scenario.py` | 9/10 | - (우수) |
| `premium_velocity.py` | 8/10 | 설정 하드코딩 |
| `backtest.py` | 9/10 | "보통" 정확도 낮음 |
| `vc_mm_collector.py` | 8/10 | Rootdata API 미검증 |
| `ddari_tab.py` | 7/10 | **VC/MM 하드코딩** (즉시 수정 필요) |
| `unlock_schedules.yaml` | 9/10 | - (우수) |
| `vc_tiers.yaml` | 9/10 | - (우수) |
| `test_phase7_integration.py` | 8/10 | VC 수집기 테스트 없음 |

---

## 🎯 Action Items

### 즉시 (Week 4 시작 전)
- [ ] `ddari_tab.py` UI 하드코딩 → YAML 로드 변경
- [ ] `test_vc_mm_collector.py` 기본 테스트 추가

### Week 4-5
- [ ] CoinGecko ID 매핑 YAML 외부화
- [ ] Premium velocity 설정 외부화
- [ ] Rootdata API 문서 확인 및 연동

### Phase 9
- [ ] "보통" 카테고리 정확도 개선 연구
- [ ] VC 데이터 100개+ 확장
- [ ] MM 조작 감지 로직 추가

---

## 📝 결론

Week 1-3 개발은 **성공적으로 완료**됨.

핵심 지표인 백테스트 정확도 73.1%를 달성했고,  
코드 품질도 전반적으로 우수함.

**즉시 수정이 필요한 항목은 2개:**
1. UI 하드코딩 (30분)
2. VC 수집기 테스트 (1시간)

이 두 가지만 처리하면 Week 4로 넘어가기에 충분함.

---

*보고서 끝*
