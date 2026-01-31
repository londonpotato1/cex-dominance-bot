"""따리분석 실시간 현황 탭 (Tab 1).

시간이 중요한 정보: Gate 분석, 통계, 프리미엄 차트, 현선갭 모니터.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime

from ui.ddari_common import (
    CARD_STYLE,
    COLORS,
    PREMIUM_THRESHOLDS,
    SECTION_HEADER_STYLE,
    PHASE8_AVAILABLE,
    badge_style,
    get_read_conn,
    load_vasp_matrix_cached,
    fetch_recent_analyses_cached,
    fetch_stats_cached,
    fetch_premium_history_cached,
    render_degradation_badges,
    render_vasp_badge,
    render_vcmm_badge,
    get_market_mood_cached,
)


# ------------------------------------------------------------------
# Gate 분석 카드 (Phase 2.1: 신호등 시스템)
# ------------------------------------------------------------------


def _calculate_confidence_score(row: dict) -> tuple[int, str]:
    """신뢰도 점수 계산 (0-100).
    
    Returns:
        tuple: (점수, 주요 감점 사유)
    """
    score = 100
    reasons = []
    
    # 1. FX 소스 신뢰도 (-20점)
    fx_source = row.get("fx_source", "")
    if fx_source == "hardcoded_fallback":
        score -= 30
        reasons.append("FX 기본값")
    elif fx_source == "cache":
        score -= 10
        reasons.append("캐시 FX")
    
    # 2. 프리미엄 정보 유무 (-15점)
    if row.get("premium_pct") is None:
        score -= 15
        reasons.append("프리미엄 없음")
    
    # 3. 순수익 마진 (마이너스면 감점)
    net_profit = row.get("net_profit_pct")
    if net_profit is not None:
        if net_profit < 0:
            score -= 20
            reasons.append("순수익 마이너스")
        elif net_profit < 1:
            score -= 10
            reasons.append("순수익 낮음")
    
    # 4. Blockers/Warnings 개수
    blockers = json.loads(row.get("blockers_json", "[]") or "[]")
    warnings = json.loads(row.get("warnings_json", "[]") or "[]")
    
    if blockers:
        score -= len(blockers) * 10
        reasons.append(f"차단 {len(blockers)}건")
    if warnings:
        score -= len(warnings) * 5
    
    # 5. 분석 속도 (느리면 감점)
    duration_ms = row.get("gate_duration_ms")
    if duration_ms and duration_ms > 5000:
        score -= 10
        reasons.append("분석 지연")
    
    score = max(0, min(100, score))
    reason = reasons[0] if reasons else ""
    
    return score, reason


def _render_confidence_bar(score: int) -> str:
    """신뢰도 바 HTML 생성."""
    filled = score // 10
    empty = 10 - filled
    
    if score >= 70:
        color = "#4ade80"  # 녹색
    elif score >= 40:
        color = "#fbbf24"  # 노랑
    else:
        color = "#f87171"  # 빨강
    
    bar = f'<span style="color:{color};">{"█" * filled}</span>'
    bar += f'<span style="color:#374151;">{"░" * empty}</span>'
    
    return f'{bar} <span style="color:{color};font-weight:600;">{score}%</span>'


def _render_traffic_light(can_proceed: bool, score: int, has_warnings: bool) -> str:
    """신호등 HTML 생성."""
    if can_proceed:
        if score >= 70 and not has_warnings:
            # 🟢 GO - 높은 신뢰도
            return '<span style="font-size:1.8rem;">🟢</span> <span style="font-size:1.4rem;font-weight:700;color:#4ade80;">GO</span>'
        else:
            # 🟡 GO - 주의 필요
            return '<span style="font-size:1.8rem;">🟡</span> <span style="font-size:1.4rem;font-weight:700;color:#fbbf24;">GO</span>'
    else:
        # 🔴 NO-GO
        return '<span style="font-size:1.8rem;">🔴</span> <span style="font-size:1.4rem;font-weight:700;color:#f87171;">NO-GO</span>'


def _render_analysis_card(row: dict, vasp_matrix: dict, highlight: bool = False) -> None:
    """개별 분석 결과 카드 렌더링 (Phase 2.1: 신호등 시스템).
    
    Args:
        row: 분석 결과 데이터.
        vasp_matrix: VASP 매트릭스.
        highlight: True면 GO 강조 스타일 적용.
    """
    import streamlit as st

    symbol = row.get("symbol", "?")
    exchange = row.get("exchange", "?")
    can_proceed = row.get("can_proceed", 0)
    premium = row.get("premium_pct")
    net_profit = row.get("net_profit_pct")
    total_cost = row.get("total_cost_pct")
    duration_ms = row.get("gate_duration_ms")
    ts = row.get("timestamp", 0)

    # Blockers/Warnings
    blockers = json.loads(row.get("blockers_json", "[]") or "[]")
    warnings = json.loads(row.get("warnings_json", "[]") or "[]")
    
    # 신뢰도 계산
    confidence_score, confidence_reason = _calculate_confidence_score(row)
    
    # 신호등 + 신뢰도 바
    traffic_light = _render_traffic_light(can_proceed, confidence_score, len(warnings) > 0)
    confidence_bar = _render_confidence_bar(confidence_score)

    # 시간 포맷
    time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
    
    # 예상 수익 계산 (50만원 기준)
    base_krw = 500_000
    if net_profit is not None:
        profit_krw = int(base_krw * net_profit / 100)
        if net_profit > 0:
            profit_display = f'<span style="font-size:1.6rem;font-weight:700;color:#4ade80;">+{net_profit:.2f}%</span>'
            profit_krw_display = f'<span style="color:#4ade80;">(≈₩{profit_krw:,})</span>'
        else:
            profit_display = f'<span style="font-size:1.6rem;font-weight:700;color:#f87171;">{net_profit:.2f}%</span>'
            profit_krw_display = f'<span style="color:#f87171;">(≈₩{profit_krw:,})</span>'
    else:
        profit_display = '<span style="font-size:1.6rem;color:#6b7280;">N/A</span>'
        profit_krw_display = ""
    
    # 김프/비용/속도 한 줄
    premium_text = f"{premium:+.2f}%" if premium is not None else "N/A"
    cost_text = f"{total_cost:.2f}%" if total_cost is not None else "N/A"
    duration_text = f"{duration_ms:.0f}ms" if duration_ms is not None else "N/A"
    
    # 흥/망따리 분류 (supply_score 기반 또는 순수익 기반)
    supply_score = row.get("supply_score")
    if supply_score is not None:
        if supply_score > 6:
            supply_badge = '<span style="background:#166534;color:#4ade80;padding:2px 8px;border-radius:4px;font-size:0.8rem;">🔥 흥따리</span>'
        elif supply_score < 3:
            supply_badge = '<span style="background:#7f1d1d;color:#fca5a5;padding:2px 8px;border-radius:4px;font-size:0.8rem;">💀 망따리</span>'
        else:
            supply_badge = '<span style="background:#374151;color:#9ca3af;padding:2px 8px;border-radius:4px;font-size:0.8rem;">😐 보통</span>'
    elif net_profit is not None:
        if net_profit > 3:
            supply_badge = '<span style="background:#166534;color:#4ade80;padding:2px 8px;border-radius:4px;font-size:0.8rem;">🔥 흥따리</span>'
        elif net_profit < 0:
            supply_badge = '<span style="background:#7f1d1d;color:#fca5a5;padding:2px 8px;border-radius:4px;font-size:0.8rem;">💀 망따리</span>'
        else:
            supply_badge = '<span style="background:#374151;color:#9ca3af;padding:2px 8px;border-radius:4px;font-size:0.8rem;">😐 보통</span>'
    else:
        supply_badge = ""

    # 경고사항 (간결하게)
    alerts_html = ""
    if blockers:
        items = "".join(f'<div style="color:#f87171;font-size:0.75rem;">🚫 {b[:35]}</div>' for b in blockers[:2])
        alerts_html += items
    if warnings and can_proceed:
        items = "".join(f'<div style="color:#fbbf24;font-size:0.75rem;">⚠️ {w[:35]}</div>' for w in warnings[:2])
        alerts_html += items
    
    # 신뢰도 감점 사유
    if confidence_reason:
        alerts_html += f'<div style="color:#6b7280;font-size:0.7rem;margin-top:0.2rem;">📉 {confidence_reason}</div>'

    # 카드 스타일
    if highlight and can_proceed:
        card_style = """background:linear-gradient(135deg, #1a3a2a 0%, #1f4a35 100%);
            border:2px solid #4ade80;border-radius:16px;padding:1rem;margin-bottom:0.75rem;
            box-shadow:0 4px 20px rgba(74,222,128,0.15);"""
    elif can_proceed:
        card_style = """background:linear-gradient(135deg, #1a2e1a 0%, #1f3d25 100%);
            border:1px solid #166534;border-radius:16px;padding:1rem;margin-bottom:0.75rem;"""
    else:
        card_style = """background:linear-gradient(135deg, #1f1f1f 0%, #2a2a2a 100%);
            border:1px solid #374151;border-radius:16px;padding:1rem;margin-bottom:0.75rem;"""

    card_html = f"""
    <div style="{card_style}">
        <!-- 1행: 신호등 + 신뢰도 바 -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <div>{traffic_light}</div>
            <div style="font-size:0.85rem;font-family:monospace;">{confidence_bar}</div>
        </div>
        
        <!-- 2행: 심볼 + 시간 -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.6rem;">
            <div>
                <span style="font-size:1.2rem;font-weight:600;color:#fff;">{symbol}</span>
                <span style="color:#9ca3af;font-size:0.9rem;margin-left:0.4rem;">@{exchange}</span>
                <span style="margin-left:0.5rem;">{supply_badge}</span>
            </div>
            <span style="color:#6b7280;font-size:0.8rem;">{time_str}</span>
        </div>
        
        <!-- 3행: 예상 수익 (크게) -->
        <div style="margin-bottom:0.5rem;">
            <span style="color:#9ca3af;font-size:0.8rem;">예상 수익: </span>
            {profit_display} {profit_krw_display}
        </div>
        
        <!-- 4행: 김프/비용/속도 -->
        <div style="display:flex;gap:1rem;font-size:0.8rem;color:#9ca3af;margin-bottom:0.4rem;">
            <span>📈 김프 <b style="color:#60a5fa;">{premium_text}</b></span>
            <span>💸 비용 <b style="color:#fbbf24;">{cost_text}</b></span>
            <span>⚡ <b>{duration_text}</b></span>
        </div>
        
        <!-- 5행: 경고사항 -->
        {f'<div style="margin-top:0.4rem;border-top:1px solid #374151;padding-top:0.4rem;">{alerts_html}</div>' if alerts_html else ''}
    </div>
    """
    
    if hasattr(st, 'html'):
        st.html(card_html)
    else:
        st.markdown(card_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 프리미엄 차트 섹션
# ------------------------------------------------------------------


def _render_premium_chart_section(conn_id: int) -> None:
    """실시간 프리미엄 차트 섹션 (Phase 7 Week 4)."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">📈 프리미엄 추이 차트</p>',
        unsafe_allow_html=True,
    )

    # 최근 24시간 프리미엄 히스토리 조회
    premium_history = fetch_premium_history_cached(conn_id, hours=24)

    if not premium_history:
        st.info("프리미엄 데이터가 없습니다. Gate 분석이 실행되면 차트가 표시됩니다.")
        return

    # 심볼별로 데이터 그룹화 (defaultdict로 간소화)
    symbols_data = defaultdict(lambda: {"timestamps": [], "premiums": []})
    for row in premium_history:
        symbol = row.get("symbol", "unknown")
        symbols_data[symbol]["timestamps"].append(row["timestamp"])
        symbols_data[symbol]["premiums"].append(row["premium_pct"] or 0)

    if not symbols_data:
        st.info("차트에 표시할 데이터가 없습니다.")
        return

    # 심볼 선택 (최근 활성 심볼 기준)
    recent_symbols = list(symbols_data.keys())[-10:]  # 최근 10개 심볼
    selected_symbol = st.selectbox(
        "심볼 선택",
        recent_symbols,
        index=len(recent_symbols) - 1 if recent_symbols else 0,
        key="premium_chart_symbol_live",
    )

    if selected_symbol and selected_symbol in symbols_data:
        data = symbols_data[selected_symbol]

        # pandas 없이 간단한 차트 구현
        try:
            import pandas as pd

            df = pd.DataFrame({
                "시간": [datetime.fromtimestamp(ts) for ts in data["timestamps"]],
                "프리미엄 (%)": data["premiums"],
            })
            df = df.set_index("시간")

            # 라인 차트
            st.line_chart(df, use_container_width=True)

            # 통계 표시
            premiums = data["premiums"]
            if premiums:
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("현재", f"{premiums[-1]:.2f}%")
                with col2:
                    st.metric("최고", f"{max(premiums):.2f}%")
                with col3:
                    st.metric("최저", f"{min(premiums):.2f}%")
                with col4:
                    avg_premium = sum(premiums) / len(premiums)
                    st.metric("평균", f"{avg_premium:.2f}%")

        except ImportError:
            # pandas 없으면 간단한 텍스트 표시
            st.warning("pandas 미설치 — 차트 대신 텍스트로 표시합니다.")
            premiums = data["premiums"]
            if premiums:
                st.write(f"**{selected_symbol}** 프리미엄 데이터 ({len(premiums)}건)")
                st.write(f"- 현재: {premiums[-1]:.2f}%")
                st.write(f"- 최고: {max(premiums):.2f}%")
                st.write(f"- 최저: {min(premiums):.2f}%")

    # 프리미엄 임계값 안내 (styles.py에서 import)
    if hasattr(st, 'html'):
        st.html(PREMIUM_THRESHOLDS)
    else:
        st.markdown(PREMIUM_THRESHOLDS, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 현선갭 모니터 섹션 (Phase 8)
# ------------------------------------------------------------------


def _fetch_spot_futures_gap_cached(conn_id: int, limit: int = 5) -> list[dict]:
    """현선갭 데이터 조회 (30초 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=30)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = get_read_conn()
        try:
            rows = conn.execute(
                """
                SELECT symbol, domestic_exchange, global_exchange,
                       domestic_price_krw, global_price_usd, fx_rate,
                       gap_pct, hedge_strategy, is_profitable,
                       estimated_profit_pct, created_at
                FROM spot_futures_gap
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, limit)


def _render_spot_futures_gap_card_html(data: dict) -> str:
    """현선갭 카드 HTML 생성."""
    symbol = data.get("symbol", "?")
    domestic_ex = data.get("domestic_exchange", "upbit")
    global_ex = data.get("global_exchange", "binance")
    domestic_price = data.get("domestic_price_krw", 0)
    global_price = data.get("global_price_usd", 0)
    fx_rate = data.get("fx_rate", 1350)
    gap_pct = data.get("gap_pct", 0)
    hedge_strategy = data.get("hedge_strategy", "no_hedge")
    is_profitable = data.get("is_profitable", False)
    profit_pct = data.get("estimated_profit_pct", 0)

    # 갭 색상
    if gap_pct > 3:
        gap_color = COLORS["success"]
        gap_emoji = "🔥"
    elif gap_pct > 1:
        gap_color = COLORS["info"]
        gap_emoji = "✨"
    elif gap_pct < -1:
        gap_color = COLORS["danger"]
        gap_emoji = "📉"
    else:
        gap_color = COLORS["neutral"]
        gap_emoji = "➖"

    # 헤지 전략 스타일
    hedge_styles = {
        "long_global_short_domestic": {"name": "해외 롱 / 국내 숏", "emoji": "🔄"},
        "short_global_long_domestic": {"name": "해외 숏 / 국내 롱", "emoji": "🔄"},
        "no_hedge": {"name": "헤지 불가", "emoji": "🚫"},
    }
    hedge_style = hedge_styles.get(hedge_strategy, {"name": hedge_strategy, "emoji": "❓"})

    # 수익성 배지
    profit_badge = ""
    if is_profitable:
        profit_badge = f'<span style="{badge_style(COLORS["success"], size="0.7rem")}">💰 +{profit_pct:.2f}%</span>'

    # 가격 포맷
    domestic_str = f"₩{domestic_price:,.0f}" if domestic_price else "-"
    global_str = f"${global_price:,.4f}" if global_price else "-"

    return f"""
    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <div>
                <span style="font-size:1.1rem;font-weight:600;color:{COLORS["text_primary"]};">{symbol}</span>
                <span style="color:{gap_color};font-size:1rem;font-weight:600;margin-left:0.75rem;">
                    {gap_emoji} {gap_pct:+.2f}%
                </span>
            </div>
            {profit_badge}
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.85rem;margin-bottom:0.5rem;">
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">{domestic_ex.upper()}</span>
                <span style="margin-left:0.5rem;font-weight:600;color:{COLORS["warning"]};">{domestic_str}</span>
            </div>
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">{global_ex.upper()}</span>
                <span style="margin-left:0.5rem;font-weight:600;color:{COLORS["info"]};">{global_str}</span>
            </div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:{COLORS["text_muted"]};">
            <span>FX: ₩{fx_rate:,.0f}/USD</span>
            <span>{hedge_style['emoji']} {hedge_style['name']}</span>
        </div>
    </div>
    """


def _render_spot_futures_gap_section(conn_id: int) -> None:
    """현선갭 모니터 섹션 렌더링 (Phase 8)."""
    import streamlit as st

    if not PHASE8_AVAILABLE:
        return

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">📊 현선갭 모니터</p>',
        unsafe_allow_html=True,
    )

    # 데이터 조회
    gap_data = _fetch_spot_futures_gap_cached(conn_id, limit=5)

    if not gap_data:
        info_html = f"""
        <div style="{CARD_STYLE}">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">
                🔄 현선갭 (Spot-Futures Gap)이란?
            </p>
            <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin-bottom:0.75rem;">
                국내 거래소(업비트/빗썸) 현물 가격과 해외 거래소(바이낸스/바이빗) 선물 가격의 차이입니다.
                갭이 크면 아비트라지 기회가 발생합니다.
            </p>
            <div style="display:flex;gap:1rem;font-size:0.8rem;margin-bottom:0.5rem;">
                <div>
                    <span style="color:{COLORS["success"]};">+3% 이상</span>
                    <span style="color:{COLORS["text_muted"]};"> = 강한 김프</span>
                </div>
                <div>
                    <span style="color:{COLORS["danger"]};">-3% 이하</span>
                    <span style="color:{COLORS["text_muted"]};"> = 역프</span>
                </div>
            </div>
            <p style="font-size:0.75rem;color:{COLORS["text_muted"]};">
                💡 상장 감지 시 자동으로 갭 계산이 시작됩니다.
            </p>
        </div>
        """
        if hasattr(st, 'html'):
            st.html(info_html)
        else:
            st.markdown(info_html, unsafe_allow_html=True)
        return

    # 갭 카드들
    for data in gap_data:
        card_html = _render_spot_futures_gap_card_html(data)
        if hasattr(st, 'html'):
            st.html(card_html)
        else:
            st.markdown(card_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 메인 렌더 함수
# ------------------------------------------------------------------


def render_live_tab() -> None:
    """실시간 현황 탭 렌더링."""
    import streamlit as st

    conn = get_read_conn()
    conn_id = id(conn)

    vasp_matrix = load_vasp_matrix_cached()
    analyses = fetch_recent_analyses_cached(conn_id, limit=20)

    if not analyses:
        st.markdown(
            f'<div style="text-align:center;padding:3rem;color:{COLORS["text_muted"]};">'
            '<p style="font-size:1.2rem;">분석 기록 없음</p>'
            '<p style="font-size:0.85rem;">수집 데몬이 실행 중이고 새 상장이 감지되면 '
            '여기에 Gate 분석 결과가 표시됩니다.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # GO와 NO-GO 분리
    go_analyses = [r for r in analyses if r.get("can_proceed", 0)]
    nogo_analyses = [r for r in analyses if not r.get("can_proceed", 0)]

    # 🚀 GO 섹션 (상단 강조) + 시장 분위기 뱃지
    if go_analyses:
        # 시장 분위기 가져오기
        mood = get_market_mood_cached()
        mood_badge = ""
        if mood.get("kr_dominance") is not None:
            mood_badge = f'''
                <span style="background:rgba(0,0,0,0.3);border:1px solid {mood["color"]};
                    padding:4px 10px;border-radius:8px;font-size:0.8rem;">
                    {mood["emoji"]} 시장: <b style="color:{mood["color"]};">{mood["text"]}</b>
                    <span style="color:#6b7280;font-size:0.7rem;margin-left:0.3rem;">
                        KR {mood["kr_dominance"]:.1f}%
                    </span>
                </span>
            '''
        
        # 최고 수익 GO 찾기
        best_go = max(go_analyses, key=lambda x: x.get("net_profit_pct") or -999)
        best_profit = best_go.get("net_profit_pct")
        best_profit_text = f"+{best_profit:.1f}%" if best_profit and best_profit > 0 else ""

        st.markdown(
            f'''<div style="background:linear-gradient(135deg, #1a472a 0%, #2d5a3d 100%);
                border:2px solid #4ade80;border-radius:16px;padding:1.25rem;margin-bottom:1rem;">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
                    <div style="display:flex;align-items:center;gap:0.75rem;">
                        <span style="font-size:2rem;">🟢</span>
                        <div>
                            <div style="font-size:1.3rem;font-weight:700;color:#4ade80;">
                                GO! {len(go_analyses)}건
                            </div>
                            <div style="font-size:0.85rem;color:#86efac;">
                                최고 수익 {best_profit_text}
                            </div>
                        </div>
                    </div>
                    <div>{mood_badge}</div>
                </div>
            </div>''',
            unsafe_allow_html=True,
        )
        for row in go_analyses:
            _render_analysis_card(row, vasp_matrix, highlight=True)

    # 📋 NO-GO 섹션 (접기 가능) - 신호등 스타일
    if nogo_analyses:
        nogo_header = f"🔴 NO-GO ({len(nogo_analyses)}건) - 클릭하여 펼치기"
    else:
        nogo_header = "분석 기록 없음"
    
    with st.expander(nogo_header, expanded=False):
        if nogo_analyses:
            # NO-GO 요약 통계
            avg_profit = sum(r.get("net_profit_pct") or 0 for r in nogo_analyses) / len(nogo_analyses)
            st.markdown(
                f'''<div style="background:#1f1f1f;border-radius:8px;padding:0.75rem;margin-bottom:0.75rem;
                    font-size:0.85rem;color:#9ca3af;">
                    평균 순수익: <span style="color:#f87171;">{avg_profit:.2f}%</span> | 
                    주요 차단 사유: 순수익 부족, 입출금 제한
                </div>''',
                unsafe_allow_html=True,
            )
            for row in nogo_analyses:
                _render_analysis_card(row, vasp_matrix, highlight=False)
        else:
            st.info("NO-GO 분석 기록이 없습니다.")

    # 통계 요약
    stats = fetch_stats_cached(conn_id)
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
            go_label = "GO" if stats['go_count'] > 0 else "GO ⏳"
            go_help = None if stats['go_count'] > 0 else "현재 진입 가능한 기회 없음 - 대기 중"
            st.metric(go_label, f"{stats['go_count']}건", help=go_help)
        with col3:
            st.metric("NO-GO", f"{stats['nogo_count']}건")
        with col4:
            st.metric("평균 프리미엄", f"{stats['avg_premium']:.2f}%")

        # FX 소스 분포
        if stats["fx_distribution"]:
            st.markdown(
                f'<p style="font-size:0.85rem;font-weight:500;color:{COLORS["text_secondary"]};'
                'margin-top:0.5rem;">FX 소스 분포</p>',
                unsafe_allow_html=True,
            )
            dist_items = []
            for source, count in stats["fx_distribution"].items():
                pct = count / stats["total"] * 100
                dist_items.append(
                    f'<span style="color:{COLORS["text_tertiary"]};font-size:0.8rem;">'
                    f'{source}: {count}건 ({pct:.0f}%)</span>'
                )
            st.markdown(
                " &nbsp;|&nbsp; ".join(dist_items),
                unsafe_allow_html=True,
            )

        # 마지막 업데이트 시간
        if stats.get("last_analysis_at"):
            from datetime import datetime
            try:
                last_dt = datetime.fromisoformat(stats["last_analysis_at"].replace("Z", "+00:00"))
                time_str = last_dt.strftime("%Y-%m-%d %H:%M:%S")
                st.markdown(
                    f'<p style="font-size:0.75rem;color:{COLORS["text_muted"]};'
                    f'margin-top:0.5rem;">🕐 마지막 분석: {time_str}</p>',
                    unsafe_allow_html=True,
                )
            except (ValueError, AttributeError):
                pass

    # ------------------------------------------------------------------
    # 프리미엄 차트 섹션
    # ------------------------------------------------------------------
    _render_premium_chart_section(conn_id)

    # ------------------------------------------------------------------
    # 현선갭 모니터 (Phase 8)
    # ------------------------------------------------------------------
    _render_spot_futures_gap_section(conn_id)
