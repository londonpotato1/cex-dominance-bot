"""Go/No-Go Gate 판정 (Phase 3).

Hard Gate 4 Blockers + 3 Warnings.
MarketMonitor._on_new_listing() → gate_checker.analyze_listing(symbol, exchange)

4 Hard Blockers:
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

if TYPE_CHECKING:
    from store.writer import DatabaseWriter

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


@dataclass
class GateResult:
    """Gate 판정 결과."""
    can_proceed: bool                # Go/No-Go
    blockers: list[str] = field(default_factory=list)    # Hard Blocker 목록
    warnings: list[str] = field(default_factory=list)    # Warning 목록
    alert_level: AlertLevel = AlertLevel.INFO
    gate_input: Optional[GateInput] = None


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
    ) -> None:
        self._premium = premium
        self._cost_model = cost_model
        self._writer = writer

        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self._config_dir = Path(config_dir)

        # VASP 매트릭스 로드
        self._vasp_matrix = self._load_vasp_matrix()

        # Feature flags 로드
        self._features = self._load_features()

        # Networks 설정 로드
        self._networks = self._load_networks()

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

            # 7. Hard Gate 판정
            return self.check_hard_blockers(gate_input)

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
