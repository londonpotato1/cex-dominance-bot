"""따리분석 탭 (3탭 구조 - Lazy Loading).

3개 서브탭으로 구성 (선택된 탭만 렌더링):
  1. 📊 대시보드 — GO/NO-GO 현황, 실시간 갭 차트, 시장 분위기
  2. 🎯 분석센터 — 전략 분석기, 갭 모니터링, 상장 히스토리, 시나리오 예측, VC/MM
  3. 📖 학습가이드 — 따리란?, 전략별 가이드, 시스템 작동방식, FAQ
"""

from __future__ import annotations


def render_ddari_tab() -> None:
    """따리분석 탭 렌더링 (app.py에서 호출)."""
    import streamlit as st

    from ui.ddari_common import render_html

    # 탭 옵션
    TAB_OPTIONS = ["📊 대시보드", "🎯 분석센터", "📖 학습가이드"]

    # 세션 상태 초기화
    if "ddari_active_tab" not in st.session_state:
        st.session_state.ddari_active_tab = TAB_OPTIONS[0]

    # 라디오 버튼 스타일 CSS (탭처럼 보이게)
    render_html('''
    <style>
    /* 라디오 버튼을 탭처럼 스타일링 */
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        flex: 0 1 auto !important;
    }
    .ddari-tab-selector .stRadio > div {
        flex-direction: row !important;
        justify-content: center !important;
        gap: 0.5rem !important;
    }
    .ddari-tab-selector .stRadio > div > label {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important;
        border: 1px solid #334155 !important;
        border-radius: 8px !important;
        padding: 0.5rem 1rem !important;
        font-size: 1rem !important;
        font-weight: 600 !important;
        color: #94a3b8 !important;
        cursor: pointer !important;
        transition: all 0.2s ease !important;
    }
    .ddari-tab-selector .stRadio > div > label:hover {
        border-color: #3b82f6 !important;
        color: #e2e8f0 !important;
    }
    .ddari-tab-selector .stRadio > div > label[data-checked="true"],
    .ddari-tab-selector .stRadio > div > label:has(input:checked) {
        background: linear-gradient(135deg, #1e40af 0%, #1d4ed8 100%) !important;
        border-color: #3b82f6 !important;
        color: #ffffff !important;
    }
    /* 라디오 버튼 원형 숨기기 */
    .ddari-tab-selector .stRadio > div > label > div:first-child {
        display: none !important;
    }
    </style>
    ''')

    # 탭 선택 (라디오 버튼)
    with st.container():
        render_html('<div class="ddari-tab-selector">')
        selected_tab = st.radio(
            "탭 선택",
            TAB_OPTIONS,
            index=TAB_OPTIONS.index(st.session_state.ddari_active_tab),
            horizontal=True,
            label_visibility="collapsed",
            key="ddari_tab_radio"
        )
        render_html('</div>')

    # 탭 변경 시 세션 상태 업데이트
    if selected_tab != st.session_state.ddari_active_tab:
        st.session_state.ddari_active_tab = selected_tab

    st.markdown("---")

    # === Lazy Loading: 선택된 탭만 렌더링 ===
    if selected_tab == "📊 대시보드":
        from ui.ddari_live import render_live_tab
        
        # 탭 설명 + 우측 hover 가이드
        render_html(
            '''<div style="position:relative;margin:0 0 0.5rem 0;padding:0;">
                <div style="background:linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    border:1px solid #3b82f6;border-radius:8px;padding:0.5rem 0.75rem;">
                    <div style="font-size:0.9rem;color:#60a5fa;font-weight:600;">📊 대시보드</div>
                    <div style="font-size:0.8rem;color:#9ca3af;margin-top:0.25rem;">
                        실시간 GO/NO-GO 현황, 프리미엄 차트, 시장 분위기를 한눈에 확인하세요.
                    </div>
                </div>
                <!-- 우측 hover 가이드 -->
                <div class="hover-guide" style="position:absolute;top:0;right:0;z-index:100;">
                    <div class="hover-trigger" style="background:#3b82f6;color:#fff;padding:4px 8px;border-radius:6px;font-size:0.75rem;cursor:pointer;">💡 사용법</div>
                    <div class="hover-content" style="display:none;position:absolute;right:0;top:100%;margin-top:4px;background:#1a1a2e;border:1px solid #3b82f6;border-radius:8px;padding:12px;width:280px;font-size:0.8rem;color:#d1d5db;line-height:1.6;box-shadow:0 4px 12px rgba(0,0,0,0.5);">
                        <div style="margin-bottom:6px;"><b style="color:#4ade80;">🟢 GO 카드</b>: 진입 검토 가능. 스코어↑ = 유리</div>
                        <div style="margin-bottom:6px;"><b style="color:#f87171;">🔴 NO-GO</b>: 조건 불충족. 진입 회피</div>
                        <div style="margin-bottom:6px;"><b style="color:#60a5fa;">📈 프리미엄</b>: 김치프리미엄 추이</div>
                        <div style="margin-bottom:6px;"><b style="color:#a78bfa;">📊 현선갭</b>: 헷징 비용 판단</div>
                        <div><b style="color:#fbbf24;">🔍 빠른 분석</b>: 심볼별 즉시 조회</div>
                    </div>
                </div>
            </div>
            <style>
            .hover-guide:hover .hover-content { display:block !important; }
            .hover-trigger:hover { background:#2563eb !important; }
            </style>'''
        )
        render_live_tab()

    elif selected_tab == "🎯 분석센터":
        from ui.ddari_analysis_center import render_analysis_center_tab
        
        # 탭 설명
        render_html(
            '''<div style="background:linear-gradient(135deg, #1a2e1a 0%, #163e16 100%);
                border:1px solid #4ade80;border-radius:8px;padding:0.5rem 0.75rem;margin-bottom:0.5rem;">
                <div style="font-size:0.9rem;color:#4ade80;font-weight:600;">🎯 분석센터</div>
                <div style="font-size:0.8rem;color:#9ca3af;margin-top:0.25rem;">
                    전략 분석기, 갭 모니터링, 상장 히스토리, 시나리오 예측, VC/MM 정보를 통합 제공합니다.
                </div>
            </div>'''
        )
        render_analysis_center_tab()

    elif selected_tab == "📖 학습가이드":
        from ui.ddari_learning_guide import render_learning_guide_tab
        
        # 탭 설명
        render_html(
            '''<div style="background:linear-gradient(135deg, #2e1a2e 0%, #3e163e 100%);
                border:1px solid #a78bfa;border-radius:8px;padding:0.5rem 0.75rem;margin-bottom:0.5rem;">
                <div style="font-size:0.9rem;color:#a78bfa;font-weight:600;">📖 학습가이드</div>
                <div style="font-size:0.8rem;color:#9ca3af;margin-top:0.25rem;">
                    따리 트레이딩의 기초부터 고급 전략까지, 시스템 사용법과 FAQ를 확인하세요.
                </div>
            </div>'''
        )
        render_learning_guide_tab()
