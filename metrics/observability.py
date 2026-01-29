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
    hedge_type, network, global_volume_usd, gate_duration_ms
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        )

    await writer.enqueue(_INSERT_GATE_LOG_SQL, params, priority="normal")
    logger.debug(
        "[Observability] Gate log: %s@%s %s (%.1fms)",
        symbol,
        exchange,
        "GO" if result.can_proceed else "NO-GO",
        duration_ms,
    )
