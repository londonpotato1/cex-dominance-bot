"""비용 모델 (Phase 3).

오더북 슬리피지 시뮬레이션, 헤지 비용, 네트워크 수수료를 포함한
총 비용 모델. 프리미엄에서 비용을 차감하여 순수익을 계산.

비용 구성:
  1. 거래 수수료 (maker/taker)
  2. 오더북 슬리피지
  3. 네트워크 출금 수수료
  4. 헤지 비용 (선물 수수료 + 펀딩비)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class CostResult:
    """총 비용 계산 결과."""
    slippage_pct: float         # 오더북 슬리피지 (%)
    gas_cost_krw: float         # 네트워크 전송 비용 (KRW)
    exchange_fee_pct: float     # 거래소 수수료 (%)
    hedge_cost_pct: float       # 헤지 비용 (%)
    total_cost_pct: float       # 총 비용 (%)
    net_profit_pct: float       # 순수익 (프리미엄 - 총비용) (%)
    gas_warn: bool              # 가스비 경고 (원금 1% 초과)


@dataclass
class HedgeCost:
    """헤지 비용 (v14 스펙).

    hedge_type:
      - "cex": CEX 선물 헤징 (Binance/Bybit perpetual)
      - "dex_only": DEX 선물만 가능 (dYdX, GMX 등)
      - "none": 헤징 불가 (네이키드 포지션)
    """
    hedge_type: str
    fee_pct: float              # 헤지 수수료 (%)
    funding_cost_pct: float     # 예상 펀딩 비용 (8시간 기준, %)


class CostModel:
    """비용 모델 계산기.

    config/fees.yaml, config/networks.yaml 기반.
    """

    def __init__(self, config_dir: str | Path | None = None) -> None:
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        config_dir = Path(config_dir)

        # fees.yaml 로드
        fees_path = config_dir / "fees.yaml"
        if fees_path.exists():
            with open(fees_path, encoding="utf-8") as f:
                self._fees = yaml.safe_load(f) or {}
        else:
            logger.warning("fees.yaml 미발견, 기본값 사용")
            self._fees = {}

        # networks.yaml 로드
        networks_path = config_dir / "networks.yaml"
        if networks_path.exists():
            with open(networks_path, encoding="utf-8") as f:
                self._networks = yaml.safe_load(f) or {}
        else:
            logger.warning("networks.yaml 미발견, 기본값 사용")
            self._networks = {}

    def get_hedge_cost(self, hedge_type: str) -> HedgeCost:
        """헤지 유형별 비용 조회.

        Args:
            hedge_type: "cex", "dex_only", "none".

        Returns:
            HedgeCost 인스턴스.
        """
        hedge_fees = self._fees.get("hedge_fees", {})

        if hedge_type == "cex":
            cex = hedge_fees.get("cex_perpetual", {})
            fee = cex.get("taker", 0.0005)
            funding = cex.get("funding_8h_avg", 0.0001)
            return HedgeCost(
                hedge_type="cex",
                fee_pct=fee * 100,
                funding_cost_pct=funding * 100,
            )

        if hedge_type == "dex_only":
            dex = hedge_fees.get("dex_perpetual", {})
            fee = dex.get("taker", 0.0005)
            return HedgeCost(
                hedge_type="dex_only",
                fee_pct=fee * 100,
                funding_cost_pct=0.0,  # DEX 펀딩비는 가변, 단순화
            )

        # hedge_type == "none"
        return HedgeCost(
            hedge_type="none",
            fee_pct=0.0,
            funding_cost_pct=0.0,
        )

    def estimate_slippage(
        self,
        orderbook: dict | None,
        amount_krw: float,
    ) -> float:
        """오더북 워크스루 슬리피지 시뮬레이션.

        Args:
            orderbook: {"asks": [[price, qty], ...], "bids": [[price, qty], ...]}
                       또는 None (오더북 없을 시 기본값).
            amount_krw: 매수 금액 (KRW).

        Returns:
            슬리피지 퍼센트 (e.g., 0.5 = 0.5%).
        """
        if not orderbook or not orderbook.get("asks"):
            # 오더북 없으면 보수적 기본값
            return 1.0

        asks = orderbook["asks"]
        if not asks:
            return 1.0

        mid_price = float(asks[0][0])
        if mid_price <= 0:
            return 1.0

        remaining = amount_krw
        total_cost = 0.0
        total_qty = 0.0

        for level in asks:
            price = float(level[0])
            qty = float(level[1])
            level_value = price * qty

            if remaining <= level_value:
                # 이 호가에서 잔여 금액 소진
                fill_qty = remaining / price
                total_cost += remaining
                total_qty += fill_qty
                remaining = 0
                break
            else:
                total_cost += level_value
                total_qty += qty
                remaining -= level_value

        if total_qty <= 0:
            return 1.0

        avg_price = total_cost / total_qty
        slippage_pct = ((avg_price - mid_price) / mid_price) * 100.0

        # 잔여 금액이 있으면 (오더북 소진) 추가 슬리피지
        if remaining > 0:
            unfilled_ratio = remaining / amount_krw
            slippage_pct += unfilled_ratio * 5.0  # 미체결 비율당 5% 가산

        return max(0.0, slippage_pct)

    def get_gas_cost_krw(
        self,
        network: str,
        fx_rate: float,
    ) -> float:
        """네트워크 출금 수수료 (KRW 환산).

        Args:
            network: 네트워크 이름 (e.g., "ethereum", "solana").
            fx_rate: KRW/USD 환율.

        Returns:
            출금 수수료 (KRW).
        """
        withdrawal_fees = self._fees.get("withdrawal_fees", {})
        net_fees = withdrawal_fees.get(network, {})
        usdt_fee = net_fees.get("usdt", 1.0)  # 기본 1 USDT
        return usdt_fee * fx_rate

    def calculate_total_cost(
        self,
        premium_pct: float,
        network: str,
        amount_krw: float,
        hedge_type: str,
        fx_rate: float,
        orderbook: dict | None = None,
        domestic_exchange: str = "upbit",
        global_exchange: str = "binance",
    ) -> CostResult:
        """총 비용 계산.

        Args:
            premium_pct: 프리미엄 퍼센트.
            network: 전송 네트워크.
            amount_krw: 거래 금액 (KRW).
            hedge_type: "cex", "dex_only", "none".
            fx_rate: KRW/USD 환율.
            orderbook: 오더북 데이터 (None이면 기본값).
            domestic_exchange: 국내 거래소.
            global_exchange: 글로벌 거래소.

        Returns:
            CostResult.
        """
        # 1. 거래소 수수료 (국내 매수 taker + 글로벌 매도 taker)
        trading_fees = self._fees.get("trading_fees", {})
        domestic_fee = trading_fees.get(domestic_exchange, {}).get("taker", 0.0005)
        global_fee = trading_fees.get(global_exchange, {}).get("taker", 0.0010)
        exchange_fee_pct = (domestic_fee + global_fee) * 100

        # 2. 오더북 슬리피지
        slippage_pct = self.estimate_slippage(orderbook, amount_krw)

        # 3. 네트워크 출금 수수료
        gas_cost_krw = self.get_gas_cost_krw(network, fx_rate)
        gas_cost_pct = (gas_cost_krw / amount_krw * 100) if amount_krw > 0 else 0.0

        # 4. 헤지 비용
        hedge = self.get_hedge_cost(hedge_type)
        hedge_cost_pct = hedge.fee_pct + hedge.funding_cost_pct

        # 총 비용
        total_cost_pct = exchange_fee_pct + slippage_pct + gas_cost_pct + hedge_cost_pct

        # 순수익
        net_profit_pct = premium_pct - total_cost_pct

        # 가스비 경고
        cost_thresholds = self._fees.get("cost_thresholds", {})
        gas_warn_pct = cost_thresholds.get("gas_warn_pct", 0.01) * 100
        gas_warn = gas_cost_pct > gas_warn_pct

        return CostResult(
            slippage_pct=round(slippage_pct, 4),
            gas_cost_krw=round(gas_cost_krw, 2),
            exchange_fee_pct=round(exchange_fee_pct, 4),
            hedge_cost_pct=round(hedge_cost_pct, 4),
            total_cost_pct=round(total_cost_pct, 4),
            net_profit_pct=round(net_profit_pct, 4),
            gas_warn=gas_warn,
        )
