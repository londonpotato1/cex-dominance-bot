# Implementation Draft – Collectors / Normalizer / Feature Builder

## 목표
`DATA_COLLECTION_BOT_DESIGN.md`에 정의된 수집/정규화/피처 생성 흐름을
현재 코드베이스 구조에 맞춰 모듈 단위로 구체화한다.

---

## 1) 전체 데이터 플로우
1. **Collectors** → 원천 데이터 수집 (공지/시세/펀딩/핫월렛/DEX)
2. **Normalizer** → 공통 스키마로 정규화 (symbol/chain/시간/단위)
3. **Feature Builder** → 상장/따리 스코어링 입력 피처 생성
4. **Storage** → DB 저장 + CSV 백업
5. **Signals/Alerts** → 점수 기반 알림

---

## 2) Collectors 설계 (현 코드 기반)
### A. 공지/상장 이벤트
- `collectors/korean_notice.py`
- `collectors/notice_fetcher.py`
- `collectors/notice_parser.py`
- `collectors/listing_monitor.py`

출력 포맷(예시):
```json
{
  "exchange": "Upbit",
  "symbol": "XYZ",
  "listing_type": "상장",
  "announce_ts": "2026-02-03 10:02:00",
  "listing_ts": "2026-02-03 11:00:00",
  "source": "notice"
}
```

### B. 시세/펀딩/현선갭
- `collectors/market_monitor.py`
- `collectors/funding_rate.py`
- `collectors/gap_calculator.py`

출력 포맷:
```json
{
  "exchange": "Upbit",
  "symbol": "XYZ",
  "price": 1234.5,
  "volume_1m_krw": 100000000,
  "premium_pct": 5.4,
  "ts": "2026-02-03 10:05:00"
}
```

### C. 핫월렛/입출금
- `collectors/hot_wallet_tracker.py`
- `collectors/withdrawal_tracker.py`
- `collectors/deposit_status.py`

출력 포맷:
```json
{
  "exchange": "Upbit",
  "symbol": "XYZ",
  "chain": "ETH",
  "direction": "deposit",
  "amount": 500000,
  "usd_value": 1234567,
  "tx_hash": "...",
  "ts": "2026-02-03 10:12:00"
}
```

### D. DEX 유동성
- `collectors/dex_liquidity.py`
- `collectors/dex_monitor.py`

출력 포맷:
```json
{
  "symbol": "XYZ",
  "chain": "ETH",
  "dex": "Uniswap",
  "liquidity_usd": 250000,
  "volume_24h_usd": 1200000,
  "ts": "2026-02-03 10:15:00"
}
```

---

## 3) Normalizer 설계 (신규)
### 목적
- 심볼/체인/시간/단위를 통합
- 동일 자산의 CEX/DEX 데이터를 연결 가능하게 함

### 제안 모듈
```
normalizers/
  symbol_map.py     # ticker ↔ contract 매핑
  chain_map.py      # chain 이름 정규화
  time_norm.py      # KST/UTC 변환
  unit_norm.py      # KRW/USD/수량 단위 변환
```

### 핵심 룰
- symbol 기준: 대문자 통일
- chain 기준: ETH/BSC/SOL/ARB/OP/BASE
- ts 기준: 내부 저장은 UTC or KST 일원화

---

## 4) Feature Builder 설계 (신규)
### 목적
상장/따리 후보 스코어링을 위한 피처 생성

### 제안 모듈
```
features/
  listing_features.py     # 상장 공지/입금/출금/현선갭
  wallet_features.py      # 핫월렛 유입속도/변화율
  dex_features.py         # DEX 유동성/유저/풀수
  premium_features.py     # 현선갭/김프 지표
```

### 주요 피처 예시
- `deposit_spike_krw`: 최근 10분 입금액 급증률
- `premium_max_5m`: 최근 5분 최대 프리미엄
- `funding_divergence`: CEX간 펀비 차이
- `dex_liquidity_rank`: DEX 유동성 상대지표

---

## 5) DB 저장 연계
`docs/db_schema.sql` 기준:
- `listing_events`, `market_snapshots`, `funding_rates`, `wallet_flows`, `dex_liquidity_snapshots`
- `listing_cases`는 guide/telegram 기반 케이스를 축적

---

## 6) 실행 순서 (MVP)
1. 공지/상장 수집기 → listing_events 적재
2. 시세/펀딩 수집기 → market_snapshots, funding_rates 적재
3. 핫월렛 수집기 → wallet_flows 적재
4. DEX 수집기 → dex_liquidity_snapshots 적재
5. Feature Builder → signals 생성
6. Alert Handler → 알림 발송

