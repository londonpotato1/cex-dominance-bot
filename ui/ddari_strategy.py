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
    
    # 기본 데이터 카드 (컴팩트)
    render_html(
        f'''<div style="background:#0d1117;border:1px solid #30363d;border-radius:12px;padding:1rem;margin:0.5rem 0;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;">
            <div style="display:flex;align-items:center;gap:0.5rem;">
                <span style="font-size:1.2rem;font-weight:700;color:#fff;">📊 {rec.symbol}{name_display}</span>
                {prediction_html}
            </div>
            <div style="background:{score_color}22;color:{score_color};padding:4px 12px;border-radius:16px;font-weight:700;font-size:0.95rem;">{score_emoji} {rec.go_score}/100</div>
        </div>
        
        <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:0.5rem;margin-bottom:0.5rem;">
            <div style="background:#161b22;border-radius:8px;padding:0.5rem;text-align:center;">
                <div style="font-size:0.65rem;color:#8b949e;">현재가</div>
                <div style="font-size:0.95rem;font-weight:600;color:#fff;">{price_str}</div>
                {f'<div style="font-size:0.7rem;color:{change_color};">{price_change:+.2f}%</div>' if price_change else ''}
            </div>
            <div style="background:#161b22;border-radius:8px;padding:0.5rem;text-align:center;">
                <div style="font-size:0.65rem;color:#8b949e;">시총 (MC)</div>
                <div style="font-size:0.95rem;font-weight:600;color:#58a6ff;">{mc_str}</div>
            </div>
            <div style="background:#161b22;border-radius:8px;padding:0.5rem;text-align:center;">
                <div style="font-size:0.65rem;color:#8b949e;">FDV</div>
                <div style="font-size:0.95rem;font-weight:600;color:#a371f7;">{fdv_str}</div>
            </div>
            <div style="background:#161b22;border-radius:8px;padding:0.5rem;text-align:center;">
                <div style="font-size:0.65rem;color:#8b949e;">24h 거래량</div>
                <div style="font-size:0.95rem;font-weight:600;color:#3fb950;">{vol_str}</div>
            </div>
        </div>
        
        <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:0.5rem;">
            <div style="background:#161b22;border-radius:8px;padding:0.5rem;text-align:center;">
                <div style="font-size:0.65rem;color:#8b949e;">유통량</div>
                <div style="font-size:0.9rem;font-weight:600;color:#f0883e;">{circ_str}</div>
            </div>
            <div style="background:#161b22;border-radius:8px;padding:0.5rem;text-align:center;">
                <div style="font-size:0.65rem;color:#8b949e;">체인</div>
                <div style="font-size:0.8rem;font-weight:600;color:#3fb950;">{chain_str}</div>
            </div>
            <div style="background:#161b22;border-radius:8px;padding:0.5rem;text-align:center;">
                <div style="font-size:0.65rem;color:#8b949e;">DEX 유동성</div>
                <div style="font-size:0.9rem;font-weight:600;color:#58a6ff;">{format_usd(rec.dex_liquidity_usd) if rec.dex_liquidity_usd else "없음"}</div>
            </div>
        </div>
        </div>'''
    )
    
    # === 2. 거래소별 마켓 + 입출금 상태 (컴팩트 테이블) ===
    exchange_markets = getattr(rec, 'exchange_markets', []) or []
    if exchange_markets:
        rows_html = ""
        for em in exchange_markets:
            spot_icon = "🟢" if em.has_spot else "🔴"
            futures_icon = "🟢" if em.has_futures else "🔴"
            
            # 입출금 상태
            dep_icon = "🟢" if getattr(em, 'deposit_enabled', False) else "⚪"
            wd_icon = "🟢" if getattr(em, 'withdraw_enabled', False) else "⚪"
            
            # 네트워크 정보
            networks = getattr(em, 'networks', []) or []
            net_str = ", ".join(networks[:3]) if networks else "-"
            if len(networks) > 3:
                net_str += f" +{len(networks)-3}"
            
            rows_html += f'''<tr style="border-bottom:1px solid #21262d;">
                <td style="padding:0.4rem 0.5rem;color:#fff;font-weight:500;">{em.exchange.upper()}</td>
                <td style="padding:0.4rem;text-align:center;">{spot_icon}</td>
                <td style="padding:0.4rem;text-align:center;">{futures_icon}</td>
                <td style="padding:0.4rem;text-align:center;">{dep_icon}</td>
                <td style="padding:0.4rem;text-align:center;">{wd_icon}</td>
                <td style="padding:0.4rem;color:#8b949e;font-size:0.75rem;">{net_str}</td>
            </tr>'''
        
        render_html(
            f'''<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:0.75rem;margin-bottom:0.5rem;">
            <div style="font-size:0.8rem;font-weight:600;color:#fff;margin-bottom:0.5rem;">🏦 거래소 현황</div>
            <table style="width:100%;border-collapse:collapse;font-size:0.75rem;">
            <tr style="color:#8b949e;border-bottom:1px solid #30363d;">
                <th style="text-align:left;padding:0.3rem 0.5rem;">거래소</th>
                <th style="padding:0.3rem;text-align:center;">현물</th>
                <th style="padding:0.3rem;text-align:center;">선물</th>
                <th style="padding:0.3rem;text-align:center;">입금</th>
                <th style="padding:0.3rem;text-align:center;">출금</th>
                <th style="padding:0.3rem;text-align:left;">네트워크</th>
            </tr>
            {rows_html}
            </table>
            </div>'''
        )
    
    # === 3. 전략 추천 카드 (컴팩트) ===
    render_html(
        f'''<div style="background:{score_color}10;border:1px solid {score_color}40;border-radius:8px;padding:0.75rem;margin-bottom:0.5rem;">
        <div style="font-size:0.95rem;font-weight:600;color:#fff;margin-bottom:0.2rem;">{rec.strategy_name}</div>
        <div style="font-size:0.8rem;color:#d1d5db;">{rec.strategy_detail}</div>
        </div>'''
    )
    
    # === 현선갭 + 론 (한 줄에 컴팩트하게) ===
    all_gaps = getattr(rec, 'all_gaps', []) or []
    loan_details = getattr(rec, 'loan_details', []) or []
    
    # 현선갭 행
    if all_gaps:
        gaps_items = []
        for gap in all_gaps[:4]:
            gap_color = "#3fb950" if gap.gap_percent < 2 else "#f0883e" if gap.gap_percent < 4 else "#f85149"
            gaps_items.append(f'<span style="color:{gap_color};margin-right:0.75rem;">{gap.exchange.split("/")[0][:3].upper()} {gap.gap_percent:.1f}%</span>')
        gaps_html = "".join(gaps_items)
        
        render_html(
            f'''<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:0.6rem 0.75rem;margin-bottom:0.4rem;">
            <span style="color:#8b949e;font-size:0.75rem;margin-right:0.5rem;">📈 현선갭</span>{gaps_html}
            </div>'''
        )
    
    # 론 가능 행
    if rec.loan_available and loan_details:
        loan_items = []
        for ld in loan_details:
            if ld.available:
                rate_str = f" {ld.hourly_rate:.3f}%/h" if ld.hourly_rate else ""
                is_best = ld.exchange == rec.best_loan_exchange
                color = "#3fb950" if is_best else "#8b949e"
                best_mark = " ✅" if is_best else ""
                loan_items.append(f'<span style="color:{color};margin-right:0.75rem;">{ld.exchange}{rate_str}{best_mark}</span>')
        if loan_items:
            loans_html = "".join(loan_items)
            render_html(
                f'''<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:0.6rem 0.75rem;margin-bottom:0.4rem;">
                <span style="color:#8b949e;font-size:0.75rem;margin-right:0.5rem;">💰 론</span>{loans_html}
                </div>'''
            )
    elif not rec.loan_available:
        render_html(
            '''<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:0.6rem 0.75rem;margin-bottom:0.4rem;">
            <span style="color:#8b949e;font-size:0.75rem;margin-right:0.5rem;">💰 론</span><span style="color:#f85149;">없음</span>
            </div>'''
        )
    
    # === 네트워크 (체인명 + 시간 표시) ===
    network_chain = getattr(rec, 'network_chain', None)
    network_time = rec.network_time or "확인 필요"
    platforms = getattr(rec, 'platforms', []) or []
    
    # 체인 이름 결정 (platforms에서 가져오거나 network_chain 사용)
    chain_display = network_chain
    if not chain_display and platforms:
        chain_display = platforms[0].upper()[:10]
    if not chain_display:
        chain_display = "미확인"
    
    render_html(
        f'''<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:0.6rem 0.75rem;margin-bottom:0.4rem;">
        <span style="color:#8b949e;font-size:0.75rem;margin-right:0.5rem;">⚡ 네트워크</span>
        <span style="color:#58a6ff;font-weight:500;">{chain_display}</span>
        <span style="color:#8b949e;margin-left:0.5rem;">({network_time})</span>
        </div>'''
    )
    
    # === 유사 케이스 (있으면) ===
    similar_cases = getattr(rec, 'similar_cases', []) or []
    if similar_cases:
        cases_items = []
        for case in similar_cases[:3]:
            label_map = {
                'heung': '🔥', 'heung_big': '🔥🔥', '흥따리': '🔥', '대흥따리': '🔥🔥',
                'mang': '💀', '망따리': '💀',
                'neutral': '😐', '보통': '😐'
            }
            emoji = label_map.get(case.result_label, '❓')
            prem_str = f"+{case.max_premium_pct:.0f}%" if case.max_premium_pct else ""
            cases_items.append(f'<span style="color:#d1d5db;margin-right:0.75rem;">{emoji}{case.symbol} {prem_str}</span>')
        cases_html = "".join(cases_items)
        
        render_html(
            f'''<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:0.6rem 0.75rem;margin-bottom:0.4rem;">
            <span style="color:#8b949e;font-size:0.75rem;margin-right:0.5rem;">📊 유사</span>{cases_html}
            </div>'''
        )
    
    # === 액션 플랜 (컴팩트) ===
    if rec.actions:
        actions_html = "".join([
            f'<div style="padding:0.2rem 0;color:#d1d5db;font-size:0.8rem;">{action}</div>'
            for action in rec.actions[:5]
        ])
        
        render_html(
            f'''<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:0.75rem;margin-top:0.4rem;">
            <div style="font-size:0.8rem;font-weight:600;color:#fff;margin-bottom:0.4rem;">📋 액션 플랜</div>{actions_html}
            </div>'''
        )
    
    # === 경고 (있으면) ===
    if rec.warnings:
        warnings_html = "".join([
            f'<div style="padding:0.2rem 0;color:#f0883e;font-size:0.75rem;">{w}</div>'
            for w in rec.warnings[:3]
        ])
        
        render_html(
            f'''<div style="background:#2d1b0e;border:1px solid #9e6a03;border-radius:8px;padding:0.6rem 0.75rem;margin-top:0.4rem;">{warnings_html}</div>'''
        )


def render_gap_monitor_section():
    """갭 모니터링 섹션 렌더링 (가이드는 ddari_analysis_center.py에서 통합 제공)"""
    import streamlit as st
    
    # 활성 모니터링 상태 표시
    render_html('''<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:1rem;"><div style="color:#6b7280;font-size:0.85rem;text-align:center;padding:0.75rem;background:#1f2937;border-radius:8px;">🔄 활성 모니터링 없음<br><span style="font-size:0.75rem;color:#4b5563;">상장 공지 감지 시 자동 시작됩니다</span></div></div>''')
