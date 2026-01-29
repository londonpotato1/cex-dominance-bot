"""Collectors package (Phase 5b).

데이터 수집기 모듈:
  - robust_ws: WebSocket 베이스 클래스
  - upbit_ws / bithumb_ws: 국내 거래소 WebSocket
  - market_monitor: 신규 상장 감지
  - aggregator: 거래 데이터 집계

Phase 5b 외부 데이터 모듈 (필요시 직접 import):
  - api_client: Resilient HTTP 클라이언트
  - dex_monitor: DEX 유동성 모니터
  - hot_wallet_tracker: 거래소 핫월렛 잔액 추적
  - withdrawal_tracker: 입출금 상태 추적
"""

# Phase 5b 외부 데이터 모듈은 여기서 import하지 않음 (시작 시간 최적화)
# 필요시 직접 import: from collectors.api_client import ResilientHTTPClient

__all__: list[str] = []
