"""상장 전략 분석 UI 컴포넌트.

빠른 전략 분석 & 갭 모니터링 UI.
ddari_live.py에서 import하여 사용.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ui.ddari_common import render_html

logger = logging.getLogger(__name__)


def render_strategy_analysis_section():
    """전략 분석 섹션 렌더링 (빠른 분석용)"""
    import streamlit as st
    
    # 전략 분석기 메인 (가이드는 ddari_analysis_center.py에서 통합 제공)
    render_html(
        '''<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:1rem;margin-bottom:0.75rem;"><div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.5rem;">🎯 전략 분석기</div><p style="font-size:0.75rem;color:#9ca3af;margin:0;">상장 예정 코인 심볼을 입력하고 분석 버튼을 누르세요. GO Score와 추천 전략을 확인할 수 있습니다.</p></div>'''
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
    """전략 분석 결과 렌더링 (업그레이드: 기본 데이터 → 전략 순서)"""
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
    
    # 흥/망 예측 표시
    prediction_html = ""
    if hasattr(rec, 'predicted_result') and rec.predicted_result:
        if rec.predicted_result == "heung":
            pred_color = "#4ade80"
            pred_text = "🔥 흥따리 유력"
        elif rec.predicted_result == "mang":
            pred_color = "#f87171"
            pred_text = "💀 망따리 주의"
        else:
            pred_color = "#fbbf24"
            pred_text = "😐 보통"
        prediction_html = f'<span style="background:{pred_color}22;color:{pred_color};padding:4px 12px;border-radius:12px;font-size:0.8rem;margin-left:0.5rem;">{pred_text}</span>'
    
    # === 1. 기본 데이터 (가장 위에 크게) ===
    name_display = f' ({rec.name})' if getattr(rec, 'name', None) else ''
    price = getattr(rec, 'current_price_usd', None)
    price_change = getattr(rec, 'price_change_24h_pct', None)
    market_cap = getattr(rec, 'market_cap_usd', None)
    fdv = getattr(rec, 'fdv_usd', None)
    volume_24h = getattr(rec, 'volume_24h_usd', None)
    circ_pct = getattr(rec, 'circulating_percent', None)
    platforms = getattr(rec, 'platforms', []) or []
    
    # 가격 + 등락률
    price_str = f"${price:.6f}" if price and price < 0.01 else f"${price:.4f}" if price and price < 1 else f"${price:.2f}" if price else "N/A"
    if price_change:
        change_color = "#4ade80" if price_change >= 0 else "#f87171"
        change_str = f'<span style="color:{change_color};font-size:0.9rem;margin-left:0.5rem;">{price_change:+.2f}%</span>'
    else:
        change_str = ""
    
    # 시총/FDV/거래량 포맷
    def format_usd(val):
        if not val:
            return "N/A"
        if val >= 1e9:
            return f"${val/1e9:.2f}B"
        elif val >= 1e6:
            return f"${val/1e6:.2f}M"
        elif val >= 1e3:
            return f"${val/1e3:.0f}K"
        else:
            return f"${val:.2f}"
    
    mc_str = format_usd(market_cap)
    fdv_str = format_usd(fdv)
    vol_str = format_usd(volume_24h)
    circ_str = f"{circ_pct:.1f}%" if circ_pct else "N/A"
    chain_str = " · ".join([p.upper()[:5] for p in platforms[:4]]) if platforms else "N/A"
    
    # 기본 데이터 카드 (맨 위)
    render_html(
        f'''<div style="background:linear-gradient(135deg, #0d1117 0%, #161b22 100%);border:1px solid #30363d;border-radius:16px;padding:1.5rem;margin:1rem 0;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.25rem;flex-wrap:wrap;gap:0.5rem;">
            <div style="display:flex;align-items:center;">
                <span style="font-size:1.4rem;font-weight:700;color:#fff;">📊 {rec.symbol}{name_display}</span>
                {prediction_html}
            </div>
            <div style="background:{score_color}22;color:{score_color};padding:8px 16px;border-radius:20px;font-weight:700;font-size:1.1rem;">{score_emoji} {rec.go_score}/100</div>
        </div>
        
        <div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:1rem;margin-bottom:1rem;">
            <div style="background:#21262d;border-radius:12px;padding:1rem;text-align:center;">
                <div style="font-size:0.75rem;color:#8b949e;margin-bottom:0.25rem;">현재가</div>
                <div style="font-size:1.5rem;font-weight:700;color:#fff;">{price_str}{change_str}</div>
            </div>
            <div style="background:#21262d;border-radius:12px;padding:1rem;text-align:center;">
                <div style="font-size:0.75rem;color:#8b949e;margin-bottom:0.25rem;">24h 거래량</div>
                <div style="font-size:1.3rem;font-weight:600;color:#58a6ff;">{vol_str}</div>
            </div>
        </div>
        
        <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:0.75rem;">
            <div style="background:#21262d;border-radius:8px;padding:0.75rem;text-align:center;">
                <div style="font-size:0.7rem;color:#8b949e;">시총 (MC)</div>
                <div style="font-size:1rem;font-weight:600;color:#58a6ff;">{mc_str}</div>
            </div>
            <div style="background:#21262d;border-radius:8px;padding:0.75rem;text-align:center;">
                <div style="font-size:0.7rem;color:#8b949e;">FDV</div>
                <div style="font-size:1rem;font-weight:600;color:#a371f7;">{fdv_str}</div>
            </div>
            <div style="background:#21262d;border-radius:8px;padding:0.75rem;text-align:center;">
                <div style="font-size:0.7rem;color:#8b949e;">유통량</div>
                <div style="font-size:1rem;font-weight:600;color:#f0883e;">{circ_str}</div>
            </div>
            <div style="background:#21262d;border-radius:8px;padding:0.75rem;text-align:center;">
                <div style="font-size:0.7rem;color:#8b949e;">체인</div>
                <div style="font-size:0.85rem;font-weight:600;color:#3fb950;overflow:hidden;text-overflow:ellipsis;">{chain_str}</div>
            </div>
        </div>
        </div>'''
    )
    
    # === 2. 전략 추천 카드 ===
    render_html(
        f'''<div style="background:{score_color}10;border:1px solid {score_color}40;border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="font-size:1.1rem;font-weight:600;color:#fff;margin-bottom:0.3rem;">{rec.strategy_name}</div>
        <div style="font-size:0.9rem;color:#d1d5db;">{rec.strategy_detail}</div>
        </div>'''
    )
    
    # === 거래소별 마켓 정보 ===
    exchange_markets = getattr(rec, 'exchange_markets', []) or []
    if exchange_markets:
        market_rows = []
        for em in exchange_markets:
            spot_icon = "🟢" if em.has_spot else "🔴"
            futures_icon = "🟢" if em.has_futures else "🔴"
            market_rows.append(
                f'<div style="display:flex;justify-content:space-between;padding:0.3rem 0;border-bottom:1px solid #374151;">'
                f'<span style="color:#d1d5db;font-weight:500;">{em.exchange.upper()}</span>'
                f'<span>S{spot_icon} F{futures_icon}</span>'
                f'</div>'
            )
        
        if market_rows:
            markets_html = "".join(market_rows)
            render_html(
                f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-bottom:0.5rem;">
                <div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.5rem;">🏦 거래소 마켓 (S=현물, F=선물)</div>
                {markets_html}
                </div>'''
            )
    
    # === 거래소별 현선갭 (all_gaps) ===
    all_gaps = getattr(rec, 'all_gaps', []) or []
    if all_gaps:
        gaps_rows = []
        for gap in all_gaps[:5]:  # 최대 5개
            gap_color = "#4ade80" if gap.gap_percent < 2 else "#fbbf24" if gap.gap_percent < 4 else "#f87171"
            status = "🟢" if gap.gap_percent < 2 else "🟡" if gap.gap_percent < 4 else "🔴"
            gaps_rows.append(
                f'<div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid #374151;">'
                f'<span style="color:#9ca3af;">{gap.exchange}</span>'
                f'<span style="color:{gap_color};font-weight:600;">{gap.gap_percent:.2f}% {status}</span>'
                f'</div>'
            )
        gaps_html = "".join(gaps_rows)
        
        render_html(
            f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-bottom:0.5rem;">
            <div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.75rem;">📈 거래소별 현선갭</div>
            {gaps_html}
            </div>'''
        )
    
    # 상세 정보 (2컬럼)
    col1, col2 = st.columns(2)
    
    with col1:
        # 론 가능 거래소 (상세 - 이자율 포함)
        loan_details = getattr(rec, 'loan_details', []) or []
        if rec.loan_available and loan_details:
            loan_rows = []
            for ld in loan_details:
                if ld.available:
                    rate_str = f" ({ld.hourly_rate:.4f}%/h)" if ld.hourly_rate else ""
                    is_best = ld.exchange == rec.best_loan_exchange
                    best_mark = " ✅" if is_best else ""
                    loan_rows.append(
                        f'<div style="padding:0.3rem 0;color:#d1d5db;">{ld.exchange}{rate_str}{best_mark}</div>'
                    )
            if loan_rows:
                loans_html = "".join(loan_rows)
                render_html(
                    f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-bottom:0.5rem;">
                    <div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">💰 론 가능 거래소</div>
                    {loans_html}
                    </div>'''
                )
            else:
                render_html('''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-bottom:0.5rem;"><div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">💰 론 가능</div><div style="font-size:1rem;font-weight:600;color:#f87171;">없음</div></div>''')
        elif rec.loan_available:
            exchanges = getattr(rec, 'loan_exchanges', []) or []
            ex_list = ", ".join(exchanges) if exchanges else (rec.best_loan_exchange or "있음")
            render_html(f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-bottom:0.5rem;"><div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">💰 론 가능</div><div style="font-size:1rem;font-weight:600;color:#4ade80;">{ex_list}</div></div>''')
        else:
            render_html('''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-bottom:0.5rem;"><div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">💰 론 가능</div><div style="font-size:1rem;font-weight:600;color:#f87171;">없음</div></div>''')
        
        # DEX 유동성
        if rec.dex_liquidity_usd:
            dex_str = f"${rec.dex_liquidity_usd/1000:.0f}K"
            dex_color = "#4ade80" if rec.dex_liquidity_usd < 500000 else "#fbbf24"
        else:
            dex_str = "N/A"
            dex_color = "#6b7280"
        
        render_html(
            f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;"><div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">💧 DEX 유동성</div><div style="font-size:1rem;font-weight:600;color:{dex_color};">{dex_str}</div></div>'''
        )
    
    with col2:
        # 네트워크
        speed = rec.network_speed or "unknown"
        time_str = rec.network_time or "확인 필요"
        
        speed_map = {
            "very_fast": ("🚀 매우 빠름", "#f87171", "입금 경쟁 치열"),
            "fast": ("⚡ 빠름", "#fbbf24", "경쟁 있음"),
            "medium": ("🕐 보통", "#60a5fa", "적당한 속도"),
            "slow": ("🐢 느림", "#4ade80", "유리 (경쟁↓)"),
            "very_slow": ("🦥 매우 느림", "#4ade80", "매우 유리"),
            "unknown": ("❓ 확인 필요", "#6b7280", "")
        }
        speed_label, speed_color, speed_note = speed_map.get(speed, ("❓ 확인 필요", "#6b7280", ""))
        
        time_display = f" ({time_str})" if time_str and time_str != "확인 필요" else ""
        note_display = f"<div style='font-size:0.75rem;color:#9ca3af;margin-top:0.25rem;'>{speed_note}</div>" if speed_note else ""
        
        render_html(
            f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-bottom:0.5rem;"><div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">⚡ 네트워크</div><div style="font-size:1rem;font-weight:600;color:{speed_color};">{speed_label}{time_display}</div>{note_display}</div>'''
        )
        
        # 흥/망 예측 (유사 케이스)
        similar_cases = getattr(rec, 'similar_cases', []) or []
        if similar_cases:
            cases_rows = []
            for case in similar_cases[:3]:
                label_map = {
                    'heung': ('🔥', '#4ade80'), 'heung_big': ('🔥🔥', '#4ade80'), '흥따리': ('🔥', '#4ade80'), '대흥따리': ('🔥🔥', '#4ade80'),
                    'mang': ('💀', '#f87171'), '망따리': ('💀', '#f87171'),
                    'neutral': ('😐', '#fbbf24'), '보통': ('😐', '#fbbf24')
                }
                emoji, color = label_map.get(case.result_label, ('❓', '#6b7280'))
                prem_str = f" (+{case.max_premium_pct:.0f}%)" if case.max_premium_pct else ""
                cases_rows.append(
                    f'<div style="padding:0.25rem 0;font-size:0.8rem;color:#d1d5db;">{emoji} {case.symbol}{prem_str}</div>'
                )
            cases_html = "".join(cases_rows)
            
            render_html(
                f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;">
                <div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.5rem;">📊 유사 케이스</div>
                {cases_html}
                </div>'''
            )
    
    # === 전송 분석 섹션 ===
    exchange_networks = getattr(rec, 'exchange_networks', {}) or {}
    bridge_required = getattr(rec, 'bridge_required', False)
    bridge_name = getattr(rec, 'bridge_name', None)
    best_transfer_route = getattr(rec, 'best_transfer_route', None)
    fastest_transfer_time = getattr(rec, 'fastest_transfer_time', None)
    
    if exchange_networks or bridge_required or best_transfer_route:
        transfer_content = []
        
        # 브릿지 필요 여부
        if bridge_required:
            bridge_text = f"🔗 브릿지 필요" + (f" ({bridge_name})" if bridge_name else "")
            transfer_content.append(f'<div style="color:#fbbf24;font-weight:600;margin-bottom:0.5rem;">{bridge_text}</div>')
        else:
            transfer_content.append('<div style="color:#4ade80;margin-bottom:0.5rem;">✅ 직접 전송 가능</div>')
        
        # 최적 경로
        if best_transfer_route:
            time_text = f" ({fastest_transfer_time})" if fastest_transfer_time else ""
            transfer_content.append(f'<div style="color:#d1d5db;font-size:0.85rem;">📤 {best_transfer_route}{time_text}</div>')
        
        # 거래소별 출금 네트워크
        if exchange_networks:
            transfer_content.append('<div style="margin-top:0.5rem;padding-top:0.5rem;border-top:1px solid #374151;font-size:0.8rem;">')
            for ex, nets in list(exchange_networks.items())[:3]:
                nets_str = ", ".join(nets[:4]) if nets else "없음"
                if len(nets) > 4:
                    nets_str += f" +{len(nets)-4}"
                transfer_content.append(f'<div style="color:#9ca3af;padding:0.2rem 0;">{ex}: {nets_str}</div>')
            transfer_content.append('</div>')
        
        transfer_html = "".join(transfer_content)
        render_html(
            f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-top:0.5rem;">
            <div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.5rem;">⚡ 전송 분석</div>
            {transfer_html}
            </div>'''
        )
    
    # 액션 플랜
    if rec.actions:
        actions_html = "".join([
            f'<div style="padding:0.3rem 0;color:#d1d5db;font-size:0.9rem;">{action}</div>'
            for action in rec.actions
        ])
        
        render_html(
            f'''<div style="background:#1f2937;padding:1rem;border-radius:12px;margin-top:0.5rem;"><div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.5rem;">📋 액션 플랜</div>{actions_html}</div>'''
        )
    
    # 경고
    if rec.warnings:
        warnings_html = "".join([
            f'<div style="padding:0.3rem 0;color:#fbbf24;font-size:0.85rem;">{w}</div>'
            for w in rec.warnings
        ])
        
        render_html(
            f'''<div style="background:#7f1d1d33;border:1px solid #991b1b;padding:1rem;border-radius:12px;margin-top:0.5rem;">{warnings_html}</div>'''
        )


def render_gap_monitor_section():
    """갭 모니터링 섹션 렌더링 (가이드는 ddari_analysis_center.py에서 통합 제공)"""
    import streamlit as st
    
    # 활성 모니터링 상태 표시
    render_html('''<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:1rem;"><div style="color:#6b7280;font-size:0.85rem;text-align:center;padding:0.75rem;background:#1f2937;border-radius:8px;">🔄 활성 모니터링 없음<br><span style="font-size:0.75rem;color:#4b5563;">상장 공지 감지 시 자동 시작됩니다</span></div></div>''')
