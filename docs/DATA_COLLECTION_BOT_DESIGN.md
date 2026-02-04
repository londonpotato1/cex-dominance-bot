# Data Collection Bot Design (Listing + Arbitrage)

## 목표
상장/따리/아비트라지 후보를 한눈에 분석하기 위해 필요한 데이터를 자동 수집하고,
정규화 스키마로 저장하여 스코어링/알림/리포팅에 연결한다.

## 범위
1) 거래소 공지/상장 이벤트 수집
2) 현물/선물 가격, 펀딩비, 프리미엄(현선갭) 스냅샷 수집
3) 핫월렛/입금/출금 흐름 수집
4) DEX 유동성/볼륨 수집
5) 텔레그램/가이드 기반 케이스 정리 (복기 포함)

## 핵심 산출물
- `docs/guide_listing_cases.csv` (정규화 컬럼 추가)
- `data/labeling/listing_data.csv` (학습/스코어링 입력)
- `data/telegram_exports/guide_notes_listing_summary.csv` (가이드 요약)

## 정규화 컬럼 (guide_listing_cases.csv)
필수 확장 컬럼(요청 반영):
- `listing_type`: 상장타입 (TGE/직상장/원상/상장 등)
- `network_chain`: 체인
- `hot_wallet_usd`: 핫월렛 추정 보유/이체 규모
- `max_premium_pct`: 현선갭/김프 최대치
- `result_label`: 결과(대흥따리/흥따리/보통/망따리)

추가 보강 컬럼(향후 자동화 대상):
- `profit_pct`, `market_cap_usd`, `deposit_krw`, `hedge_type`,
  `dex_liquidity_usd`, `withdrawal_open`, `airdrop_claim_rate`, `notes_norm`

## 수집 파이프라인 설계
1) Collectors
   - 공지 수집: 업비트/빗썸/코인원 공지 크롤러
   - 시세 수집: CEX 현물/선물 가격, 펀딩비, OI
   - 온체인: 거래소 핫월렛 주소 모니터링, 입금/출금 흐름
   - DEX: 유동성/볼륨, 풀 상태
   - 텔레그램/가이드: 케이스/복기 글 파싱

2) Normalizers
   - 동일 자산 심볼 정규화 (티커/체인/컨트랙트 매핑)
   - 시간 정규화 (Asia/Seoul 기준)
   - 숫자 정규화 (KRW/USD 변환 등)

3) Feature Builders
   - 현선갭, 프리미엄, 펀딩비 추이
   - 입금/출금 증가율, 핫월렛 유입 속도
   - DEX 유동성/풀 분산도
   - 과거 결과 대비 유사 패턴 유사도

4) Scoring / Alerts
   - 상장 후보 점수화
   - 입금 폭증 / 현선갭 급증 / 출금 지연 트리거
   - 텔레그램 케이스 기반 학습과 대조

## 운영 루틴 (예시)
- 1~5분: 공지/가격/펀딩비/현선갭 스냅샷
- 10~30분: 핫월렛/입금/출금 모니터링
- 30~60분: DEX 유동성/볼륨 스냅샷
- 일 1회: 케이스 정리/정규화/라벨링 업데이트

## 데이터 품질 규칙
- 중복 제거: (symbol, exchange, date) 키
- 시간대 통일: KST 기준 저장
- 신뢰도 태깅: 수동/자동/출처 기반 점수

## 파일/DB 연결
- CSV(가이드/복기)는 수집봇의 보조 학습 데이터
- DB는 실시간 수집/분석의 중심 저장소

---

# DB 스키마 개요
자세한 SQL은 `docs/db_schema.sql` 참고.

핵심 테이블:
- assets, exchanges
- listing_events, listing_cases
- market_snapshots, funding_rates, premiums
- hot_wallets, wallet_flows
- dex_liquidity_snapshots
- signals, alerts
