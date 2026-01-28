# Phase 0 라벨링 데이터

## listing_data.csv 필드 설명

| # | 필드 | 타입 | 설명 | 예시 |
|---|------|------|------|------|
| 1 | symbol | str | 토큰 심볼 | CKB, MINA, RED |
| 2 | exchange | str | 거래소 | Upbit, Bithumb |
| 3 | date | str | 상장일 | 2024-03-15 |
| 4 | listing_type | str | 상장 유형 | TGE, 직상장, 옆상장 |
| 5 | market_cap_usd | float | 시가총액(USD) | 500000000 |
| 6 | top_exchange | str | 최대거래량 거래소 | Binance, Bybit |
| 7 | top_exchange_tier | int | 거래소 티어 | 1, 2, 3 |
| 8 | deposit_krw | float | 예치금(KRW) | 50000000000 |
| 9 | volume_5m_krw | float | 5분 거래량(KRW) | 10000000000 |
| 10 | volume_1m_krw | float | 1분 거래량(KRW) | 3000000000 |
| 11 | turnover_ratio | float | 거래량/예치금 비율 | 4.2 |
| 12 | max_premium_pct | float | 최대 김프(%) | 35.5 |
| 13 | premium_at_5m_pct | float | 5분 시점 김프(%) | 12.3 |
| 14 | supply_label | str | 공급 분류 | constrained, smooth |
| 15 | hedge_type | enum | 헤징 유형 (v14) | cex_futures, dex_futures, none |
| 16 | dex_liquidity_usd | float | DEX 유동성(USD) | 2000000 |
| 17 | hot_wallet_usd | float | 핫월렛 잔액(USD) | 5000000 |
| 18 | network_chain | str | 블록체인 네트워크 | ERC20, SOL, MATIC |
| 19 | network_speed_min | float | 네트워크 확인 시간(분) | 5.0 |
| 20 | withdrawal_open | bool | 출금 개방 여부 | true, false |
| 21 | airdrop_claim_rate | float | 에어드롭 청구율(%) | 45.0 |
| 22 | prev_listing_result | str | 직전 상장 결과 | heung, mang, neutral |
| 23 | market_condition | str | 시장 상황 | bull, bear, neutral |
| 24 | result_label | str | 판정 결과 | 대흥따리, 흥따리, 보통, 망따리 |
| 25 | result_notes | str | 비고 | 피뢰침, 후펌핑 등 |

## 판정 기준

| 판정 | 기준 |
|------|------|
| **대흥따리** | 최대 김프 >= 30% |
| **흥따리** | 최대 김프 >= 8% AND 5분 이상 유지 |
| **보통** | 최대 김프 3~8% OR 피뢰침(1분 내 소멸) |
| **망따리** | 최대 김프 < 3% OR 역프 발생 |

## 데이터 수집 소스

1. 강의 자료 (Part 04/05 PDF) → ~30건
2. 카일 텔레그램 채널 (@info_Arbitrage)
3. 업비트/빗썸 과거 공지사항 + 차트
4. 직접 참여한 상장 기록

## 분석 실행

```bash
python scripts/phase0_analysis.py
```
