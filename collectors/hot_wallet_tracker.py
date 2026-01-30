"""핫월렛 잔액 추적기 (Phase 5b → Week 6 확장).

Alchemy RPC 연동:
  - 무료 티어: 300M compute units/month
  - EVM 4체인 지원: Ethereum, Arbitrum, Polygon, Base
  - TTL: 15분 (온체인 데이터 상대적 안정)

Week 6 추가:
  - 입금 감지 (잔액 변화 추적)
  - Telegram 알림 콜백
  - 심볼-토큰 자동 매핑

열화 규칙:
  - RPC 실패 → stale 캐시 반환
  - API 키 없으면 → 기능 비활성화 (warning)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

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

# 토큰 decimals (USD 환산용)
_TOKEN_DECIMALS: dict[str, int] = {
    # Stablecoins
    "USDT": 6,
    "USDC": 6,
    # Native tokens (18 decimals)
    "ETH": 18,
    "WETH": 18,
    "MATIC": 18,
    "ARB": 18,
}

# 기본 가격 (stablecoins = $1, 나머지는 외부 조회 필요)
_DEFAULT_PRICES_USD: dict[str, float] = {
    "USDT": 1.0,
    "USDC": 1.0,
}

# 체인별 네이티브 토큰 심볼
_CHAIN_NATIVE_TOKEN: dict[str, str] = {
    "ethereum": "ETH",
    "arbitrum": "ETH",
    "base": "ETH",
    "polygon": "MATIC",
}


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


@dataclass
class DepositEvent:
    """입금 감지 이벤트 (Week 6)."""
    exchange: str                    # 거래소 ID
    chain: str                       # 체인 (ethereum, arbitrum, ...)
    wallet_address: str              # 입금된 지갑 주소
    wallet_label: str                # 지갑 라벨
    token_symbol: str                # 토큰 심볼 (ETH, USDT, ...)
    token_address: str               # 토큰 컨트랙트 (native면 빈 문자열)
    amount_raw: int                  # 원시 금액 (wei)
    amount_human: float              # 사람 읽기 금액
    amount_usd: float                # USD 환산
    previous_balance: int            # 이전 잔액
    current_balance: int             # 현재 잔액
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0          # 신뢰도


class AlertCallback(Protocol):
    """알림 콜백 프로토콜 (Telegram 등)."""

    async def __call__(self, event: DepositEvent) -> None:
        """입금 이벤트 발생 시 호출."""
        ...


# 스냅샷 키 생성
def _snapshot_key(exchange: str, chain: str, address: str, token: str) -> str:
    """스냅샷 캐시 키 생성."""
    return f"{exchange}:{chain}:{address.lower()}:{token.lower()}"


class HotWalletTracker:
    """거래소 핫월렛 잔액 추적기.

    Alchemy RPC를 사용하여 EVM 체인의 거래소 핫월렛 잔액 조회.

    Week 6 확장:
        - 입금 감지: 잔액 변화 추적 → DepositEvent 생성
        - 알림 콜백: Telegram 등 외부 알림 연동
        - 연속 모니터링: start_monitoring() 루프

    사용법:
        tracker = HotWalletTracker(alert_callback=my_telegram_alert)
        await tracker.start_monitoring(interval_sec=600)  # 10분 간격
        # 또는 단발성 조회
        result = await tracker.get_exchange_balance("binance")
        await tracker.close()
    """

    def __init__(
        self,
        config_dir: str | Path | None = None,
        client: ResilientHTTPClient | None = None,
        alert_callback: AlertCallback | None = None,
        min_deposit_usd: float = 100_000.0,  # 최소 알림 금액 ($10만)
    ) -> None:
        """
        Args:
            config_dir: 설정 디렉토리 (hot_wallets.yaml 위치).
            client: HTTP 클라이언트 (공유 가능).
            alert_callback: 입금 감지 시 호출할 콜백 (Telegram 등).
            min_deposit_usd: 알림 최소 금액 (USD). 기본 $10만.
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

        # Week 6: 입금 감지 설정
        self._alert_callback = alert_callback
        self._min_deposit_usd = min_deposit_usd
        self._balance_snapshots: dict[str, tuple[int, float]] = {}  # key → (balance, timestamp)
        self._monitoring = False

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
        total_balance_usd = 0.0
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

            # 네이티브 토큰 심볼 결정
            native_symbol = _CHAIN_NATIVE_TOKEN.get(chain, "ETH")

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
                    token_symbol = ""  # 토큰 심볼은 호출자가 알아야 함
                else:
                    balance = await self._get_native_balance(rpc_url, address)
                    token_symbol = native_symbol

                if balance is not None:
                    total_balance_raw += balance
                    # USD 환산 (네이티브 토큰은 외부 가격 필요)
                    balance_usd = self._calculate_balance_usd(
                        balance, token_symbol,
                    ) if token_symbol else 0.0
                    total_balance_usd += balance_usd
                    balances.append(WalletBalance(
                        address=address,
                        label=label,
                        chain=chain,
                        balance_raw=balance,
                        balance_usd=balance_usd,
                        token_address=token_address or "",
                        token_symbol=token_symbol,
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
            "[HotWalletTracker] %s: %d wallets, total_raw=%d, total_usd=%.2f",
            exchange, len(balances), total_balance_raw, total_balance_usd,
        )

        return HotWalletResult(
            symbol="",  # 호출자가 설정
            exchange=exchange,
            total_balance_usd=total_balance_usd,
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
        total_balance_usd = 0.0
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
                    # USD 환산
                    balance_usd = self._calculate_balance_usd(
                        balance, symbol,
                    )
                    total_balance_usd += balance_usd
                    balances.append(WalletBalance(
                        address=address,
                        label=label,
                        chain=chain,
                        balance_raw=balance,
                        balance_usd=balance_usd,
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
            "[HotWalletTracker] %s@%s: %d wallets, total_raw=%d, total_usd=%.2f",
            symbol, exchange, len(balances), total_balance_raw, total_balance_usd,
        )

        return HotWalletResult(
            symbol=symbol,
            exchange=exchange,
            total_balance_usd=total_balance_usd,
            balances=balances,
            chains_checked=chains_checked,
            confidence=1.0,
        )

    # ------------------------------------------------------------------
    # Week 6: 입금 감지 및 모니터링
    # ------------------------------------------------------------------

    async def start_monitoring(
        self,
        interval_sec: int = 600,
        exchanges: list[str] | None = None,
        tokens: list[str] | None = None,
    ) -> None:
        """연속 모니터링 시작.

        Args:
            interval_sec: 체크 간격 (초). 기본 10분.
            exchanges: 모니터링할 거래소. None이면 전체.
            tokens: 모니터링할 토큰. None이면 common_tokens 전체.
        """
        if not self._alchemy_key:
            logger.warning("[HotWalletTracker] API 키 없음, 모니터링 불가")
            return

        self._monitoring = True
        logger.info(
            "[HotWalletTracker] 모니터링 시작 (interval=%ds, min_deposit=$%.0f)",
            interval_sec, self._min_deposit_usd,
        )

        # 기본 거래소/토큰 설정
        if exchanges is None:
            exchanges = list(self._hot_wallets.get("exchanges", {}).keys())
        if tokens is None:
            tokens = list(self._hot_wallets.get("common_tokens", {}).keys())

        while self._monitoring:
            try:
                deposits = await self.detect_deposits(exchanges, tokens)
                if deposits:
                    logger.info(
                        "[HotWalletTracker] %d건 입금 감지", len(deposits),
                    )
                    for event in deposits:
                        await self._handle_deposit(event)
            except Exception as e:
                logger.error("[HotWalletTracker] 모니터링 오류: %s", e)

            await asyncio.sleep(interval_sec)

    def stop_monitoring(self) -> None:
        """모니터링 중지."""
        self._monitoring = False
        logger.info("[HotWalletTracker] 모니터링 중지")

    async def detect_deposits(
        self,
        exchanges: list[str],
        tokens: list[str],
    ) -> list[DepositEvent]:
        """입금 감지 (잔액 변화 체크).

        Args:
            exchanges: 체크할 거래소 목록.
            tokens: 체크할 토큰 목록.

        Returns:
            감지된 입금 이벤트 목록.
        """
        deposits: list[DepositEvent] = []

        for exchange in exchanges:
            exchange_config = self._hot_wallets.get("exchanges", {}).get(exchange)
            if not exchange_config:
                continue

            wallets = exchange_config.get("wallets", {})

            for chain, chain_wallets in wallets.items():
                rpc_url = self._get_rpc_url(chain)
                if not rpc_url:
                    continue

                native_symbol = _CHAIN_NATIVE_TOKEN.get(chain, "ETH")

                for wallet_info in chain_wallets:
                    address = wallet_info.get("address", "")
                    label = wallet_info.get("label", "")
                    if not address:
                        continue

                    # 네이티브 토큰 체크
                    event = await self._check_balance_change(
                        exchange, chain, address, label,
                        token_address="",
                        token_symbol=native_symbol,
                        rpc_url=rpc_url,
                    )
                    if event:
                        deposits.append(event)

                    # ERC-20 토큰 체크
                    for token in tokens:
                        token_addresses = self._hot_wallets.get(
                            "common_tokens", {},
                        ).get(token, {})
                        token_addr = token_addresses.get(chain)
                        if not token_addr:
                            continue

                        event = await self._check_balance_change(
                            exchange, chain, address, label,
                            token_address=token_addr,
                            token_symbol=token,
                            rpc_url=rpc_url,
                        )
                        if event:
                            deposits.append(event)

        return deposits

    async def _check_balance_change(
        self,
        exchange: str,
        chain: str,
        address: str,
        label: str,
        token_address: str,
        token_symbol: str,
        rpc_url: str,
    ) -> DepositEvent | None:
        """단일 지갑/토큰 잔액 변화 체크.

        Returns:
            입금 감지 시 DepositEvent, 없으면 None.
        """
        # 현재 잔액 조회
        if token_address:
            current_balance = await self._get_token_balance(
                rpc_url, address, token_address,
            )
        else:
            current_balance = await self._get_native_balance(rpc_url, address)

        if current_balance is None:
            return None

        # 스냅샷 키
        key = _snapshot_key(exchange, chain, address, token_address or "native")

        # 이전 잔액 조회
        prev_data = self._balance_snapshots.get(key)
        prev_balance = prev_data[0] if prev_data else 0

        # 스냅샷 업데이트
        self._balance_snapshots[key] = (current_balance, time.time())

        # 첫 조회면 스킵 (기준점 설정)
        if prev_data is None:
            return None

        # 잔액 증가 감지 (입금)
        delta = current_balance - prev_balance
        if delta <= 0:
            return None

        # USD 환산
        decimals = _TOKEN_DECIMALS.get(token_symbol.upper(), 18)
        amount_human = delta / (10 ** decimals)
        amount_usd = self._calculate_balance_usd(delta, token_symbol)

        # 최소 금액 필터
        if amount_usd < self._min_deposit_usd:
            logger.debug(
                "[HotWalletTracker] 소액 입금 무시: %s %.2f (< $%.0f)",
                token_symbol, amount_usd, self._min_deposit_usd,
            )
            return None

        logger.info(
            "[HotWalletTracker] 입금 감지: %s@%s %s +%.4f ($%.0f)",
            exchange, chain, token_symbol, amount_human, amount_usd,
        )

        return DepositEvent(
            exchange=exchange,
            chain=chain,
            wallet_address=address,
            wallet_label=label,
            token_symbol=token_symbol,
            token_address=token_address,
            amount_raw=delta,
            amount_human=amount_human,
            amount_usd=amount_usd,
            previous_balance=prev_balance,
            current_balance=current_balance,
            timestamp=datetime.now(),
            confidence=1.0,
        )

    async def _handle_deposit(self, event: DepositEvent) -> None:
        """입금 이벤트 처리 (알림 콜백 호출)."""
        if self._alert_callback:
            try:
                await self._alert_callback(event)
            except Exception as e:
                logger.error(
                    "[HotWalletTracker] 알림 콜백 오류: %s", e,
                )

    def get_snapshot_count(self) -> int:
        """현재 스냅샷 수 반환 (테스트/디버깅용)."""
        return len(self._balance_snapshots)

    async def close(self) -> None:
        """클라이언트 종료."""
        if self._owns_client:
            await self._client.close()

    # ------------------------------------------------------------------
    # USD Conversion
    # ------------------------------------------------------------------

    def _calculate_balance_usd(
        self,
        balance_raw: int,
        token_symbol: str,
        price_usd: float | None = None,
    ) -> float:
        """원시 잔액을 USD로 환산.

        Args:
            balance_raw: 원시 잔액 (wei/smallest unit).
            token_symbol: 토큰 심볼 (e.g., "USDT", "ETH").
            price_usd: USD 가격. None이면 기본값 사용.

        Returns:
            USD 환산 금액.
        """
        if balance_raw == 0:
            return 0.0

        # decimals 조회
        decimals = _TOKEN_DECIMALS.get(token_symbol.upper(), 18)

        # 실제 수량 계산
        balance_human = balance_raw / (10 ** decimals)

        # 가격 결정
        if price_usd is None:
            price_usd = _DEFAULT_PRICES_USD.get(token_symbol.upper())

        if price_usd is None:
            # 가격 정보 없으면 0 반환 (외부 가격 조회 필요)
            logger.debug(
                "[HotWalletTracker] %s 가격 정보 없음, USD 환산 불가",
                token_symbol,
            )
            return 0.0

        return balance_human * price_usd

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


# =============================================================================
# Telegram 알림 포맷터 (Week 6)
# =============================================================================


def format_deposit_alert(event: DepositEvent) -> str:
    """입금 이벤트를 Telegram 메시지로 포맷.

    Args:
        event: DepositEvent 객체.

    Returns:
        Telegram용 마크다운 메시지.
    """
    # 금액 크기에 따른 이모지
    if event.amount_usd >= 10_000_000:
        emoji = "🚨🐋"  # $1000만+ 고래
        urgency = "**[긴급]**"
    elif event.amount_usd >= 1_000_000:
        emoji = "💰🔥"  # $100만+
        urgency = "**[대량]**"
    elif event.amount_usd >= 100_000:
        emoji = "💵"    # $10만+
        urgency = ""
    else:
        emoji = "📥"
        urgency = ""

    # KRW 환산 (환율 1350 가정)
    amount_krw = event.amount_usd * 1350
    krw_display = f"{amount_krw / 1e8:.1f}억원" if amount_krw >= 1e8 else f"{amount_krw / 1e4:.0f}만원"

    # 거래소 라벨
    exchange_labels = {
        "binance": "바이낸스",
        "okx": "OKX",
        "bybit": "바이빗",
        "coinbase": "코인베이스",
        "kraken": "크라켄",
        "gateio": "게이트",
        "kucoin": "쿠코인",
    }
    exchange_name = exchange_labels.get(event.exchange, event.exchange.upper())

    # 체인 라벨
    chain_labels = {
        "ethereum": "이더리움",
        "arbitrum": "아비트럼",
        "polygon": "폴리곤",
        "base": "베이스",
    }
    chain_name = chain_labels.get(event.chain, event.chain.upper())

    return f"""{emoji} {urgency} **핫월렛 입금 감지**
━━━━━━━━━━━━━━━
🏢 거래소: {exchange_name}
⛓️ 체인: {chain_name}
🪙 토큰: {event.token_symbol}
💵 금액: +{event.amount_human:,.4f} {event.token_symbol}
💲 USD: ${event.amount_usd:,.0f}
💴 KRW: ~{krw_display}
📍 지갑: {event.wallet_label}
⏰ 시간: {event.timestamp.strftime('%H:%M:%S')}
━━━━━━━━━━━━━━━
⚠️ 상장 전 대량 입금 = 따리 기회 가능성!"""


# =============================================================================
# 심볼-토큰 매핑 (Week 6)
# =============================================================================

# 알려진 토큰 주소 → 심볼 매핑 (역방향 조회용)
_TOKEN_ADDRESS_TO_SYMBOL: dict[str, str] = {}


def _build_reverse_token_map(hot_wallets_config: dict) -> dict[str, str]:
    """common_tokens에서 역방향 매핑 생성.

    Args:
        hot_wallets_config: hot_wallets.yaml 내용.

    Returns:
        {토큰주소(lowercase): 심볼} 딕셔너리.
    """
    result: dict[str, str] = {}
    common_tokens = hot_wallets_config.get("common_tokens", {})

    for symbol, chains in common_tokens.items():
        for chain, address in chains.items():
            if address:
                result[address.lower()] = symbol.upper()

    return result


def get_symbol_from_address(
    token_address: str,
    hot_wallets_config: dict | None = None,
) -> str | None:
    """토큰 주소로 심볼 조회.

    Args:
        token_address: 토큰 컨트랙트 주소.
        hot_wallets_config: hot_wallets.yaml 내용 (캐시용).

    Returns:
        토큰 심볼 또는 None.
    """
    global _TOKEN_ADDRESS_TO_SYMBOL

    # 캐시가 비어있으면 빌드
    if not _TOKEN_ADDRESS_TO_SYMBOL and hot_wallets_config:
        _TOKEN_ADDRESS_TO_SYMBOL = _build_reverse_token_map(hot_wallets_config)

    return _TOKEN_ADDRESS_TO_SYMBOL.get(token_address.lower())


# =============================================================================
# 편의 함수
# =============================================================================


async def create_telegram_alert_callback(
    telegram_bot_token: str,
    chat_id: str | int,
) -> AlertCallback:
    """Telegram 알림 콜백 생성.

    사용법:
        callback = await create_telegram_alert_callback(token, chat_id)
        tracker = HotWalletTracker(alert_callback=callback)

    Args:
        telegram_bot_token: 텔레그램 봇 토큰.
        chat_id: 알림 받을 채팅 ID.

    Returns:
        AlertCallback 함수.
    """
    import aiohttp

    async def send_alert(event: DepositEvent) -> None:
        message = format_deposit_alert(event)
        url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[HotWalletTracker] Telegram 전송 실패: %s",
                        await resp.text(),
                    )

    return send_alert
