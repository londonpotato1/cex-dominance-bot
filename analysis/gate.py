"""Go/No-Go Gate 판정 (Phase 3 + Phase 5a 확장).

5단계 파이프라인 (v9):
  1단계: Hard Gate (v5) → 입출금/수익성/전송시간/VASP Blocker 체크
  2단계: Supply Classification (v6) → 원활/미원활 판정
  3단계: Listing Type (v6) → TGE/직상장/옆상장 분류
  4단계: Strategy Determination (v6) → 공급+유형 조합별 전략 결정
  5단계: Scenario Generation (v6) → 흥/망따리 카드 생성

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

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import aiohttp
import yaml

from analysis.premium import PremiumCalculator, _fetch_upbit_price
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

    # Phase 5a 확장 필드
    supply_result: Optional[SupplyResult] = None
    listing_type_result: Optional[ListingTypeResult] = None
    recommended_strategy: StrategyCode = StrategyCode.WATCH_ONLY


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

    async def analyze_listing(
        self, symbol: str, exchange: str,
    ) -> GateResult:
        """상장 감지 시 전체 분석 파이프라인 실행.

        MarketMonitor._on_new_listing()에서 호출.

        Args:
            symbol: 토큰 심볼 (e.g., "XYZ").
            exchange: 상장 거래소 (e.g., "upbit", "bithumb").

        Returns:
            GateResult.
        """
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            # 1. FX 환율 조회
            fx_rate, fx_source = await self._premium.get_implied_fx(session)

            # 2. 국내 가격 조회
            krw_market = self._make_domestic_market(symbol, exchange)
            krw_price = await _fetch_upbit_price(krw_market, session) if exchange == "upbit" else None
            if krw_price is None:
                # Upbit 외 거래소이거나 조회 실패 시
                krw_price = await self._fetch_domestic_price(symbol, exchange, session)

            # 3. 글로벌 VWAP 조회
            vwap_result = await self._premium.get_global_vwap(symbol, session)

            if krw_price is None or krw_price <= 0:
                logger.warning(
                    "[Gate] 국내 가격 조회 실패: %s@%s", symbol, exchange,
                )
                return GateResult(
                    can_proceed=False,
                    blockers=[f"국내 가격 조회 실패: {symbol}@{exchange}"],
                    alert_level=AlertLevel.LOW,
                )

            if vwap_result is None or vwap_result.price_usd <= 0:
                logger.warning(
                    "[Gate] 글로벌 가격 조회 실패: %s", symbol,
                )
                # 글로벌 가격 없으면 프리미엄 계산 불가 → blocker는 아님, 경고 수준
                return GateResult(
                    can_proceed=False,
                    blockers=["글로벌 가격 조회 실패 (VWAP 없음)"],
                    alert_level=AlertLevel.MEDIUM,
                )

            # 4. 프리미엄 계산
            premium_result = await self._premium.calculate_premium(
                krw_price=krw_price,
                global_usd_price=vwap_result.price_usd,
                fx_rate=fx_rate,
                fx_source=fx_source,
            )

            # 5. 비용 계산
            # 네트워크/헤지 유형은 Phase 3에서는 기본값 사용
            network = "ethereum"  # Phase 5+에서 동적 결정
            hedge_type = "none"   # Phase 5+에서 선물 마켓 탐색

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
            transfer_time = net_config.get("avg_transfer_min", 5.0)

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
            )

            # 7. Hard Gate 판정 (1단계)
            result = self.check_hard_blockers(gate_input)

            # 8. Phase 5a 확장: Feature flag에 따라 2~4단계 실행
            if result.can_proceed:
                await self._run_phase5a_pipeline(result, gate_input, session)

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
