"""HTTP 클라이언트 인프라 (Phase 5b).

Production-grade 신뢰성 패턴:
  - CircuitBreaker: 실패 서비스 차단 (CLOSED→OPEN→HALF_OPEN)
  - RateLimiter: Token Bucket 기반 API 쿼터 관리
  - Retry: 지수 백오프 재시도
  - Session: aiohttp 세션 중앙 관리

열화 규칙:
  - API 실패 → warning 로그 + stale 캐시 반환
  - 모든 실패는 GO 유지 (Hard Gate 이후 단계)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

import aiohttp

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Circuit Breaker
# =============================================================================


class CircuitState(Enum):
    """회로 차단기 상태."""
    CLOSED = "closed"        # 정상 동작
    OPEN = "open"            # 차단됨 (요청 거부)
    HALF_OPEN = "half_open"  # 테스트 중 (일부 요청 허용)


@dataclass
class CircuitBreakerConfig:
    """회로 차단기 설정."""
    failure_threshold: int = 5       # OPEN 전환 실패 횟수
    recovery_timeout: float = 60.0   # OPEN→HALF_OPEN 대기 시간(초)
    half_open_max: int = 3           # HALF_OPEN 테스트 요청 수
    name: str = "default"


class CircuitBreaker:
    """회로 차단기 패턴.

    상태 전이:
      CLOSED → (failures >= threshold) → OPEN
      OPEN → (recovery_timeout 경과) → HALF_OPEN
      HALF_OPEN → (성공) → CLOSED
      HALF_OPEN → (실패) → OPEN
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_successes = 0

    @property
    def state(self) -> CircuitState:
        """현재 상태."""
        return self._state

    @property
    def is_open(self) -> bool:
        """차단 상태 여부 (요청 불가)."""
        self._check_recovery()
        return self._state == CircuitState.OPEN

    def record_success(self) -> None:
        """성공 기록."""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self._config.half_open_max:
                logger.info(
                    "[CircuitBreaker:%s] HALF_OPEN → CLOSED (테스트 통과)",
                    self._config.name,
                )
                self._state = CircuitState.CLOSED
                self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        """실패 기록."""
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            logger.warning(
                "[CircuitBreaker:%s] HALF_OPEN → OPEN (테스트 실패)",
                self._config.name,
            )
            self._state = CircuitState.OPEN
            self._half_open_successes = 0
        elif self._state == CircuitState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self._config.failure_threshold:
                logger.warning(
                    "[CircuitBreaker:%s] CLOSED → OPEN (failures=%d)",
                    self._config.name, self._failure_count,
                )
                self._state = CircuitState.OPEN

    def _check_recovery(self) -> None:
        """OPEN 상태에서 recovery_timeout 경과 확인."""
        if self._state != CircuitState.OPEN:
            return
        elapsed = time.monotonic() - self._last_failure_time
        if elapsed >= self._config.recovery_timeout:
            logger.info(
                "[CircuitBreaker:%s] OPEN → HALF_OPEN (%.0f초 경과)",
                self._config.name, elapsed,
            )
            self._state = CircuitState.HALF_OPEN
            self._half_open_successes = 0


class CircuitOpenError(Exception):
    """회로 차단 상태에서 요청 시도 시 발생."""


# =============================================================================
# Rate Limiter (Token Bucket)
# =============================================================================


@dataclass
class RateLimiterConfig:
    """Rate Limiter 설정."""
    tokens_per_second: float = 5.0   # 초당 토큰 리필
    max_tokens: float = 60.0         # 최대 토큰 (버스트 허용량)
    name: str = "default"


