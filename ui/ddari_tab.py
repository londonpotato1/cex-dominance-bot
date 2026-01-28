"""따리분석 탭 (Phase 4).

gate_analysis_log DB에서 최근 분석 결과를 조회하여 표시.

섹션:
  1. 최근 분석 카드 — GO/NO-GO 배지, 프리미엄, 순수익, blockers/warnings
  2. Gate 열화 UI — FX 소스 신뢰도, 헤지 상태, 네트워크 기본값
  3. VASP alt_note 배지
  4. 통계 요약 — GO/NO-GO 건수, 평균 프리미엄, FX 소스 분포
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent / "ddari.db"
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


# ------------------------------------------------------------------
# 순수 로직 함수 (streamlit 의존 없음 — 테스트 가능)
# ------------------------------------------------------------------


def _render_degradation_badges(row: dict) -> str:
    """Gate 열화 배지 HTML 생성 (v9)."""
    badges = []

    fx_source = row.get("fx_source", "")
    if fx_source == "hardcoded_fallback":
        badges.append(
            '<span style="background:#dc2626;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:0.75rem;">FX 기본값 사용</span>'
        )
    elif fx_source and fx_source not in ("btc_implied", "eth_implied"):
        badges.append(
            '<span style="background:#d97706;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:0.75rem;">FX 2차 소스</span>'
        )

    hedge = row.get("hedge_type", "")
    if hedge == "none":
        badges.append(
            '<span style="background:#ea580c;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:0.75rem;">헤지 불가</span>'
        )

    network = row.get("network", "")
    if network == "ethereum":
        badges.append(
            '<span style="background:#6b7280;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:0.75rem;">네트워크 기본값</span>'
        )

    return " ".join(badges)


def _render_vasp_badge(exchange: str, vasp_matrix: dict) -> str:
    """VASP alt_note 배지 HTML 생성 (v15)."""
    matrix = vasp_matrix.get("vasp_matrix", {})
    from_routes = matrix.get(exchange, {})
    badges = []

    for to_exchange, route in from_routes.items():
        status = route.get("status", "unknown")
        alt_note = route.get("alt_note", "")

        if status == "blocked":
            badges.append(
                f'<span style="color:#ef4444;font-size:0.75rem;">'
                f'{to_exchange}: blocked</span>'
            )
        elif status == "partial":
            note_text = f" — {alt_note}" if alt_note else ""
            badges.append(
                f'<span style="color:#f59e0b;font-size:0.75rem;">'
                f'{to_exchange}: 일부제한{note_text}</span>'
            )
        elif alt_note:
            badges.append(
                f'<span style="color:#6b7280;font-size:0.75rem;">'
                f'{to_exchange}: {alt_note}</span>'
            )

    return "<br>".join(badges) if badges else ""


# ------------------------------------------------------------------
# Streamlit UI 함수 (lazy import)
# ------------------------------------------------------------------


def _get_read_conn() -> sqlite3.Connection:
    """읽기 전용 DB 커넥션 (세션 수명)."""
    import streamlit as st

    @st.cache_resource
    def _inner():
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    return _inner()


def _load_vasp_matrix_cached() -> dict:
    """VASP 매트릭스 (5분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=300)
    def _inner():
        path = _CONFIG_DIR / "vasp_matrix.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    return _inner()


def _fetch_recent_analyses_cached(conn_id: int, limit: int = 20) -> list[dict]:
    """최근 Gate 분석 결과 조회 (1분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=60)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = _get_read_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM gate_analysis_log ORDER BY timestamp DESC LIMIT ?",
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, limit)


def _fetch_stats_cached(conn_id: int) -> dict:
    """통계 요약 (1시간 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=3600)
    def _inner(_conn_id: int) -> dict:
        conn = _get_read_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM gate_analysis_log"
            ).fetchone()["cnt"]

            go_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM gate_analysis_log WHERE can_proceed = 1"
            ).fetchone()["cnt"]

            avg_premium = conn.execute(
                "SELECT AVG(premium_pct) as avg_p FROM gate_analysis_log "
                "WHERE premium_pct IS NOT NULL"
            ).fetchone()["avg_p"]

            fx_dist = conn.execute(
                "SELECT fx_source, COUNT(*) as cnt FROM gate_analysis_log "
                "WHERE fx_source IS NOT NULL GROUP BY fx_source ORDER BY cnt DESC"
            ).fetchall()

            return {
                "total": total,
                "go_count": go_count,
                "nogo_count": total - go_count,
                "avg_premium": avg_premium or 0.0,
                "fx_distribution": {r["fx_source"]: r["cnt"] for r in fx_dist},
            }
        except sqlite3.OperationalError:
            return {"total": 0, "go_count": 0, "nogo_count": 0,
                    "avg_premium": 0.0, "fx_distribution": {}}

    return _inner(conn_id)


