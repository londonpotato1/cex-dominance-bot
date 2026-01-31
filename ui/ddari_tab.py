"""따리분석 탭 (Phase 4 + Phase 8).

5개 서브탭으로 구성:
  1. 🔥 실시간 현황 — Gate 분석, 통계, 프리미엄 차트, 현선갭
  2. 📊 분석 인텔리전스 — 상장 히스토리, 시나리오, VC/MM, 토크노믹스
  3. 🎯 후따리 전략 — 후따리 분석, 매도 타이밍
  4. 🔍 전략 분석 — 상장 전략 분석기, 갭 모니터링
  5. 📖 가이드 — 따리 전략 완벽 가이드
"""

from __future__ import annotations


def render_ddari_tab() -> None:
    """따리분석 탭 렌더링 (app.py에서 호출)."""
    import streamlit as st

    from ui.ddari_live import render_live_tab
    from ui.ddari_intel import render_intel_tab
    from ui.ddari_post import render_post_tab
    from ui.ddari_guide import render_user_guide
    from ui.ddari_strategy import render_strategy_analysis_section, render_gap_monitor_section

    # 5개 서브탭 생성
    live_tab, intel_tab, post_tab, strategy_tab, guide_tab = st.tabs([
        "🔥 실시간",
        "📊 인텔리전스",
        "🎯 후따리",
        "🔍 전략분석",
        "📖 가이드"
    ])

    with live_tab:
        render_live_tab()

    with intel_tab:
        render_intel_tab()

    with post_tab:
        render_post_tab()

    with strategy_tab:
        render_strategy_analysis_section()
        render_gap_monitor_section()

    with guide_tab:
        render_user_guide()