class RateLimiter:
    """Token Bucket 기반 Rate Limiter.

    - 토큰이 있으면 즉시 통과
    - 토큰 부족 시 대기 또는 거부
    """

    def __init__(self, config: RateLimiterConfig | None = None) -> None:
        self._config = config or RateLimiterConfig()
        self._tokens = self._config.max_tokens
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0, wait: bool = True) -> bool:
        """토큰 획득 시도.

        Args:
            tokens: 필요 토큰 수.
            wait: 토큰 부족 시 대기 여부.

        Returns:
            토큰 획득 성공 여부.
        """
        async with self._lock:
            self._refill()

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True

            if not wait:
                return False

            # 토큰 리필 대기
            needed = tokens - self._tokens
            wait_time = needed / self._config.tokens_per_second
            logger.debug(
                "[RateLimiter:%s] 토큰 대기: %.2f초",
                self._config.name, wait_time,
            )

        await asyncio.sleep(wait_time)

        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def _refill(self) -> None:
        """토큰 리필."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        refill = elapsed * self._config.tokens_per_second
        self._tokens = min(self._tokens + refill, self._config.max_tokens)
        self._last_refill = now


# =============================================================================
# Cache Entry
# =============================================================================


@dataclass
class CacheEntry:
    """캐시 엔트리."""
    data: Any
    fetched_at: float
    ttl: float

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.fetched_at) > self.ttl

    @property
    def age_sec(self) -> float:
        return time.time() - self.fetched_at


# =============================================================================
# Resilient HTTP Client
# =============================================================================


@dataclass
class ResilientHTTPConfig:
    """ResilientHTTPClient 설정."""
    # Retry
    max_retries: int = 3
    retry_delay_base: float = 1.0
    retry_delay_max: float = 30.0

    # Timeout
    total_timeout: float = 15.0
    connect_timeout: float = 5.0

    # Cache
    default_ttl: float = 300.0  # 5분

    # Circuit Breaker
    circuit_breaker: CircuitBreakerConfig = field(
        default_factory=CircuitBreakerConfig
    )

    # Rate Limiter
    rate_limiter: RateLimiterConfig = field(
        default_factory=RateLimiterConfig
    )


class ResilientHTTPClient:
    """Production-grade HTTP 클라이언트.

    특징:
      - Circuit Breaker: 실패 서비스 자동 차단
      - Rate Limiter: API 쿼터 준수
      - Retry: 지수 백오프 재시도
      - Cache: TTL 기반 응답 캐싱
      - Graceful Degradation: 실패 시 stale 캐시 반환

    사용법:
        client = ResilientHTTPClient(config)
        data = await client.get("https://api.example.com/data")
        await client.close()
    """

    def __init__(
        self,
        config: ResilientHTTPConfig | None = None,
        name: str = "default",
    ) -> None:
        self._config = config or ResilientHTTPConfig()
        self._name = name
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: dict[str, CacheEntry] = {}

        # Circuit Breaker per domain
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

        # Rate Limiter per domain
        self._rate_limiters: dict[str, RateLimiter] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        ttl: float | None = None,
        use_cache: bool = True,
    ) -> Any | None:
        """GET 요청.

        Args:
            url: 요청 URL.
            params: 쿼리 파라미터.
            headers: 추가 헤더.
            ttl: 캐시 TTL (초). None이면 기본값.
            use_cache: 캐시 사용 여부.

        Returns:
            JSON 응답 또는 None (실패 시).
        """
        cache_key = self._make_cache_key(url, params)
        ttl = ttl if ttl is not None else self._config.default_ttl

        # 캐시 확인
        if use_cache:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired:
                logger.debug("[%s] Cache hit: %s", self._name, url)
                return entry.data

        # Circuit Breaker 확인
        domain = self._extract_domain(url)
        circuit = self._get_circuit_breaker(domain)
        if circuit.is_open:
            logger.warning(
                "[%s] Circuit OPEN, stale 캐시 반환: %s", self._name, domain,
            )
            return self._get_stale_cache(cache_key)

        # Rate Limiter
        limiter = self._get_rate_limiter(domain)
        await limiter.acquire()

        # Retry Loop
        delay = self._config.retry_delay_base
        last_error: Optional[Exception] = None

        for attempt in range(self._config.max_retries):
            try:
                session = await self._get_session()
                timeout = aiohttp.ClientTimeout(
                    total=self._config.total_timeout,
                    connect=self._config.connect_timeout,
                )
                async with session.get(
                    url, params=params, headers=headers, timeout=timeout,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        circuit.record_success()
                        if use_cache:
                            self._cache[cache_key] = CacheEntry(
                                data=data, fetched_at=time.time(), ttl=ttl,
                            )
                        return data

                    if resp.status == 429:
                        # Rate limited
                        logger.warning(
                            "[%s] Rate limited (429): %s", self._name, url,
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, self._config.retry_delay_max)
                        continue

                    # 4xx/5xx
                    logger.warning(
                        "[%s] HTTP %d: %s", self._name, resp.status, url,
                    )
                    circuit.record_failure()
                    last_error = Exception(f"HTTP {resp.status}")

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                circuit.record_failure()
                logger.warning(
                    "[%s] Request failed (attempt %d/%d): %s — %s",
                    self._name, attempt + 1, self._config.max_retries, url, e,
                )
                if attempt < self._config.max_retries - 1:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self._config.retry_delay_max)

        # 모든 재시도 실패 → stale 캐시 반환
        logger.warning(
            "[%s] All retries failed, returning stale cache: %s", self._name, url,
        )
        return self._get_stale_cache(cache_key)

    async def post(
        self,
        url: str,
        *,
        json_data: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any | None:
        """POST 요청 (캐시 없음).

        Args:
            url: 요청 URL.
            json_data: JSON 바디.
            headers: 추가 헤더.

        Returns:
            JSON 응답 또는 None.
        """
        domain = self._extract_domain(url)
        circuit = self._get_circuit_breaker(domain)
        if circuit.is_open:
            logger.warning("[%s] Circuit OPEN: %s", self._name, domain)
            return None

        limiter = self._get_rate_limiter(domain)
        await limiter.acquire()

        delay = self._config.retry_delay_base

        for attempt in range(self._config.max_retries):
            try:
                session = await self._get_session()
                timeout = aiohttp.ClientTimeout(
                    total=self._config.total_timeout,
                    connect=self._config.connect_timeout,
                )
                async with session.post(
                    url, json=json_data, headers=headers, timeout=timeout,
                ) as resp:
                    if resp.status in (200, 201):
                        circuit.record_success()
                        return await resp.json()

                    logger.warning(
                        "[%s] POST HTTP %d: %s", self._name, resp.status, url,
                    )
                    circuit.record_failure()

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                circuit.record_failure()
                logger.warning(
                    "[%s] POST failed (attempt %d/%d): %s — %s",
                    self._name, attempt + 1, self._config.max_retries, url, e,
                )
                if attempt < self._config.max_retries - 1:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self._config.retry_delay_max)

        return None

    async def close(self) -> None:
        """세션 종료."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        logger.info("[%s] HTTP client closed", self._name)

    def clear_cache(self) -> None:
        """캐시 초기화."""
        self._cache.clear()

    def invalidate_cache(self, url: str, params: dict[str, str] | None = None) -> None:
        """특정 캐시 키 무효화."""
        cache_key = self._make_cache_key(url, params)
        self._cache.pop(cache_key, None)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        """세션 lazy 생성."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _get_circuit_breaker(self, domain: str) -> CircuitBreaker:
        """도메인별 Circuit Breaker."""
        if domain not in self._circuit_breakers:
            config = CircuitBreakerConfig(
                failure_threshold=self._config.circuit_breaker.failure_threshold,
                recovery_timeout=self._config.circuit_breaker.recovery_timeout,
                half_open_max=self._config.circuit_breaker.half_open_max,
                name=domain,
            )
            self._circuit_breakers[domain] = CircuitBreaker(config)
        return self._circuit_breakers[domain]

    def _get_rate_limiter(self, domain: str) -> RateLimiter:
        """도메인별 Rate Limiter."""
        if domain not in self._rate_limiters:
            config = RateLimiterConfig(
                tokens_per_second=self._config.rate_limiter.tokens_per_second,
                max_tokens=self._config.rate_limiter.max_tokens,
                name=domain,
            )
            self._rate_limiters[domain] = RateLimiter(config)
        return self._rate_limiters[domain]

    def _get_stale_cache(self, cache_key: str) -> Any | None:
        """만료된 캐시라도 반환 (Graceful Degradation)."""
        entry = self._cache.get(cache_key)
        if entry:
            logger.debug(
                "[%s] Returning stale cache (age=%.0fs)",
                self._name, entry.age_sec,
            )
            return entry.data
        return None

    @staticmethod
    def _make_cache_key(url: str, params: dict[str, str] | None) -> str:
        """캐시 키 생성."""
        if params:
            sorted_params = "&".join(
                f"{k}={v}" for k, v in sorted(params.items())
            )
            return f"{url}?{sorted_params}"
        return url

    @staticmethod
    def _extract_domain(url: str) -> str:
        """URL에서 도메인 추출."""
        # https://api.example.com/v1/data → api.example.com
        if "://" in url:
            url = url.split("://", 1)[1]
        return url.split("/", 1)[0]


# =============================================================================
# Helper: 환경변수에서 API 키 로드
# =============================================================================


def get_api_key(env_name: str, required: bool = False) -> str | None:
    """환경변수에서 API 키 로드.

    Args:
        env_name: 환경변수 이름.
        required: 필수 여부.

    Returns:
        API 키 또는 None.

    Raises:
        ValueError: required=True인데 키가 없는 경우.
    """
    key = os.environ.get(env_name)
    if required and not key:
        raise ValueError(f"환경변수 {env_name} 필요")
    if key:
        logger.debug("API key loaded: %s=***%s", env_name, key[-4:])
    return key
