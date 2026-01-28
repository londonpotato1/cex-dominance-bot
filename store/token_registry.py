"""토큰 식별 기반 (Phase 2: Writer Queue 경유 + CoinGecko 부트스트랩)."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from store.writer import DatabaseWriter

logger = logging.getLogger(__name__)

_INSERT_TOKEN_SQL = (
    "INSERT OR IGNORE INTO token_registry "
    "(symbol, coingecko_id, name, chain, contract_address, decimals) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)

# CoinGecko API (Free tier: 10-50 calls/min)
_CG_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
_CG_SEARCH_URL = "https://api.coingecko.com/api/v3/search"
_CG_COIN_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}"


@dataclass(frozen=True)
class ChainInfo:
    """토큰의 체인별 정보."""
    chain: str                         # 'ethereum', 'solana', 'bsc'
    contract_address: str
    decimals: int = 18


@dataclass
class TokenIdentity:
    """토큰 식별 정보."""
    symbol: str
    coingecko_id: Optional[str] = None
    name: Optional[str] = None
    chains: list[ChainInfo] = field(default_factory=list)


class TokenRegistry:
    """토큰 레지스트리 (읽기 + Writer Queue 쓰기).

    Phase 2: Writer Queue 경유 insert_async() 추가.
    기존 insert()는 Writer 가동 전 초기 적재 전용으로 유지.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        writer: Optional[DatabaseWriter] = None,
    ) -> None:
        """
        Args:
            conn: 읽기용 커넥션.
            writer: Phase 2 Writer Queue 경유 쓰기용. None이면 insert_async 사용 불가.
        """
        self._conn = conn
        self._writer = writer

    def get_by_symbol(self, symbol: str) -> Optional[TokenIdentity]:
        """심볼로 토큰 조회. 여러 체인에 존재하면 chains에 모두 포함."""
        rows = self._conn.execute(
            "SELECT symbol, coingecko_id, name, chain, contract_address, decimals "
            "FROM token_registry WHERE symbol = ?",
            (symbol,),
        ).fetchall()

        if not rows:
            return None

        first = rows[0]
        token = TokenIdentity(
            symbol=first["symbol"],
            coingecko_id=first["coingecko_id"],
            name=first["name"],
        )
        for row in rows:
            if row["chain"]:
                token.chains.append(
                    ChainInfo(
                        chain=row["chain"],
                        contract_address=row["contract_address"] or "",
                        decimals=row["decimals"] or 18,
                    )
                )
        return token

    def get_all(self) -> list[TokenIdentity]:
        """전체 토큰 목록 조회."""
        rows = self._conn.execute(
            "SELECT symbol, coingecko_id, name, chain, contract_address, decimals "
            "FROM token_registry ORDER BY symbol"
        ).fetchall()

        tokens: dict[str, TokenIdentity] = {}
        for row in rows:
            sym = row["symbol"]
            if sym not in tokens:
                tokens[sym] = TokenIdentity(
                    symbol=sym,
                    coingecko_id=row["coingecko_id"],
                    name=row["name"],
                )
            if row["chain"]:
                tokens[sym].chains.append(
                    ChainInfo(
                        chain=row["chain"],
                        contract_address=row["contract_address"] or "",
                        decimals=row["decimals"] or 18,
                    )
                )

        return list(tokens.values())

    def insert(self, token: TokenIdentity) -> None:
        """토큰 수동 등록 — 서비스 가동 전 초기 적재 전용.

        Single Writer 원칙 예외:
            이 메서드는 Writer Queue를 경유하지 않고 직접 커밋한다.
            반드시 Writer 가동 전(서비스 시작 전)에만 호출할 것.
            Writer 가동 중 호출 금지 — 동시 쓰기로 WAL 충돌 가능.

        chains가 비어있으면 chain=NULL로 1행 INSERT.
        """
        if not token.chains:
            self._conn.execute(
                "INSERT OR IGNORE INTO token_registry "
                "(symbol, coingecko_id, name, chain, contract_address, decimals) "
                "VALUES (?, ?, ?, '', '', 18)",
                (token.symbol, token.coingecko_id, token.name),
            )
        else:
            for ci in token.chains:
                self._conn.execute(
                    "INSERT OR IGNORE INTO token_registry "
                    "(symbol, coingecko_id, name, chain, contract_address, decimals) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        token.symbol,
                        token.coingecko_id,
                        token.name,
                        ci.chain,
                        ci.contract_address,
                        ci.decimals,
                    ),
                )
        self._conn.commit()
        logger.info("토큰 등록: %s (%d chains)", token.symbol, len(token.chains))

    async def insert_async(self, token: TokenIdentity) -> None:
        """Writer Queue 경유 INSERT (서비스 가동 중 사용).

        Args:
            token: 등록할 토큰 정보.

        Raises:
            RuntimeError: Writer 미설정 시.
        """
        if self._writer is None:
            raise RuntimeError("Writer 미설정 — insert_async 호출 불가")

        if not token.chains:
            await self._writer.enqueue(
                _INSERT_TOKEN_SQL,
                (token.symbol, token.coingecko_id, token.name, "", "", 18),
            )
        else:
            for ci in token.chains:
                await self._writer.enqueue(
                    _INSERT_TOKEN_SQL,
                    (
                        token.symbol,
                        token.coingecko_id,
                        token.name,
                        ci.chain,
                        ci.contract_address,
                        ci.decimals,
                    ),
                )
        logger.info("토큰 등록 (async): %s (%d chains)", token.symbol, len(token.chains))


