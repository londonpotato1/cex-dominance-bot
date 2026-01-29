"""DEX 유동성 모니터 (Phase 5b).

DexScreener API 연동:
  - 무료 API (300 req/min)
  - 6체인 지원: Ethereum, Solana, BSC, Arbitrum, Polygon, Base
  - TTL: 5분 (유동성 변동 큼)

열화 규칙:
  - API 실패 → stale 캐시 반환
  - 캐시도 없으면 → None (warning만, GO 유지)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from collectors.api_client import (
    ResilientHTTPClient,
    ResilientHTTPConfig,
    RateLimiterConfig,
    CircuitBreakerConfig,
)

logger = logging.getLogger(__name__)

# DexScreener API
_DEXSCREENER_BASE = "https://api.dexscreener.com/latest/dex"

# 지원 체인 (DexScreener chain ID)
SUPPORTED_CHAINS = [
    "ethereum",
    "solana",
    "bsc",
    "arbitrum",
    "polygon",
    "base",
]

# TTL: 5분 (DEX 유동성은 변동 큼)
_DEX_TTL = 300.0


@dataclass
class DexLiquidityResult:
    """DEX 유동성 조회 결과."""
    symbol: str
    total_liquidity_usd: float        # 총 유동성 (USD)
    total_volume_24h_usd: float       # 24h 거래량 (USD)
    pairs_count: int                  # 발견된 페어 수
    chains: list[str]                 # 유동성 있는 체인 목록
    top_pair_address: str = ""        # 최대 유동성 페어 주소
    top_pair_chain: str = ""          # 최대 유동성 페어 체인
    confidence: float = 1.0           # 신뢰도 (0.0~1.0)


class DEXMonitor:
    """DEX 유동성 모니터.

    DexScreener API를 통해 멀티체인 DEX 유동성 집계.

    사용법:
        monitor = DEXMonitor()
        result = await monitor.get_liquidity("XYZ")
        await monitor.close()
    """

    def __init__(
        self,
        client: ResilientHTTPClient | None = None,
    ) -> None:
        """
        Args:
            client: HTTP 클라이언트 (공유 가능). None이면 내부 생성.
        """
        if client is None:
            # DexScreener: 300 req/min = 5 req/sec
            config = ResilientHTTPConfig(
                rate_limiter=RateLimiterConfig(
                    tokens_per_second=5.0,
                    max_tokens=60.0,
                    name="dexscreener",
                ),
                circuit_breaker=CircuitBreakerConfig(
                    failure_threshold=5,
                    recovery_timeout=60.0,
                    name="dexscreener",
                ),
                default_ttl=_DEX_TTL,
            )
            client = ResilientHTTPClient(config, name="DEXMonitor")
            self._owns_client = True
        else:
            self._owns_client = False

        self._client = client

    async def get_liquidity(
        self,
        symbol: str,
        chains: list[str] | None = None,
    ) -> DexLiquidityResult | None:
        """토큰 심볼로 DEX 유동성 조회.

        DexScreener 토큰 검색 API 사용.
        여러 체인의 유동성을 합산.

        Args:
            symbol: 토큰 심볼 (e.g., "XYZ").
            chains: 검색할 체인 목록. None이면 전체 체인.

        Returns:
            DexLiquidityResult 또는 None (실패 시).
        """
        chains = chains or SUPPORTED_CHAINS

        url = f"{_DEXSCREENER_BASE}/search"
        params = {"q": symbol}

        data = await self._client.get(url, params=params, ttl=_DEX_TTL)
        if data is None:
            logger.warning("[DEXMonitor] API 조회 실패: %s", symbol)
            return None

        pairs = data.get("pairs", [])
        if not pairs:
            logger.debug("[DEXMonitor] 페어 없음: %s", symbol)
            return DexLiquidityResult(
                symbol=symbol,
                total_liquidity_usd=0.0,
                total_volume_24h_usd=0.0,
                pairs_count=0,
                chains=[],
                confidence=0.5,  # 페어가 없는 것이 확인됨
            )

        # 심볼 매칭 및 체인 필터링
        total_liquidity = 0.0
        total_volume = 0.0
        found_chains: set[str] = set()
        matched_pairs = 0

        top_liquidity = 0.0
        top_pair_address = ""
        top_pair_chain = ""

        for pair in pairs:
            # 심볼 매칭 (base 또는 quote)
            base_symbol = pair.get("baseToken", {}).get("symbol", "").upper()
            quote_symbol = pair.get("quoteToken", {}).get("symbol", "").upper()

            if symbol.upper() not in (base_symbol, quote_symbol):
                continue

            # 체인 필터
            chain_id = pair.get("chainId", "")
            if chain_id not in chains:
                continue

            # 유동성 / 거래량 집계
            liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
            volume_24h = float(pair.get("volume", {}).get("h24", 0) or 0)

            total_liquidity += liquidity
            total_volume += volume_24h
            found_chains.add(chain_id)
            matched_pairs += 1

            # 최대 유동성 페어 추적
            if liquidity > top_liquidity:
                top_liquidity = liquidity
                top_pair_address = pair.get("pairAddress", "")
                top_pair_chain = chain_id

        logger.info(
            "[DEXMonitor] %s: 유동성=$%.2fK, 24h=$%.2fK, %d pairs on %s",
            symbol,
            total_liquidity / 1000,
            total_volume / 1000,
            matched_pairs,
            list(found_chains),
        )

        return DexLiquidityResult(
            symbol=symbol,
            total_liquidity_usd=total_liquidity,
            total_volume_24h_usd=total_volume,
            pairs_count=matched_pairs,
            chains=list(found_chains),
            top_pair_address=top_pair_address,
            top_pair_chain=top_pair_chain,
            confidence=1.0 if matched_pairs > 0 else 0.5,
        )

    async def get_liquidity_by_address(
        self,
        token_address: str,
        chain: str,
    ) -> DexLiquidityResult | None:
        """토큰 주소로 DEX 유동성 조회.

        더 정확한 조회가 필요할 때 사용.

        Args:
            token_address: 토큰 컨트랙트 주소.
            chain: 체인 ID (e.g., "ethereum").

        Returns:
            DexLiquidityResult 또는 None.
        """
        url = f"{_DEXSCREENER_BASE}/tokens/{token_address}"

        data = await self._client.get(url, ttl=_DEX_TTL)
        if data is None:
            logger.warning(
                "[DEXMonitor] 주소 조회 실패: %s@%s", token_address, chain,
            )
            return None

        pairs = data.get("pairs", [])

        # 체인 필터링
        total_liquidity = 0.0
        total_volume = 0.0
        matched_pairs = 0
        symbol = ""

        top_liquidity = 0.0
        top_pair_address = ""

        for pair in pairs:
            pair_chain = pair.get("chainId", "")
            if chain and pair_chain != chain:
                continue

            if not symbol:
                # 첫 번째 페어에서 심볼 추출
                base = pair.get("baseToken", {})
                quote = pair.get("quoteToken", {})
                if base.get("address", "").lower() == token_address.lower():
                    symbol = base.get("symbol", "")
                else:
                    symbol = quote.get("symbol", "")

            liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
            volume_24h = float(pair.get("volume", {}).get("h24", 0) or 0)

            total_liquidity += liquidity
            total_volume += volume_24h
            matched_pairs += 1

            if liquidity > top_liquidity:
                top_liquidity = liquidity
                top_pair_address = pair.get("pairAddress", "")

        if matched_pairs == 0:
            logger.debug(
                "[DEXMonitor] 페어 없음: %s@%s", token_address, chain,
            )
            return None

        logger.info(
            "[DEXMonitor] %s@%s: 유동성=$%.2fK, %d pairs",
            symbol or token_address[:8], chain,
            total_liquidity / 1000, matched_pairs,
        )

        return DexLiquidityResult(
            symbol=symbol or token_address[:8],
            total_liquidity_usd=total_liquidity,
            total_volume_24h_usd=total_volume,
            pairs_count=matched_pairs,
            chains=[chain] if chain else [],
            top_pair_address=top_pair_address,
            top_pair_chain=chain,
            confidence=1.0,
        )

    async def close(self) -> None:
        """클라이언트 종료."""
        if self._owns_client:
            await self._client.close()
