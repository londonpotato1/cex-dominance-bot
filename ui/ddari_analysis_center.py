"""분석센터 탭 (전략 분석기 + 인텔리전스 통합).

섹션 순서:
  1. 전략 분석기 (GO/NO-GO 분석)
  2. 갭 모니터링
  3. 상장 히스토리
  4. 시나리오 예측
  5. VC/MM 정보
"""

from __future__ import annotations


def render_analysis_center_tab() -> None:
    """분석센터 탭 렌더링."""
    import streamlit as st
    
    from ui.ddari_strategy import render_strategy_analysis_section, render_gap_monitor_section
    from ui.ddari_intel import (
        render_intel_tab,
        _render_go_nogo_section,
        _render_listing_history_card,
        _render_scenario_section,
        _render_vc_mm_section,
        _render_tokenomics_section,
        _render_hot_wallet_section,
    )
    from ui.ddari_common import (
        COLORS,
        SECTION_HEADER_STYLE,
        get_read_conn,
        fetch_listing_history_cached,
    )
    
    conn = get_read_conn()
    conn_id = id(conn)
    
    # ========================================
    # 1. 전략 분석기 섹션
    # ========================================
    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">🎯 전략 분석기</p>',
        unsafe_allow_html=True,
    )
    
    # 전략 분석기 가이드 (접이식)
    with st.expander("📖 전략 분석기 사용 가이드", expanded=False):
        st.markdown(
            '''
            <div style="background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.3);
                border-radius:12px;padding:1rem;margin-bottom:1rem;">
                <div style="font-size:1rem;font-weight:700;color:#60a5fa;margin-bottom:0.75rem;">
                    🎯 전략 분석기란?
                </div>
                <p style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">
                    <b>상장 예정 또는 신규 코인</b>의 최적 진입 전략을 자동 분석합니다.<br>
                    현선갭, 론 가능 여부, DEX 유동성, 네트워크 속도 등을 종합해서<br>
                    <b>GO/NO-GO 점수</b>와 <b>추천 전략</b>을 제시합니다.
                </p>
            </div>
            
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-bottom:1rem;">
                <div style="background:#1f2937;border-radius:8px;padding:0.75rem;">
                    <div style="font-size:0.85rem;font-weight:600;color:#4ade80;margin-bottom:0.5rem;">
                        🟢 헷지 갭익절 전략
                    </div>
                    <p style="font-size:0.75rem;color:#9ca3af;margin:0;">
                        갭 1-2% + 론 가능<br>
                        → 현물 매수 + 선물 숏 헷지<br>
                        → 갭 벌어지면 단계별 익절
                    </p>
                </div>
                <div style="background:#1f2937;border-radius:8px;padding:0.75rem;">
                    <div style="font-size:0.85rem;font-weight:600;color:#fbbf24;margin-bottom:0.5rem;">
                        🟡 현물 선따리
                    </div>
                    <p style="font-size:0.75rem;color:#9ca3af;margin:0;">
                        갭 낮음 + 론 불가<br>
                        → 현물만 매수 (헷지 없이)<br>
                        → 가격 변동 리스크 있음
                    </p>
                </div>
                <div style="background:#1f2937;border-radius:8px;padding:0.75rem;">
                    <div style="font-size:0.85rem;font-weight:600;color:#60a5fa;margin-bottom:0.5rem;">
                        🔵 후따리 대기
                    </div>
                    <p style="font-size:0.75rem;color:#9ca3af;margin:0;">
                        갭 높음 + DEX 유동성 충분<br>
                        → 상장 후 김프 확인<br>
                        → 유지되면 후따리 진입
                    </p>
                </div>
                <div style="background:#1f2937;border-radius:8px;padding:0.75rem;">
                    <div style="font-size:0.85rem;font-weight:600;color:#a78bfa;margin-bottom:0.5rem;">
                        🔄 역따리 전략
                    </div>
                    <p style="font-size:0.75rem;color:#9ca3af;margin:0;">
                        역프 발생 시<br>
                        → 국내 매수 + 해외 숏<br>
                        → 해외로 전송 후 청산
                    </p>
                </div>
            </div>
            ''',
            unsafe_allow_html=True
        )
    
    render_strategy_analysis_section()
    
    # ========================================
    # 2. 갭 모니터링 섹션
    # ========================================
    st.markdown("---")
    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">📊 갭 모니터링</p>',
        unsafe_allow_html=True,
    )
    
    # 갭 모니터링 가이드 (접이식)
    with st.expander("📖 갭 모니터링 가이드", expanded=False):
        st.markdown(
            '''
            <div style="background:rgba(74,222,128,0.1);border:1px solid rgba(74,222,128,0.3);
                border-radius:12px;padding:1rem;">
                <div style="font-size:0.9rem;font-weight:600;color:#4ade80;margin-bottom:0.5rem;">
                    📈 갭(프리미엄) 단계별 익절 기준
                </div>
                <div style="display:flex;gap:0.5rem;flex-wrap:wrap;font-size:0.8rem;margin-bottom:0.5rem;">
                    <span style="background:#4ade8020;color:#4ade80;padding:4px 10px;border-radius:6px;">
                        5% → 모니터링
                    </span>
                    <span style="background:#fbbf2420;color:#fbbf24;padding:4px 10px;border-radius:6px;">
                        10% → 1/3 익절
                    </span>
                    <span style="background:#f8717120;color:#f87171;padding:4px 10px;border-radius:6px;">
                        20% → 2/3 익절
                    </span>
                    <span style="background:#a78bfa20;color:#a78bfa;padding:4px 10px;border-radius:6px;">
                        30%+ → 전량 익절
                    </span>
                </div>
                <p style="font-size:0.75rem;color:#9ca3af;margin:0;">
                    💡 헷지 진입 시 갭이 벌어지면 단계별로 익절하여 수익 확정
                </p>
            </div>
            ''',
            unsafe_allow_html=True
        )
    
    render_gap_monitor_section()
    
    # ========================================
    # 3. 상장 히스토리 섹션
    # ========================================
    st.markdown("---")
    
    listing_history = fetch_listing_history_cached(conn_id, limit=10)
    if listing_history:
        labeled_count = sum(1 for r in listing_history if r.get("result_label"))
        heung_count = sum(
            1 for r in listing_history
            if r.get("result_label") in ("heung", "heung_big", "대흥따리", "흥따리")
        )
        mang_count = sum(
            1 for r in listing_history
            if r.get("result_label") in ("mang", "망따리")
        )
        
        st.markdown(
            f'<p style="{SECTION_HEADER_STYLE}">📋 상장 히스토리</p>',
            unsafe_allow_html=True,
        )
        
        # 상장 히스토리 가이드 (접이식)
        with st.expander("📖 상장 히스토리 활용법", expanded=False):
            st.markdown(
                '''
                <div style="background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);
                    border-radius:12px;padding:1rem;">
                    <p style="font-size:0.85rem;color:#d1d5db;line-height:1.6;margin:0;">
                        과거 상장 결과를 분석하여 비슷한 유형의 코인 성과를 예측합니다.<br>
                        <b>직전 상장 흥행</b> → 다음 상장도 흥행 확률 ↑<br>
                        <b>흥/망 라벨</b>을 확인하고 패턴을 파악하세요.
                    </p>
                </div>
                ''',
                unsafe_allow_html=True
            )
        
        with st.expander(f"📋 최근 {len(listing_history)}건 | 흥:{heung_count} 망:{mang_count}", expanded=False):
            for row in listing_history:
                _render_listing_history_card(row)
    
    # ========================================
    # 4. 시나리오 예측 섹션
    # ========================================
    st.markdown("---")
    
    # 시나리오 가이드 (접이식)
    with st.expander("📖 시나리오 예측 가이드", expanded=False):
        st.markdown(
            '''
            <div style="background:rgba(168,139,250,0.1);border:1px solid rgba(168,139,250,0.3);
                border-radius:12px;padding:1rem;">
                <p style="font-size:0.85rem;color:#d1d5db;line-height:1.6;margin:0;">
                    과거 데이터와 현재 조건을 기반으로 <b>흥/망 확률</b>을 예측합니다.<br>
                    • <b>공급 제약</b>: 헷지 불가, 입금 어려움 → 흥따리 확률 ↑<br>
                    • <b>공급 원활</b>: 입금 쉬움, 물량 많음 → 망따리 확률 ↑<br>
                    <span style="color:#fbbf24;">⚠️ 예측값이므로 참고용으로 활용하세요.</span>
                </p>
            </div>
            ''',
            unsafe_allow_html=True
        )
    
    _render_scenario_section(conn_id)
    
    # ========================================
    # 5. VC/MM 정보 섹션
    # ========================================
    st.markdown("---")
    
    # VC/MM 가이드 (접이식)
    with st.expander("📖 VC/MM 정보 활용법", expanded=False):
        st.markdown(
            '''
            <div style="background:rgba(96,165,250,0.1);border:1px solid rgba(96,165,250,0.3);
                border-radius:12px;padding:1rem;">
                <div style="font-size:0.9rem;font-weight:600;color:#60a5fa;margin-bottom:0.5rem;">
                    VC (벤처캐피탈) 정보
                </div>
                <p style="font-size:0.8rem;color:#d1d5db;margin-bottom:0.75rem;">
                    <b>Tier 1 VC</b> (Paradigm, a16z, Polychain 등) 투자 프로젝트는 상장 성공률이 높습니다.
                </p>
                
                <div style="font-size:0.9rem;font-weight:600;color:#f87171;margin-bottom:0.5rem;">
                    MM (마켓메이커) 리스크
                </div>
                <p style="font-size:0.8rem;color:#d1d5db;margin:0;">
                    리스크 점수가 높은 MM (예: DWF Labs)은 워시트레이딩, 펌핑덤핑 가능성이 있으니 주의하세요.
                </p>
            </div>
            ''',
            unsafe_allow_html=True
        )
    
    _render_vc_mm_section()
    
    # ========================================
    # 6. 토크노믹스 (TGE 언락) 섹션
    # ========================================
    st.markdown("---")
    
    # 토크노믹스 가이드 (접이식)
    with st.expander("📖 TGE 언락 가이드", expanded=False):
        st.markdown(
            '''
            <div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);
                border-radius:12px;padding:1rem;">
                <div style="font-size:0.9rem;font-weight:600;color:#f87171;margin-bottom:0.5rem;">
                    ⚠️ TGE 언락 리스크
                </div>
                <div style="display:flex;gap:0.5rem;flex-wrap:wrap;font-size:0.8rem;margin-bottom:0.5rem;">
                    <span style="background:#4ade8020;color:#4ade80;padding:4px 8px;border-radius:4px;">
                        5% 미만: 안전
                    </span>
                    <span style="background:#fbbf2420;color:#fbbf24;padding:4px 8px;border-radius:4px;">
                        5-10%: 주의
                    </span>
                    <span style="background:#f8717120;color:#f87171;padding:4px 8px;border-radius:4px;">
                        10%+: 위험
                    </span>
                    <span style="background:#7f1d1d;color:#fca5a5;padding:4px 8px;border-radius:4px;">
                        15%+: 매우 위험
                    </span>
                </div>
                <p style="font-size:0.75rem;color:#9ca3af;margin:0;">
                    TGE 언락률이 높으면 상장 직후 대량 덤핑 가능성이 있습니다.
                </p>
            </div>
            ''',
            unsafe_allow_html=True
        )
    
    _render_tokenomics_section()
    
    # ========================================
    # 7. 핫월렛 모니터링 섹션
    # ========================================
    st.markdown("---")
    
    # 핫월렛 가이드 (접이식)
    with st.expander("📖 핫월렛 모니터링 가이드", expanded=False):
        st.markdown(
            '''
            <div style="background:rgba(251,146,60,0.1);border:1px solid rgba(251,146,60,0.3);
                border-radius:12px;padding:1rem;">
                <div style="font-size:0.9rem;font-weight:600;color:#fb923c;margin-bottom:0.5rem;">
                    🔥 핫월렛이란?
                </div>
                <p style="font-size:0.8rem;color:#d1d5db;margin-bottom:0.5rem;">
                    거래소가 즉시 출금 가능하도록 보관하는 지갑입니다.
                </p>
                <div style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">
                    • <b>핫월렛 물량 적음</b> (20억 미만) → 공급 제약 → 흥따리 확률 ↑<br>
                    • <b>핫월렛 물량 많음</b> (100억+) → 입금 경쟁 치열 → 망따리 확률 ↑<br>
                    • <b>대량 입금 감지</b> → 상장 전 물량 유입 시그널
                </div>
            </div>
            ''',
            unsafe_allow_html=True
        )
    
    _render_hot_wallet_section()