# ---- 모듈 레벨 함수 ----


async def bootstrap_top_tokens(
    registry: TokenRegistry,
    limit: int = 500,
) -> int:
    """CoinGecko 상위 토큰 자동 등록.

    데몬 시작 시 1회 호출. 이미 등록된 토큰은 skip (INSERT OR IGNORE).
    Writer Queue가 반드시 활성화된 상태에서 호출해야 한다.

    Args:
        registry: TokenRegistry 인스턴스 (Writer 설정 필수).
        limit: 시딩할 토큰 수 (기본 500).

    Returns:
        신규 등록 시도한 토큰 수.

    Raises:
        RuntimeError: Writer 미설정 시.
    """
    if registry._writer is None:
        raise RuntimeError(
            "bootstrap_top_tokens()은 Writer 가동 후 호출 필수"
        )

    registered = 0
    per_page = 250
    pages = (limit + per_page - 1) // per_page  # ceil division

    try:
        async with aiohttp.ClientSession() as session:
            for page in range(1, pages + 1):
                try:
                    params = {
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": str(per_page),
                        "page": str(page),
                        "sparkline": "false",
                    }
                    async with session.get(
                        _CG_MARKETS_URL, params=params, timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        if resp.status != 200:
                            logger.warning(
                                "CoinGecko markets API 실패: status=%d (page %d)",
                                resp.status, page,
                            )
                            break
                        coins = await resp.json()

                    for coin in coins:
                        symbol = coin.get("symbol", "").upper()
                        cg_id = coin.get("id", "")
                        name = coin.get("name", "")

                        if not symbol or not cg_id:
                            continue

                        token = TokenIdentity(
                            symbol=symbol,
                            coingecko_id=cg_id,
                            name=name,
                        )

                        try:
                            await registry.insert_async(token)
                            registered += 1
                        except Exception as e:
                            logger.debug("토큰 등록 실패 (%s): %s", symbol, e)

                    # Rate limit 배려: 페이지 간 2초 대기
                    if page < pages:
                        await asyncio.sleep(2.0)

                except asyncio.TimeoutError:
                    logger.warning("CoinGecko API 타임아웃 (page %d)", page)
                    break
                except aiohttp.ClientError as e:
                    logger.warning("CoinGecko API 에러 (page %d): %s", page, e)
                    break

    except Exception as e:
        logger.warning("CoinGecko 부트스트랩 실패: %s", e)

    logger.info("CoinGecko 부트스트랩 완료: %d개 토큰 등록 시도", registered)
    return registered


async def fetch_token_by_symbol(symbol: str) -> Optional[TokenIdentity]:
    """CoinGecko에서 심볼로 토큰 정보 조회 (상장 감지 시 사용).

    Args:
        symbol: 토큰 심볼 (예: "BTC", "ETH").

    Returns:
        TokenIdentity 또는 조회 실패 시 None.
    """
    try:
        async with aiohttp.ClientSession() as session:
            # 1. 심볼 검색
            async with session.get(
                _CG_SEARCH_URL,
                params={"query": symbol},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            coins = data.get("coins", [])
            if not coins:
                return None

            # 심볼이 정확히 일치하는 첫 번째 결과 우선
            coin_id = None
            coin_name = None
            for c in coins:
                if c.get("symbol", "").upper() == symbol.upper():
                    coin_id = c.get("id")
                    coin_name = c.get("name")
                    break

            if not coin_id:
                coin_id = coins[0].get("id")
                coin_name = coins[0].get("name")

            if not coin_id:
                return None

            # 2. 상세 조회 (플랫폼 정보 포함)
            await asyncio.sleep(0.5)  # Rate limit
            async with session.get(
                _CG_COIN_URL.format(coin_id=coin_id),
                params={"localization": "false", "tickers": "false",
                        "market_data": "false", "community_data": "false",
                        "developer_data": "false"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    # 상세 조회 실패해도 최소 정보로 반환
                    return TokenIdentity(
                        symbol=symbol.upper(),
                        coingecko_id=coin_id,
                        name=coin_name,
                    )
                detail = await resp.json()

            # 플랫폼 정보 추출
            platforms = detail.get("platforms", {})
            chains: list[ChainInfo] = []
            for chain_name, address in platforms.items():
                if chain_name and address:
                    chains.append(ChainInfo(
                        chain=chain_name,
                        contract_address=address,
                    ))

            return TokenIdentity(
                symbol=symbol.upper(),
                coingecko_id=coin_id,
                name=detail.get("name", coin_name),
                chains=chains,
            )

    except Exception as e:
        logger.warning("CoinGecko 토큰 조회 실패 (%s): %s", symbol, e)
        return None
