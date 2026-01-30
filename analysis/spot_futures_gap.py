"""현선갭 모니터 (Phase 8 Week 7).

국내 현물 가격 vs 글로벌 참조 가격 갭 계산.

핵심 기능:
  1. 국내 현물 (업비트/빗썸) KRW 가격 조회
  2. 글로벌 참조 가격 (6단계 폴백 체인 via reference_price.py)
  3. FX 환율 적용 → KRW 갭 계산
  4. 헤징 가능 여부 판단
  5. 실시간 갭 추적 + 알림

헤징 전략:
  - 갭 > 0 (김프): 국내 매도 + 글로벌 롱
  - 갭 < 0 (역프): 국내 매수 + 글로벌 숏 (주의!)
  - |갭| < 2%: 헤지 불가 (비용 > 수익)

v17 개선:
  - ReferencePriceFetcher 연동 (6단계 폴백)
  - 신뢰도 기반 의사결정
  - 갭 히스토리 추적
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, Protocol

import aiohttp

from analysis.reference_price import ReferencePriceFetcher, ReferencePrice, ReferenceSource

logger = logging.getLogger(__name__)


# FX 환율 기본값 (외부 주입 권장)
_DEFAULT_FX_RATE = 1350.0


class HedgeStrategy(Enum):
    """헤징 전략."""
    LONG_GLOBAL_SHORT_DOMESTIC = "long_global"    # 역프: 글로벌 롱 + 국내 숏
    SHORT_GLOBAL_LONG_DOMESTIC = "short_global"   # 김프: 글로벌 숏 + 국내 롱
    NO_HEDGE = "no_hedge"                         # 헤지 불가


class HedgeType(Enum):
    """헤지 유형."""
    CEX_FUTURES = "cex_futures"    # 글로벌 선물로 헤지
    CEX_SPOT = "cex_spot"          # 글로벌 현물로 헤지
    DEX_PERP = "dex_perp"          # DEX 무기한 선물
    NONE = "none"                  # 헤지 불가


@dataclass
class SpotFuturesGap:
    """현선갭 결과."""
    symbol: str
    domestic_exchange: str        # "upbit" or "bithumb"

    # 가격 정보
    domestic_price_krw: float     # 국내 현물 가격 (KRW)
    reference_price_usd: float    # 글로벌 참조 가격 (USD)
    reference_price_krw: float    # 글로벌 참조 가격 (KRW 환산)

    # FX
    fx_rate: float                # 적용된 환율

    # 갭
    gap_krw: float                # 갭 (KRW)
    gap_pct: float                # 갭 (%)
    is_positive_gap: bool         # True = 김프, False = 역프

    # 참조 가격 메타데이터
    reference_source: ReferenceSource
    reference_confidence: float   # 참조 가격 신뢰도 (0.0 ~ 1.0)

    # 헤징 정보
    hedgeable: bool               # 헤지 가능 여부
    hedge_strategy: HedgeStrategy
    hedge_type: HedgeType
    min_profitable_gap: float     # 수익 가능 최소 갭 (%)

    # 타임스탬프
    timestamp: datetime = field(default_factory=datetime.now)

    # 경고
    warnings: list[str] = field(default_factory=list)


@dataclass
class GapHistoryEntry:
    """갭 히스토리 항목."""
    timestamp: datetime
    gap_pct: float
    domestic_price_krw: float
    reference_price_krw: float


class GapAlertCallback(Protocol):
    """갭 알림 콜백."""
    async def __call__(self, gap: SpotFuturesGap) -> None:
        ...


class SpotFuturesGapMonitor:
    """현선갭 모니터.

    국내 현물 vs 글로벌 참조 가격 갭을 계산하고 추적.

    사용법:
        monitor = SpotFuturesGapMonitor(fx_rate=1350.0)
        gap = await monitor.calculate_gap(
            symbol="BTC",
            domestic_exchange="upbit",
            domestic_price_krw=135_000_000,
        )
        if gap.hedgeable:
            print(f"Gap: {gap.gap_pct:.2f}%, Strategy: {gap.hedge_strategy}")
    """

    # 헤지 비용 (수수료 + 슬리피지)
    HEDGE_COST_CEX_FUTURES = 0.15   # 0.15% (maker 0.02% x 2 + 슬리피지)
    HEDGE_COST_CEX_SPOT = 0.30      # 0.30% (maker 0.1% x 2 + 슬리피지)
    HEDGE_COST_DEX = 0.50           # 0.50% (DEX 수수료 + 가스)

    # 최소 갭 (수익 가능)
    MIN_PROFITABLE_GAP_FUTURES = 1.0  # 1%
    MIN_PROFITABLE_GAP_SPOT = 2.0     # 2%

    def __init__(
        self,
        fx_rate: float = _DEFAULT_FX_RATE,
        ref_fetcher: ReferencePriceFetcher | None = None,
        session: aiohttp.ClientSession | None = None,
        alert_callback: GapAlertCallback | None = None,
        alert_threshold_pct: float = 5.0,
    ) -> None:
        """
        Args:
            fx_rate: USD/KRW 환율.
            ref_fetcher: Reference price fetcher (없으면 생성).
            session: aiohttp 세션.
            alert_callback: 갭 알림 콜백.
            alert_threshold_pct: 알림 임계값 (%).
        """
        self._fx_rate = fx_rate
        self._ref_fetcher = ref_fetcher or ReferencePriceFetcher()
        self._external_session = session  # 외부 주입 세션
        self._internal_session: aiohttp.ClientSession | None = None  # 내부 생성 세션
        self._alert_callback = alert_callback
        self._alert_threshold = alert_threshold_pct

        # 갭 히스토리 {symbol: [GapHistoryEntry]}
        self._gap_history: dict[str, list[GapHistoryEntry]] = {}
        self._max_history_size = 100  # 심볼당 최대 100개

    async def _get_session(self) -> aiohttp.ClientSession:
        """세션 반환 (외부 주입 또는 내부 생성)."""
        if self._external_session is not None:
            return self._external_session
        if self._internal_session is None:
            self._internal_session = aiohttp.ClientSession()
        return self._internal_session

    async def close(self) -> None:
        """내부 생성 세션 정리 (외부 주입 세션은 정리 안함)."""
        if self._internal_session is not None:
            await self._internal_session.close()
            self._internal_session = None

    async def __aenter__(self) -> "SpotFuturesGapMonitor":
        """Async context manager 진입."""
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager 종료."""
        await self.close()

    async def calculate_gap(
        self,
        symbol: str,
        domestic_exchange: str,
        domestic_price_krw: float,
        fx_rate: float | None = None,
    ) -> SpotFuturesGap | None:
        """현선갭 계산.

        Args:
            symbol: 토큰 심볼.
            domestic_exchange: 국내 거래소 ("upbit", "bithumb").
            domestic_price_krw: 국내 현물 가격 (KRW).
            fx_rate: 환율 (None이면 기본값).

        Returns:
            SpotFuturesGap 또는 참조 가격 조회 실패 시 None.
        """
        if fx_rate is None:
            fx_rate = self._fx_rate

        # 세션 획득 (외부 주입 또는 내부 생성)
        session = await self._get_session()

        # 참조 가격 조회 (6단계 폴백)
        ref_price = await self._ref_fetcher.get_reference_price(
            symbol, session,
        )

        if ref_price is None:
            logger.warning(
                "[SpotFuturesGap] %s 참조 가격 조회 실패", symbol,
            )
            return None

        # KRW 환산
        ref_price_krw = ref_price.price_usd * fx_rate

        # 갭 계산
        gap_krw = domestic_price_krw - ref_price_krw
        gap_pct = (gap_krw / ref_price_krw) * 100 if ref_price_krw > 0 else 0
        is_positive = gap_pct > 0

        # 헤지 유형 결정
        hedge_type = self._determine_hedge_type(ref_price.source)

        # 최소 수익 갭
        min_gap = self._get_min_profitable_gap(hedge_type)

        # 헤지 가능 여부
        hedgeable = abs(gap_pct) >= min_gap and hedge_type != HedgeType.NONE

        # 헤지 전략
        if not hedgeable:
            strategy = HedgeStrategy.NO_HEDGE
        elif is_positive:
            strategy = HedgeStrategy.SHORT_GLOBAL_LONG_DOMESTIC
        else:
            strategy = HedgeStrategy.LONG_GLOBAL_SHORT_DOMESTIC

        # 경고 생성
        warnings = self._generate_warnings(
            gap_pct, ref_price.confidence, hedge_type,
        )

        gap_result = SpotFuturesGap(
            symbol=symbol,
            domestic_exchange=domestic_exchange,
            domestic_price_krw=domestic_price_krw,
            reference_price_usd=ref_price.price_usd,
            reference_price_krw=ref_price_krw,
            fx_rate=fx_rate,
            gap_krw=gap_krw,
            gap_pct=gap_pct,
            is_positive_gap=is_positive,
            reference_source=ref_price.source,
            reference_confidence=ref_price.confidence,
            hedgeable=hedgeable,
            hedge_strategy=strategy,
            hedge_type=hedge_type,
            min_profitable_gap=min_gap,
            warnings=warnings,
        )

        # 히스토리 저장
        self._add_to_history(symbol, gap_result)

        # 알림 체크
        if self._alert_callback and abs(gap_pct) >= self._alert_threshold:
            await self._alert_callback(gap_result)

        logger.info(
            "[SpotFuturesGap] %s@%s: gap=%.2f%%, hedgeable=%s, source=%s",
            symbol, domestic_exchange, gap_pct, hedgeable, ref_price.source.value,
        )

        return gap_result

    def _determine_hedge_type(self, source: ReferenceSource) -> HedgeType:
        """참조 소스에 따른 헤지 유형."""
        if source in (ReferenceSource.BINANCE_FUTURES, ReferenceSource.BYBIT_FUTURES):
            return HedgeType.CEX_FUTURES
        elif source in (ReferenceSource.BINANCE_SPOT, ReferenceSource.OKX_SPOT):
            return HedgeType.CEX_SPOT
        elif source == ReferenceSource.COINGECKO:
            # CoinGecko는 집계 가격 → 헤지 불가 (특정 거래소 아님)
            return HedgeType.NONE
        else:
            return HedgeType.NONE

    def _get_min_profitable_gap(self, hedge_type: HedgeType) -> float:
        """헤지 유형에 따른 최소 수익 갭."""
        if hedge_type == HedgeType.CEX_FUTURES:
            return self.MIN_PROFITABLE_GAP_FUTURES + self.HEDGE_COST_CEX_FUTURES
        elif hedge_type == HedgeType.CEX_SPOT:
            return self.MIN_PROFITABLE_GAP_SPOT + self.HEDGE_COST_CEX_SPOT
        elif hedge_type == HedgeType.DEX_PERP:
            return self.MIN_PROFITABLE_GAP_SPOT + self.HEDGE_COST_DEX
        else:
            return 100.0  # 헤지 불가

    def _generate_warnings(
        self,
        gap_pct: float,
        confidence: float,
        hedge_type: HedgeType,
    ) -> list[str]:
        """경고 생성."""
        warnings = []

        # 낮은 신뢰도
        if confidence < 0.6:
            warnings.append(f"⚠️ 참조 가격 신뢰도 낮음 ({confidence:.0%})")
        elif confidence < 0.8:
            warnings.append(f"⚠️ 참조 가격 신뢰도 보통 ({confidence:.0%})")

        # 역프
        if gap_pct < -2:
            warnings.append(f"🚨 역프리미엄 주의 ({gap_pct:.1f}%)")

        # 헤지 불가
        if hedge_type == HedgeType.NONE:
            warnings.append("⚠️ 헤지 불가 (참조 소스가 거래소 아님)")

        # 현물만 가능
        if hedge_type == HedgeType.CEX_SPOT:
            warnings.append("ℹ️ 선물 미상장 → 현물 헤지만 가능")

        return warnings

    def _add_to_history(self, symbol: str, gap: SpotFuturesGap) -> None:
        """히스토리에 추가."""
        if symbol not in self._gap_history:
            self._gap_history[symbol] = []

        history = self._gap_history[symbol]
        history.append(GapHistoryEntry(
            timestamp=gap.timestamp,
            gap_pct=gap.gap_pct,
            domestic_price_krw=gap.domestic_price_krw,
            reference_price_krw=gap.reference_price_krw,
        ))

        # 최대 크기 제한
        if len(history) > self._max_history_size:
            self._gap_history[symbol] = history[-self._max_history_size:]

    def get_gap_history(
        self,
        symbol: str,
        limit: int = 50,
    ) -> list[GapHistoryEntry]:
        """갭 히스토리 조회."""
        history = self._gap_history.get(symbol, [])
        return history[-limit:]

    def get_gap_statistics(
        self,
        symbol: str,
    ) -> dict[str, float]:
        """갭 통계 계산."""
        history = self._gap_history.get(symbol, [])
        if not history:
            return {
                "count": 0,
                "avg_gap": 0.0,
                "max_gap": 0.0,
                "min_gap": 0.0,
                "current_gap": 0.0,
            }

        gaps = [h.gap_pct for h in history]
        return {
            "count": len(gaps),
            "avg_gap": sum(gaps) / len(gaps),
            "max_gap": max(gaps),
            "min_gap": min(gaps),
            "current_gap": gaps[-1] if gaps else 0.0,
        }

    def update_fx_rate(self, fx_rate: float) -> None:
        """환율 업데이트."""
        self._fx_rate = fx_rate
        logger.info("[SpotFuturesGap] FX rate updated: %.2f", fx_rate)


