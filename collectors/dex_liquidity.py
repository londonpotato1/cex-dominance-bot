"""DEX 유동성 수집기 (DexScreener API).

상장 전 GO/NO-GO 판단의 핵심 요소.
- 500k 이하: GO (물량 부족 → 흥따리 가능성)
- 1M 이상: NO-GO (후따리 물량 충분)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# DexScreener API (무료, rate limit 주의)
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex"


@dataclass
class DexPair:
    """DEX 페어 정보."""
    pair_address: str
    base_token: str
    quote_token: str
    chain: str
    dex: str
    price_usd: float
    liquidity_usd: float
    volume_24h: float
    price_change_24h: float
    url: str
    timestamp: datetime

    @property
    def liquidity_level(self) -> str:
        """유동성 수준 판단."""
        if self.liquidity_usd < 200_000:
            return "very_low"  # 매우 적음 - 강력 GO
        elif self.liquidity_usd < 500_000:
            return "low"  # 적음 - GO
        elif self.liquidity_usd < 1_000_000:
            return "medium"  # 중간 - 주의
        else:
            return "high"  # 많음 - NO-GO


@dataclass 
class DexLiquidityResult:
    """DEX 유동성 조회 결과."""
    symbol: str
    total_liquidity_usd: float
    total_volume_24h: float
    pair_count: int
    pairs: list[DexPair]
    best_pair: Optional[DexPair]
    timestamp: datetime

    @property
    def go_signal(self) -> str:
        """GO/NO-GO 신호."""
        if self.total_liquidity_usd < 200_000:
            return "STRONG_GO"  # 🟢🟢 강력 GO
        elif self.total_liquidity_usd < 500_000:
            return "GO"  # 🟢 GO
        elif self.total_liquidity_usd < 1_000_000:
            return "CAUTION"  # 🟡 주의
        else:
            return "NO_GO"  # 🔴 NO-GO

    @property
    def go_emoji(self) -> str:
        """GO 신호 이모지."""
        return {
            "STRONG_GO": "🟢🟢",
            "GO": "🟢",
            "CAUTION": "🟡",
            "NO_GO": "🔴",
        }.get(self.go_signal, "❓")


async def search_token(query: str) -> list[dict]:
    """토큰 검색 (심볼 또는 주소)."""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{DEXSCREENER_API}/search?q={query}"
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", [])
    except Exception as e:
        logger.warning(f"DexScreener 검색 실패: {e}")
    return []


async def get_token_pairs(token_address: str) -> list[dict]:
    """토큰 주소로 페어 조회."""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{DEXSCREENER_API}/tokens/{token_address}"
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", [])
    except Exception as e:
        logger.warning(f"DexScreener 토큰 조회 실패: {e}")
    return []


def _parse_pair(raw: dict) -> Optional[DexPair]:
    """API 응답을 DexPair로 변환."""
    try:
        return DexPair(
            pair_address=raw.get("pairAddress", ""),
            base_token=raw.get("baseToken", {}).get("symbol", ""),
            quote_token=raw.get("quoteToken", {}).get("symbol", ""),
            chain=raw.get("chainId", ""),
            dex=raw.get("dexId", ""),
            price_usd=float(raw.get("priceUsd", 0) or 0),
            liquidity_usd=float(raw.get("liquidity", {}).get("usd", 0) or 0),
            volume_24h=float(raw.get("volume", {}).get("h24", 0) or 0),
            price_change_24h=float(raw.get("priceChange", {}).get("h24", 0) or 0),
            url=raw.get("url", ""),
            timestamp=datetime.now(),
        )
    except Exception as e:
        logger.warning(f"페어 파싱 실패: {e}")
        return None


async def _search_with_symbol(symbol: str, original_symbol: str) -> list[DexPair]:
    """특정 심볼로 검색 후 페어 파싱."""
    raw_pairs = await search_token(symbol)
    
    pairs = []
    for raw in raw_pairs:
        base_symbol = raw.get("baseToken", {}).get("symbol", "").upper()
        # 원본 심볼 또는 검색 심볼과 일치
        if base_symbol == original_symbol.upper() or base_symbol == symbol.upper():
            pair = _parse_pair(raw)
            if pair:
                pairs.append(pair)
    
    return pairs


# 심볼 변환 규칙 (알려진 래핑/변형 토큰)
SYMBOL_ALIASES = {
    # 래핑 토큰
    "BTC": ["WBTC", "BTCB", "tBTC"],
    "ETH": ["WETH", "stETH", "wstETH"],
    "SOL": ["WSOL", "mSOL"],
    "AVAX": ["WAVAX"],
    "BNB": ["WBNB"],
    "MATIC": ["WMATIC", "POL"],
    "POL": ["WMATIC", "MATIC"],
    # 특수 케이스
    "USDT": ["USDT.e", "USDTe"],
    "USDC": ["USDC.e", "USDCe", "USDbC"],
}


async def get_dex_liquidity(
    symbol: str, 
    chain: Optional[str] = None,
    try_aliases: bool = True
) -> Optional[DexLiquidityResult]:
    """심볼로 DEX 유동성 조회 (자동 보정 포함).
    
    검색 실패 시 자동으로 대안 시도:
    1. 원본 심볼 검색
    2. 래핑 토큰 시도 (WBTC, WETH 등)
    3. 알려진 별칭 시도
    
    Args:
        symbol: 토큰 심볼 (예: "AVAIL", "ME", "NXPC")
        chain: 특정 체인만 검색 (예: "ethereum", "solana")
        try_aliases: 별칭 검색 시도 여부
    
    Returns:
        DexLiquidityResult 또는 None
    """
    original_symbol = symbol.upper()
    all_pairs = []
    searched_symbols = [original_symbol]
    
    # 1. 원본 심볼 검색
    pairs = await _search_with_symbol(symbol, original_symbol)
    all_pairs.extend(pairs)
    
    # 2. 결과 없으면 래핑 토큰 시도 (W prefix)
    if not all_pairs and try_aliases:
        wrapped_symbol = f"W{original_symbol}"
        if wrapped_symbol not in searched_symbols:
            searched_symbols.append(wrapped_symbol)
            pairs = await _search_with_symbol(wrapped_symbol, original_symbol)
            all_pairs.extend(pairs)
    
    # 3. 알려진 별칭 시도
    if not all_pairs and try_aliases:
        aliases = SYMBOL_ALIASES.get(original_symbol, [])
        for alias in aliases:
            if alias not in searched_symbols:
                searched_symbols.append(alias)
                pairs = await _search_with_symbol(alias, original_symbol)
                all_pairs.extend(pairs)
                if pairs:
                    break  # 찾으면 중단
    
    if not all_pairs:
        logger.info(f"DEX 페어 없음: {symbol} (시도: {searched_symbols})")
        return None
    
    # 체인 필터링 (선택적)
    if chain:
        all_pairs = [p for p in all_pairs if p.chain.lower() == chain.lower()]
        if not all_pairs:
            logger.info(f"{symbol}: {chain} 체인에서 페어 없음")
            return None
    
    # 중복 제거 (pair_address 기준)
    seen_addresses = set()
    unique_pairs = []
    for p in all_pairs:
        if p.pair_address not in seen_addresses:
            seen_addresses.add(p.pair_address)
            unique_pairs.append(p)
    
    # 유동성 합산
    total_liquidity = sum(p.liquidity_usd for p in unique_pairs)
    total_volume = sum(p.volume_24h for p in unique_pairs)
    
    # 최고 유동성 페어
    best_pair = max(unique_pairs, key=lambda p: p.liquidity_usd) if unique_pairs else None
    
    return DexLiquidityResult(
        symbol=original_symbol,
        total_liquidity_usd=total_liquidity,
        total_volume_24h=total_volume,
        pair_count=len(unique_pairs),
        pairs=unique_pairs,
        best_pair=best_pair,
        timestamp=datetime.now(),
    )


def format_liquidity_report(result: DexLiquidityResult) -> str:
    """유동성 리포트 포맷."""
    lines = [
        f"📊 DEX 유동성 리포트: {result.symbol}",
        f"",
        f"{result.go_emoji} 신호: {result.go_signal}",
        f"💰 총 유동성: ${result.total_liquidity_usd:,.0f}",
        f"📈 24h 거래량: ${result.total_volume_24h:,.0f}",
        f"🔗 페어 수: {result.pair_count}개",
    ]
    
    if result.best_pair:
        bp = result.best_pair
        lines.extend([
            f"",
            f"🏆 최대 유동성 페어:",
            f"   {bp.dex} ({bp.chain})",
            f"   ${bp.liquidity_usd:,.0f} 유동성",
            f"   {bp.url}",
        ])
    
    # GO/NO-GO 해석
    lines.append("")
    if result.go_signal == "STRONG_GO":
        lines.append("💡 해석: DEX 유동성 매우 적음 → 후따리 어려움 → 흥따리 가능성 높음")
    elif result.go_signal == "GO":
        lines.append("💡 해석: DEX 유동성 적음 → 흥따리 가능성 있음")
    elif result.go_signal == "CAUTION":
        lines.append("💡 해석: DEX 유동성 중간 → 다른 요소 함께 고려 필요")
    else:
        lines.append("💡 해석: DEX 유동성 충분 → 후따리 쉬움 → 망따리 주의")
    
    return "\n".join(lines)


# 테스트
if __name__ == "__main__":
    async def test():
        symbols = ["AVAIL", "ME", "NXPC", "VIRTUAL"]
        for symbol in symbols:
            print(f"\n{'='*50}")
            result = await get_dex_liquidity(symbol)
            if result:
                print(format_liquidity_report(result))
            else:
                print(f"❌ {symbol}: 데이터 없음")
    
    asyncio.run(test())
