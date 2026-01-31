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
    fetch_funding_rates_cached,
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
    """개별 분석 결과 카드 렌더링 (Phase 2.2: 개선된 UI).
    
    GO 카드: 크고 눈에 띄게, 핵심 정보 강조
    NO-GO 카드: 컴팩트하게
    
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

    # 시간 포맷
    time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
    
    # 예상 수익 계산 (50만원 기준)
    base_krw = 500_000
    profit_krw = int(base_krw * (net_profit or 0) / 100)
    
    # 흥/망따리 분류
    supply_score = row.get("supply_score")
    if supply_score is not None:
        if supply_score > 6:
            supply_emoji, supply_text = "🔥", "흥따리"
        elif supply_score < 3:
            supply_emoji, supply_text = "💀", "망따리"
        else:
            supply_emoji, supply_text = "😐", "보통"
    elif net_profit is not None:
        if net_profit > 3:
            supply_emoji, supply_text = "🔥", "흥따리"
        elif net_profit < 0:
            supply_emoji, supply_text = "💀", "망따리"
        else:
            supply_emoji, supply_text = "😐", "보통"
    else:
        supply_emoji, supply_text = "", ""

    # ============================================================
    # GO 카드: 크고 눈에 띄게 (히어로 스타일)
    # ============================================================
    if highlight and can_proceed:
        # 프리미엄 바 (시각화)
        premium_val = premium or 0
        premium_bar_width = min(max(premium_val * 10, 5), 100)  # 5-100% 범위
        premium_color = "#4ade80" if premium_val > 0 else "#f87171"
        
        # 신뢰도 바 (간소화)
        conf_filled = confidence_score // 10
        conf_bar = f'{"●" * conf_filled}{"○" * (10 - conf_filled)}'
        conf_color = "#4ade80" if confidence_score >= 70 else "#fbbf24" if confidence_score >= 40 else "#f87171"
        
        card_html = f"""
        <div style="background:linear-gradient(135deg, #0a2e1a 0%, #1a4a2a 50%, #0d3d1d 100%);
            border:3px solid #4ade80;border-radius:20px;padding:1.5rem;margin-bottom:1rem;
            box-shadow:0 8px 32px rgba(74,222,128,0.25), inset 0 1px 0 rgba(255,255,255,0.1);">
            
            <!-- 헤더: 심볼 + 뱃지 -->
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem;">
                <div>
                    <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.25rem;">
                        <span style="font-size:2rem;font-weight:800;color:#fff;text-shadow:0 2px 4px rgba(0,0,0,0.3);">
                            {symbol}
                        </span>
                        <span style="background:linear-gradient(135deg, #166534, #15803d);color:#4ade80;
                            padding:6px 14px;border-radius:20px;font-size:0.85rem;font-weight:700;
                            border:1px solid #22c55e;box-shadow:0 2px 8px rgba(34,197,94,0.3);">
                            {supply_emoji} {supply_text}
                        </span>
                    </div>
                    <span style="color:#86efac;font-size:0.9rem;">@{exchange} · {time_str}</span>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:0.7rem;color:#6b7280;margin-bottom:2px;">신뢰도</div>
                    <div style="font-family:monospace;font-size:0.75rem;color:{conf_color};">{conf_bar}</div>
                </div>
            </div>
            
            <!-- 메인: 순수익 (초대형) -->
            <div style="text-align:center;padding:1.25rem 0;border-top:1px solid rgba(74,222,128,0.2);
                border-bottom:1px solid rgba(74,222,128,0.2);margin-bottom:1rem;">
                <div style="font-size:0.85rem;color:#86efac;margin-bottom:0.25rem;">예상 순수익</div>
                <div style="font-size:3rem;font-weight:800;color:#4ade80;line-height:1;
                    text-shadow:0 0 30px rgba(74,222,128,0.5);">
                    +{net_profit:.2f}%
                </div>
                <div style="font-size:1.1rem;color:#86efac;margin-top:0.25rem;">
                    ≈ ₩{profit_krw:,} <span style="font-size:0.8rem;color:#6b7280;">(50만원 기준)</span>
                </div>
            </div>
            
            <!-- 프리미엄 바 (시각화) -->
            <div style="margin-bottom:1rem;">
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:0.3rem;">
                    <span style="color:#9ca3af;">📈 김치프리미엄</span>
                    <span style="color:{premium_color};font-weight:700;">{premium:+.2f}%</span>
                </div>
                <div style="background:#1f2937;border-radius:4px;height:8px;overflow:hidden;">
                    <div style="background:linear-gradient(90deg, {premium_color}, {premium_color}88);
                        width:{premium_bar_width}%;height:100%;border-radius:4px;
                        box-shadow:0 0 10px {premium_color}66;"></div>
                </div>
            </div>
            
            <!-- 하단: 비용/속도 -->
            <div style="display:flex;justify-content:space-around;font-size:0.85rem;color:#9ca3af;">
                <div style="text-align:center;">
                    <div style="color:#6b7280;font-size:0.7rem;">총 비용</div>
                    <div style="font-weight:600;color:#fbbf24;">{total_cost:.2f}%</div>
                </div>
                <div style="width:1px;background:#374151;"></div>
                <div style="text-align:center;">
                    <div style="color:#6b7280;font-size:0.7rem;">분석 속도</div>
                    <div style="font-weight:600;color:#60a5fa;">{duration_ms:.0f}ms</div>
                </div>
                <div style="width:1px;background:#374151;"></div>
                <div style="text-align:center;">
                    <div style="color:#6b7280;font-size:0.7rem;">신뢰도</div>
                    <div style="font-weight:600;color:{conf_color};">{confidence_score}%</div>
                </div>
            </div>
        </div>
        """
        
        if hasattr(st, 'html'):
            st.html(card_html)
        else:
            st.markdown(card_html, unsafe_allow_html=True)
        
        # 상세 정보 접이식
        with st.expander(f"📋 {symbol} 상세 정보", expanded=False):
            detail_cols = st.columns(2)
            with detail_cols[0]:
                st.markdown("**⚠️ 주의사항**")
                if blockers:
                    for b in blockers[:3]:
                        st.markdown(f"🚫 {b}")
                if warnings:
                    for w in warnings[:3]:
                        st.markdown(f"⚠️ {w}")
                if not blockers and not warnings:
                    st.markdown("✅ 특이사항 없음")
            with detail_cols[1]:
                st.markdown("**📊 분석 상세**")
                st.markdown(f"- 프리미엄: {premium:+.2f}%" if premium else "- 프리미엄: N/A")
                st.markdown(f"- 비용: {total_cost:.2f}%" if total_cost else "- 비용: N/A")
                if confidence_reason:
                    st.markdown(f"- 신뢰도 감점: {confidence_reason}")
        
        return

    # ============================================================
    # NO-GO 카드: 컴팩트 (또는 일반 GO)
    # ============================================================
    traffic_light = _render_traffic_light(can_proceed, confidence_score, len(warnings) > 0)
    confidence_bar = _render_confidence_bar(confidence_score)
    
    premium_text = f"{premium:+.2f}%" if premium is not None else "N/A"
    cost_text = f"{total_cost:.2f}%" if total_cost is not None else "N/A"
    
    if net_profit is not None:
        if net_profit > 0:
            profit_display = f'<span style="color:#4ade80;font-weight:700;">+{net_profit:.2f}%</span>'
        else:
            profit_display = f'<span style="color:#f87171;font-weight:700;">{net_profit:.2f}%</span>'
    else:
        profit_display = '<span style="color:#6b7280;">N/A</span>'

    # 경고사항 (간결하게)
    alert_text = ""
    if blockers:
        alert_text = f'<span style="color:#f87171;font-size:0.75rem;">🚫 {blockers[0][:30]}</span>'
    elif warnings:
        alert_text = f'<span style="color:#fbbf24;font-size:0.75rem;">⚠️ {warnings[0][:30]}</span>'

    card_style = """background:linear-gradient(135deg, #1f1f1f 0%, #2a2a2a 100%);
        border:1px solid #374151;border-radius:12px;padding:0.85rem;margin-bottom:0.5rem;"""

    card_html = f"""
    <div style="{card_style}">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="display:flex;align-items:center;gap:0.5rem;">
                {traffic_light}
                <span style="font-size:1rem;font-weight:600;color:#fff;">{symbol}</span>
                <span style="color:#6b7280;font-size:0.8rem;">@{exchange}</span>
            </div>
            <div style="text-align:right;">
                <div>{profit_display} <span style="color:#6b7280;font-size:0.75rem;">순수익</span></div>
                <div style="font-size:0.7rem;color:#6b7280;">{time_str}</div>
            </div>
        </div>
        <div style="display:flex;justify-content:space-between;margin-top:0.5rem;font-size:0.8rem;">
            <div style="color:#9ca3af;">
                김프 <b style="color:#60a5fa;">{premium_text}</b> · 비용 <b style="color:#fbbf24;">{cost_text}</b>
            </div>
            {alert_text}
        </div>
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
# 펀딩비 섹션
# ------------------------------------------------------------------


def _render_funding_rate_section() -> None:
    """펀딩비 섹션 렌더링."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">💹 펀딩비 (Funding Rate)</p>',
        unsafe_allow_html=True,
    )

    funding_data = fetch_funding_rates_cached()

    if funding_data.get("status") == "error" or funding_data.get("status") == "no_data":
        info_html = f"""
        <div style="{CARD_STYLE}">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">
                📊 펀딩비란?
            </p>
            <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin-bottom:0.75rem;">
                선물 거래소에서 롱/숏 포지션 밸런스를 맞추기 위해 8시간마다 지불하는 수수료입니다.
            </p>
            <div style="display:flex;gap:1rem;font-size:0.8rem;margin-bottom:0.5rem;">
                <div>
                    <span style="color:{COLORS["success"]};">양수</span>
                    <span style="color:{COLORS["text_muted"]};"> = 롱 과다 (롱이 숏에 지불)</span>
                </div>
                <div>
                    <span style="color:{COLORS["danger"]};">음수</span>
                    <span style="color:{COLORS["text_muted"]};"> = 숏 과다 (숏이 롱에 지불)</span>
                </div>
            </div>
            <p style="font-size:0.75rem;color:{COLORS["text_muted"]};">
                ⚠️ 펀딩비 데이터를 불러오지 못했습니다.
            </p>
        </div>
        """
        if hasattr(st, 'html'):
            st.html(info_html)
        else:
            st.markdown(info_html, unsafe_allow_html=True)
        return

    # 펀딩비 요약
    avg_rate = funding_data.get("avg_funding_rate_pct", 0)
    position_bias = funding_data.get("position_bias", "neutral")
    symbols_data = funding_data.get("symbols", {})

    # 쏠림 방향에 따른 스타일
    if position_bias == "long_heavy":
        bias_color = COLORS["success"]
        bias_emoji = "📈"
        bias_text = "롱 과다"
        bias_hint = "시장이 상승을 기대 중"
    elif position_bias == "short_heavy":
        bias_color = COLORS["danger"]
        bias_emoji = "📉"
        bias_text = "숏 과다"
        bias_hint = "시장이 하락을 기대 중"
    else:
        bias_color = COLORS["neutral"]
        bias_emoji = "➖"
        bias_text = "중립"
        bias_hint = "롱/숏 균형"

    # 요약 카드
    summary_html = f"""
    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;">
            <div>
                <span style="font-size:1rem;font-weight:600;color:{COLORS["text_primary"]};">
                    평균 펀딩비
                </span>
                <span style="font-size:1.2rem;font-weight:700;color:{bias_color};margin-left:0.75rem;">
                    {avg_rate:+.4f}%
                </span>
            </div>
            <div style="background:rgba(0,0,0,0.3);border:1px solid {bias_color};
                        padding:4px 12px;border-radius:8px;font-size:0.85rem;">
                {bias_emoji} <span style="color:{bias_color};font-weight:600;">{bias_text}</span>
            </div>
        </div>
        <p style="font-size:0.8rem;color:{COLORS["text_muted"]};margin-bottom:0.75rem;">
            💡 {bias_hint}
        </p>
        <div style="display:flex;flex-wrap:wrap;gap:0.75rem;">
    """

    for symbol, data in symbols_data.items():
        rate_pct = data.get("rate_pct", 0)
        sym_bias = data.get("bias", "neutral")
        
        if sym_bias == "long_heavy":
            sym_color = COLORS["success"]
        elif sym_bias == "short_heavy":
            sym_color = COLORS["danger"]
        else:
            sym_color = COLORS["text_secondary"]

        summary_html += f"""
            <div style="background:{COLORS["bg_card"]};border:1px solid {COLORS["border_gray"]};
                        padding:8px 12px;border-radius:8px;min-width:100px;">
                <div style="font-size:0.85rem;font-weight:600;color:{COLORS["text_primary"]};">
                    {symbol.replace('USDT', '')}
                </div>
                <div style="font-size:0.9rem;font-weight:700;color:{sym_color};">
                    {rate_pct:+.4f}%
                </div>
            </div>
        """

    summary_html += """
        </div>
    </div>
    """

    if hasattr(st, 'html'):
        st.html(summary_html)
    else:
        st.markdown(summary_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 실시간 현선갭 조회 섹션
# ------------------------------------------------------------------


def _render_realtime_gap_section() -> None:
    """실시간 현선갭 조회 섹션."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">📊 실시간 현선갭 조회</p>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns([3, 1])
    with col1:
        symbol = st.text_input(
            "심볼",
            placeholder="예: BTC, ETH, SOL",
            key="gap_symbol",
            label_visibility="collapsed",
        )
    with col2:
        search_btn = st.button("🔍 조회", key="gap_search", use_container_width=True)

    if search_btn and symbol:
        symbol = symbol.upper().strip()
        
        with st.spinner(f"{symbol} 현선갭 조회 중..."):
            try:
                from collectors.exchange_service import ExchangeService
                from collectors.gap_calculator import GapCalculator

                service = ExchangeService()
                
                # 모든 거래소에서 가격 조회
                spot_exchanges = ['binance', 'bybit', 'okx', 'upbit', 'bithumb']
                futures_exchanges = ['binance', 'bybit', 'okx', 'hyperliquid']
                
                prices = service.fetch_all_prices(symbol, spot_exchanges, futures_exchanges)
                
                # 현선갭 계산
                gaps = GapCalculator.calculate_all_gaps(prices, symbol)
                
                if not gaps:
                    st.warning(f"{symbol}: 데이터를 찾을 수 없습니다.")
                else:
                    # 결과 표시
                    result_html = f"""
                    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                                border-radius:12px;padding:1rem;margin-top:0.75rem;">
                        <p style="font-size:1rem;font-weight:600;color:{COLORS["text_primary"]};margin-bottom:0.75rem;">
                            {symbol} 현선갭 (상위 5개)
                        </p>
                        <div style="display:flex;flex-direction:column;gap:0.5rem;">
                    """
                    
                    for gap in gaps[:5]:
                        gap_color = COLORS["success"] if gap.gap_percent > 0 else COLORS["danger"]
                        funding_text = f" | 펀딩: {gap.funding_rate*100:.4f}%" if gap.funding_rate else ""
                        krw_text = f" (₩{gap.spot_krw_price:,.0f})" if gap.spot_krw_price else ""
                        
                        result_html += f"""
                            <div style="display:flex;justify-content:space-between;align-items:center;
                                        background:{COLORS["bg_card"]};padding:0.5rem 0.75rem;border-radius:6px;">
                                <div>
                                    <span style="color:{COLORS["text_secondary"]};">{gap.spot_exchange}</span>
                                    <span style="color:{COLORS["text_muted"]};"> → </span>
                                    <span style="color:{COLORS["text_secondary"]};">{gap.futures_exchange}</span>
                                    {krw_text}
                                </div>
                                <div>
                                    <span style="font-weight:600;color:{gap_color};">{gap.gap_percent:+.3f}%</span>
                                    <span style="color:{COLORS["text_muted"]};font-size:0.8rem;">{funding_text}</span>
                                </div>
                            </div>
                        """
                    
                    # 가격 정보
                    spot_prices = prices.get('spot', {})
                    futures_prices = prices.get('futures', {})
                    
                    if spot_prices or futures_prices:
                        result_html += f"""
                            <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid {COLORS["border_gray"]};">
                                <p style="font-size:0.8rem;color:{COLORS["text_muted"]};margin-bottom:0.5rem;">가격 정보</p>
                                <div style="display:flex;gap:1rem;flex-wrap:wrap;font-size:0.85rem;">
                        """
                        for ex, data in spot_prices.items():
                            krw = f" (₩{data.krw_price:,.0f})" if data.krw_price else ""
                            result_html += f'<span style="color:{COLORS["text_secondary"]};">{ex}: ${data.price:.4f}{krw}</span>'
                        for ex, data in futures_prices.items():
                            result_html += f'<span style="color:{COLORS["info"]};">{ex}(F): ${data.price:.4f}</span>'
                        result_html += "</div></div>"
                    
                    result_html += """
                        </div>
                    </div>
                    """
                    
                    if hasattr(st, 'html'):
                        st.html(result_html)
                    else:
                        st.markdown(result_html, unsafe_allow_html=True)

            except Exception as e:
                st.error(f"조회 실패: {e}")

    # 설명
    info_html = f"""
    <div style="{CARD_STYLE}margin-top:0.75rem;">
        <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};">
            💡 <b>현선갭</b> = (선물가격 - 현물가격) / 현물가격 × 100
        </p>
        <p style="font-size:0.75rem;color:{COLORS["text_muted"]};margin-top:0.25rem;">
            양수: 선물 프리미엄 | 음수: 선물 디스카운트 | 갭이 클수록 헷징 어려움 → GO 신호
        </p>
    </div>
    """
    if hasattr(st, 'html'):
        st.html(info_html)
    else:
        st.markdown(info_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 🔍 빠른 분석 통합 섹션 (현선갭 + DEX 유동성 통합)
# ------------------------------------------------------------------


def _render_quick_analysis_section() -> None:
    """빠른 분석 통합 섹션 (현선갭 + DEX 유동성 한번에 조회)."""
    import streamlit as st
    import asyncio

    # 헤더 (완전한 HTML 블록)
    header_html = '''
    <div style="background:linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border:1px solid #3b82f6;border-radius:16px 16px 0 0;padding:1rem 1.25rem 0.75rem 1.25rem;">
        <div style="display:flex;align-items:center;gap:0.5rem;">
            <span style="font-size:1.3rem;">🔍</span>
            <span style="font-size:1.1rem;font-weight:700;color:#fff;">빠른 분석</span>
            <span style="font-size:0.75rem;color:#6b7280;margin-left:0.5rem;">현선갭 + DEX 유동성 통합 조회</span>
        </div>
    </div>
    '''
    if hasattr(st, 'html'):
        st.html(header_html)
    else:
        st.markdown(header_html, unsafe_allow_html=True)

    # 입력 필드 (Streamlit 컴포넌트)
    col1, col2 = st.columns([4, 1])
    with col1:
        symbol = st.text_input(
            "심볼 입력",
            placeholder="심볼 입력 (예: SOL, AVAIL, ME)",
            key="quick_analysis_symbol",
            label_visibility="collapsed",
        )
    with col2:
        search_btn = st.button("🚀 분석", key="quick_analysis_btn", use_container_width=True)

    if search_btn and symbol:
        symbol = symbol.upper().strip()
        
        with st.spinner(f"🔄 {symbol} 통합 분석 중..."):
            results = {"gap": None, "dex": None, "gap_error": None, "dex_error": None}
            
            # 1. 현선갭 조회
            try:
                from collectors.exchange_service import ExchangeService
                from collectors.gap_calculator import GapCalculator

                service = ExchangeService()
                spot_exchanges = ['binance', 'bybit', 'okx', 'upbit', 'bithumb']
                futures_exchanges = ['binance', 'bybit', 'okx', 'hyperliquid']
                
                prices = service.fetch_all_prices(symbol, spot_exchanges, futures_exchanges)
                gaps = GapCalculator.calculate_all_gaps(prices, symbol)
                results["gap"] = {"prices": prices, "gaps": gaps}
            except Exception as e:
                results["gap_error"] = str(e)
            
            # 2. DEX 유동성 조회
            try:
                from collectors.dex_liquidity import get_dex_liquidity
                dex_result = asyncio.run(get_dex_liquidity(symbol))
                results["dex"] = dex_result
            except Exception as e:
                results["dex_error"] = str(e)
            
            # 결과 렌더링
            _render_quick_analysis_results(symbol, results)


def _render_quick_analysis_results(symbol: str, results: dict) -> None:
    """빠른 분석 결과 렌더링."""
    import streamlit as st

    gap_data = results.get("gap")
    dex_data = results.get("dex")
    
    # 종합 판정
    overall_signal = "🟡 분석중"
    signal_color = "#fbbf24"
    
    gap_signal = None
    dex_signal = None
    
    if gap_data and gap_data.get("gaps"):
        best_gap = gap_data["gaps"][0].gap_percent if gap_data["gaps"] else 0
        if best_gap > 3:
            gap_signal = "GO"
        elif best_gap > 1:
            gap_signal = "CAUTION"
        else:
            gap_signal = "NO_GO"
    
    if dex_data:
        dex_signal = dex_data.go_signal
    
    # 종합 판정 로직
    if gap_signal == "GO" and dex_signal in ["STRONG_GO", "GO"]:
        overall_signal = "🟢🟢 STRONG GO"
        signal_color = "#4ade80"
    elif gap_signal == "GO" or dex_signal in ["STRONG_GO", "GO"]:
        overall_signal = "🟢 GO"
        signal_color = "#4ade80"
    elif gap_signal == "NO_GO" and dex_signal == "NO_GO":
        overall_signal = "🔴 NO-GO"
        signal_color = "#f87171"
    else:
        overall_signal = "🟡 CAUTION"
        signal_color = "#fbbf24"

    # 메인 결과 카드
    result_html = f"""
    <div style="background:linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        border:2px solid {signal_color};border-radius:16px;padding:1.25rem;margin-top:0.5rem;">
        
        <!-- 헤더: 심볼 + 종합 판정 -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;
            padding-bottom:0.75rem;border-bottom:1px solid #374151;">
            <span style="font-size:1.5rem;font-weight:800;color:#fff;">{symbol}</span>
            <div style="background:{signal_color};color:#000;padding:8px 16px;border-radius:10px;
                font-weight:700;font-size:0.9rem;">{overall_signal}</div>
        </div>
        
        <!-- 2컬럼: 현선갭 | DEX 유동성 -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
    """
    
    # 현선갭 결과
    result_html += '<div style="background:#1f2937;border-radius:12px;padding:1rem;">'
    result_html += '<div style="font-size:0.85rem;font-weight:600;color:#60a5fa;margin-bottom:0.75rem;">📊 현선갭</div>'
    
    if results.get("gap_error"):
        result_html += f'<div style="color:#f87171;font-size:0.8rem;">❌ {results["gap_error"][:40]}</div>'
    elif gap_data and gap_data.get("gaps"):
        for i, gap in enumerate(gap_data["gaps"][:3]):
            gap_color = "#4ade80" if gap.gap_percent > 0 else "#f87171"
            result_html += f'''
            <div style="display:flex;justify-content:space-between;padding:0.4rem 0;
                border-bottom:1px solid #374151;font-size:0.8rem;">
                <span style="color:#9ca3af;">{gap.spot_exchange}→{gap.futures_exchange}</span>
                <span style="color:{gap_color};font-weight:600;">{gap.gap_percent:+.2f}%</span>
            </div>
            '''
        # 가격 정보
        spot_prices = gap_data.get("prices", {}).get("spot", {})
        if spot_prices:
            first_price = list(spot_prices.values())[0] if spot_prices else None
            if first_price:
                krw_text = f"₩{first_price.krw_price:,.0f}" if first_price.krw_price else ""
                result_html += f'<div style="font-size:0.75rem;color:#6b7280;margin-top:0.5rem;">현재가: ${first_price.price:.4f} {krw_text}</div>'
    else:
        result_html += '<div style="color:#6b7280;font-size:0.8rem;">데이터 없음</div>'
    
    result_html += '</div>'
    
    # DEX 유동성 결과
    result_html += '<div style="background:#1f2937;border-radius:12px;padding:1rem;">'
    result_html += '<div style="font-size:0.85rem;font-weight:600;color:#a78bfa;margin-bottom:0.75rem;">💧 DEX 유동성</div>'
    
    if results.get("dex_error"):
        result_html += f'<div style="color:#f87171;font-size:0.8rem;">❌ {results["dex_error"][:40]}</div>'
    elif dex_data:
        dex_color = "#4ade80" if dex_data.go_signal in ["STRONG_GO", "GO"] else "#fbbf24" if dex_data.go_signal == "CAUTION" else "#f87171"
        result_html += f'''
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <span style="color:#9ca3af;font-size:0.8rem;">총 유동성</span>
            <span style="color:{dex_color};font-weight:700;font-size:1.1rem;">${dex_data.total_liquidity_usd:,.0f}</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <span style="color:#9ca3af;font-size:0.8rem;">24h 거래량</span>
            <span style="color:#fff;font-weight:600;">${dex_data.total_volume_24h:,.0f}</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="color:#9ca3af;font-size:0.8rem;">신호</span>
            <span style="background:{dex_color};color:#000;padding:2px 8px;border-radius:4px;
                font-size:0.75rem;font-weight:600;">{dex_data.go_emoji} {dex_data.go_signal}</span>
        </div>
        '''
        if dex_data.best_pair:
            bp = dex_data.best_pair
            result_html += f'''
            <div style="font-size:0.7rem;color:#6b7280;margin-top:0.5rem;
                padding-top:0.5rem;border-top:1px solid #374151;">
                🏆 {bp.dex} ({bp.chain})
            </div>
            '''
    else:
        result_html += '<div style="color:#6b7280;font-size:0.8rem;">데이터 없음</div>'
    
    result_html += '</div>'
    
    result_html += """
        </div>
    </div>
    """
    
    if hasattr(st, 'html'):
        st.html(result_html)
    else:
        st.markdown(result_html, unsafe_allow_html=True)

    # 판정 기준 설명 (접이식)
    with st.expander("💡 판정 기준", expanded=False):
        st.markdown("""
        **현선갭 (Spot-Futures Gap)**
        - 🟢 +3% 이상: GO (헷징 어려움 → 공급 제약)
        - 🟡 +1~3%: CAUTION
        - 🔴 +1% 미만: NO-GO
        
        **DEX 유동성**
        - 🟢🟢 $200K 이하: STRONG GO
        - 🟢 $500K 이하: GO
        - 🟡 $1M 이하: CAUTION
        - 🔴 $1M 초과: NO-GO
        
        **종합 판정**: 둘 다 GO면 STRONG GO, 하나라도 GO면 GO
        """)


# ------------------------------------------------------------------
# 메인 렌더 함수 (Phase 2.2: 개선된 레이아웃)
# ------------------------------------------------------------------


def render_live_tab() -> None:
    """실시간 현황 탭 렌더링.
    
    레이아웃 구조:
    1. GO 카드 (최상단, 크게)
    2. 2컬럼: [실시간 정보 | 빠른 분석]
    3. 차트/통계 (접이식)
    4. NO-GO (접이식)
    """
    import streamlit as st

    conn = get_read_conn()
    conn_id = id(conn)

    vasp_matrix = load_vasp_matrix_cached()
    analyses = fetch_recent_analyses_cached(conn_id, limit=20)

    # ============================================================
    # 섹션 1: GO 카드 (최상단, 눈에 띄게)
    # ============================================================
    go_analyses = [r for r in analyses if r.get("can_proceed", 0)] if analyses else []
    nogo_analyses = [r for r in analyses if not r.get("can_proceed", 0)] if analyses else []

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
            f'''<div style="background:linear-gradient(135deg, #0d3320 0%, #166534 50%, #15803d 100%);
                border:3px solid #4ade80;border-radius:20px;padding:1.25rem 1.5rem;margin-bottom:1.25rem;
                box-shadow:0 8px 32px rgba(74,222,128,0.2);">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
                    <div style="display:flex;align-items:center;gap:1rem;">
                        <span style="font-size:2.5rem;filter:drop-shadow(0 0 8px #4ade80);">🚀</span>
                        <div>
                            <div style="font-size:1.5rem;font-weight:800;color:#4ade80;
                                text-shadow:0 0 20px rgba(74,222,128,0.5);">
                                GO! {len(go_analyses)}건
                            </div>
                            <div style="font-size:0.9rem;color:#86efac;">
                                최고 수익 <b>{best_profit_text}</b>
                            </div>
                        </div>
                    </div>
                    <div>{mood_badge}</div>
                </div>
            </div>''',
            unsafe_allow_html=True,
        )
        
        # GO 카드들 렌더링
        for row in go_analyses:
            _render_analysis_card(row, vasp_matrix, highlight=True)

    elif not analyses:
        # 데이터 없음 상태
        st.markdown(
            f'''<div style="background:linear-gradient(135deg, #1f1f1f 0%, #2a2a2a 100%);
                border:1px dashed #374151;border-radius:16px;padding:2.5rem;text-align:center;margin-bottom:1rem;">
                <div style="font-size:2.5rem;margin-bottom:0.75rem;">⏳</div>
                <div style="font-size:1.2rem;color:#9ca3af;margin-bottom:0.5rem;">분석 기록 없음</div>
                <div style="font-size:0.85rem;color:#6b7280;">
                    수집 데몬이 실행 중이고 새 상장이 감지되면<br>여기에 GO/NO-GO 분석 결과가 표시됩니다.
                </div>
            </div>''',
            unsafe_allow_html=True,
        )

    else:
        # GO 없음 - 대기 상태
        st.markdown(
            f'''<div style="background:linear-gradient(135deg, #1a1a1a 0%, #262626 100%);
                border:2px dashed #374151;border-radius:16px;padding:1.5rem;text-align:center;margin-bottom:1rem;">
                <div style="font-size:1.8rem;margin-bottom:0.5rem;">😴</div>
                <div style="font-size:1.1rem;color:#9ca3af;">현재 GO 기회 없음</div>
                <div style="font-size:0.8rem;color:#6b7280;">대기 중... 새 상장 감지 시 알림</div>
            </div>''',
            unsafe_allow_html=True,
        )

    # ============================================================
    # 섹션 2: 2컬럼 레이아웃 (실시간 정보 | 빠른 분석)
    # ============================================================
    col_left, col_right = st.columns([1, 1])

    with col_left:
        # 📊 실시간 시장 정보 - 전체를 하나의 HTML 블록으로
        stats = fetch_stats_cached(conn_id)
        
        # 통계 그리드 HTML
        if stats["total"] > 0:
            stats_grid = f'''
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:0.5rem;">
                <div style="background:#1f2937;padding:0.6rem;border-radius:8px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:700;color:#4ade80;">{stats['go_count']}</div>
                    <div style="font-size:0.7rem;color:#6b7280;">GO</div>
                </div>
                <div style="background:#1f2937;padding:0.6rem;border-radius:8px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:700;color:#f87171;">{stats['nogo_count']}</div>
                    <div style="font-size:0.7rem;color:#6b7280;">NO-GO</div>
                </div>
                <div style="background:#1f2937;padding:0.6rem;border-radius:8px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:700;color:#60a5fa;">{stats['avg_premium']:.1f}%</div>
                    <div style="font-size:0.7rem;color:#6b7280;">평균 김프</div>
                </div>
                <div style="background:#1f2937;padding:0.6rem;border-radius:8px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:700;color:#fff;">{stats['total']}</div>
                    <div style="font-size:0.7rem;color:#6b7280;">총 분석</div>
                </div>
            </div>
            '''
        else:
            stats_grid = '''
            <div style="color:#6b7280;font-size:0.85rem;text-align:center;padding:1rem 0;">
                분석 데이터 없음
            </div>
            '''
        
        market_info_html = f'''
        <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
            border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
            <div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.75rem;">
                📊 실시간 시장 정보
            </div>
            {stats_grid}
        </div>
        '''
        
        if hasattr(st, 'html'):
            st.html(market_info_html)
        else:
            st.markdown(market_info_html, unsafe_allow_html=True)
        
        # 펀딩비 (컴팩트)
        _render_funding_rate_compact()

    with col_right:
        # 🔍 빠른 분석 섹션
        _render_quick_analysis_section()

    # ============================================================
    # 섹션 3: 차트/상세 정보 (접이식)
    # ============================================================
    with st.expander("📈 차트 & 상세 분석", expanded=False):
        _render_premium_chart_section(conn_id)
        _render_spot_futures_gap_section(conn_id)

    # ============================================================
    # 섹션 4: NO-GO 목록 (접이식)
    # ============================================================
    if nogo_analyses:
        avg_profit = sum(r.get("net_profit_pct") or 0 for r in nogo_analyses) / len(nogo_analyses)
        nogo_header = f"🔴 NO-GO ({len(nogo_analyses)}건) · 평균 {avg_profit:.1f}%"
    else:
        nogo_header = "🔴 NO-GO (0건)"
    
    with st.expander(nogo_header, expanded=False):
        if nogo_analyses:
            for row in nogo_analyses:
                _render_analysis_card(row, vasp_matrix, highlight=False)
        else:
            st.info("NO-GO 분석 기록이 없습니다.")


def _render_funding_rate_compact() -> None:
    """펀딩비 컴팩트 버전."""
    import streamlit as st

    funding_data = fetch_funding_rates_cached()
    
    if funding_data.get("status") in ["error", "no_data"]:
        no_data_html = f'''
        <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
            border-radius:12px;padding:1rem;">
            <div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.5rem;">
                💹 펀딩비
            </div>
            <div style="color:#6b7280;font-size:0.8rem;">데이터 로딩 중...</div>
        </div>
        '''
        if hasattr(st, 'html'):
            st.html(no_data_html)
        else:
            st.markdown(no_data_html, unsafe_allow_html=True)
        return

    avg_rate = funding_data.get("avg_funding_rate_pct", 0)
    position_bias = funding_data.get("position_bias", "neutral")
    symbols_data = funding_data.get("symbols", {})

    # 쏠림 방향
    if position_bias == "long_heavy":
        bias_color, bias_emoji, bias_text = "#4ade80", "📈", "롱 과다"
    elif position_bias == "short_heavy":
        bias_color, bias_emoji, bias_text = "#f87171", "📉", "숏 과다"
    else:
        bias_color, bias_emoji, bias_text = "#9ca3af", "➖", "중립"

    # 심볼별 펀딩비 HTML 생성
    symbols_html = ""
    for symbol, data in list(symbols_data.items())[:4]:
        rate_pct = data.get("rate_pct", 0)
        sym_color = "#4ade80" if rate_pct > 0 else "#f87171" if rate_pct < 0 else "#9ca3af"
        symbols_html += f'''
            <span style="background:#1f2937;padding:4px 8px;border-radius:4px;font-size:0.75rem;display:inline-block;">
                <span style="color:#9ca3af;">{symbol.replace('USDT', '')}</span>
                <span style="color:{sym_color};font-weight:600;margin-left:4px;">{rate_pct:+.3f}%</span>
            </span>
        '''

    funding_html = f'''
    <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
        border-radius:12px;padding:1rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;">
            <span style="font-size:0.9rem;font-weight:600;color:#fff;">💹 펀딩비</span>
            <span style="background:{bias_color}22;color:{bias_color};padding:3px 8px;
                border-radius:6px;font-size:0.75rem;font-weight:600;">
                {bias_emoji} {bias_text}
            </span>
        </div>
        <div style="font-size:1.3rem;font-weight:700;color:{bias_color};margin-bottom:0.5rem;">
            {avg_rate:+.4f}%
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:0.4rem;">
            {symbols_html}
        </div>
    </div>
    '''
    
    if hasattr(st, 'html'):
        st.html(funding_html)
    else:
        st.markdown(funding_html, unsafe_allow_html=True)
