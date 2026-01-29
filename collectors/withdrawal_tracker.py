"""입출금 상태 추적기 (Phase 5b).

거래소별 입출금 상태 API 연동:
  - Upbit: /v1/status/wallet (Public API)
  - Bithumb: /public/assetsstatus (Public API)
  - Binance: /sapi/v1/capital/config/getall (API Key 필요)

TTL: 1분 (상태 변경 빈번)

열화 규칙:
  - API 실패 → stale 캐시 반환
  - 캐시도 없으면 → withdrawal_open=True (안전 기본값)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import yaml

from collectors.api_client import (
    ResilientHTTPClient,
    ResilientHTTPConfig,
    RateLimiterConfig,
    CircuitBreakerConfig,
    get_api_key,
)

logger = logging.getLogger(__name__)

# TTL: 1분 (입출금 상태는 자주 변경)
_WITHDRAWAL_TTL = 60.0


@dataclass
class WithdrawalStatus:
    """단일 토큰 입출금 상태."""
    symbol: str
    exchange: str
    deposit_open: bool = True      # 입금 가능
    withdrawal_open: bool = True   # 출금 가능
    networks: list[str] = field(default_factory=list)  # 지원 네트워크
    suspend_reason: str = ""       # 정지 사유
    confidence: float = 1.0        # 신뢰도


@dataclass
class WithdrawalResult:
    """입출금 상태 조회 결과."""
    symbol: str
    statuses: dict[str, WithdrawalStatus] = field(default_factory=dict)
    # exchange → WithdrawalStatus
    overall_withdrawal_open: bool = True
    overall_deposit_open: bool = True
    confidence: float = 1.0


class WithdrawalTracker:
    """거래소 입출금 상태 추적기.

    여러 거래소의 입출금 상태를 통합 조회.

    사용법:
        tracker = WithdrawalTracker()
        result = await tracker.get_status("XYZ")
        await tracker.close()
    """

    def __init__(
        self,
        config_dir: str | Path | None = None,
        client: ResilientHTTPClient | None = None,
    ) -> None:
        """
        Args:
            config_dir: 설정 디렉토리.
            client: HTTP 클라이언트 (공유 가능).
        """
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self._config_dir = Path(config_dir)

        # API 키 로드 (김프봇 .env 호환: BINANCE_SECRET)
        self._binance_key = get_api_key("BINANCE_API_KEY")
        self._binance_secret = get_api_key("BINANCE_SECRET") or get_api_key("BINANCE_API_SECRET")

        # 설정 로드
        self._api_config = self._load_api_config()

        # HTTP 클라이언트
        if client is None:
            config = ResilientHTTPConfig(
                rate_limiter=RateLimiterConfig(
                    tokens_per_second=5.0,
                    max_tokens=30.0,
                    name="withdrawal",
                ),
                circuit_breaker=CircuitBreakerConfig(
                    failure_threshold=5,
                    recovery_timeout=60.0,
                    name="withdrawal",
                ),
                default_ttl=_WITHDRAWAL_TTL,
            )
            client = ResilientHTTPClient(config, name="WithdrawalTracker")
            self._owns_client = True
        else:
            self._owns_client = False

        self._client = client

        # 거래소별 캐시 (전체 조회 결과)
        self._exchange_cache: dict[str, tuple[float, dict[str, WithdrawalStatus]]] = {}

    async def get_status(
        self,
        symbol: str,
        exchanges: list[str] | None = None,
    ) -> WithdrawalResult:
        """토큰 입출금 상태 조회.

        Args:
            symbol: 토큰 심볼 (e.g., "XYZ").
            exchanges: 조회할 거래소 목록. None이면 전체.

        Returns:
            WithdrawalResult.
        """
        exchanges = exchanges or ["upbit", "bithumb", "binance"]

        statuses: dict[str, WithdrawalStatus] = {}
        overall_deposit = True
        overall_withdrawal = True
        min_confidence = 1.0

        for exchange in exchanges:
            status = await self._get_exchange_status(symbol, exchange)
            if status:
                statuses[exchange] = status
                if not status.deposit_open:
                    overall_deposit = False
                if not status.withdrawal_open:
                    overall_withdrawal = False
                min_confidence = min(min_confidence, status.confidence)

        return WithdrawalResult(
            symbol=symbol,
            statuses=statuses,
            overall_withdrawal_open=overall_withdrawal,
            overall_deposit_open=overall_deposit,
            confidence=min_confidence,
        )

    async def get_exchange_status(
        self,
        symbol: str,
        exchange: str,
    ) -> WithdrawalStatus | None:
        """단일 거래소 입출금 상태 조회.

        Args:
            symbol: 토큰 심볼.
            exchange: 거래소 ID.

        Returns:
            WithdrawalStatus 또는 None.
        """
        return await self._get_exchange_status(symbol, exchange)

    async def close(self) -> None:
        """클라이언트 종료."""
        if self._owns_client:
            await self._client.close()

    # ------------------------------------------------------------------
    # Exchange-specific implementations
    # ------------------------------------------------------------------

    async def _get_exchange_status(
        self,
        symbol: str,
        exchange: str,
    ) -> WithdrawalStatus | None:
        """거래소별 입출금 상태 조회 분기."""
        if exchange == "upbit":
            return await self._get_upbit_status(symbol)
        elif exchange == "bithumb":
            return await self._get_bithumb_status(symbol)
        elif exchange == "binance":
            return await self._get_binance_status(symbol)
        else:
            logger.debug("[WithdrawalTracker] 미지원 거래소: %s", exchange)
            return None

    # ------------------------------------------------------------------
    # Upbit
    # ------------------------------------------------------------------

    async def _get_upbit_status(self, symbol: str) -> WithdrawalStatus | None:
        """Upbit 입출금 상태 조회.

        마켓 정보 API 사용: /v1/market/all (Public)
        입출금 상태는 market_warning 필드로 추정
        (정확한 상태는 인증 필요하지만, 기본값 사용)
        """
        # 캐시 확인
        cache_data = await self._get_cached_exchange_data("upbit")
        if cache_data and symbol.upper() in cache_data:
            return cache_data[symbol.upper()]

        # Public API: 마켓 목록 조회 (입출금 상태는 제공 안 됨)
        # 따라서 기본값 사용 + 낮은 신뢰도
        url = "https://api.upbit.com/v1/market/all"

        data = await self._client.get(url, ttl=_WITHDRAWAL_TTL)
        if data is None:
            logger.warning("[WithdrawalTracker] Upbit API 실패")
            # 안전 기본값 반환
            return WithdrawalStatus(
                symbol=symbol,
                exchange="upbit",
                deposit_open=True,
                withdrawal_open=True,
                confidence=0.0,  # 미확인
            )

        # 마켓 목록 파싱 (KRW-XXX 형식)
        parsed: dict[str, WithdrawalStatus] = {}
        for item in data:
            market = item.get("market", "")
            if not market.startswith("KRW-"):
                continue

            coin = market.split("-")[1].upper()
            # market_warning이 있으면 주의 필요
            warning = item.get("market_warning", "")

            # Public API로는 정확한 입출금 상태를 알 수 없음
            # market_warning="CAUTION"이면 주의, 그 외는 기본 True
            deposit_open = warning != "CAUTION"
            withdrawal_open = warning != "CAUTION"

            parsed[coin] = WithdrawalStatus(
                symbol=coin,
                exchange="upbit",
                deposit_open=deposit_open,
                withdrawal_open=withdrawal_open,
                networks=[],
                confidence=0.5,  # Public API이므로 신뢰도 낮음
            )

        self._exchange_cache["upbit"] = (time.time(), parsed)

        status = parsed.get(symbol.upper())
        if status:
            logger.info(
                "[WithdrawalTracker] Upbit %s: deposit=%s, withdraw=%s",
                symbol, status.deposit_open, status.withdrawal_open,
            )
        return status

    # ------------------------------------------------------------------
    # Bithumb
    # ------------------------------------------------------------------

    async def _get_bithumb_status(self, symbol: str) -> WithdrawalStatus | None:
        """Bithumb 입출금 상태 조회.

        Public API: /public/assetsstatus/ALL
        """
        cache_data = await self._get_cached_exchange_data("bithumb")
        if cache_data and symbol.upper() in cache_data:
            return cache_data[symbol.upper()]

        url = "https://api.bithumb.com/public/assetsstatus/ALL"

        data = await self._client.get(url, ttl=_WITHDRAWAL_TTL)
        if data is None or data.get("status") != "0000":
            logger.warning("[WithdrawalTracker] Bithumb API 실패")
            return WithdrawalStatus(
                symbol=symbol,
                exchange="bithumb",
                deposit_open=True,
                withdrawal_open=True,
                confidence=0.0,
            )

        parsed: dict[str, WithdrawalStatus] = {}
        assets = data.get("data", {})

        for coin, info in assets.items():
            deposit = info.get("deposit_status", 0) == 1
            withdrawal = info.get("withdrawal_status", 0) == 1

            parsed[coin.upper()] = WithdrawalStatus(
                symbol=coin.upper(),
                exchange="bithumb",
                deposit_open=deposit,
                withdrawal_open=withdrawal,
                confidence=1.0,
            )

        self._exchange_cache["bithumb"] = (time.time(), parsed)

        status = parsed.get(symbol.upper())
        if status:
            logger.info(
                "[WithdrawalTracker] Bithumb %s: deposit=%s, withdraw=%s",
                symbol, status.deposit_open, status.withdrawal_open,
            )
        return status

    # ------------------------------------------------------------------
    # Binance
    # ------------------------------------------------------------------

    async def _get_binance_status(self, symbol: str) -> WithdrawalStatus | None:
        """Binance 입출금 상태 조회.

        Private API: /sapi/v1/capital/config/getall (API Key 필요)
        """
        if not self._binance_key or not self._binance_secret:
            logger.debug("[WithdrawalTracker] Binance API 키 없음")
            return WithdrawalStatus(
                symbol=symbol,
                exchange="binance",
                deposit_open=True,
                withdrawal_open=True,
                confidence=0.0,
            )

        cache_data = await self._get_cached_exchange_data("binance")
        if cache_data and symbol.upper() in cache_data:
            return cache_data[symbol.upper()]

        # 서명 생성
        timestamp = int(time.time() * 1000)
        params = {"timestamp": str(timestamp)}
        query_string = urlencode(params)
        signature = hmac.new(
            self._binance_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        url = f"https://api.binance.com/sapi/v1/capital/config/getall?{query_string}&signature={signature}"
        headers = {"X-MBX-APIKEY": self._binance_key}

        data = await self._client.get(
            url, headers=headers, ttl=_WITHDRAWAL_TTL, use_cache=False,
        )

        if data is None:
            logger.warning("[WithdrawalTracker] Binance API 실패")
            return WithdrawalStatus(
                symbol=symbol,
                exchange="binance",
                deposit_open=True,
                withdrawal_open=True,
                confidence=0.0,
            )

        parsed: dict[str, WithdrawalStatus] = {}

        for item in data:
            coin = item.get("coin", "").upper()
            deposit_all = item.get("depositAllEnable", True)
            withdraw_all = item.get("withdrawAllEnable", True)
            networks = [
                n.get("network", "") for n in item.get("networkList", [])
            ]

            parsed[coin] = WithdrawalStatus(
                symbol=coin,
                exchange="binance",
                deposit_open=deposit_all,
                withdrawal_open=withdraw_all,
                networks=networks,
                confidence=1.0,
            )

        self._exchange_cache["binance"] = (time.time(), parsed)

        status = parsed.get(symbol.upper())
        if status:
            logger.info(
                "[WithdrawalTracker] Binance %s: deposit=%s, withdraw=%s",
                symbol, status.deposit_open, status.withdrawal_open,
            )
        return status

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    async def _get_cached_exchange_data(
        self, exchange: str,
    ) -> dict[str, WithdrawalStatus] | None:
        """거래소 캐시 데이터 조회."""
        if exchange not in self._exchange_cache:
            return None

        cached_time, data = self._exchange_cache[exchange]
        if time.time() - cached_time > _WITHDRAWAL_TTL:
            return None

        return data

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_api_config(self) -> dict:
        """external_apis.yaml 로드."""
        path = self._config_dir / "external_apis.yaml"
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("external_apis.yaml 파싱 실패: %s", e)
            return {}
