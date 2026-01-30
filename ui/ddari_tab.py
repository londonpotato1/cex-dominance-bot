"""따리분석 탭 (Phase 4 + Phase 8).

3개 서브탭으로 구성:
  1. 🔥 실시간 현황 — Gate 분석, 통계, 프리미엄 차트, 현선갭
  2. 📊 분석 인텔리전스 — 상장 히스토리, 시나리오, VC/MM, 토크노믹스
  3. 🎯 후따리 전략 — 후따리 분석, 매도 타이밍

사용자 가이드는 실시간 현황 탭 하단에 접이식으로 제공.
"""

from __future__ import annotations


def render_ddari_tab() -> None:
    """따리분석 탭 렌더링 (app.py에서 호출)."""
    import streamlit as st

    from ui.ddari_live import render_live_tab
    from ui.ddari_intel import render_intel_tab
    from ui.ddari_post import render_post_tab
    from ui.ddari_guide import render_user_guide

    # 3개 서브탭 생성
    live_tab, intel_tab, post_tab = st.tabs([
        "🔥 실시간 현황",
        "📊 분석 인텔리전스",
        "🎯 후따리 전략"
    ])

    with live_tab:
        render_live_tab()
        # 사용자 가이드는 실시간 현황 탭 하단에 표시
        render_user_guide()

    with intel_tab:
        render_intel_tab()

    with post_tab:
        render_post_tab()
