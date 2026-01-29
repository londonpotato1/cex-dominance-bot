"""핫월렛 잔액 추적기 (Phase 5b).

Alchemy RPC 연동:
  - 무료 티어: 300M compute units/month
  - EVM 4체인 지원: Ethereum, Arbitrum, Polygon, Base
  - TTL: 15분 (온체인 데이터 상대적 안정)

열화 규칙:
  - RPC 실패 → stale 캐시 반환
  - API 키 없으면 → 기능 비활성화 (warning)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from collectors.api_client import (
    ResilientHTTPClient,
    ResilientHTTPConfig,
    RateLimiterConfig,
    CircuitBreakerConfig,
    get_api_key,
)

logger = logging.getLogger(__name__)

# TTL: 15분 (핫월렛 잔액은 상대적 안정)
_HOT_WALLET_TTL = 900.0

# ERC-20 balanceOf 함수 시그니처
_BALANCE_OF_SELECTOR = "0x70a08231"  # balanceOf(address)

# 네이티브 토큰 주소 (placeholder)
_NATIVE_TOKEN = "0x0000000000000000000000000000000000000000"


@dataclass
class WalletBalance:
    """단일 지갑 잔액."""
    address: str
    label: str
    chain: str
    balance_raw: int           # 원본 잔액 (wei/smallest unit)
    balance_usd: float = 0.0   # USD 환산 (가격 데이터 있을 때)
    token_address: str = ""    # 토큰 주소 (native면 빈 문자열)
    token_symbol: str = ""     # 토큰 심볼


@dataclass
class HotWalletResult:
    """핫월렛 조회 결과."""
    symbol: str
    exchange: str                                # 거래소 ID
    total_balance_usd: float                     # 총 USD 잔액
    balances: list[WalletBalance] = field(default_factory=list)
    chains_checked: list[str] = field(default_factory=list)
    confidence: float = 1.0                      # 신뢰도


class HotWalletTracker:
    """거래소 핫월렛 잔액 추적기.

    Alchemy RPC를 사용하여 EVM 체인의 거래소 핫월렛 잔액 조회.

    사용법:
        tracker = HotWalletTracker()
        result = await tracker.get_balance("XYZ", "binance")
        await tracker.close()
    """

    def __init__(
        self,
        config_dir: str | Path | None = None,
        client: ResilientHTTPClient | None = None,
    ) -> None:
        """
        Args:
            config_dir: 설정 디렉토리 (hot_wallets.yaml 위치).
            client: HTTP 클라이언트 (공유 가능).
        """
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self._config_dir = Path(config_dir)

        # API 키 로드
        self._alchemy_key = get_api_key("ALCHEMY_API_KEY")
        if not self._alchemy_key:
            logger.warning(
                "[HotWalletTracker] ALCHEMY_API_KEY 없음 — 기능 비활성화"
            )

        # 설정 로드
        self._hot_wallets = self._load_hot_wallets()
        self._api_config = self._load_api_config()

        # HTTP 클라이언트
        if client is None:
            config = ResilientHTTPConfig(
                rate_limiter=RateLimiterConfig(
                    tokens_per_second=10.0,  # Alchemy 제한
                    max_tokens=50.0,
                    name="alchemy",
                ),
                circuit_breaker=CircuitBreakerConfig(
                    failure_threshold=5,
                    recovery_timeout=60.0,
                    name="alchemy",
                ),
                default_ttl=_HOT_WALLET_TTL,
            )
            client = ResilientHTTPClient(config, name="HotWalletTracker")
            self._owns_client = True
        else:
            self._owns_client = False

        self._client = client

    async def get_exchange_balance(
        self,
        exchange: str,
        token_address: str | None = None,
        chains: list[str] | None = None,
    ) -> HotWalletResult | None:
        """거래소 핫월렛 총 잔액 조회.

        Args:
            exchange: 거래소 ID (e.g., "binance").
            token_address: 토큰 컨트랙트 주소. None이면 네이티브.
            chains: 검색할 체인. None이면 설정된 전체 체인.

        Returns:
            HotWalletResult 또는 None.
        """
        if not self._alchemy_key:
            logger.debug("[HotWalletTracker] API 키 없음, 건너뜀")
            return None

        # 거래소 지갑 설정 조회
        exchange_config = self._hot_wallets.get("exchanges", {}).get(exchange)
        if not exchange_config:
            logger.debug("[HotWalletTracker] %s 지갑 설정 없음", exchange)
            return None

        wallets = exchange_config.get("wallets", {})
        chains = chains or list(wallets.keys())

        balances: list[WalletBalance] = []
        total_balance_raw = 0
        chains_checked: list[str] = []

        for chain in chains:
            chain_wallets = wallets.get(chain, [])
            if not chain_wallets:
                continue

            rpc_url = self._get_rpc_url(chain)
            if not rpc_url:
                logger.debug("[HotWalletTracker] %s RPC URL 없음", chain)
                continue

            chains_checked.append(chain)

            for wallet_info in chain_wallets:
                address = wallet_info.get("address", "")
                label = wallet_info.get("label", "")

                if not address:
                    continue

                # 잔액 조회
                if token_address:
                    balance = await self._get_token_balance(
                        rpc_url, address, token_address,
                    )
                else:
                    balance = await self._get_native_balance(rpc_url, address)

                if balance is not None:
                    total_balance_raw += balance
                    balances.append(WalletBalance(
                        address=address,
                        label=label,
                        chain=chain,
                        balance_raw=balance,
                        token_address=token_address or "",
                    ))

        if not balances:
            logger.debug(
                "[HotWalletTracker] %s 잔액 조회 실패", exchange,
            )
            return HotWalletResult(
                symbol="",
                exchange=exchange,
                total_balance_usd=0.0,
                confidence=0.0,
            )

        logger.info(
            "[HotWalletTracker] %s: %d wallets, total_raw=%d",
            exchange, len(balances), total_balance_raw,
        )

        return HotWalletResult(
            symbol="",  # 호출자가 설정
            exchange=exchange,
            total_balance_usd=0.0,  # 가격 데이터 연동 필요
            balances=balances,
            chains_checked=chains_checked,
            confidence=1.0,
        )

    async def get_token_balance_for_symbol(
        self,
        symbol: str,
        exchange: str,
        token_addresses: dict[str, str] | None = None,
    ) -> HotWalletResult | None:
        """심볼 기반 토큰 잔액 조회.

        Args:
            symbol: 토큰 심볼 (e.g., "USDT").
            exchange: 거래소 ID.
            token_addresses: 체인별 토큰 주소 매핑.
                            None이면 common_tokens 사용.

        Returns:
            HotWalletResult 또는 None.
        """
        if not self._alchemy_key:
            return None

        # 토큰 주소 매핑
        if token_addresses is None:
            common = self._hot_wallets.get("common_tokens", {})
            token_addresses = common.get(symbol.upper(), {})

        if not token_addresses:
            logger.debug(
                "[HotWalletTracker] %s 토큰 주소 없음", symbol,
            )
            return None

        # 거래소 지갑 설정
        exchange_config = self._hot_wallets.get("exchanges", {}).get(exchange)
        if not exchange_config:
            return None

        wallets = exchange_config.get("wallets", {})

        balances: list[WalletBalance] = []
        total_balance_raw = 0
        chains_checked: list[str] = []

        for chain, token_addr in token_addresses.items():
            chain_wallets = wallets.get(chain, [])
            if not chain_wallets:
                continue

            rpc_url = self._get_rpc_url(chain)
            if not rpc_url:
                continue

            chains_checked.append(chain)

            for wallet_info in chain_wallets:
                address = wallet_info.get("address", "")
                label = wallet_info.get("label", "")

                if not address:
                    continue

                balance = await self._get_token_balance(
                    rpc_url, address, token_addr,
                )

                if balance is not None:
                    total_balance_raw += balance
                    balances.append(WalletBalance(
                        address=address,
                        label=label,
                        chain=chain,
                        balance_raw=balance,
                        token_address=token_addr,
                        token_symbol=symbol,
                    ))

        if not balances:
            return HotWalletResult(
                symbol=symbol,
                exchange=exchange,
                total_balance_usd=0.0,
                confidence=0.0,
            )

        logger.info(
            "[HotWalletTracker] %s@%s: %d wallets, total_raw=%d",
            symbol, exchange, len(balances), total_balance_raw,
        )

        return HotWalletResult(
            symbol=symbol,
            exchange=exchange,
            total_balance_usd=0.0,
            balances=balances,
            chains_checked=chains_checked,
            confidence=1.0,
        )

    async def close(self) -> None:
        """클라이언트 종료."""
        if self._owns_client:
            await self._client.close()

    # ------------------------------------------------------------------
    # RPC Calls
    # ------------------------------------------------------------------

    async def _get_native_balance(
        self, rpc_url: str, address: str,
    ) -> int | None:
        """네이티브 토큰 잔액 조회 (eth_getBalance)."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getBalance",
            "params": [address, "latest"],
        }

        result = await self._client.post(rpc_url, json_data=payload)
        if result and "result" in result:
            hex_balance = result["result"]
            return int(hex_balance, 16)
        return None

    async def _get_token_balance(
        self, rpc_url: str, wallet_address: str, token_address: str,
    ) -> int | None:
        """ERC-20 토큰 잔액 조회 (eth_call balanceOf)."""
        # balanceOf(address) 인코딩
        # 함수 선택자 (4 bytes) + address (32 bytes, 패딩)
        padded_address = wallet_address[2:].lower().zfill(64)
        data = f"{_BALANCE_OF_SELECTOR}{padded_address}"

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [
                {
                    "to": token_address,
                    "data": data,
                },
                "latest",
            ],
        }

        result = await self._client.post(rpc_url, json_data=payload)
        if result and "result" in result:
            hex_balance = result["result"]
            if hex_balance and hex_balance != "0x":
                return int(hex_balance, 16)
            return 0
        return None

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _get_rpc_url(self, chain: str) -> str | None:
        """체인별 RPC URL 생성."""
        if not self._alchemy_key:
            return None

        alchemy_config = self._api_config.get("alchemy", {})
        networks = alchemy_config.get("networks", {})
        chain_config = networks.get(chain, {})
        url_template = chain_config.get("url_template", "")

        if not url_template:
            return None

        return url_template.replace("{api_key}", self._alchemy_key)

    def _load_hot_wallets(self) -> dict:
        """hot_wallets.yaml 로드."""
        path = self._config_dir / "hot_wallets.yaml"
        if not path.exists():
            logger.warning("hot_wallets.yaml 미발견")
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("hot_wallets.yaml 파싱 실패: %s", e)
            return {}

    def _load_api_config(self) -> dict:
        """external_apis.yaml 로드."""
        path = self._config_dir / "external_apis.yaml"
        if not path.exists():
            logger.warning("external_apis.yaml 미발견")
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("external_apis.yaml 파싱 실패: %s", e)
            return {}
