"""pytest 공통 fixture (Phase 7).

CoinGecko API 429 rate limit 대응을 위한 mock 데이터 제공.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import Any


# =============================================================================
# CoinGecko Mock 데이터
# =============================================================================

# 토큰별 CoinGecko 응답 mock 데이터
_MOCK_COIN_DATA: dict[str, dict[str, Any]] = {
    "matic-network": {
        "id": "matic-network",
        "symbol": "matic",
        "name": "Polygon",
        "market_data": {
            "current_price": {"usd": 0.65},
            "market_cap": {"usd": 6_500_000_000},
            "fully_diluted_valuation": {"usd": 6_500_000_000},
            "total_volume": {"usd": 250_000_000},
            "circulating_supply": 10_000_000_000,
            "total_supply": 10_000_000_000,
            "max_supply": 10_000_000_000,
        },
    },
    "starknet": {
        "id": "starknet",
        "symbol": "strk",
        "name": "Starknet",
        "market_data": {
            "current_price": {"usd": 0.45},
            "market_cap": {"usd": 900_000_000},
            "fully_diluted_valuation": {"usd": 4_500_000_000},
            "total_volume": {"usd": 50_000_000},
            "circulating_supply": 2_000_000_000,
            "total_supply": 10_000_000_000,
            "max_supply": 10_000_000_000,
        },
    },
    "moca-network": {
        "id": "moca-network",
        "symbol": "moca",
        "name": "Moca Network",
        "market_data": {
            "current_price": {"usd": 0.08},
            "market_cap": {"usd": 160_000_000},
            "fully_diluted_valuation": {"usd": 800_000_000},
            "total_volume": {"usd": 20_000_000},
            "circulating_supply": 2_000_000_000,
            "total_supply": 10_000_000_000,
            "max_supply": 10_000_000_000,
        },
    },
    "bitcoin": {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "market_data": {
            "current_price": {"usd": 100_000},
            "market_cap": {"usd": 2_000_000_000_000},
            "fully_diluted_valuation": {"usd": 2_100_000_000_000},
            "total_volume": {"usd": 30_000_000_000},
            "circulating_supply": 19_600_000,
            "total_supply": 21_000_000,
            "max_supply": 21_000_000,
        },
    },
    "ethereum": {
        "id": "ethereum",
        "symbol": "eth",
        "name": "Ethereum",
        "market_data": {
            "current_price": {"usd": 3_500},
            "market_cap": {"usd": 420_000_000_000},
            "fully_diluted_valuation": {"usd": 420_000_000_000},
            "total_volume": {"usd": 15_000_000_000},
            "circulating_supply": 120_000_000,
            "total_supply": 120_000_000,
            "max_supply": None,
        },
    },
    "arbitrum": {
        "id": "arbitrum",
        "symbol": "arb",
        "name": "Arbitrum",
        "market_data": {
            "current_price": {"usd": 0.80},
            "market_cap": {"usd": 3_200_000_000},
            "fully_diluted_valuation": {"usd": 8_000_000_000},
            "total_volume": {"usd": 200_000_000},
            "circulating_supply": 4_000_000_000,
            "total_supply": 10_000_000_000,
            "max_supply": 10_000_000_000,
        },
    },
}

# 심볼 → CoinGecko ID 매핑
_SYMBOL_TO_ID: dict[str, str] = {
    "MATIC": "matic-network",
    "STRK": "starknet",
    "MOCA": "moca-network",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "ARB": "arbitrum",
}


# =============================================================================
# Mock CoinGeckoCache 클래스
# =============================================================================


class MockCoinGeckoCache:
    """테스트용 CoinGecko 캐시 mock.

    실제 API 호출 없이 사전 정의된 데이터 반환.
    """

    def __init__(self) -> None:
        self._api_key = None
        self._cache: dict[str, Any] = {}
        self._rate_limited_until: float = 0.0

    async def get(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
        ttl: float = 3600,
    ) -> Any | None:
        """Mock API 호출."""
        # /coins/{coin_id} 엔드포인트 처리
        if endpoint.startswith("/coins/") and not endpoint.endswith("/markets"):
            coin_id = endpoint.split("/")[-1]
            return _MOCK_COIN_DATA.get(coin_id)

        # /coins/markets 엔드포인트 처리
        if endpoint == "/coins/markets":
            return list(_MOCK_COIN_DATA.values())

        # /search 엔드포인트 처리
        if endpoint == "/search":
            query = params.get("query", "").upper() if params else ""
            coin_id = _SYMBOL_TO_ID.get(query)
            if coin_id:
                return {
                    "coins": [{"id": coin_id, "symbol": query.lower()}]
                }
            return {"coins": []}

        return None

    async def get_coin_data(self, coin_id: str) -> dict | None:
        """코인 상세 데이터 조회 mock."""
        return _MOCK_COIN_DATA.get(coin_id)

    async def get_coin_market_data(
        self,
        vs_currency: str = "usd",
        ids: str | None = None,
        per_page: int = 250,
        page: int = 1,
    ) -> list[dict] | None:
        """코인 마켓 데이터 목록 조회 mock."""
        if ids:
            id_list = ids.split(",")
            return [
                _MOCK_COIN_DATA[cid]
                for cid in id_list
                if cid in _MOCK_COIN_DATA
            ]
        return list(_MOCK_COIN_DATA.values())

    async def close(self) -> None:
        """세션 종료 (no-op)."""
        pass

    def invalidate(self, endpoint: str, params: dict[str, str] | None = None) -> None:
        """캐시 무효화 (no-op)."""
        pass

    def clear(self) -> None:
        """캐시 초기화 (no-op)."""
        pass


# =============================================================================
# Pytest Fixtures
# =============================================================================


@pytest.fixture
def mock_coingecko_cache():
    """CoinGecko mock 캐시 fixture.

    Usage:
        def test_something(mock_coingecko_cache):
            result = await get_tokenomics("BTC", mock_coingecko_cache)
    """
    return MockCoinGeckoCache()


@pytest.fixture
def coingecko_cache_with_fallback(monkeypatch):
    """실제 CoinGeckoCache를 mock으로 교체하는 fixture.

    테스트에서 CoinGeckoCache()를 직접 생성해도 mock이 사용됨.

    Usage:
        def test_something(coingecko_cache_with_fallback):
            cache = CoinGeckoCache()  # MockCoinGeckoCache 반환됨
    """
    monkeypatch.setattr(
        "store.cache.CoinGeckoCache",
        MockCoinGeckoCache,
    )
    return MockCoinGeckoCache


@pytest.fixture
def mock_coin_data():
    """토큰별 mock 데이터 접근용 fixture."""
    return _MOCK_COIN_DATA.copy()


@pytest.fixture
def symbol_to_coingecko_id():
    """심볼 → CoinGecko ID 매핑 접근용 fixture."""
    return _SYMBOL_TO_ID.copy()