def format_gap_alert(gap: SpotFuturesGap) -> str:
    """갭 결과를 Telegram 메시지로 포맷."""
    # 방향 이모지
    if gap.is_positive_gap:
        direction = "📈 김프"
    else:
        direction = "📉 역프"

    # 헤지 상태
    if gap.hedgeable:
        hedge_status = f"✅ 헤지 가능 ({gap.hedge_type.value})"
    else:
        hedge_status = "❌ 헤지 불가"

    # 신뢰도 바
    conf_filled = int(gap.reference_confidence * 5)
    conf_bar = "█" * conf_filled + "░" * (5 - conf_filled)

    lines = [
        f"{direction} **현선갭: {gap.symbol}@{gap.domestic_exchange}**",
        "━━━━━━━━━━━━━━━",
        f"🇰🇷 국내: ₩{gap.domestic_price_krw:,.0f}",
        f"🌍 글로벌: ${gap.reference_price_usd:,.4f} (₩{gap.reference_price_krw:,.0f})",
        f"💱 환율: {gap.fx_rate:,.0f}",
        "━━━━━━━━━━━━━━━",
        f"📊 갭: {gap.gap_pct:+.2f}% (₩{gap.gap_krw:+,.0f})",
        f"🎯 최소 수익 갭: {gap.min_profitable_gap:.2f}%",
        f"🔗 참조: {gap.reference_source.value}",
        f"🎯 신뢰도: {conf_bar} {gap.reference_confidence:.0%}",
        "━━━━━━━━━━━━━━━",
        hedge_status,
    ]

    if gap.hedgeable:
        if gap.hedge_strategy == HedgeStrategy.SHORT_GLOBAL_LONG_DOMESTIC:
            lines.append("💡 전략: 글로벌 숏 + 국내 매수 후 청산")
        else:
            lines.append("💡 전략: 글로벌 롱 + 국내 매도 (주의!)")

    if gap.warnings:
        lines.append("")
        lines.extend(gap.warnings)

    return "\n".join(lines)


# 편의 함수
async def quick_gap_check(
    symbol: str,
    domestic_price_krw: float,
    domestic_exchange: str = "upbit",
    fx_rate: float = 1350.0,
) -> SpotFuturesGap | None:
    """빠른 갭 체크 (단발성).

    Args:
        symbol: 토큰 심볼.
        domestic_price_krw: 국내 현물 가격.
        domestic_exchange: 국내 거래소.
        fx_rate: 환율.

    Returns:
        SpotFuturesGap 또는 None.
    """
    monitor = SpotFuturesGapMonitor(fx_rate=fx_rate)
    return await monitor.calculate_gap(
        symbol=symbol,
        domestic_exchange=domestic_exchange,
        domestic_price_krw=domestic_price_krw,
    )
