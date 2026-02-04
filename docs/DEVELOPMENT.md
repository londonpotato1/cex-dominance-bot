# CEX Dominance Bot 개발 가이드

## UI 동기화 규칙 ⚠️

### 필수 동기화 대상

다음 두 UI는 **항상 동일한 데이터/기능**을 표시해야 함:

| 구분 | 파일 | 설명 |
|------|------|------|
| **대시보드 상장공지** | `ui/ddari_live.py` | 바이낸스 상장 자동 분석 |
| **분석센터 수동분석** | `ui/ddari_strategy.py` | 전략 분석기 (심볼 입력) |

### 동기화 항목

수정 시 **양쪽 모두** 업데이트 필요:

1. **거래소 현황 테이블**
   - 현물/선물 마켓 표시
   - 입금/출금 상태
   - 핫월렛 정보 (잔액 또는 개수)
   - 네트워크 정보

2. **토크노믹스 데이터**
   - 시가총액, FDV
   - 유통량/총공급량
   - 24h 거래량
   - 가격 등락률

3. **전략 추천 카드**
   - GO/NO-GO 스코어
   - 액션 플랜
   - 경고/리스크

4. **핫월렛 잔액 조회**
   - 체인별 컨트랙트 주소 사용
   - 온체인 잔액 표시

### 공유 컴포넌트

- `collectors/listing_intel.py` - 토크노믹스 수집
- `collectors/listing_strategy.py` - 전략 분석 로직
- `collectors/hot_wallet_db.py` - 핫월렛 DB
- `collectors/wallet_balance.py` - 잔액 조회
- `ui/ddari_common.py` - 공통 UI 유틸

### 수정 체크리스트

새 기능 추가 시:
- [ ] `ddari_live.py` 수정
- [ ] `ddari_strategy.py` 수정
- [ ] 공통 로직은 `listing_strategy.py` 또는 `ddari_common.py`로 추출
- [ ] 두 UI에서 동일하게 표시되는지 확인

---

## 기타 규칙

### 특수 문자 처리 (Railway 호환)

Railway Python 3.11 환경에서 UTF-8 인코딩 이슈가 있음.

**금지:**
- f-string 안에 f-string 중첩 (`{f'''...'''}`)
- 이모지/특수문자 직접 사용

**대신:**
- 중첩 f-string → 변수로 분리
- 이모지 → HTML 엔티티 (`&#128640;`)
- 화살표 → HTML 엔티티 (`&#8594;`)
