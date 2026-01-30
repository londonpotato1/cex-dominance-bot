"""Go/No-Go Gate 판정 (Phase 3 + Phase 5a + Phase 7 확장).

6단계 파이프라인 (v10):
  1단계: Hard Gate (v5) → 입출금/수익성/전송시간/VASP Blocker 체크
  2단계: Supply Classification (v6) → 원활/미원활 판정
  3단계: Listing Type (v6) → TGE/직상장/옆상장 분류
  4단계: Strategy Determination (v6) → 공급+유형 조합별 전략 결정
  5단계: Scenario Generation (v6) → 흥/망따리 카드 생성
  6단계: VC/MM Check (v10) → 투자자/MM 리스크 평가

Hard Gate 4 Blockers:
  1. 입출금 차단 (deposit/withdrawal closed)
  2. 수익성 부족 (net_profit <= 0)
  3. 전송 시간 초과 (> 30분)
  4. VASP 차단

3 Warnings:
  1. 유동성 부족 (글로벌 24h volume < $100K)
  2. 네트워크 혼잡 (가스비 경고)
  3. DEX-only 헤징 (CEX 선물 미지원)

AlertLevel (v10 정밀화):
  - CRITICAL: GO + 행동 가능 전략 + 신뢰 FX
  - HIGH: GO (일부 미달) 또는 NO-GO (즉시 전송)
  - MEDIUM: (미사용 — debounce 전용)
  - LOW: 정보성
  - INFO: 로그만

열화 규칙 (v9):
  - 1단계(Hard Gate)만 GO/NO-GO 의사결정 차단 권한
  - 2~5단계는 정보 제공 목적 — 실패해도 Gate 통과
  - ListingType.UNKNOWN → WATCH_ONLY 강제 (v12)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, TYPE_CHECKING, TypeVar

import aiohttp
import yaml

# 타입 변수 (제네릭 데코레이터용)
T = TypeVar("T")


# ============================================================
# A3: LRU 캐시 (메모리 누수 방지)
# ============================================================

class LRUCache:
    """TTL + LRU 캐시 (메모리 누수 방지).

    - maxsize: 최대 항목 수 (초과 시 가장 오래된 항목 제거)
    - ttl: 항목 만료 시간 (초)
    - 조회 시 LRU 순서 갱신 (최근 사용 항목 유지)
    """

    def __init__(self, maxsize: int = 1000, ttl: float = 300.0) -> None:
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl

    def get(self, key: str) -> tuple[bool, Any]:
        """캐시 조회.

        Returns:
            (hit, value): hit=True면 캐시 히트, value는 저장된 값.
        """
        if key not in self._cache:
            return False, None

        timestamp, value = self._cache[key]
        if time.time() - timestamp > self._ttl:
            # 만료됨 → 삭제
            del self._cache[key]
            return False, None

        # LRU: 최근 사용 항목을 끝으로 이동
        self._cache.move_to_end(key)
        return True, value

    def set(self, key: str, value: Any) -> None:
        """캐시 저장."""
        # 기존 키가 있으면 삭제 후 재삽입 (순서 갱신)
        if key in self._cache:
            del self._cache[key]

        # maxsize 초과 시 가장 오래된 항목 제거
        while len(self._cache) >= self._maxsize:
            self._cache.popitem(last=False)

        self._cache[key] = (time.time(), value)

    def cleanup(self) -> int:
        """만료된 항목 정리.

        Returns:
            제거된 항목 수.
        """
        now = time.time()
        expired = [k for k, (ts, _) in self._cache.items() if now - ts > self._ttl]
        for k in expired:
            del self._cache[k]
        return len(expired)

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        hit, _ = self.get(key)
        return hit


# ============================================================
# B1: 재시도 데코레이터 (지수 백오프 + 지터)
# ============================================================

def async_retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    exponential: bool = True,
    jitter: bool = True,
    exceptions: tuple = (aiohttp.ClientError, asyncio.TimeoutError),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """비동기 함수 재시도 데코레이터.

    Args:
        max_retries: 최대 재시도 횟수 (기본 3)
        base_delay: 기본 대기 시간 (초)
        max_delay: 최대 대기 시간 (초)
        exponential: 지수 백오프 사용 여부
        jitter: 랜덤 지터 추가 여부 (thundering herd 방지)
        exceptions: 재시도할 예외 타입들

    Example:
        @async_retry(max_retries=3, base_delay=0.5)
        async def fetch_data(url):
            async with session.get(url) as resp:
                return await resp.json()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception: Exception | None = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt < max_retries - 1:
                        # 대기 시간 계산
                        if exponential:
                            delay = base_delay * (2 ** attempt)
                        else:
                            delay = base_delay

                        # 최대 대기 시간 제한
                        delay = min(delay, max_delay)

                        # 지터 추가 (0.5~1.5배)
                        if jitter:
                            delay *= (0.5 + random.random())

                        logger.warning(
                            "[Retry] %s 실패 (시도 %d/%d), %.2fs 후 재시도: %s",
                            func.__name__, attempt + 1, max_retries, delay, e,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "[Retry] %s 최종 실패 (%d회 시도): %s",
                            func.__name__, max_retries, e,
                        )

            # 모든 재시도 실패
            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed after {max_retries} retries")

        return wrapper
    return decorator


# ============================================================
# B2: API 메트릭 수집
# ============================================================

@dataclass
class APIMetrics:
    """API 호출 메트릭.

    성공률, 평균 지연 시간, 에러 유형별 카운트 추적.
    """
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    errors: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """성공률 (0.0 ~ 1.0)."""
        if self.total_calls == 0:
            return 0.0
        return self.success_calls / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        """평균 지연 시간 (ms)."""
        if self.success_calls == 0:
            return 0.0
        return self.total_latency_ms / self.success_calls

    def record_success(self, latency_ms: float) -> None:
        """성공 기록."""
        self.total_calls += 1
        self.success_calls += 1
        self.total_latency_ms += latency_ms

    def record_failure(self, error_type: str) -> None:
        """실패 기록."""
        self.total_calls += 1
        self.failed_calls += 1
        self.errors[error_type] = self.errors.get(error_type, 0) + 1

    def to_dict(self) -> dict:
        """딕셔너리 변환 (JSON 직렬화용)."""
        return {
            "total_calls": self.total_calls,
            "success_calls": self.success_calls,
            "failed_calls": self.failed_calls,
            "success_rate": f"{self.success_rate:.1%}",
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "errors": dict(self.errors) if self.errors else {},
        }

    def reset(self) -> None:
        """메트릭 초기화."""
        self.total_calls = 0
        self.success_calls = 0
        self.failed_calls = 0
        self.total_latency_ms = 0.0
        self.errors.clear()


from analysis.premium import PremiumCalculator, _fetch_upbit_price, _get_fallback_fx
from analysis.cost_model import CostModel, CostResult
from analysis.listing_type import (
    ListingType,
    ListingTypeClassifier,
    ListingTypeResult,
    get_strategy_modifier,
)
from analysis.supply_classifier import (
    SupplyClassification,
    SupplyClassifier,
    SupplyInput,
    SupplyResult,
)
from analysis.scenario import (
    ScenarioCard,
    ScenarioPlanner,
    ScenarioOutcome,
    format_scenario_card_text,
)
from collectors.vc_mm_collector import (
    VCMMCollector,
    ProjectVCInfo,
)

# Phase 5b: External Data Collectors (Lazy Import)
# 실제 사용 시에만 import하여 시작 시간 최적화

if TYPE_CHECKING:
    from store.writer import DatabaseWriter
    from store.token_registry import TokenRegistry

logger = logging.getLogger(__name__)

# Gate 기본 설정
_DEFAULT_AMOUNT_KRW = 10_000_000   # 1천만원 기준 비용 계산
_MIN_GLOBAL_VOLUME_USD = 100_000   # 최소 글로벌 24h 거래량 ($100K)
_MAX_TRANSFER_MIN = 30              # 최대 허용 전송 시간 (분)


