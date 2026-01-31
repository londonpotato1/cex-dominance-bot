#!/usr/bin/env python3
"""Phase 5b External Data Collectors 테스트.

Usage:
    python scripts/test_phase5b.py [--live]

Options:
    --live    실제 API 호출 (기본: Mock 테스트만)
"""

import asyncio
import logging
import sys
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, patch, MagicMock
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# 1. CircuitBreaker 테스트
# =============================================================================

def test_circuit_breaker_states():
    """CircuitBreaker 상태 전환 테스트."""
    from collectors.api_client import (
        CircuitBreaker,
        CircuitBreakerConfig,
        CircuitState,
    )

    config = CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=0.1,  # 테스트용 짧은 타임아웃
        half_open_max=2,
        name="test",
    )
    cb = CircuitBreaker(config)

    # 초기 상태: CLOSED
    assert cb.state == CircuitState.CLOSED, "초기 상태는 CLOSED"
    assert not cb.is_open, "CLOSED 상태에서 is_open=False"

    # 실패 누적 → OPEN
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN, "3회 실패 후 OPEN"
    assert cb.is_open, "OPEN 상태에서 is_open=True"

    # recovery_timeout 경과 → HALF_OPEN
    time.sleep(0.15)
    assert not cb.is_open, "타임아웃 후 HALF_OPEN (is_open=False)"
    assert cb.state == CircuitState.HALF_OPEN, "HALF_OPEN 상태"

    # HALF_OPEN에서 성공 → CLOSED
    cb.record_success()
    cb.record_success()
    assert cb.state == CircuitState.CLOSED, "2회 성공 후 CLOSED"

    logger.info("✓ CircuitBreaker 상태 전환 테스트 통과")


# =============================================================================
# 2. RateLimiter 테스트
# =============================================================================

async def test_rate_limiter():
    """RateLimiter Token Bucket 테스트."""
    from collectors.api_client import RateLimiter, RateLimiterConfig

    config = RateLimiterConfig(
        tokens_per_second=10.0,
        max_tokens=5.0,  # 버스트 5개
        name="test",
    )
    limiter = RateLimiter(config)

    # 버스트: 5개 즉시 획득
    for i in range(5):
        acquired = await limiter.acquire(wait=False)
        assert acquired, f"버스트 토큰 {i+1} 획득 실패"

    # 6번째는 실패 (wait=False)
    acquired = await limiter.acquire(wait=False)
    assert not acquired, "버스트 초과 시 획득 실패"

    # 대기 후 획득
    start = time.time()
    acquired = await limiter.acquire(wait=True)
    elapsed = time.time() - start
    assert acquired, "대기 후 획득 성공"
    assert elapsed >= 0.05, f"대기 시간 확인 (elapsed={elapsed:.3f}s)"

    logger.info("✓ RateLimiter 테스트 통과")


# =============================================================================
# 3. DEXMonitor Mock 테스트
# =============================================================================

