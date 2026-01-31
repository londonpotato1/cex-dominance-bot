"""상장 전략 분석 UI 컴포넌트.

빠른 전략 분석 & 갭 모니터링 UI.
ddari_live.py에서 import하여 사용.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def render_strategy_analysis_section():
    """전략 분석 섹션 렌더링 (빠른 분석용)"""
    import streamlit as st
    
    # 전략 분석기 메인 (가이드는 ddari_analysis_center.py에서 통합 제공)
    st.markdown(
        '''<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
            border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
            <div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.5rem;">
                🎯 전략 분석기
            </div>
            <p style="font-size:0.75rem;color:#9ca3af;margin:0;">
                상장 예정 코인 심볼을 입력하고 분석 버튼을 누르세요. GO Score와 추천 전략을 확인할 수 있습니다.
            </p>
        </div>''',
        unsafe_allow_html=True
    )
    
    # 심볼 입력
    col1, col2 = st.columns([3, 1])
    with col1:
        symbol = st.text_input(
            "심볼 입력",
            placeholder="예: BTC, ETH, NEWCOIN",
            label_visibility="collapsed"
        )
    with col2:
        analyze_btn = st.button("🔍 분석", use_container_width=True)
    
    if analyze_btn and symbol:
        with st.spinner("분석 중..."):
            result = _run_strategy_analysis(symbol.upper())
            if result:
                _render_strategy_result(result)


def _run_strategy_analysis(symbol: str) -> Optional[dict]:
    """전략 분석 실행"""
    try:
        from collectors.listing_strategy import analyze_listing
        
        # asyncio 이벤트 루프 처리
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, 
                        analyze_listing(symbol)
                    ).result(timeout=30)
            else:
                result = loop.run_until_complete(analyze_listing(symbol))
        except RuntimeError:
            result = asyncio.run(analyze_listing(symbol))
        
        return result
    except Exception as e:
        logger.error(f"전략 분석 에러: {e}")
        return None


def _render_strategy_result(rec):
    """전략 분석 결과 렌더링"""
    import streamlit as st
    
    # GO Score 색상
    if rec.go_score >= 70:
        score_color = "#4ade80"
        score_emoji = "🟢"
    elif rec.go_score >= 50:
        score_color = "#fbbf24"
        score_emoji = "🟡"
    else:
        score_color = "#f87171"
        score_emoji = "🔴"
    
    # 메인 카드
    st.markdown(
        f'''<div style="background:linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border:2px solid {score_color}40;border-radius:16px;padding:1.5rem;margin:1rem 0;">
            
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
                <div style="font-size:1.3rem;font-weight:700;color:#fff;">
                    📊 {rec.symbol}
                </div>
                <div style="background:{score_color}22;color:{score_color};padding:8px 16px;
                    border-radius:20px;font-weight:700;font-size:1.1rem;">
                    {score_emoji} {rec.go_score}/100
                </div>
            </div>
            
            <div style="background:{score_color}15;border-left:4px solid {score_color};
                padding:1rem;border-radius:0 12px 12px 0;margin-bottom:1rem;">
                <div style="font-size:1.1rem;font-weight:600;color:#fff;margin-bottom:0.3rem;">
                    {rec.strategy_name}
                </div>
                <div style="font-size:0.9rem;color:#d1d5db;">
                    {rec.strategy_detail}
                </div>
            </div>
        </div>''',
        unsafe_allow_html=True
    )
    
    # 상세 정보 (2컬럼)
    col1, col2 = st.columns(2)
    
    with col1:
        # 론 가능 거래소
        if rec.loan_available:
            loan_html = f'''
            <div style="background:#1f2937;padding:1rem;border-radius:12px;margin-bottom:0.5rem;">
                <div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">💰 론 가능</div>
                <div style="font-size:1rem;font-weight:600;color:#4ade80;">
                    {rec.best_loan_exchange or "있음"}
                </div>
            </div>
            '''
        else:
            loan_html = '''
            <div style="background:#1f2937;padding:1rem;border-radius:12px;margin-bottom:0.5rem;">
                <div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">💰 론 가능</div>
                <div style="font-size:1rem;font-weight:600;color:#f87171;">없음</div>
            </div>
            '''
        st.markdown(loan_html, unsafe_allow_html=True)
        
        # DEX 유동성
        if rec.dex_liquidity_usd:
            dex_str = f"${rec.dex_liquidity_usd/1000:.0f}K"
            dex_color = "#4ade80" if rec.dex_liquidity_usd < 500000 else "#fbbf24"
        else:
            dex_str = "N/A"
            dex_color = "#6b7280"
        
        st.markdown(
            f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;">
                <div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">💧 DEX 유동성</div>
                <div style="font-size:1rem;font-weight:600;color:{dex_color};">{dex_str}</div>
            </div>''',
            unsafe_allow_html=True
        )
    
    with col2:
        # 현선갭
        if rec.best_gap:
            gap = rec.best_gap.gap_percent
            gap_color = "#4ade80" if gap < 2 else "#fbbf24" if gap < 4 else "#f87171"
            gap_str = f"{gap:.1f}%"
        else:
            gap_str = "1.5% (기본값)"
            gap_color = "#4ade80"
        
        st.markdown(
            f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-bottom:0.5rem;">
                <div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">📈 현선갭</div>
                <div style="font-size:1rem;font-weight:600;color:{gap_color};">{gap_str}</div>
            </div>''',
            unsafe_allow_html=True
        )
        
        # 네트워크
        st.markdown(
            f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;">
                <div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">⚡ 네트워크</div>
                <div style="font-size:1rem;font-weight:600;color:#60a5fa;">
                    {rec.network_speed or "unknown"} ({rec.network_time or "N/A"})
                </div>
            </div>''',
            unsafe_allow_html=True
        )
    
    # 액션 플랜
    if rec.actions:
        actions_html = "\n".join([
            f'<div style="padding:0.3rem 0;color:#d1d5db;font-size:0.9rem;">{action}</div>'
            for action in rec.actions
        ])
        
        st.markdown(
            f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-top:0.5rem;">
                <div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.5rem;">
                    📋 액션 플랜
                </div>
                {actions_html}
            </div>''',
            unsafe_allow_html=True
        )
    
    # 경고
    if rec.warnings:
        warnings_html = "\n".join([
            f'<div style="padding:0.3rem 0;color:#fbbf24;font-size:0.85rem;">{w}</div>'
            for w in rec.warnings
        ])
        
        st.markdown(
            f'''<div style="background:#7f1d1d33;border:1px solid #991b1b;
                padding:1rem;border-radius:12px;margin-top:0.5rem;">
                {warnings_html}
            </div>''',
            unsafe_allow_html=True
        )


def render_gap_monitor_section():
    """갭 모니터링 섹션 렌더링 (가이드는 ddari_analysis_center.py에서 통합 제공)"""
    import streamlit as st
    
    # 활성 모니터링 상태 표시
    html = '''<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:1rem;"><div style="color:#6b7280;font-size:0.85rem;text-align:center;padding:0.75rem;background:#1f2937;border-radius:8px;">🔄 활성 모니터링 없음<br><span style="font-size:0.75rem;color:#4b5563;">상장 공지 감지 시 자동 시작됩니다</span></div></div>'''
    if hasattr(st, 'html'):
        st.html(html)
    else:
        st.markdown(html, unsafe_allow_html=True)
