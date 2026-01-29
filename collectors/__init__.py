"""Collectors package (Phase 5b).

데이터 수집기 모듈:
  - api_client: Resilient HTTP 클라이언트 (Circuit Breaker, Rate Limiter)
  - dex_monitor: DEX 유동성 모니터 (DexScreener)
  - hot_wallet_tracker: 거래소 핫월렛 잔액 추적 (Alchemy RPC)
  - withdrawal_tracker: 입출금 상태 추적 (Upbit/Bithumb/Binance)
  - robust_ws: WebSocket 베이스 클래스
  - upbit_ws / bithumb_ws: 국내 거래소 WebSocket
  - market_monitor: 신규 상장 감지
  - aggregator: 거래 데이터 집계

Note: Phase 5b 모듈은 lazy import (필요시 import)로 시작 시간 최적화.
      직접 사용 시: from collectors.api_client import ResilientHTTPClient
"""

# Lazy imports - 시작 시간 최적화를 위해 여기서 import하지 않음
# Phase 5b 모듈은 필요할 때 직접 import:
#   from collectors.api_client import ResilientHTTPClient, ...
#   from collectors.dex_monitor import DEXMonitor, ...
#   from collectors.hot_wallet_tracker import HotWalletTracker, ...
#   from collectors.withdrawal_tracker import WithdrawalTracker, ...

__all__ = [
    # API Client Infrastructure (lazy import)
    "ResilientHTTPClient",
    "ResilientHTTPConfig",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "CircuitOpenError",
    "RateLimiter",
    "RateLimiterConfig",
    "get_api_key",
    # DEX Monitor (lazy import)
    "DEXMonitor",
    "DexLiquidityResult",
    # Hot Wallet Tracker (lazy import)
    "HotWalletTracker",
    "HotWalletResult",
    # Withdrawal Tracker (lazy import)
    "WithdrawalTracker",
    "WithdrawalResult",
    "WithdrawalStatus",
]


def __getattr__(name: str):
    """Lazy import for Phase 5b modules."""
    if name in ("ResilientHTTPClient", "ResilientHTTPConfig", "CircuitBreaker",
                "CircuitBreakerConfig", "CircuitState", "CircuitOpenError",
                "RateLimiter", "RateLimiterConfig", "get_api_key"):
        from collectors.api_client import (
            ResilientHTTPClient, ResilientHTTPConfig, CircuitBreaker,
            CircuitBreakerConfig, CircuitState, CircuitOpenError,
            RateLimiter, RateLimiterConfig, get_api_key,
        )
        return locals()[name]
    elif name in ("DEXMonitor", "DexLiquidityResult"):
        from collectors.dex_monitor import DEXMonitor, DexLiquidityResult
        return locals()[name]
    elif name in ("HotWalletTracker", "HotWalletResult"):
        from collectors.hot_wallet_tracker import HotWalletTracker, HotWalletResult
        return locals()[name]
    elif name in ("WithdrawalTracker", "WithdrawalResult", "WithdrawalStatus"):
        from collectors.withdrawal_tracker import WithdrawalTracker, WithdrawalResult, WithdrawalStatus
        return locals()[name]
    raise AttributeError(f"module 'collectors' has no attribute '{name}'")