async def test_dex_monitor_mock():
    """DEXMonitor Mock 테스트."""
    from collectors.dex_monitor import DEXMonitor

    # Mock 응답
    mock_response = {
        "pairs": [
            {
                "chainId": "ethereum",
                "pairAddress": "0x1234",
                "baseToken": {"symbol": "XYZ"},
                "quoteToken": {"symbol": "WETH"},
                "liquidity": {"usd": 500000},
                "volume": {"h24": 100000},
            },
            {
                "chainId": "arbitrum",
                "pairAddress": "0x5678",
                "baseToken": {"symbol": "XYZ"},
                "quoteToken": {"symbol": "USDC"},
                "liquidity": {"usd": 200000},
                "volume": {"h24": 50000},
            },
        ]
    }

    monitor = DEXMonitor()

    with patch.object(
        monitor._client, "get", new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = mock_response

        result = await monitor.get_liquidity("XYZ")

        assert result is not None, "결과 존재"
        assert result.total_liquidity_usd == 700000, "유동성 합계"
        assert result.total_volume_24h_usd == 150000, "거래량 합계"
        assert result.pairs_count == 2, "페어 수"
        assert "ethereum" in result.chains, "이더리움 체인"
        assert "arbitrum" in result.chains, "아비트럼 체인"

    await monitor.close()
    logger.info("✓ DEXMonitor Mock 테스트 통과")


# =============================================================================
# 4. WithdrawalTracker Mock 테스트
# =============================================================================

async def test_withdrawal_tracker_mock():
    """WithdrawalTracker Mock 테스트."""
    from collectors.withdrawal_tracker import WithdrawalTracker

    # Upbit /v1/market/all Mock 응답 (Public API)
    upbit_response = [
        {
            "market": "KRW-XYZ",
            "korean_name": "XYZ토큰",
            "english_name": "XYZ Token",
            "market_warning": "NONE",
        },
        {
            "market": "KRW-ABC",
            "korean_name": "ABC토큰",
            "english_name": "ABC Token",
            "market_warning": "CAUTION",  # 주의 종목
        },
    ]

    tracker = WithdrawalTracker()

    with patch.object(
        tracker._client, "get", new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = upbit_response

        result = await tracker.get_exchange_status("XYZ", "upbit")

        assert result is not None, "결과 존재"
        assert result.symbol == "XYZ", "심볼 일치"
        assert result.deposit_open is True, "입금 가능"
        assert result.withdrawal_open is True, "출금 가능"
        assert result.confidence == 0.5, "Public API 신뢰도 0.5"

        # 주의 종목 테스트
        result2 = await tracker.get_exchange_status("ABC", "upbit")
        assert result2 is not None
        assert result2.deposit_open is False, "입금 불가 (CAUTION)"
        assert result2.withdrawal_open is False, "출금 불가 (CAUTION)"

    await tracker.close()
    logger.info("✓ WithdrawalTracker Mock 테스트 통과")


# =============================================================================
# 5. 열화 규칙 테스트
# =============================================================================

async def test_graceful_degradation():
    """API 실패 시 열화 규칙 테스트."""
    from collectors.dex_monitor import DEXMonitor

    monitor = DEXMonitor()

    with patch.object(
        monitor._client, "get", new_callable=AsyncMock,
    ) as mock_get:
        # API 실패
        mock_get.return_value = None

        result = await monitor.get_liquidity("XYZ")

        # 실패해도 None 반환 (예외 발생 안 함)
        assert result is None, "API 실패 시 None 반환"

    await monitor.close()
    logger.info("✓ 열화 규칙 테스트 통과")


# =============================================================================
# 6. Live API 테스트 (선택적)
# =============================================================================

async def test_dex_monitor_live():
    """DEXMonitor 실제 API 테스트."""
    from collectors.dex_monitor import DEXMonitor

    monitor = DEXMonitor()

    try:
        # 잘 알려진 토큰으로 테스트
        result = await monitor.get_liquidity("PEPE")

        if result:
            logger.info(
                "PEPE DEX 유동성: $%.2fK, %d pairs on %s",
                result.total_liquidity_usd / 1000,
                result.pairs_count,
                result.chains,
            )
            assert result.pairs_count > 0, "PEPE 페어 존재"
        else:
            logger.warning("PEPE DEX 데이터 없음 (API 제한일 수 있음)")

    finally:
        await monitor.close()

    logger.info("✓ DEXMonitor Live 테스트 완료")


async def test_withdrawal_tracker_live():
    """WithdrawalTracker 실제 API 테스트 (Upbit)."""
    from collectors.withdrawal_tracker import WithdrawalTracker

    tracker = WithdrawalTracker()

    try:
        # BTC 상태 조회 (항상 존재)
        result = await tracker.get_exchange_status("BTC", "upbit")

        if result:
            logger.info(
                "Upbit BTC: deposit=%s, withdraw=%s, confidence=%.1f",
                result.deposit_open,
                result.withdrawal_open,
                result.confidence,
            )
            # Public API는 신뢰도 0.5 (정확한 상태는 인증 필요)
            assert result.confidence >= 0, "신뢰도 존재"
        else:
            logger.warning("Upbit API 실패")

    finally:
        await tracker.close()

    logger.info("✓ WithdrawalTracker Live 테스트 완료")


# =============================================================================
# 메인
# =============================================================================

async def run_mock_tests():
    """Mock 테스트 실행."""
    logger.info("=" * 60)
    logger.info("Phase 5b Mock 테스트 시작")
    logger.info("=" * 60)

    test_circuit_breaker_states()
    await test_rate_limiter()
    await test_dex_monitor_mock()
    await test_withdrawal_tracker_mock()
    await test_graceful_degradation()

    logger.info("=" * 60)
    logger.info("✓ 모든 Mock 테스트 통과!")
    logger.info("=" * 60)


async def run_live_tests():
    """Live API 테스트 실행."""
    logger.info("=" * 60)
    logger.info("Phase 5b Live API 테스트 시작")
    logger.info("=" * 60)

    await test_dex_monitor_live()
    await test_withdrawal_tracker_live()

    logger.info("=" * 60)
    logger.info("✓ Live API 테스트 완료!")
    logger.info("=" * 60)


async def main():
    """메인 함수."""
    live_mode = "--live" in sys.argv

    await run_mock_tests()

    if live_mode:
        await run_live_tests()
    else:
        logger.info("(Live 테스트 건너뜀 — --live 옵션으로 실행)")


if __name__ == "__main__":
    asyncio.run(main())