class AlertLevel(Enum):
    """알림 레벨 (5단계)."""
    CRITICAL = "CRITICAL"   # 즉시 행동 필요
    HIGH = "HIGH"           # 즉시 전송
    MEDIUM = "MEDIUM"       # 5분 debounce
    LOW = "LOW"             # 배치 전송
    INFO = "INFO"           # 로그만


@dataclass
class GateInput:
    """Gate 판정 입력 데이터."""
    symbol: str
    exchange: str                    # 상장 거래소 (upbit/bithumb)
    premium_pct: float               # 프리미엄 (%)
    cost_result: CostResult          # 비용 모델 결과
    deposit_open: bool               # 입금 가능 여부
    withdrawal_open: bool            # 출금 가능 여부
    transfer_time_min: float         # 예상 전송 시간 (분)
    global_volume_usd: float         # 글로벌 24h 거래량 (USD)
    fx_source: str                   # FX 소스
    hedge_type: str                  # "cex", "dex_only", "none"
    network: str = "unknown"         # 전송 네트워크
    top_exchange: str = ""           # 글로벌 주요 거래소
    # 가격 정보 (UI 표시용)
    domestic_price_krw: float = 0.0  # 국내 거래소 가격 (KRW)
    global_price_usd: float = 0.0    # 글로벌 거래소 가격 (USD)


class StrategyCode(Enum):
    """전략 코드 (v6)."""
    AGGRESSIVE = "AGGRESSIVE"      # 공격적 매수
    MODERATE = "MODERATE"          # 보통 매수
    CONSERVATIVE = "CONSERVATIVE"  # 보수적 매수
    WATCH_ONLY = "WATCH_ONLY"      # 관망 (매수 금지)
    NO_TRADE = "NO_TRADE"          # 거래 금지 (NO-GO)


@dataclass
class GateResult:
    """Gate 판정 결과."""
    can_proceed: bool                # Go/No-Go
    blockers: list[str] = field(default_factory=list)    # Hard Blocker 목록
    warnings: list[str] = field(default_factory=list)    # Warning 목록
    alert_level: AlertLevel = AlertLevel.INFO
    gate_input: Optional[GateInput] = None
    # 조기 실패 시에도 symbol/exchange 정보 보존
    symbol: str = ""
    exchange: str = ""

    # Phase 5a 확장 필드
    supply_result: Optional[SupplyResult] = None
    listing_type_result: Optional[ListingTypeResult] = None
    recommended_strategy: StrategyCode = StrategyCode.WATCH_ONLY

    # Phase 6 확장 필드
    scenario_card: Optional[ScenarioCard] = None

    # Phase 7 확장 필드 (v10): VC/MM 정보
    vc_mm_info: Optional[ProjectVCInfo] = None