def _render_analysis_card(row: dict, vasp_matrix: dict) -> None:
    """개별 분석 결과 카드 렌더링."""
    import streamlit as st
    from datetime import datetime

    symbol = row.get("symbol", "?")
    exchange = row.get("exchange", "?")
    can_proceed = row.get("can_proceed", 0)
    alert_level = row.get("alert_level", "INFO")
    premium = row.get("premium_pct")
    net_profit = row.get("net_profit_pct")
    total_cost = row.get("total_cost_pct")
    fx_source = row.get("fx_source", "")
    duration_ms = row.get("gate_duration_ms")
    ts = row.get("timestamp", 0)

    # GO/NO-GO 배지
    if can_proceed:
        status_badge = (
            '<span style="background:#059669;color:#fff;padding:3px 10px;'
            'border-radius:6px;font-weight:600;">GO</span>'
        )
    else:
        status_badge = (
            '<span style="background:#dc2626;color:#fff;padding:3px 10px;'
            'border-radius:6px;font-weight:600;">NO-GO</span>'
        )

    # 시간 포맷
    time_str = datetime.fromtimestamp(ts).strftime("%m/%d %H:%M:%S") if ts else "?"

    # 메트릭 텍스트
    premium_text = f"{premium:.2f}%" if premium is not None else "N/A"
    profit_text = f"{net_profit:.2f}%" if net_profit is not None else "N/A"
    cost_text = f"{total_cost:.2f}%" if total_cost is not None else "N/A"
    duration_text = f"{duration_ms:.0f}ms" if duration_ms is not None else "N/A"

    # Blockers/Warnings
    blockers = json.loads(row.get("blockers_json", "[]") or "[]")
    warnings = json.loads(row.get("warnings_json", "[]") or "[]")

    blockers_html = ""
    if blockers:
        items = "".join(
            f'<li style="color:#ef4444;font-size:0.8rem;">{b}</li>'
            for b in blockers
        )
        blockers_html = f'<ul style="margin:0.3rem 0;padding-left:1.2rem;">{items}</ul>'

    warnings_html = ""
    if warnings:
        items = "".join(
            f'<li style="color:#f59e0b;font-size:0.8rem;">{w}</li>'
            for w in warnings
        )
        warnings_html = f'<ul style="margin:0.3rem 0;padding-left:1.2rem;">{items}</ul>'

    # 열화 배지
    degradation = _render_degradation_badges(row)
    degradation_html = f'<div style="margin-top:0.3rem;">{degradation}</div>' if degradation else ""

    # VASP 배지
    vasp = _render_vasp_badge(exchange, vasp_matrix)
    vasp_html = f'<div style="margin-top:0.3rem;">{vasp}</div>' if vasp else ""

    card_html = f"""
    <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
                border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <div>
                <span style="font-size:1.1rem;font-weight:600;color:#fff;">{symbol}</span>
                <span style="color:#8b8b8b;font-size:0.8rem;margin-left:0.5rem;">@{exchange}</span>
                <span style="color:#6b7280;font-size:0.75rem;margin-left:0.5rem;">[{alert_level}]</span>
            </div>
            <div>
                {status_badge}
                <span style="color:#6b7280;font-size:0.75rem;margin-left:0.5rem;">{time_str}</span>
            </div>
        </div>
        <div style="display:flex;gap:1.5rem;font-size:0.85rem;color:#a0a0a0;margin-bottom:0.3rem;">
            <span>프리미엄: <b style="color:#00d4ff;">{premium_text}</b></span>
            <span>순수익: <b style="color:#10b981;">{profit_text}</b></span>
            <span>비용: <b style="color:#f59e0b;">{cost_text}</b></span>
            <span>FX: <b>{fx_source or 'N/A'}</b></span>
            <span>소요: <b>{duration_text}</b></span>
        </div>
        {blockers_html}
        {warnings_html}
        {degradation_html}
        {vasp_html}
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)


def render_ddari_tab() -> None:
    """따리분석 탭 렌더링 (app.py에서 호출)."""
    import streamlit as st

    conn = _get_read_conn()
    conn_id = id(conn)

    vasp_matrix = _load_vasp_matrix_cached()
    analyses = _fetch_recent_analyses_cached(conn_id, limit=20)

    if not analyses:
        st.markdown(
            '<div style="text-align:center;padding:3rem;color:#6b7280;">'
            '<p style="font-size:1.2rem;">분석 기록 없음</p>'
            '<p style="font-size:0.85rem;">수집 데몬이 실행 중이고 새 상장이 감지되면 '
            '여기에 Gate 분석 결과가 표시됩니다.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # 헤더
    st.markdown(
        '<p style="font-size:1rem;font-weight:600;color:#fff;margin-bottom:0.75rem;">'
        'Gate 분석 결과 (최근 20건)</p>',
        unsafe_allow_html=True,
    )

    # 분석 카드 목록
    for row in analyses:
        _render_analysis_card(row, vasp_matrix)

    # 통계 요약
    stats = _fetch_stats_cached(conn_id)
    if stats["total"] > 0:
        st.markdown(
            '<p style="font-size:1rem;font-weight:600;color:#fff;'
            'margin-top:1.5rem;margin-bottom:0.75rem;">통계 요약</p>',
            unsafe_allow_html=True,
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("전체 분석", f"{stats['total']}건")
        with col2:
            st.metric("GO", f"{stats['go_count']}건")
        with col3:
            st.metric("NO-GO", f"{stats['nogo_count']}건")
        with col4:
            st.metric("평균 프리미엄", f"{stats['avg_premium']:.2f}%")

        # FX 소스 분포
        if stats["fx_distribution"]:
            st.markdown(
                '<p style="font-size:0.85rem;font-weight:500;color:#a0a0a0;'
                'margin-top:0.5rem;">FX 소스 분포</p>',
                unsafe_allow_html=True,
            )
            dist_items = []
            for source, count in stats["fx_distribution"].items():
                pct = count / stats["total"] * 100
                dist_items.append(
                    f'<span style="color:#8b8b8b;font-size:0.8rem;">'
                    f'{source}: {count}건 ({pct:.0f}%)</span>'
                )
            st.markdown(
                " &nbsp;|&nbsp; ".join(dist_items),
                unsafe_allow_html=True,
            )
