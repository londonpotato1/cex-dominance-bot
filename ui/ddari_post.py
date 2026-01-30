"""따리분석 후따리 전략 탭 (Tab 3).

포지션 진입 후 관리: 후따리 분석, 매도 타이밍.
"""

from __future__ import annotations

import sqlite3

from ui.ddari_common import (
    CARD_STYLE,
    COLORS,
    SECTION_HEADER_STYLE,
    PHASE8_AVAILABLE,
    badge_style,
    get_read_conn,
)


# ------------------------------------------------------------------
# 후따리 분석 섹션
# ------------------------------------------------------------------


def _fetch_post_listing_data_cached(conn_id: int, limit: int = 5) -> list[dict]:
    """후따리 분석 데이터 조회 (1분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=60)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = get_read_conn()
        try:
            rows = conn.execute(
                """
                SELECT symbol, exchange, listing_time, phase, signal,
                       time_score, price_score, volume_score, premium_score,
                       total_score, confidence, reason
                FROM post_listing_analysis
                ORDER BY analyzed_at DESC
                LIMIT ?
                """,
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, limit)


def _render_post_listing_card_html(data: dict) -> str:
    """후따리 분석 카드 HTML 생성."""
    symbol = data.get("symbol", "?")
    exchange = data.get("exchange", "?")
    phase = data.get("phase", "unknown")
    signal = data.get("signal", "hold")
    total_score = data.get("total_score", 0)
    confidence = data.get("confidence", 0)
    reason = data.get("reason", "")

    # Phase별 스타일
    phase_styles = {
        "initial_pump": {"emoji": "🚀", "name": "초기 펌핑", "color": COLORS["success"]},
        "first_dump": {"emoji": "📉", "name": "1차 덤핑", "color": COLORS["danger"]},
        "consolidation": {"emoji": "📊", "name": "횡보 구간", "color": COLORS["neutral"]},
        "second_pump": {"emoji": "🔥", "name": "2차 펌핑", "color": COLORS["warning"]},
        "fade_out": {"emoji": "💤", "name": "소강 국면", "color": COLORS["text_muted"]},
    }
    phase_style = phase_styles.get(phase, {"emoji": "❓", "name": phase, "color": COLORS["neutral"]})

    # Signal별 스타일
    signal_styles = {
        "strong_buy": {"emoji": "🔥🔥", "name": "강력 매수", "bg": COLORS["success"]},
        "buy": {"emoji": "✨", "name": "매수", "bg": COLORS["info"]},
        "hold": {"emoji": "⏸️", "name": "관망", "bg": COLORS["neutral"]},
        "avoid": {"emoji": "🚫", "name": "회피", "bg": COLORS["danger"]},
    }
    signal_style = signal_styles.get(signal, {"emoji": "❓", "name": signal, "bg": COLORS["neutral"]})

    # 점수 바
    score_width = min(total_score * 10, 100)  # 0-10 → 0-100%
    score_color = (
        COLORS["success"] if total_score >= 7 else
        COLORS["info"] if total_score >= 5 else
        COLORS["warning"] if total_score >= 3 else
        COLORS["danger"]
    )

    # 개별 점수
    time_score = data.get("time_score", 0)
    price_score = data.get("price_score", 0)
    volume_score = data.get("volume_score", 0)
    premium_score = data.get("premium_score", 0)

    return f"""
    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <div>
                <span style="font-size:1.1rem;font-weight:600;color:{COLORS["text_primary"]};">{symbol}</span>
                <span style="color:{COLORS["text_tertiary"]};font-size:0.8rem;margin-left:0.5rem;">@{exchange}</span>
            </div>
            <div style="display:flex;gap:0.5rem;align-items:center;">
                <span style="{badge_style(phase_style['color'], size='0.75rem')}">{phase_style['emoji']} {phase_style['name']}</span>
                <span style="background:{signal_style['bg']};color:{COLORS["text_primary"]};padding:4px 12px;
                            border-radius:6px;font-weight:600;font-size:0.85rem;">
                    {signal_style['emoji']} {signal_style['name']}
                </span>
            </div>
        </div>
        <div style="margin:0.75rem 0;">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                <span style="font-size:0.8rem;color:{COLORS["text_secondary"]};">종합 점수</span>
                <span style="font-size:0.8rem;color:{score_color};font-weight:600;">{total_score:.1f}/10</span>
            </div>
            <div style="background:#2d2d2d;border-radius:4px;height:8px;overflow:hidden;">
                <div style="background:{score_color};width:{score_width}%;height:100%;"></div>
            </div>
        </div>
        <div style="display:flex;gap:1rem;font-size:0.75rem;color:{COLORS["text_tertiary"]};margin-bottom:0.5rem;">
            <span>시간: {time_score:.1f}</span>
            <span>가격: {price_score:.1f}</span>
            <span>거래량: {volume_score:.1f}</span>
            <span>프리미엄: {premium_score:.1f}</span>
        </div>
        {f'<p style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin:0;">{reason}</p>' if reason else ''}
        <div style="margin-top:0.5rem;font-size:0.7rem;color:{COLORS["text_muted"]};">
            신뢰도: {confidence*100:.0f}%
        </div>
    </div>
    """


def _render_post_listing_section(conn_id: int) -> None:
    """후따리 분석 섹션 렌더링 (Phase 8)."""
    import streamlit as st

    if not PHASE8_AVAILABLE:
        return

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">🔥 후따리 분석 (2차 펌핑 기회)</p>',
        unsafe_allow_html=True,
    )

    # 데이터 조회
    post_listing_data = _fetch_post_listing_data_cached(conn_id, limit=5)

    if not post_listing_data:
        # 데이터 없으면 설명 카드 표시
        info_html = f"""
        <div style="{CARD_STYLE}">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">
                📊 후따리 전략이란?
            </p>
            <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin-bottom:0.75rem;">
                상장 직후 초기 펌핑 → 1차 덤핑 후 발생하는 <b>2차 펌핑 기회</b>를 포착하는 전략입니다.
            </p>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.5rem;">
                <span style="{badge_style(COLORS["success"], size="0.7rem")}">🚀 초기 펌핑 (0-10분)</span>
                <span style="{badge_style(COLORS["danger"], size="0.7rem")}">📉 1차 덤핑 (10-30분)</span>
                <span style="{badge_style(COLORS["neutral"], size="0.7rem")}">📊 횡보 (30분-2시간)</span>
                <span style="{badge_style(COLORS["warning"], size="0.7rem")}">🔥 2차 펌핑 (기회)</span>
            </div>
            <p style="font-size:0.75rem;color:{COLORS["text_muted"]};">
                💡 상장 감지 시 자동으로 분석이 시작됩니다.
            </p>
        </div>
        """
        if hasattr(st, 'html'):
            st.html(info_html)
        else:
            st.markdown(info_html, unsafe_allow_html=True)
        return

    # 분석 결과 카드들
    for data in post_listing_data:
        card_html = _render_post_listing_card_html(data)
        if hasattr(st, 'html'):
            st.html(card_html)
        else:
            st.markdown(card_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 매도 타이밍 섹션
# ------------------------------------------------------------------


def _fetch_exit_timing_cached(conn_id: int, limit: int = 5) -> list[dict]:
    """매도 타이밍 데이터 조회 (15초 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=15)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = get_read_conn()
        try:
            rows = conn.execute(
                """
                SELECT symbol, exchange, should_exit, trigger_type, urgency,
                       reason, current_premium_pct, entry_premium_pct,
                       peak_premium_pct, position_duration_min, created_at
                FROM exit_timing
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, limit)


def _render_exit_timing_card_html(data: dict) -> str:
    """매도 타이밍 카드 HTML 생성."""
    symbol = data.get("symbol", "?")
    exchange = data.get("exchange", "?")
    should_exit = data.get("should_exit", False)
    trigger_type = data.get("trigger_type", "none")
    urgency = data.get("urgency", "low")
    reason = data.get("reason", "")
    current_prem = data.get("current_premium_pct", 0)
    entry_prem = data.get("entry_premium_pct", 0)
    peak_prem = data.get("peak_premium_pct", 0)
    duration_min = data.get("position_duration_min", 0)

    # Urgency 스타일
    urgency_styles = {
        "critical": {"emoji": "🚨", "name": "즉시 청산", "bg": COLORS["danger"], "border": COLORS["danger"]},
        "high": {"emoji": "⚠️", "name": "긴급", "bg": COLORS["warning"], "border": COLORS["warning"]},
        "medium": {"emoji": "📊", "name": "주의", "bg": COLORS["info"], "border": COLORS["info"]},
        "low": {"emoji": "✅", "name": "정상", "bg": COLORS["success"], "border": COLORS["success"]},
    }
    urg_style = urgency_styles.get(urgency, urgency_styles["low"])

    # Trigger 타입 스타일
    trigger_styles = {
        "premium_target": {"emoji": "🎯", "name": "목표가 도달"},
        "premium_floor": {"emoji": "🔻", "name": "손절선 이탈"},
        "time_limit": {"emoji": "⏰", "name": "시간 초과"},
        "volume_spike": {"emoji": "📈", "name": "거래량 급증"},
        "premium_reversal": {"emoji": "↩️", "name": "프리미엄 반전"},
        "trailing_stop": {"emoji": "📉", "name": "추적 손절"},
        "manual": {"emoji": "✋", "name": "수동"},
        "none": {"emoji": "➖", "name": "없음"},
    }
    trig_style = trigger_styles.get(trigger_type, {"emoji": "❓", "name": trigger_type})

    # 카드 테두리 색상 (should_exit이면 강조)
    border_color = urg_style["border"] if should_exit else COLORS["card_border"]

    # 프리미엄 변화
    prem_change = current_prem - entry_prem
    prem_change_color = COLORS["success"] if prem_change > 0 else COLORS["danger"]

    # 시간 포맷
    if duration_min >= 60:
        duration_str = f"{duration_min // 60}시간 {duration_min % 60}분"
    else:
        duration_str = f"{duration_min}분"

    return f"""
    <div style="background:{COLORS["card_bg"]};border:2px solid {border_color};
                border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <div>
                <span style="font-size:1.1rem;font-weight:600;color:{COLORS["text_primary"]};">{symbol}</span>
                <span style="color:{COLORS["text_tertiary"]};font-size:0.8rem;margin-left:0.5rem;">@{exchange}</span>
            </div>
            <div style="display:flex;gap:0.5rem;align-items:center;">
                <span style="{badge_style(COLORS["neutral"] if not should_exit else urg_style["bg"], size="0.75rem")}">{trig_style['emoji']} {trig_style['name']}</span>
                {f'<span style="background:{urg_style["bg"]};color:{COLORS["text_primary"]};padding:4px 12px;border-radius:6px;font-weight:600;font-size:0.85rem;">{urg_style["emoji"]} {urg_style["name"]}</span>' if should_exit else ''}
            </div>
        </div>
        <div style="display:flex;gap:1.5rem;font-size:0.85rem;margin-bottom:0.5rem;">
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">현재</span>
                <span style="margin-left:4px;font-weight:600;color:{COLORS["text_accent"]};">{current_prem:+.2f}%</span>
            </div>
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">진입</span>
                <span style="margin-left:4px;">{entry_prem:+.2f}%</span>
            </div>
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">최고</span>
                <span style="margin-left:4px;color:{COLORS["success"]};">{peak_prem:+.2f}%</span>
            </div>
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">변화</span>
                <span style="margin-left:4px;color:{prem_change_color};">{prem_change:+.2f}%</span>
            </div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:{COLORS["text_muted"]};">
            <span>포지션 유지: {duration_str}</span>
            {f'<span style="color:{urg_style["border"]};">{reason}</span>' if reason else ''}
        </div>
    </div>
    """


def _render_exit_timing_section(conn_id: int) -> None:
    """매도 타이밍 섹션 렌더링 (Phase 8)."""
    import streamlit as st

    if not PHASE8_AVAILABLE:
        return

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">⏰ 매도 타이밍</p>',
        unsafe_allow_html=True,
    )

    # 데이터 조회
    exit_data = _fetch_exit_timing_cached(conn_id, limit=5)

    if not exit_data:
        info_html = f"""
        <div style="{CARD_STYLE}">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">
                ⏰ 매도 타이밍 엔진
            </p>
            <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin-bottom:0.75rem;">
                포지션 진입 후 최적의 청산 시점을 자동으로 감지합니다.
            </p>
            <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.5rem;">
                <span style="{badge_style(COLORS["success"], size="0.7rem")}">🎯 목표가 도달</span>
                <span style="{badge_style(COLORS["danger"], size="0.7rem")}">🔻 손절선 이탈</span>
                <span style="{badge_style(COLORS["warning"], size="0.7rem")}">⏰ 시간 초과</span>
                <span style="{badge_style(COLORS["info"], size="0.7rem")}">📈 거래량 급증</span>
                <span style="{badge_style(COLORS["neutral"], size="0.7rem")}">↩️ 프리미엄 반전</span>
            </div>
            <p style="font-size:0.75rem;color:{COLORS["text_muted"]};">
                💡 포지션 진입 시 자동으로 모니터링이 시작됩니다.
            </p>
        </div>
        """
        if hasattr(st, 'html'):
            st.html(info_html)
        else:
            st.markdown(info_html, unsafe_allow_html=True)
        return

    # 긴급 청산 알림 (critical/high urgency)
    urgent_positions = [d for d in exit_data if d.get("should_exit") and d.get("urgency") in ("critical", "high")]
    if urgent_positions:
        alert_html = f"""
        <div style="background:rgba(239,68,68,0.15);border:1px solid {COLORS["danger"]};
                    border-radius:12px;padding:1rem;margin-bottom:1rem;">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["danger"]};margin-bottom:0.5rem;">
                🚨 긴급 청산 필요: {len(urgent_positions)}건
            </p>
            <div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
        """
        for pos in urgent_positions:
            alert_html += f"""
                <span style="{badge_style(COLORS["danger_dark"], size="0.8rem")}">{pos.get("symbol", "?")} {pos.get("current_premium_pct", 0):+.1f}%</span>
            """
        alert_html += """
            </div>
        </div>
        """
        if hasattr(st, 'html'):
            st.html(alert_html)
        else:
            st.markdown(alert_html, unsafe_allow_html=True)

    # 타이밍 카드들
    for data in exit_data:
        card_html = _render_exit_timing_card_html(data)
        if hasattr(st, 'html'):
            st.html(card_html)
        else:
            st.markdown(card_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 메인 렌더 함수
# ------------------------------------------------------------------


def render_post_tab() -> None:
    """후따리 전략 탭 렌더링."""
    import streamlit as st

    conn = get_read_conn()
    conn_id = id(conn)

    if not PHASE8_AVAILABLE:
        st.info("Phase 8 모듈이 설치되지 않았습니다. 후따리 분석 기능을 사용하려면 Phase 8 모듈을 설치하세요.")
        return

    st.markdown(
        '<p style="font-size:1.2rem;font-weight:700;color:#fff;'
        'margin-bottom:1rem;border-bottom:1px solid #333;'
        'padding-bottom:0.5rem;">🎯 Phase 8: 후따리 전략</p>',
        unsafe_allow_html=True,
    )

    # 후따리 분석
    _render_post_listing_section(conn_id)

    # 매도 타이밍
    _render_exit_timing_section(conn_id)
