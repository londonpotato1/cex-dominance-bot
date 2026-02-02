"""따리분석 탭 (3탭 구조로 개편).

3개 서브탭으로 구성:
  1. 📊 대시보드 — GO/NO-GO 현황, 실시간 갭 차트, 시장 분위기
  2. 🎯 분석센터 — 전략 분석기, 갭 모니터링, 상장 히스토리, 시나리오 예측, VC/MM
  3. 📖 학습가이드 — 따리란?, 전략별 가이드, 시스템 작동방식, FAQ
"""

from __future__ import annotations


def render_ddari_tab() -> None:
    """따리분석 탭 렌더링 (app.py에서 호출)."""
    import streamlit as st

    from ui.ddari_live import render_live_tab
    from ui.ddari_analysis_center import render_analysis_center_tab
    from ui.ddari_learning_guide import render_learning_guide_tab
    from ui.ddari_common import render_html

    # 탭 스타일 커스터마이징 (폰트 크게, 중앙 정렬)
    render_html('''
    <style>
    /* 탭 컨테이너 중앙 정렬 */
    div[data-testid="stTabs"] > div[role="tablist"] {
        justify-content: center !important;
        gap: 1rem !important;
    }
    /* 탭 버튼 폰트 크게 */
    div[data-testid="stTabs"] button[role="tab"] {
        font-size: 1.1rem !important;
        font-weight: 600 !important;
        padding: 0.75rem 1.5rem !important;
    }
    /* 선택된 탭 강조 */
    div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
        font-size: 1.2rem !important;
        font-weight: 700 !important;
    }
    </style>
    ''')

    # 3개 서브탭 생성
    dashboard_tab, analysis_tab, guide_tab = st.tabs([
        "📊 대시보드",
        "🎯 분석센터",
        "📖 학습가이드"
    ])

    with dashboard_tab:
        # 탭 설명
        render_html(
            '''<div style="background:linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                border:1px solid #3b82f6;border-radius:12px;padding:1rem;margin-bottom:1rem;">
                <div style="font-size:0.9rem;color:#60a5fa;font-weight:600;">📊 대시보드</div>
                <div style="font-size:0.8rem;color:#9ca3af;margin-top:0.25rem;">
                    실시간 GO/NO-GO 현황, 프리미엄 차트, 시장 분위기를 한눈에 확인하세요.
                </div>
            </div>'''
        )
        
        # 대시보드 사용법 가이드 (접이식)
        with st.expander("💡 대시보드 사용법", expanded=False):
            render_html(
                '''
                <div style="font-size:0.85rem;color:#d1d5db;line-height:1.7;">
                    <p><b>🟢 GO 카드</b>: 진입 검토 가능한 상장 건. GO 스코어가 높을수록 유리한 조건입니다.</p>
                    <p><b>🔴 NO-GO 카드</b>: 조건 불충족. 진입을 피해야 합니다.</p>
                    <p><b>📈 프리미엄 차트</b>: 시간별 김치프리미엄 추이를 확인합니다.</p>
                    <p><b>📊 현선갭 모니터</b>: 현물-선물 가격 차이. 헷징 비용 판단에 활용합니다.</p>
                    <p><b>🔍 빠른 분석</b>: 심볼 입력 후 현선갭 + DEX 유동성을 즉시 조회합니다.</p>
                </div>
                '''
            )
        
        render_live_tab()

    with analysis_tab:
        # 탭 설명
        render_html(
            '''<div style="background:linear-gradient(135deg, #1a2e1a 0%, #163e16 100%);
                border:1px solid #4ade80;border-radius:12px;padding:1rem;margin-bottom:1rem;">
                <div style="font-size:0.9rem;color:#4ade80;font-weight:600;">🎯 분석센터</div>
                <div style="font-size:0.8rem;color:#9ca3af;margin-top:0.25rem;">
                    전략 분석기, 갭 모니터링, 상장 히스토리, 시나리오 예측, VC/MM 정보를 통합 제공합니다.
                </div>
            </div>'''
        )
        render_analysis_center_tab()

    with guide_tab:
        # 탭 설명
        render_html(
            '''<div style="background:linear-gradient(135deg, #2e1a2e 0%, #3e163e 100%);
                border:1px solid #a78bfa;border-radius:12px;padding:1rem;margin-bottom:1rem;">
                <div style="font-size:0.9rem;color:#a78bfa;font-weight:600;">📖 학습가이드</div>
                <div style="font-size:0.8rem;color:#9ca3af;margin-top:0.25rem;">
                    따리 트레이딩의 기초부터 고급 전략까지, 시스템 사용법과 FAQ를 확인하세요.
                </div>
            </div>'''
        )
        render_learning_guide_tab()