class GateChecker:
    """Go/No-Go Gate 판정기.

    단일 진입점: analyze_listing(symbol, exchange)
    내부에서 PremiumCalculator + CostModel 조합 처리.
    """

    def __init__(
        self,
        premium: PremiumCalculator,
        cost_model: CostModel,
        writer: DatabaseWriter,
        config_dir: str | Path | None = None,
        registry: Optional[TokenRegistry] = None,
    ) -> None:
        self._premium = premium
        self._cost_model = cost_model
        self._writer = writer
        self._registry = registry

        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self._config_dir = Path(config_dir)

        # VASP 매트릭스 로드
        self._vasp_matrix = self._load_vasp_matrix()

        # Feature flags 로드
        self._features = self._load_features()

        # Networks 설정 로드
        self._networks = self._load_networks()

        # Phase 5a: 분류기 초기화
        self._supply_classifier = SupplyClassifier(config_dir=config_dir)
        self._listing_classifier = ListingTypeClassifier(registry=registry)

        # Phase 5b: External Data Collectors (lazy init)
        self._dex_monitor = None
        self._hot_wallet_tracker = None
        self._withdrawal_tracker = None

        # Phase 6: Scenario Planner (lazy init)
        self._scenario_planner: Optional[ScenarioPlanner] = None

        # Phase 7: VC/MM Collector (lazy init)
        self._vc_mm_collector: Optional[VCMMCollector] = None

        # A3: 중복 분석 방지 캐시 (LRU + TTL)
        # maxsize=1000: 최대 1000개 분석 결과 보관
        # ttl=300: 5분 후 만료
        self._analysis_cache = LRUCache(maxsize=1000, ttl=300.0)

        # A2: 선물 마켓 목록 캐시 (1시간 TTL)
        # B3: Hyperliquid DEX 추가
        self._futures_cache: dict[str, set[str]] = {
            "binance": set(),
            "bybit": set(),
            "hyperliquid": set(),  # B3: DEX 선물
        }
        self._futures_cache_time: dict[str, float] = {
            "binance": 0.0,
            "bybit": 0.0,
            "hyperliquid": 0.0,
        }
        self._futures_cache_ttl = 3600.0  # 1시간

        # B2: API 메트릭 수집
        self._metrics: dict[str, APIMetrics] = {
            "binance_futures": APIMetrics(),
            "bybit_futures": APIMetrics(),
            "hyperliquid": APIMetrics(),  # B3: DEX 선물
            "coingecko": APIMetrics(),
            "upbit": APIMetrics(),
            "bithumb": APIMetrics(),
            "domestic_price": APIMetrics(),
            "global_vwap": APIMetrics(),
            "implied_fx": APIMetrics(),
            "etherscan_gas": APIMetrics(),  # C1: 네트워크 혼잡도
            "solana_rpc": APIMetrics(),
        }

        # C1: 네트워크 혼잡도 캐시 (5분 TTL)
        self._congestion_cache: dict[str, float] = {}  # network → congestion (0.0~1.0)
        self._congestion_cache_time: dict[str, float] = {}
        self._congestion_cache_ttl = 300.0  # 5분

        # C2: 공유 ClientSession (연결 풀 재사용)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """공유 aiohttp 세션 반환 (lazy init).

        연결 풀을 재사용하여 TCP 핸드셰이크 오버헤드 감소.
        - limit=100: 총 동시 연결 수
        - limit_per_host=30: 호스트당 동시 연결 수
        """
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,  # DNS 캐시 5분
                enable_cleanup_closed=True,
            )
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
            )
            logger.debug("[Gate] 공유 ClientSession 생성")
        return self._session

    async def close(self) -> None:
        """리소스 정리 (세션 종료).

        애플리케이션 종료 시 호출 권장.
        """
        if self._session is not None and not self._session.closed:
            await self._session.close()
            logger.debug("[Gate] 공유 ClientSession 종료")
        self._session = None

        # Phase 7: VCMMCollector 정리
        if self._vc_mm_collector is not None:
            await self._vc_mm_collector.close()
            logger.debug("[Gate] VCMMCollector 종료")
        self._vc_mm_collector = None

    async def analyze_listing(
        self, symbol: str, exchange: str,
        force: bool = False,
    ) -> GateResult | None:
        """상장 감지 시 전체 분석 파이프라인 실행.

        MarketMonitor._on_new_listing()에서 호출.

        Args:
            symbol: 토큰 심볼 (e.g., "XYZ").
            exchange: 상장 거래소 (e.g., "upbit", "bithumb").
            force: True면 캐시 무시하고 강제 분석.

        Returns:
            GateResult. 캐시 히트 시 캐시된 결과 반환.
        """
        import asyncio
        cache_key = f"{symbol}@{exchange}"

        # A3: LRU 캐시 조회 (5분 TTL, maxsize 1000)
        if not force:
            hit, cached_result = self._analysis_cache.get(cache_key)
            if hit:
                logger.info("[Gate] 캐시 히트: %s", cache_key)
                return cached_result

        # 주기적 캐시 정리 (10% 확률로 실행)
        import random
        if random.random() < 0.1:
            cleaned = self._analysis_cache.cleanup()
            if cleaned > 0:
                logger.debug("[Gate] 캐시 정리: %d개 만료 항목 제거", cleaned)

        # C2: 공유 세션 사용 (연결 풀 재사용)
        session = await self._get_session()

        # ============================================================
        # Phase A1: 독립 API 호출 병렬 실행 (asyncio.gather)
        # 순차 실행 시 ~3초 → 병렬 실행 시 ~1초
        # ============================================================

        # 병렬 실행할 태스크 정의
        fx_task = self._premium.get_implied_fx(session)
        krw_task = self._fetch_domestic_price_safe(symbol, exchange, session)
        vwap_task = self._premium.get_global_vwap(symbol, session)
        hedge_task = self._check_futures_market(symbol, session)

        # 병렬 실행 (예외 발생해도 다른 태스크 계속 실행)
        results = await asyncio.gather(
            fx_task, krw_task, vwap_task, hedge_task,
            return_exceptions=True,
        )

        fx_result, krw_price, vwap_result, hedge_type = results

        # FX 결과 처리 (실패 시 fallback) + 메트릭 기록
        if isinstance(fx_result, Exception):
            logger.warning("[Gate] FX 조회 실패: %s → fallback 사용", fx_result)
            self._record_api_failure("implied_fx", type(fx_result).__name__)
            fx_rate, fx_source = _get_fallback_fx(), "hardcoded_fallback"
        else:
            # FX 성공 (PremiumCalculator 내부 타이밍 미측정, 0으로 기록)
            self._record_api_success("implied_fx", 0)
            fx_rate, fx_source = fx_result

        # KRW 가격 처리 (실패 시 None) - 메트릭은 _fetch_domestic_price_safe에서 기록
        if isinstance(krw_price, Exception):
            logger.warning("[Gate] 국내 가격 조회 예외: %s", krw_price)
            krw_price = None

        # VWAP 결과 처리 (실패 시 None) + 메트릭 기록
        if isinstance(vwap_result, Exception):
            logger.warning("[Gate] VWAP 조회 예외: %s", vwap_result)
            self._record_api_failure("global_vwap", type(vwap_result).__name__)
            vwap_result = None
        else:
            # VWAP 성공 (PremiumCalculator 내부 타이밍 미측정, 0으로 기록)
            self._record_api_success("global_vwap", 0)

        # hedge_type 처리 (실패 시 "none") - 메트릭은 _refresh_futures_cache에서 기록
        if isinstance(hedge_type, Exception):
            logger.warning("[Gate] 선물 마켓 조회 예외: %s", hedge_type)
            hedge_type = "none"

        if krw_price is None or krw_price <= 0:
            logger.warning(
                "[Gate] 국내 가격 조회 실패: %s@%s", symbol, exchange,
            )
            result = GateResult(
                can_proceed=False,
                blockers=[f"국내 가격 조회 실패: {symbol}@{exchange}"],
                alert_level=AlertLevel.LOW,
                symbol=symbol,
                exchange=exchange,
            )
            self._analysis_cache.set(cache_key, result)
            return result

        if vwap_result is None or vwap_result.price_usd <= 0:
            logger.warning(
                "[Gate] 글로벌 가격 조회 실패: %s", symbol,
            )
            # 글로벌 가격 없으면 프리미엄 계산 불가 → blocker는 아님, 경고 수준
            result = GateResult(
                can_proceed=False,
                blockers=["글로벌 가격 조회 실패 (VWAP 없음)"],
                alert_level=AlertLevel.MEDIUM,
                symbol=symbol,
                exchange=exchange,
            )
            self._analysis_cache.set(cache_key, result)
            return result

        # 4. 프리미엄 계산
        premium_result = await self._premium.calculate_premium(
            krw_price=krw_price,
            global_usd_price=vwap_result.price_usd,
            fx_rate=fx_rate,
            fx_source=fx_source,
        )

        # 5. 네트워크 결정 (TokenRegistry 기반)
        network = self._determine_optimal_network(symbol)
        # hedge_type은 이미 병렬 실행에서 조회됨

        cost_result = self._cost_model.calculate_total_cost(
            premium_pct=premium_result.premium_pct,
            network=network,
            amount_krw=_DEFAULT_AMOUNT_KRW,
            hedge_type=hedge_type,
            fx_rate=fx_rate,
            domestic_exchange=exchange,
        )

        # 6. Gate 입력 조립
        # Phase 3: 입출금 상태는 알 수 없음 → 기본 open 가정
        networks_config = self._networks.get("networks", {})
        net_config = networks_config.get(network, {})
        base_transfer_time = net_config.get("avg_transfer_min", 5.0)

        # C1: 네트워크 혼잡도 반영
        congestion = await self._get_network_congestion(network, session)
        transfer_time = self._apply_congestion_to_transfer_time(
            base_transfer_time, congestion
        )
        if congestion > 0.5:
            logger.info(
                "[Gate] 네트워크 혼잡: %s (%.0f%%) → 전송시간 %.1f→%.1f분",
                network, congestion * 100, base_transfer_time, transfer_time,
            )

        gate_input = GateInput(
            symbol=symbol,
            exchange=exchange,
            premium_pct=premium_result.premium_pct,
            cost_result=cost_result,
            deposit_open=True,       # Phase 5+: 실제 API 조회
            withdrawal_open=True,    # Phase 5+: 실제 API 조회
            transfer_time_min=transfer_time,
            global_volume_usd=vwap_result.total_volume_usd,
            fx_source=fx_source,
            hedge_type=hedge_type,
            network=network,
            top_exchange=vwap_result.sources[0] if vwap_result.sources else "",
            domestic_price_krw=krw_price,
            global_price_usd=vwap_result.price_usd,
        )

        # 7. Hard Gate 판정 (1단계)
        result = self.check_hard_blockers(gate_input)

        # 8. Phase 5a 확장: Feature flag에 따라 2~4단계 실행
        if result.can_proceed:
            await self._run_phase5a_pipeline(result, gate_input, session)

        # A3: LRU 캐시 저장
        self._analysis_cache.set(cache_key, result)
        return result

    def check_hard_blockers(self, gate_input: GateInput) -> GateResult:
        """Hard Gate 4 Blockers + 3 Warnings 체크.

        단위 테스트용 공개 메서드: GateInput 직접 전달 가능.

        Args:
            gate_input: Gate 입력 데이터.

        Returns:
            GateResult.
        """
        blockers: list[str] = []
        warnings: list[str] = []

        # ---- Hard Blockers ----

        # 1. 입출금 차단
        if not gate_input.deposit_open:
            blockers.append(f"입금 차단: {gate_input.exchange}")
        if not gate_input.withdrawal_open:
            blockers.append(f"출금 차단: {gate_input.exchange}")

        # 2. 수익성 부족
        if gate_input.cost_result.net_profit_pct <= 0:
            blockers.append(
                f"수익성 부족: 순수익 {gate_input.cost_result.net_profit_pct:.2f}% "
                f"(프리미엄 {gate_input.premium_pct:.2f}% - "
                f"비용 {gate_input.cost_result.total_cost_pct:.2f}%)"
            )

        # 3. 전송 시간 초과
        if gate_input.transfer_time_min > _MAX_TRANSFER_MIN:
            blockers.append(
                f"전송 시간 초과: {gate_input.transfer_time_min:.0f}분 "
                f"(최대 {_MAX_TRANSFER_MIN}분)"
            )

        # 4. VASP 차단
        vasp_status = self._check_vasp(gate_input.exchange, gate_input.top_exchange)
        if vasp_status == "blocked":
            blockers.append(
                f"VASP 차단: {gate_input.exchange} → {gate_input.top_exchange}"
            )

        # ---- Warnings ----

        # 1. 유동성 부족
        if gate_input.global_volume_usd < _MIN_GLOBAL_VOLUME_USD:
            warnings.append(
                f"유동성 부족: 글로벌 24h volume ${gate_input.global_volume_usd:,.0f} "
                f"(최소 ${_MIN_GLOBAL_VOLUME_USD:,.0f})"
            )

        # 2. 네트워크 혼잡 (가스비 경고)
        if gate_input.cost_result.gas_warn:
            warnings.append(
                f"가스비 경고: {gate_input.network} "
                f"({gate_input.cost_result.gas_cost_krw:,.0f}원)"
            )

        # 3. DEX-only 헤징
        if gate_input.hedge_type == "dex_only":
            warnings.append("DEX-only 헤징: CEX 선물 미지원")

        # VASP warning (partial/unknown)
        if vasp_status in ("partial", "unknown"):
            warnings.append(
                f"VASP 주의: {gate_input.exchange} → {gate_input.top_exchange} "
                f"(상태: {vasp_status})"
            )

        # ---- FX hardcoded → WATCH_ONLY 강제 (v10) ----
        if self._is_watch_only(gate_input.fx_source):
            blockers.append(
                "FX 하드코딩 기본값 사용 중 — 프리미엄 신뢰 불가 (WATCH_ONLY)"
            )

        # ---- Feature Flag 분기 ----
        # Phase 5a: supply_classifier, listing_type
        # Phase 6: scenario_planner
        # 현재는 stub만 — feature flag OFF → skip

        # ---- 결과 조립 ----
        can_proceed = len(blockers) == 0
        alert_level = self._determine_alert_level(
            can_proceed, blockers, warnings, gate_input,
        )

        result = GateResult(
            can_proceed=can_proceed,
            blockers=blockers,
            warnings=warnings,
            alert_level=alert_level,
            gate_input=gate_input,
            symbol=gate_input.symbol,
            exchange=gate_input.exchange,
        )

        logger.info(
            "[Gate] %s@%s: %s (프리미엄=%.2f%%, 순수익=%.2f%%, "
            "blockers=%d, warnings=%d, level=%s)",
            gate_input.symbol, gate_input.exchange,
            "GO" if can_proceed else "NO-GO",
            gate_input.premium_pct,
            gate_input.cost_result.net_profit_pct,
            len(blockers), len(warnings),
            alert_level.value,
        )

        return result

    def _determine_alert_level(
        self,
        can_proceed: bool,
        blockers: list[str],
        warnings: list[str],
        gate_input: GateInput,
    ) -> AlertLevel:
        """알림 레벨 결정 (v10 정밀화).

        - GO + 행동 가능 전략 + 신뢰 FX → CRITICAL
        - GO + 일부 미달 → HIGH
        - NO-GO + blockers → HIGH (즉시 전송)
        - Warning만 → LOW
        - 기본 → INFO
        """
        if can_proceed:
            # FX 소스 신뢰성: btc_implied/eth_implied → 신뢰, 나머지 → 비신뢰
            trusted_fx = gate_input.fx_source in ("btc_implied", "eth_implied")

            # 행동 가능: hedge != none (CEX 또는 DEX 선물 존재)
            actionable = gate_input.hedge_type != "none"

            if trusted_fx and actionable and not warnings:
                return AlertLevel.CRITICAL
            return AlertLevel.HIGH

        # NO-GO — 상장 감지는 시간 민감 → 즉시 전송 (HIGH)
        if blockers:
            return AlertLevel.HIGH

        if warnings:
            return AlertLevel.LOW

        return AlertLevel.INFO

    def _check_vasp(
        self, from_exchange: str, to_exchange: str,
    ) -> str:
        """VASP 호환성 체크.

        Returns:
            "ok", "partial", "blocked", "unknown".
        """
        if not to_exchange:
            return "unknown"

        matrix = self._vasp_matrix.get("vasp_matrix", {})
        from_routes = matrix.get(from_exchange, {})
        route = from_routes.get(to_exchange, {})
        return route.get("status", "unknown")

    # ------------------------------------------------------------------
    # FX hardcoded → WATCH_ONLY 강제 (v10)
    # ------------------------------------------------------------------

    def _is_watch_only(self, fx_source: str) -> bool:
        """FX hardcoded 사용 시 WATCH_ONLY 강제."""
        return fx_source == "hardcoded_fallback"

    # ------------------------------------------------------------------
    # B2: API 메트릭 관리
    # ------------------------------------------------------------------

    def _record_api_success(self, api_name: str, latency_ms: float) -> None:
        """API 호출 성공 기록.

        Args:
            api_name: API 식별자 (e.g., "binance_futures", "coingecko")
            latency_ms: 응답 시간 (밀리초)
        """
        if api_name in self._metrics:
            self._metrics[api_name].record_success(latency_ms)

    def _record_api_failure(self, api_name: str, error_type: str) -> None:
        """API 호출 실패 기록.

        Args:
            api_name: API 식별자
            error_type: 에러 유형 (e.g., "timeout", "rate_limit", "http_500")
        """
        if api_name in self._metrics:
            self._metrics[api_name].record_failure(error_type)

    def get_metrics(self) -> dict[str, dict]:
        """전체 API 메트릭 반환 (health.json 연동용).

        Returns:
            각 API별 메트릭 딕셔너리
        """
        return {name: m.to_dict() for name, m in self._metrics.items()}

    def get_metrics_summary(self) -> str:
        """메트릭 요약 문자열 반환 (로깅/디버깅용)."""
        lines = ["[API Metrics Summary]"]
        for name, m in self._metrics.items():
            if m.total_calls > 0:
                lines.append(
                    f"  {name}: {m.success_rate:.1%} success, "
                    f"{m.avg_latency_ms:.0f}ms avg, "
                    f"{m.total_calls} calls"
                )
        return "\n".join(lines) if len(lines) > 1 else "[API Metrics] No calls yet"

    def reset_metrics(self) -> None:
        """모든 메트릭 초기화 (테스트용)."""
        for m in self._metrics.values():
            m.total_calls = 0
            m.success_calls = 0
            m.failed_calls = 0
            m.total_latency_ms = 0.0
            m.errors.clear()

    # ------------------------------------------------------------------
    # Config 로드
    # ------------------------------------------------------------------

    def _load_vasp_matrix(self) -> dict:
        """VASP 매트릭스 YAML 로드."""
        path = self._config_dir / "vasp_matrix.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        logger.warning("vasp_matrix.yaml 미발견")
        return {}

    def _load_features(self) -> dict:
        """Feature flags YAML 로드."""
        path = self._config_dir / "features.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        logger.warning("features.yaml 미발견")
        return {}

    def _load_networks(self) -> dict:
        """Networks YAML 로드."""
        path = self._config_dir / "networks.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        logger.warning("networks.yaml 미발견")
        return {}

    # ------------------------------------------------------------------
    # 국내 가격 조회 (빗썸)
    # ------------------------------------------------------------------

    @staticmethod
    async def _fetch_domestic_price(
        symbol: str, exchange: str, session: aiohttp.ClientSession,
    ) -> float | None:
        """빗썸 등 국내 거래소 가격 조회."""
        if exchange == "bithumb":
            try:
                url = f"https://api.bithumb.com/public/ticker/{symbol}_KRW"
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json(content_type=None)
                    if data.get("status") == "0000":
                        return float(data["data"].get("closing_price", 0))
            except Exception as e:
                logger.debug("빗썸 가격 조회 실패 (%s): %s", symbol, e)
        return None

    @staticmethod
    def _make_domestic_market(symbol: str, exchange: str) -> str:
        """국내 거래소별 마켓 코드 생성."""
        if exchange == "upbit":
            return f"KRW-{symbol}"
        if exchange == "bithumb":
            return f"{symbol}_KRW"
        return symbol

    async def _fetch_domestic_price_safe(
        self, symbol: str, exchange: str, session: aiohttp.ClientSession,
    ) -> float | None:
        """국내 가격 조회 (업비트/빗썸 통합, 병렬 실행용).

        asyncio.gather에서 사용하기 위한 안전한 래퍼.
        예외 발생 시 None 반환 (gather의 return_exceptions와 별도 처리).
        """
        start_time = time.time()
        api_name = exchange  # "upbit" or "bithumb"
        try:
            price: float | None = None
            if exchange == "upbit":
                krw_market = self._make_domestic_market(symbol, exchange)
                price = await _fetch_upbit_price(krw_market, session)
                if price is not None and price > 0:
                    latency_ms = (time.time() - start_time) * 1000
                    self._record_api_success(api_name, latency_ms)
                    return price
                # upbit 실패 시 fallback 없음 (upbit 전용)
                self._record_api_failure(api_name, "no_price")
                return None
            elif exchange == "bithumb":
                price = await self._fetch_domestic_price(symbol, exchange, session)
                latency_ms = (time.time() - start_time) * 1000
                if price is not None:
                    self._record_api_success(api_name, latency_ms)
                else:
                    self._record_api_failure(api_name, "no_price")
                return price
            else:
                # 알 수 없는 거래소
                logger.warning("[Gate] 지원하지 않는 거래소: %s", exchange)
                return None
        except Exception as e:
            self._record_api_failure(api_name, type(e).__name__)
            logger.debug("[Gate] 국내 가격 조회 예외 (%s@%s): %s", symbol, exchange, e)
            return None

    # ------------------------------------------------------------------
    # 선물 마켓 탐색 (hedge_type 결정)
    # ------------------------------------------------------------------

    @async_retry(max_retries=3, base_delay=0.5, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
    async def _fetch_binance_futures_list(
        self, session: aiohttp.ClientSession,
    ) -> set[str]:
        """Binance 선물 마켓 목록 조회 (재시도 적용)."""
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return {s["symbol"] for s in data.get("symbols", [])}

    @async_retry(max_retries=3, base_delay=0.5, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
    async def _fetch_bybit_futures_list(
        self, session: aiohttp.ClientSession,
    ) -> set[str]:
        """Bybit 선물 마켓 목록 조회 (재시도 적용)."""
        url = "https://api.bybit.com/v5/market/instruments-info?category=linear&limit=1000"
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if data.get("retCode") != 0:
                raise ValueError(f"Bybit API error: {data.get('retMsg')}")
            return {s["symbol"] for s in data.get("result", {}).get("list", [])}

    @async_retry(max_retries=3, base_delay=0.5, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
    async def _fetch_hyperliquid_futures_list(
        self, session: aiohttp.ClientSession,
    ) -> set[str]:
        """Hyperliquid DEX 무기한 선물 마켓 목록 조회 (재시도 적용).

        Hyperliquid는 탈중앙화 거래소로, CEX에 선물이 없는 토큰의
        헤지 수단으로 활용 가능 (hedge_type="dex_only").

        API 문서: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
        """
        url = "https://api.hyperliquid.xyz/info"
        payload = {"type": "meta"}
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            # Hyperliquid meta API 응답: {"universe": [{"name": "BTC", ...}, ...]}
            universe = data.get("universe", [])
            # Hyperliquid는 심볼 형식이 "BTC", "ETH" (USDT 접미사 없음)
            # CEX와 비교를 위해 "BTCUSDT" 형식으로 변환
            return {f"{asset['name']}USDT" for asset in universe if asset.get("name")}

    async def _refresh_futures_cache(
        self, exchange: str, session: aiohttp.ClientSession,
    ) -> None:
        """선물 마켓 목록 캐시 갱신 (1시간 TTL).

        Args:
            exchange: "binance", "bybit", 또는 "hyperliquid"
            session: aiohttp 세션
        """
        now = time.time()
        cache_age = now - self._futures_cache_time.get(exchange, 0)

        # TTL 내면 갱신 불필요 (단, 캐시가 비어있으면 항상 갱신 시도)
        if cache_age < self._futures_cache_ttl and self._futures_cache.get(exchange):
            return

        symbols: set[str] = set()
        # Hyperliquid는 _futures가 아닌 그냥 hyperliquid로 메트릭 기록
        api_name = "hyperliquid" if exchange == "hyperliquid" else f"{exchange}_futures"
        start_time = time.time()

        if exchange == "binance":
            try:
                symbols = await self._fetch_binance_futures_list(session)
                latency_ms = (time.time() - start_time) * 1000
                self._record_api_success(api_name, latency_ms)
                logger.info("[Gate] Binance 선물 캐시 갱신: %d 심볼 (%.0fms)", len(symbols), latency_ms)
            except Exception as e:
                self._record_api_failure(api_name, type(e).__name__)
                logger.warning("[Gate] Binance 선물 목록 조회 실패 (3회 재시도 후): %s", e)
                return  # 실패 시 기존 캐시 유지

        elif exchange == "bybit":
            try:
                symbols = await self._fetch_bybit_futures_list(session)
                latency_ms = (time.time() - start_time) * 1000
                self._record_api_success(api_name, latency_ms)
                logger.info("[Gate] Bybit 선물 캐시 갱신: %d 심볼 (%.0fms)", len(symbols), latency_ms)
            except Exception as e:
                self._record_api_failure(api_name, type(e).__name__)
                logger.warning("[Gate] Bybit 선물 목록 조회 실패 (3회 재시도 후): %s", e)
                return  # 실패 시 기존 캐시 유지

        elif exchange == "hyperliquid":
            try:
                symbols = await self._fetch_hyperliquid_futures_list(session)
                latency_ms = (time.time() - start_time) * 1000
                self._record_api_success(api_name, latency_ms)
                logger.info("[Gate] Hyperliquid DEX 캐시 갱신: %d 심볼 (%.0fms)", len(symbols), latency_ms)
            except Exception as e:
                self._record_api_failure(api_name, type(e).__name__)
                logger.warning("[Gate] Hyperliquid 마켓 목록 조회 실패 (3회 재시도 후): %s", e)
                return  # 실패 시 기존 캐시 유지

        if symbols:
            self._futures_cache[exchange] = symbols
            self._futures_cache_time[exchange] = now

    async def _check_futures_market(
        self, symbol: str, session: aiohttp.ClientSession,
    ) -> str:
        """선물 마켓 존재 여부 확인 (캐시 기반, O(1) 조회).

        확인 순서: Bybit → Binance → Hyperliquid (DEX)
        캐시 미스 시 자동 갱신 (1시간 TTL).

        Returns:
            "cex": CEX 선물 마켓 존재 (Bybit 또는 Binance)
            "dex_only": DEX에만 선물 존재 (Hyperliquid)
            "none": 선물 마켓 없음
        """
        futures_symbol = f"{symbol}USDT"

        # 캐시 갱신 (필요 시) - CEX 먼저
        await self._refresh_futures_cache("bybit", session)
        await self._refresh_futures_cache("binance", session)

        # 캐시가 비어있으면 경고 (API 실패 가능성)
        bybit_cache = self._futures_cache.get("bybit", set())
        binance_cache = self._futures_cache.get("binance", set())
        if not bybit_cache and not binance_cache:
            logger.warning(
                "[Gate] CEX 선물 캐시 비어있음 - API 연결 문제 가능성 (symbol=%s)",
                symbol
            )

        # Bybit 캐시에서 확인 (CEX 우선)
        if futures_symbol in bybit_cache:
            logger.debug("[Gate] 선물 발견: %s@Bybit (CEX)", futures_symbol)
            return "cex"

        # Binance 캐시에서 확인
        if futures_symbol in binance_cache:
            logger.debug("[Gate] 선물 발견: %s@Binance (CEX)", futures_symbol)
            return "cex"

        # B3: Hyperliquid DEX 확인 (CEX 없을 때만)
        await self._refresh_futures_cache("hyperliquid", session)
        hyperliquid_cache = self._futures_cache.get("hyperliquid", set())
        if futures_symbol in hyperliquid_cache:
            logger.debug("[Gate] 선물 발견: %s@Hyperliquid (DEX)", futures_symbol)
            return "dex_only"

        logger.debug("[Gate] 선물 마켓 없음: %s (bybit=%d, binance=%d, hl=%d)",
                     futures_symbol, len(bybit_cache), len(binance_cache), len(hyperliquid_cache))
        return "none"

    # ------------------------------------------------------------------
    # 네트워크 동적 결정 (TokenRegistry 기반)
    # ------------------------------------------------------------------

    # CoinGecko chain name → networks.yaml key 매핑
    _CHAIN_NAME_MAP = {
        "ethereum": "ethereum",
        "solana": "solana",
        "binance-smart-chain": "bsc",
        "bsc": "bsc",
        "arbitrum-one": "arbitrum",
        "arbitrum": "arbitrum",
        "polygon-pos": "polygon",
        "polygon": "polygon",
        "avalanche": "avalanche",
        "tron": "tron",
        "base": "base",
    }

    def _determine_optimal_network(self, symbol: str) -> str:
        """토큰의 최적 전송 네트워크 결정.

        TokenRegistry에서 토큰의 지원 체인 목록을 조회하고,
        networks.yaml 기준 가장 빠른 (avg_transfer_min 최소) 네트워크 선택.

        Args:
            symbol: 토큰 심볼 (e.g., "XYZ").

        Returns:
            네트워크 ID (e.g., "solana", "bsc", "ethereum").
            체인 정보 없으면 "ethereum" 반환.
        """
        # TokenRegistry 미설정 시 기본값
        if self._registry is None:
            logger.debug("[Gate] TokenRegistry 없음 → 기본 네트워크: ethereum")
            return "ethereum"

        # 토큰 정보 조회
        token = self._registry.get_by_symbol(symbol)
        if token is None or not token.chains:
            logger.debug("[Gate] 토큰 체인 정보 없음 (%s) → 기본 네트워크: ethereum", symbol)
            return "ethereum"

        # networks.yaml 설정
        networks_config = self._networks.get("networks", {})
        if not networks_config:
            logger.debug("[Gate] networks.yaml 없음 → 기본 네트워크: ethereum")
            return "ethereum"

        # 지원 체인 중 가장 빠른 네트워크 선택
        best_network = "ethereum"
        best_time = float("inf")

        for chain_info in token.chains:
            chain_name = chain_info.chain.lower()

            # CoinGecko chain name → networks.yaml key 변환
            network_key = self._CHAIN_NAME_MAP.get(chain_name)
            if network_key is None:
                logger.debug(
                    "[Gate] 알 수 없는 체인: %s (토큰: %s)", chain_name, symbol,
                )
                continue

            # networks.yaml에서 전송 시간 조회
            net_config = networks_config.get(network_key)
            if net_config is None:
                continue

            transfer_time = net_config.get("avg_transfer_min", float("inf"))
            if transfer_time < best_time:
                best_time = transfer_time
                best_network = network_key

        logger.info(
            "[Gate] 네트워크 결정: %s → %s (avg %.1f분, %d 체인 검토)",
            symbol, best_network, best_time if best_time < float("inf") else 5.0,
            len(token.chains),
        )
        return best_network

    # ------------------------------------------------------------------
    # C1: 네트워크 혼잡도 실시간 반영
    # ------------------------------------------------------------------

    async def _get_network_congestion(
        self, network: str, session: aiohttp.ClientSession,
    ) -> float:
        """네트워크 혼잡도 조회 (0.0~1.0, 캐시 5분 TTL).

        혼잡도는 전송 시간에 곱해지는 계수로 사용:
        - 0.0: 한산 (전송 시간 그대로)
        - 0.5: 보통
        - 1.0: 혼잡 (전송 시간 2배)

        Args:
            network: 네트워크 ID (e.g., "ethereum", "solana", "bsc")
            session: aiohttp 세션

        Returns:
            혼잡도 (0.0~1.0). 조회 실패 시 0.3 (보수적 기본값).
        """
        now = time.time()

        # 캐시 히트
        if network in self._congestion_cache:
            if now - self._congestion_cache_time.get(network, 0) < self._congestion_cache_ttl:
                return self._congestion_cache[network]

        # 네트워크별 혼잡도 조회
        congestion = 0.3  # 기본값 (보수적)

        if network == "ethereum":
            congestion = await self._fetch_ethereum_congestion(session)
        elif network == "solana":
            congestion = await self._fetch_solana_congestion(session)
        elif network in ("bsc", "polygon", "arbitrum", "base", "avalanche"):
            # EVM 호환 체인: 가스 가격 기반 추정 (간소화)
            congestion = await self._fetch_evm_congestion(network, session)
        elif network == "tron":
            congestion = 0.2  # TRON은 대체로 빠름
        else:
            congestion = 0.3  # 알 수 없는 네트워크

        # 캐시 저장
        self._congestion_cache[network] = congestion
        self._congestion_cache_time[network] = now

        return congestion

    async def _fetch_ethereum_congestion(
        self, session: aiohttp.ClientSession,
    ) -> float:
        """Ethereum 가스 가격 기반 혼잡도 조회.

        Etherscan Gas Tracker 또는 공개 RPC 사용.
        반환: 0.0 (< 20 gwei) ~ 1.0 (> 100 gwei)
        """
        start_time = time.time()
        try:
            # 공개 가스 API 사용 (API 키 불필요)
            url = "https://api.etherscan.io/api?module=gastracker&action=gasoracle"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return 0.3
                data = await resp.json()
                if data.get("status") != "1":
                    # Etherscan API 무료 한도 초과 시 대체 API 사용
                    return await self._fetch_ethereum_congestion_fallback(session)

                # ProposeGasPrice (gwei) 기준
                gas_gwei = float(data.get("result", {}).get("ProposeGasPrice", 30))
                latency_ms = (time.time() - start_time) * 1000
                self._record_api_success("etherscan_gas", latency_ms)

                # 가스 가격 → 혼잡도 변환
                # < 20 gwei: 0.0, 20-50 gwei: 0.0-0.5, 50-100 gwei: 0.5-1.0, > 100 gwei: 1.0
                if gas_gwei < 20:
                    return 0.0
                elif gas_gwei < 50:
                    return (gas_gwei - 20) / 60  # 0.0 ~ 0.5
                elif gas_gwei < 100:
                    return 0.5 + (gas_gwei - 50) / 100  # 0.5 ~ 1.0
                else:
                    return 1.0

        except Exception as e:
            self._record_api_failure("etherscan_gas", type(e).__name__)
            logger.debug("[Gate] Ethereum 가스 조회 실패: %s", e)
            return 0.3

    async def _fetch_ethereum_congestion_fallback(
        self, session: aiohttp.ClientSession,
    ) -> float:
        """Ethereum 혼잡도 fallback (공개 RPC)."""
        try:
            # Cloudflare Ethereum RPC (무료)
            url = "https://cloudflare-eth.com"
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_gasPrice",
                "params": [],
                "id": 1,
            }
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return 0.3
                data = await resp.json()
                gas_wei = int(data.get("result", "0x0"), 16)
                gas_gwei = gas_wei / 1e9

                if gas_gwei < 20:
                    return 0.0
                elif gas_gwei < 50:
                    return (gas_gwei - 20) / 60
                elif gas_gwei < 100:
                    return 0.5 + (gas_gwei - 50) / 100
                else:
                    return 1.0
        except Exception:
            return 0.3

    async def _fetch_solana_congestion(
        self, session: aiohttp.ClientSession,
    ) -> float:
        """Solana TPS 기반 혼잡도 조회.

        반환: 0.0 (TPS > 3000) ~ 1.0 (TPS < 1000)
        """
        start_time = time.time()
        try:
            # Solana 공개 RPC
            url = "https://api.mainnet-beta.solana.com"
            payload = {
                "jsonrpc": "2.0",
                "method": "getRecentPerformanceSamples",
                "params": [1],
                "id": 1,
            }
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return 0.2  # Solana 기본값 (빠름)
                data = await resp.json()
                samples = data.get("result", [])
                if not samples:
                    return 0.2

                # TPS 계산: numTransactions / samplePeriodSecs
                sample = samples[0]
                tps = sample.get("numTransactions", 0) / max(sample.get("samplePeriodSecs", 60), 1)

                latency_ms = (time.time() - start_time) * 1000
                self._record_api_success("solana_rpc", latency_ms)

                # TPS → 혼잡도 변환
                # > 3000 TPS: 0.0, 2000-3000: 0.0-0.3, 1000-2000: 0.3-0.7, < 1000: 0.7-1.0
                if tps > 3000:
                    return 0.0
                elif tps > 2000:
                    return 0.3 * (3000 - tps) / 1000
                elif tps > 1000:
                    return 0.3 + 0.4 * (2000 - tps) / 1000
                else:
                    return 0.7 + 0.3 * max(0, 1000 - tps) / 1000

        except Exception as e:
            self._record_api_failure("solana_rpc", type(e).__name__)
            logger.debug("[Gate] Solana TPS 조회 실패: %s", e)
            return 0.2

    async def _fetch_evm_congestion(
        self, network: str, session: aiohttp.ClientSession,
    ) -> float:
        """EVM 호환 체인 혼잡도 (간소화된 추정).

        대부분의 L2/사이드체인은 혼잡도가 낮음.
        """
        # 네트워크별 기본 혼잡도 (경험적 값)
        defaults = {
            "bsc": 0.15,       # BSC는 빠름
            "polygon": 0.2,   # Polygon 보통
            "arbitrum": 0.1,  # Arbitrum 빠름
            "base": 0.1,      # Base 빠름
            "avalanche": 0.15,  # Avalanche 빠름
        }
        return defaults.get(network, 0.3)

    def _apply_congestion_to_transfer_time(
        self, base_time: float, congestion: float,
    ) -> float:
        """혼잡도를 전송 시간에 적용.

        Args:
            base_time: 기본 전송 시간 (분)
            congestion: 혼잡도 (0.0~1.0)

        Returns:
            조정된 전송 시간 (분). 최대 2배까지 증가.
        """
        # 혼잡도 0.0 → 1.0배, 혼잡도 1.0 → 2.0배
        multiplier = 1.0 + congestion
        return base_time * multiplier

    # ------------------------------------------------------------------
    # Phase 5b: External Data Collectors
    # ------------------------------------------------------------------

    async def _init_phase5b_collectors(self) -> None:
        """Phase 5b 수집기 lazy 초기화."""
        if self._features.get("dex_monitor") and self._dex_monitor is None:
            try:
                from collectors.dex_monitor import DEXMonitor
                self._dex_monitor = DEXMonitor()
                logger.info("[Gate] DEXMonitor 초기화 완료")
            except Exception as e:
                logger.warning("[Gate] DEXMonitor 초기화 실패: %s", e)

        if self._features.get("hot_wallet_tracker") and self._hot_wallet_tracker is None:
            try:
                from collectors.hot_wallet_tracker import HotWalletTracker
                self._hot_wallet_tracker = HotWalletTracker(config_dir=self._config_dir)
                logger.info("[Gate] HotWalletTracker 초기화 완료")
            except Exception as e:
                logger.warning("[Gate] HotWalletTracker 초기화 실패: %s", e)

        if self._features.get("withdrawal_tracker") and self._withdrawal_tracker is None:
            try:
                from collectors.withdrawal_tracker import WithdrawalTracker
                self._withdrawal_tracker = WithdrawalTracker(config_dir=self._config_dir)
                logger.info("[Gate] WithdrawalTracker 초기화 완료")
            except Exception as e:
                logger.warning("[Gate] WithdrawalTracker 초기화 실패: %s", e)

    async def _collect_phase5b_data(
        self,
        symbol: str,
        exchange: str,
        top_exchange: str,
    ) -> tuple[
        Optional[float],  # dex_liquidity_usd
        Optional[float],  # hot_wallet_usd
        Optional[bool],   # withdrawal_open
        float,            # confidence
    ]:
        """Phase 5b 외부 데이터 수집.

        열화 규칙: 실패해도 None 반환, warning만.

        Returns:
            (dex_liquidity_usd, hot_wallet_usd, withdrawal_open, confidence)
        """
        await self._init_phase5b_collectors()

        dex_liquidity: Optional[float] = None
        hot_wallet: Optional[float] = None
        withdrawal_open: Optional[bool] = None
        confidences: list[float] = []

        # 1. DEX 유동성 조회
        if self._dex_monitor:
            try:
                result = await self._dex_monitor.get_liquidity(symbol)
                if result:
                    dex_liquidity = result.total_liquidity_usd
                    confidences.append(result.confidence)
                    logger.debug(
                        "[Gate] DEX %s: $%.2fK",
                        symbol, (dex_liquidity or 0) / 1000,
                    )
            except Exception as e:
                logger.warning("[Gate] DEX 조회 실패 (%s): %s", symbol, e)

        # 2. 핫월렛 잔액 조회
        if self._hot_wallet_tracker and top_exchange:
            try:
                result = await self._hot_wallet_tracker.get_exchange_balance(
                    exchange=top_exchange.lower(),
                )
                if result and result.total_balance_usd > 0:
                    hot_wallet = result.total_balance_usd
                    confidences.append(result.confidence)
                    logger.debug(
                        "[Gate] HotWallet %s@%s: $%.2fK",
                        symbol, top_exchange, (hot_wallet or 0) / 1000,
                    )
            except Exception as e:
                logger.warning(
                    "[Gate] 핫월렛 조회 실패 (%s@%s): %s",
                    symbol, top_exchange, e,
                )

        # 3. 입출금 상태 조회
        if self._withdrawal_tracker:
            try:
                # 국내 거래소 상태 조회
                result = await self._withdrawal_tracker.get_exchange_status(
                    symbol=symbol,
                    exchange=exchange,
                )
                if result:
                    withdrawal_open = result.withdrawal_open
                    confidences.append(result.confidence)
                    logger.debug(
                        "[Gate] Withdrawal %s@%s: %s",
                        symbol, exchange, withdrawal_open,
                    )
            except Exception as e:
                logger.warning(
                    "[Gate] 입출금 조회 실패 (%s@%s): %s",
                    symbol, exchange, e,
                )

        # 평균 신뢰도
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return dex_liquidity, hot_wallet, withdrawal_open, avg_confidence

    # ------------------------------------------------------------------
    # Phase 5a: 5단계 파이프라인 확장
    # ------------------------------------------------------------------

    async def _run_phase5a_pipeline(
        self,
        result: GateResult,
        gate_input: GateInput,
        session: aiohttp.ClientSession,
    ) -> None:
        """Phase 5a 분류 파이프라인 실행.

        2단계: Supply Classification
        3단계: Listing Type
        4단계: Strategy Determination

        열화 규칙: 실패해도 GO 유지, warning만 추가.
        """
        # Phase 5b: 외부 데이터 수집
        dex_liquidity, hot_wallet, withdrawal_open, phase5b_conf = (
            await self._collect_phase5b_data(
                symbol=gate_input.symbol,
                exchange=gate_input.exchange,
                top_exchange=gate_input.top_exchange,
            )
        )

        # 입출금 상태 업데이트 (Phase 5b 데이터 우선)
        if withdrawal_open is not None:
            gate_input.withdrawal_open = withdrawal_open

        # 2단계: Supply Classification (feature flag 체크)
        if self._features.get("supply_classifier"):
            try:
                supply_input = SupplyInput(
                    symbol=gate_input.symbol,
                    exchange=gate_input.exchange,
                    # Phase 5b 데이터 반영
                    dex_liquidity_usd=dex_liquidity,
                    dex_confidence=0.8 if dex_liquidity is not None else 0.0,
                    hot_wallet_usd=hot_wallet,
                    hot_wallet_confidence=0.8 if hot_wallet is not None else 0.0,
                    withdrawal_open=gate_input.withdrawal_open,
                    withdrawal_confidence=phase5b_conf if withdrawal_open is not None else 0.0,
                    network_speed_min=gate_input.transfer_time_min,
                    network_confidence=0.8,
                )
                result.supply_result = await self._supply_classifier.classify(supply_input)

                if result.supply_result.classification == SupplyClassification.UNKNOWN:
                    result.warnings.append("공급 분류 불가 — 데이터 부족")

                logger.info(
                    "[Gate] Supply: %s@%s → %s (score=%.2f)",
                    gate_input.symbol, gate_input.exchange,
                    result.supply_result.classification.value,
                    result.supply_result.total_score,
                )
            except Exception as e:
                logger.warning("[Gate] Supply 분류 실패: %s", e)
                result.warnings.append(f"Supply 분류 실패: {e}")

        # 3단계: Listing Type (feature flag 체크)
        if self._features.get("listing_type"):
            try:
                result.listing_type_result = await self._listing_classifier.classify(
                    symbol=gate_input.symbol,
                    exchange=gate_input.exchange,
                    top_exchange=gate_input.top_exchange,
                    session=session,
                )

                if result.listing_type_result.listing_type == ListingType.UNKNOWN:
                    result.warnings.append("상장유형 분류 불가 — WATCH_ONLY 강제 (v12)")
                    result.recommended_strategy = StrategyCode.WATCH_ONLY

                logger.info(
                    "[Gate] ListingType: %s@%s → %s (conf=%.2f)",
                    gate_input.symbol, gate_input.exchange,
                    result.listing_type_result.listing_type.value,
                    result.listing_type_result.confidence,
                )
            except Exception as e:
                logger.warning("[Gate] ListingType 분류 실패: %s", e)
                result.warnings.append(f"상장유형 분류 실패: {e}")
                result.recommended_strategy = StrategyCode.WATCH_ONLY

        # 4단계: Strategy Determination
        if result.supply_result and result.listing_type_result:
            result.recommended_strategy = self._determine_strategy(
                result.supply_result,
                result.listing_type_result,
                gate_input,
            )
            logger.info(
                "[Gate] Strategy: %s@%s → %s",
                gate_input.symbol, gate_input.exchange,
                result.recommended_strategy.value,
            )

        # 5단계: Scenario Generation (Phase 6 feature flag)
        if self._features.get("scenario_planner"):
            try:
                if self._scenario_planner is None:
                    self._scenario_planner = ScenarioPlanner(
                        config_dir=self._config_dir,
                        use_upbit_base=(gate_input.exchange.lower() == "upbit"),
                    )

                # 시장 상황 결정 (간단한 휴리스틱)
                market_condition = self._determine_market_condition()

                result.scenario_card = self._scenario_planner.generate_card(
                    symbol=gate_input.symbol,
                    exchange=gate_input.exchange,
                    supply_result=result.supply_result,
                    listing_type_result=result.listing_type_result,
                    hedge_type=gate_input.hedge_type,
                    market_condition=market_condition,
                )

                logger.info(
                    "[Gate] Scenario: %s@%s → %s (prob=%.1f%%)",
                    gate_input.symbol, gate_input.exchange,
                    result.scenario_card.predicted_outcome.value,
                    result.scenario_card.heung_probability * 100,
                )
            except Exception as e:
                logger.warning("[Gate] Scenario 생성 실패: %s", e)
                result.warnings.append(f"시나리오 생성 실패: {e}")

        # 6단계: VC/MM Check (Phase 7 feature flag)
        if self._features.get("vc_mm_check"):
            await self._run_vc_mm_check(result, gate_input)

    def _determine_market_condition(self) -> str:
        """시장 상황 결정 (간단한 휴리스틱).

        TODO: Phase 6에서 BTC/ETH 가격 추세 기반으로 개선.
        현재는 neutral 기본값.
        """
        # 향후 구현: BTC 24h 변화율 기반
        # - > 5%: bull
        # - < -5%: bear
        # - 그 외: neutral
        return "neutral"

    def _determine_strategy(
        self,
        supply: SupplyResult,
        listing_type: ListingTypeResult,
        gate_input: GateInput,
    ) -> StrategyCode:
        """전략 결정 (v6).

        공급 분류 + 상장 유형 조합으로 전략 결정.
        UNKNOWN 유형이면 WATCH_ONLY 강제 (v12).
        """
        # v12: UNKNOWN → WATCH_ONLY 강제
        if listing_type.listing_type == ListingType.UNKNOWN:
            return StrategyCode.WATCH_ONLY

        # v10: FX hardcoded → WATCH_ONLY 강제
        if gate_input.fx_source == "hardcoded_fallback":
            return StrategyCode.WATCH_ONLY

        # 공급 상태 기반 전략 결정
        supply_class = supply.classification

        # CONSTRAINED (공급 제약) → 공격적
        if supply_class == SupplyClassification.CONSTRAINED:
            # TGE는 더 공격적
            if listing_type.listing_type == ListingType.TGE:
                return StrategyCode.AGGRESSIVE
            # 직상장은 보통
            if listing_type.listing_type == ListingType.DIRECT:
                return StrategyCode.MODERATE
            # 옆상장은 보수적
            return StrategyCode.CONSERVATIVE

        # SMOOTH (공급 원활) → 보수적
        if supply_class == SupplyClassification.SMOOTH:
            # 옆상장은 관망
            if listing_type.listing_type == ListingType.SIDE:
                return StrategyCode.WATCH_ONLY
            return StrategyCode.CONSERVATIVE

        # NEUTRAL / UNKNOWN → 보수적
        return StrategyCode.CONSERVATIVE

    # ------------------------------------------------------------------
    # Phase 7: VC/MM Check (6단계)
    # ------------------------------------------------------------------

    async def _run_vc_mm_check(
        self,
        result: GateResult,
        gate_input: GateInput,
    ) -> None:
        """VC/MM 체크 (6단계).

        VC 투자자 및 MM 리스크 정보 수집 후 경고 추가.
        열화 규칙: 실패해도 GO 유지, warning만 추가.
        """
        try:
            # VCMMCollector lazy init
            if self._vc_mm_collector is None:
                self._vc_mm_collector = VCMMCollector(
                    config_dir=self._config_dir.parent / "data" / "vc_mm_info",
                )

            # VC/MM 정보 수집
            vc_info = await self._vc_mm_collector.collect(gate_input.symbol)
            result.vc_mm_info = vc_info

            # VC/MM 기반 경고 추가
            self._add_vc_mm_warnings(result, vc_info)

            logger.info(
                "[Gate] VC/MM: %s → Tier1=%d, Tier2=%d, risk=%s (conf=%.0f%%)",
                gate_input.symbol,
                len(vc_info.tier1_investors),
                len(vc_info.tier2_investors),
                vc_info.vc_risk_level,
                vc_info.confidence * 100,
            )
        except Exception as e:
            logger.warning("[Gate] VC/MM 체크 실패: %s", e)
            result.warnings.append(f"VC/MM 정보 조회 실패: {e}")

    def _add_vc_mm_warnings(
        self,
        result: GateResult,
        vc_info: ProjectVCInfo,
    ) -> None:
        """VC/MM 기반 경고 추가.

        Tier 1 VC 없음 → 정보성 경고
        MM 리스크 높음 (>=7) → 경고
        알 수 없는 VC → 정보성 경고
        """
        # VC 정보 없음
        if vc_info.data_source == "unknown":
            result.warnings.append("VC/MM 정보 없음 — 신규 프로젝트 가능성")
            return

        # MM 리스크 높음
        if vc_info.mm_confirmed and vc_info.mm_risk_score >= 7:
            result.warnings.append(
                f"⚠️ MM 리스크 높음: {vc_info.mm_name} "
                f"(리스크 점수 {vc_info.mm_risk_score:.1f}/10)"
            )

        # Tier 1 VC 없고 펀딩 정보 있음
        if not vc_info.tier1_investors and vc_info.total_funding_usd > 0:
            result.warnings.append(
                f"Tier 1 VC 없음 (펀딩 ${vc_info.total_funding_usd:,.0f})"
            )

        # 리스크 레벨 높음
        if vc_info.vc_risk_level == "high":
            result.warnings.append("⚠️ VC/MM 종합 리스크 높음")

        # Tier 1 VC 있으면 긍정적 로깅 (경고 아님)
        if vc_info.tier1_investors:
            logger.info(
                "[Gate] ✅ Tier 1 VC 확인: %s",
                ", ".join(vc_info.tier1_investors[:3]),
            )
