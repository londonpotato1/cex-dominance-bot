"""Gate 분석 결과 DB 기록 (관측성).

gate_analysis_log 테이블에 모든 Gate 판정 결과를 기록한다.
Writer Queue 경유 (Single Writer 원칙).
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.gate import GateResult
    from store.writer import DatabaseWriter

logger = logging.getLogger(__name__)

_INSERT_GATE_LOG_SQL = """\
INSERT INTO gate_analysis_log (
    timestamp, symbol, exchange, can_proceed, alert_level,
    premium_pct, net_profit_pct, total_cost_pct,
    fx_rate, fx_source, blockers_json, warnings_json,
    hedge_type, network, global_volume_usd, gate_duration_ms,
    vc_tier1_investors, vc_tier2_investors, vc_total_funding_usd,
    vc_risk_level, mm_name, mm_risk_score, vcmm_data_source,
    domestic_price_krw, global_price_usd
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


async def log_gate_analysis(
    writer: DatabaseWriter,
    result: GateResult,
    duration_ms: float,
) -> None:
    """Gate 분석 결과를 gate_analysis_log에 기록.

    Args:
        writer: DB Writer Queue.
        result: GateResult (gate_input 포함).
        duration_ms: analyze_listing() 소요 시간 (밀리초).
    """
    gi = result.gate_input
    # symbol과 exchange는 GateResult에서 직접 가져옴 (조기 실패 시에도 보존됨)
    symbol = result.symbol or (gi.symbol if gi else "unknown")
    exchange = result.exchange or (gi.exchange if gi else "unknown")

    # VC/MM 정보 추출 (Phase 7)
    vc_tier1 = None
    vc_tier2 = None
    vc_funding = None
    vc_risk = None
    mm_name = None
    mm_risk = None
    vcmm_source = None

    if result.vc_mm_info is not None:
        vc_info = result.vc_mm_info
        vc_tier1 = json.dumps(vc_info.tier1_investors, ensure_ascii=False) if vc_info.tier1_investors else None
        vc_tier2 = json.dumps(vc_info.tier2_investors, ensure_ascii=False) if vc_info.tier2_investors else None
        vc_funding = vc_info.total_funding_usd
        vc_risk = vc_info.vc_risk_level
        mm_name = vc_info.mm_name
        mm_risk = vc_info.mm_risk_score
        vcmm_source = vc_info.data_source

    if gi is None:
        # gate_input 없는 결과 (조기 실패 등) — 최소 정보 기록
        params = (
            time.time(),
            symbol,
            exchange,
            int(result.can_proceed),
            result.alert_level.value,
            None,  # premium_pct
            None,  # net_profit_pct
            None,  # total_cost_pct
            None,  # fx_rate
            None,  # fx_source
            json.dumps(result.blockers, ensure_ascii=False),
            json.dumps(result.warnings, ensure_ascii=False),
            None,  # hedge_type
            None,  # network
            None,  # global_volume_usd
            duration_ms,
            vc_tier1,
            vc_tier2,
            vc_funding,
            vc_risk,
            mm_name,
            mm_risk,
            vcmm_source,
            None,  # domestic_price_krw
            None,  # global_price_usd
        )
    else:
        params = (
            time.time(),
            symbol,
            exchange,
            int(result.can_proceed),
            result.alert_level.value,
            gi.premium_pct,
            gi.cost_result.net_profit_pct,
            gi.cost_result.total_cost_pct,
            None,  # fx_rate — GateInput에는 fx_rate 없음, fx_source로 충분
            gi.fx_source,
            json.dumps(result.blockers, ensure_ascii=False),
            json.dumps(result.warnings, ensure_ascii=False),
            gi.hedge_type,
            gi.network,
            gi.global_volume_usd,
            duration_ms,
            vc_tier1,
            vc_tier2,
            vc_funding,
            vc_risk,
            mm_name,
            mm_risk,
            vcmm_source,
            gi.domestic_price_krw,
            gi.global_price_usd,
        )

    await writer.enqueue(_INSERT_GATE_LOG_SQL, params, priority="normal")
    logger.debug(
        "[Observability] Gate log: %s@%s %s (%.1fms)",
        symbol,
        exchange,
        "GO" if result.can_proceed else "NO-GO",
        duration_ms,
    )


# ------------------------------------------------------------------
# Listing History 기록 (Phase 5a)
# ------------------------------------------------------------------

_INSERT_LISTING_HISTORY_SQL = """\
INSERT OR REPLACE INTO listing_history (
    symbol, exchange, listing_time, listing_type,
    market_cap_usd, fdv_usd, top_exchange, top_exchange_tier, global_volume_usd,
    gate_can_proceed, premium_pct, net_profit_pct, hedge_type, network,
    created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
"""

_UPDATE_LISTING_RESULT_SQL = """\
UPDATE listing_history SET
    max_premium_pct = ?,
    premium_at_5m_pct = ?,
    premium_at_30m_pct = ?,
    duration_above_8pct_sec = ?,
    result_label = ?,
    result_notes = ?,
    labeled_by = ?,
    labeled_at = datetime('now'),
    updated_at = datetime('now')
WHERE symbol = ? AND exchange = ? AND listing_time = ?
"""


async def record_listing_history(
    writer: "DatabaseWriter",
    result: "GateResult",
    listing_time: str | None = None,
    listing_type: str | None = None,
    market_cap_usd: float | None = None,
    fdv_usd: float | None = None,
    top_exchange_tier: int | None = None,
) -> None:
    """상장 히스토리 기록 (listing_history 테이블).

    Gate 분석 결과를 listing_history에 저장.
    결과 라벨링은 별도 update_listing_result()로 처리.

    Args:
        writer: DB Writer Queue.
        result: GateResult (gate_input 포함).
        listing_time: 상장 시각 (ISO8601). None이면 현재 시각.
        listing_type: 'TGE' | 'DIRECT' | 'SIDE' | 'UNKNOWN'.
        market_cap_usd: 시가총액 (USD).
        fdv_usd: 완전희석가치 (USD).
        top_exchange_tier: 거래소 티어 (1=대형, 2=중형, 3=소형).
    """
    import datetime

    gi = result.gate_input
    symbol = result.symbol or (gi.symbol if gi else "unknown")
    exchange = result.exchange or (gi.exchange if gi else "unknown")

    if listing_time is None:
        listing_time = datetime.datetime.now().isoformat()

    if gi is None:
        # gate_input 없는 결과 — 최소 정보 기록
        params = (
            symbol,
            exchange,
            listing_time,
            listing_type or "UNKNOWN",
            market_cap_usd,
            fdv_usd,
            None,  # top_exchange
            top_exchange_tier,
            None,  # global_volume_usd
            int(result.can_proceed),
            None,  # premium_pct
            None,  # net_profit_pct
            None,  # hedge_type
            None,  # network
        )
    else:
        # 분류 결과가 있으면 listing_type 사용
        if listing_type is None and result.listing_type_result:
            listing_type = result.listing_type_result.listing_type.value

        params = (
            symbol,
            exchange,
            listing_time,
            listing_type or "UNKNOWN",
            market_cap_usd,
            fdv_usd,
            gi.top_exchange,
            top_exchange_tier,
            gi.global_volume_usd,
            int(result.can_proceed),
            gi.premium_pct,
            gi.cost_result.net_profit_pct if gi.cost_result else None,
            gi.hedge_type,
            gi.network,
        )

    await writer.enqueue(_INSERT_LISTING_HISTORY_SQL, params, priority="critical")
    logger.info(
        "[Observability] Listing history: %s@%s (%s)",
        symbol,
        exchange,
        listing_type or "UNKNOWN",
    )


async def update_listing_result(
    writer: "DatabaseWriter",
    symbol: str,
    exchange: str,
    listing_time: str,
    max_premium_pct: float | None = None,
    premium_at_5m_pct: float | None = None,
    premium_at_30m_pct: float | None = None,
    duration_above_8pct_sec: int | None = None,
    result_label: str | None = None,
    result_notes: str | None = None,
    labeled_by: str = "auto",
) -> None:
    """상장 결과 라벨 업데이트 (listing_history).

    상장 후 5분/30분 프리미엄 측정 결과 및 라벨을 기록.

    Args:
        writer: DB Writer Queue.
        symbol: 심볼.
        exchange: 거래소.
        listing_time: 상장 시각 (INSERT 시 사용된 값).
        max_premium_pct: 최대 프리미엄 (%).
        premium_at_5m_pct: 5분 후 프리미엄 (%).
        premium_at_30m_pct: 30분 후 프리미엄 (%).
        duration_above_8pct_sec: 8% 이상 유지 시간 (초).
        result_label: 'heung_big' | 'heung' | 'neutral' | 'mang'.
        result_notes: 비고.
        labeled_by: 'auto' | 'manual'.
    """
    params = (
        max_premium_pct,
        premium_at_5m_pct,
        premium_at_30m_pct,
        duration_above_8pct_sec,
        result_label,
        result_notes,
        labeled_by,
        symbol,
        exchange,
        listing_time,
    )

    await writer.enqueue(_UPDATE_LISTING_RESULT_SQL, params, priority="normal")
    logger.info(
        "[Observability] Listing result updated: %s@%s → %s",
        symbol,
        exchange,
        result_label or "pending",
    )
