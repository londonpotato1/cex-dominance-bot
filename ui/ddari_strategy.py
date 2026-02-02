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
    
    # session_state 초기화 (새로고침 시 유지)
    if 'strategy_symbol' not in st.session_state:
        st.session_state.strategy_symbol = ""
    if 'strategy_result' not in st.session_state:
        st.session_state.strategy_result = None
    
    # 전략 분석기 메인 (가이드는 ddari_analysis_center.py에서 통합 제공)
    render_html(
        '''<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:1rem;margin-bottom:0.75rem;"><div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.5rem;">🎯 전략 분석기</div><p style="font-size:0.75rem;color:#9ca3af;margin:0;">상장 예정 코인 심볼을 입력하고 분석 버튼을 누르세요. GO Score와 추천 전략을 확인할 수 있습니다.</p></div>'''
    )
    
    # 심볼 입력 (session_state에서 유지)
    col1, col2 = st.columns([3, 1])
    with col1:
        symbol = st.text_input(
            "심볼 입력",
            value=st.session_state.strategy_symbol,
            placeholder="예: BTC, ETH, NEWCOIN",
            label_visibility="collapsed",
            key="strategy_input"
        )
    with col2:
        analyze_btn = st.button("🔍 분석", use_container_width=True)
    
    # 분석 실행
    if analyze_btn and symbol:
        st.session_state.strategy_symbol = symbol.upper()
        with st.spinner("분석 중..."):
            result = _run_strategy_analysis(symbol.upper())
            if result:
                st.session_state.strategy_result = result
    
    # 저장된 결과 표시 (새로고침 후에도 유지)
    if st.session_state.strategy_result:
        _render_strategy_result(st.session_state.strategy_result)


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
    circ_supply = getattr(rec, 'circulating_supply', None)
    total_supply = getattr(rec, 'total_supply', None)
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
    
    # 수량 포맷 (토큰 개수)
    def format_amount(val):
        if not val:
            return "N/A"
        if val >= 1e12:
            return f"{val/1e12:.2f}T"
        elif val >= 1e9:
            return f"{val/1e9:.2f}B"
        elif val >= 1e6:
            return f"{val/1e6:.2f}M"
        elif val >= 1e3:
            return f"{val/1e3:.0f}K"
        else:
            return f"{val:.0f}"
    
    mc_str = format_usd(market_cap)
    fdv_str = format_usd(fdv)
    vol_str = format_usd(volume_24h)
    
    # 유통량: 실제 수량 + % (예: "2.2B / 11B (20.0%)")
    if circ_supply and total_supply:
        circ_str = f"{format_amount(circ_supply)} / {format_amount(total_supply)}"
        if circ_pct:
            circ_str += f" ({circ_pct:.1f}%)"
    elif circ_pct:
        circ_str = f"{circ_pct:.1f}%"
    else:
        circ_str = "N/A"
    
    chain_str = " · ".join([p.upper()[:5] for p in platforms[:4]]) if platforms else "N/A"
    
    # 헤더 (심볼 + 스코어)
    render_html(
        f'''<div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px 16px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;">
            <div style="display:flex;align-items:center;gap:12px;">
                <span style="font-size:1.1rem;font-weight:600;color:#fff;">{rec.symbol}</span>
                <span style="color:#8b949e;font-size:0.9rem;">{rec.name if rec.name else ''}</span>
                {prediction_html}
            </div>
            <div style="background:{score_color}20;color:{score_color};padding:6px 16px;border-radius:6px;font-weight:700;font-size:1.1rem;">{rec.go_score}점</div>
        </div>'''
    )
    
    # 실시간 시장 데이터 (hotwallet 스타일)
    render_html(
        f'''<div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:16px;margin-bottom:8px;">
            <div style="font-size:0.85rem;color:#8b949e;margin-bottom:12px;">📊 실시간 시장 데이터</div>
            <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:16px;">
                <div style="text-align:center;padding:12px;background:#0d1117;border-radius:6px;border:1px solid #2d3748;">
                    <div style="font-size:0.75rem;color:#8b949e;margin-bottom:6px;">현재가</div>
                    <div style="font-size:1.3rem;font-weight:700;color:#fff;">{price_str}</div>
                    {f'<div style="font-size:0.8rem;color:{change_color};margin-top:4px;">{price_change:+.2f}%</div>' if price_change else ''}
                </div>
                <div style="text-align:center;padding:12px;background:#0d1117;border-radius:6px;border:1px solid #2d3748;">
                    <div style="font-size:0.75rem;color:#8b949e;margin-bottom:6px;">시가총액 (MC)</div>
                    <div style="font-size:1.3rem;font-weight:700;color:#fff;">{mc_str}</div>
                </div>
                <div style="text-align:center;padding:12px;background:#0d1117;border-radius:6px;border:1px solid #2d3748;">
                    <div style="font-size:0.75rem;color:#8b949e;margin-bottom:6px;">완전희석가치 (FDV)</div>
                    <div style="font-size:1.3rem;font-weight:700;color:#fff;">{fdv_str}</div>
                </div>
                <div style="text-align:center;padding:12px;background:#0d1117;border-radius:6px;border:1px solid #2d3748;">
                    <div style="font-size:0.75rem;color:#8b949e;margin-bottom:6px;">24시간 거래량</div>
                    <div style="font-size:1.3rem;font-weight:700;color:#fff;">{vol_str}</div>
                </div>
            </div>
        </div>'''
    )
    
    # 추가 정보 (유통량, 체인, DEX)
    render_html(
        f'''<div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:8px;margin-bottom:8px;">
            <div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px;text-align:center;">
                <div style="font-size:0.75rem;color:#8b949e;margin-bottom:4px;">유통량</div>
                <div style="font-size:1.1rem;font-weight:600;color:#f0883e;">{circ_str}</div>
            </div>
            <div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px;text-align:center;">
                <div style="font-size:0.75rem;color:#8b949e;margin-bottom:4px;">체인</div>
                <div style="font-size:0.95rem;font-weight:600;color:#3fb950;">{chain_str}</div>
            </div>
            <div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px;text-align:center;">
                <div style="font-size:0.75rem;color:#8b949e;margin-bottom:4px;">DEX 유동성</div>
                <div style="font-size:1.1rem;font-weight:600;color:#58a6ff;">{format_usd(rec.dex_liquidity_usd) if rec.dex_liquidity_usd else "없음"}</div>
            </div>
        </div>'''
    )
    
    # === 2. 거래소별 마켓 + 입출금 상태 + 핫월렛 ===
    exchange_markets = getattr(rec, 'exchange_markets', []) or []
    if exchange_markets:
        rows_html = ""
        for em in exchange_markets:
            spot_icon = "🟢" if em.has_spot else "🔴"
            futures_icon = "🟢" if em.has_futures else "🔴"
            dep_icon = "🟢" if getattr(em, 'deposit_enabled', False) else "⚪"
            wd_icon = "🟢" if getattr(em, 'withdraw_enabled', False) else "⚪"
            networks = getattr(em, 'networks', []) or []
            net_str = ", ".join(networks[:3]) if networks else "-"
            
            # 핫월렛 잔고 표시
            hw_usd = getattr(em, 'hot_wallet_usd', None)
            hw_count = getattr(em, 'hot_wallet_count', 0)
            if hw_usd and hw_usd > 0:
                if hw_usd >= 1e9:
                    hw_str = f"${hw_usd/1e9:.1f}B"
                elif hw_usd >= 1e6:
                    hw_str = f"${hw_usd/1e6:.1f}M"
                elif hw_usd >= 1e3:
                    hw_str = f"${hw_usd/1e3:.0f}K"
                else:
                    hw_str = f"${hw_usd:.0f}"
                hw_color = "#3fb950" if hw_usd >= 1e6 else "#f0883e" if hw_usd >= 100000 else "#8b949e"
            else:
                hw_str = "-"
                hw_color = "#4a5568"
            
            rows_html += f'''<tr style="border-bottom:1px solid #2d3748;">
                <td style="padding:8px 12px;color:#fff;font-weight:500;">{em.exchange.upper()}</td>
                <td style="padding:8px;text-align:center;">{spot_icon}</td>
                <td style="padding:8px;text-align:center;">{futures_icon}</td>
                <td style="padding:8px;text-align:center;">{dep_icon}</td>
                <td style="padding:8px;text-align:center;">{wd_icon}</td>
                <td style="padding:8px;text-align:right;color:{hw_color};font-weight:500;">{hw_str}</td>
                <td style="padding:8px;color:#8b949e;font-size:0.85rem;">{net_str}</td>
            </tr>'''
        
        render_html(
            f'''<div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px;margin-bottom:8px;">
            <div style="font-size:0.85rem;color:#8b949e;margin-bottom:8px;">🏦 거래소 현황 <span style="color:#4a5568;font-size:0.75rem;">(현물/선물/입금/출금/핫월렛)</span></div>
            <table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
            <tr style="color:#8b949e;background:#0d1117;">
                <th style="text-align:left;padding:8px 12px;">거래소</th>
                <th style="padding:8px;text-align:center;">현물</th>
                <th style="padding:8px;text-align:center;">선물</th>
                <th style="padding:8px;text-align:center;">입금</th>
                <th style="padding:8px;text-align:center;">출금</th>
                <th style="padding:8px;text-align:right;">핫월렛</th>
                <th style="padding:8px;text-align:left;">네트워크</th>
            </tr>
            {rows_html}
            </table>
            </div>'''
        )
    
    # === 3. 전략 추천 ===
    render_html(
        f'''<div style="background:{score_color}15;border-left:4px solid {score_color};border-radius:0 8px 8px 0;padding:12px 16px;margin-bottom:8px;">
        <div style="font-size:1rem;font-weight:600;color:#fff;margin-bottom:4px;">{rec.strategy_name}</div>
        <div style="font-size:0.9rem;color:#d1d5db;">{rec.strategy_detail}</div>
        </div>'''
    )
    
    # === 현선갭 상세 테이블 ===
    all_gaps = getattr(rec, 'all_gaps', []) or []
    loan_details = getattr(rec, 'loan_details', []) or []
    network_chain = getattr(rec, 'network_chain', None)
    network_time = rec.network_time or "확인 필요"
    similar_cases = getattr(rec, 'similar_cases', []) or []
    
    # 체인 이름
    chain_display = network_chain or (platforms[0].upper()[:10] if platforms else "미확인")
    
    # 현선갭 상세 테이블 HTML
    if all_gaps:
        gap_rows = ""
        for g in all_gaps[:6]:
            ex_name = g.exchange.split("/")[0].upper()[:8]
            gap_color = "#3fb950" if g.gap_percent < 2 else "#f0883e" if g.gap_percent < 4 else "#f85149"
            gap_sign = "+" if g.gap_percent >= 0 else ""
            spot_str = f"${g.spot_price:.4f}" if g.spot_price < 1 else f"${g.spot_price:.2f}" if g.spot_price else "N/A"
            futures_str = f"${g.futures_price:.4f}" if g.futures_price < 1 else f"${g.futures_price:.2f}" if g.futures_price else "N/A"
            reverse_badge = ' <span style="color:#a855f7;font-size:0.7rem;">역프</span>' if getattr(g, 'is_reverse', False) else ""
            
            gap_rows += f'''<tr style="border-bottom:1px solid #2d3748;">
                <td style="padding:6px 8px;color:#fff;font-weight:500;">{ex_name}{reverse_badge}</td>
                <td style="padding:6px 8px;color:#8b949e;text-align:right;">{spot_str}</td>
                <td style="padding:6px 8px;color:#8b949e;text-align:right;">{futures_str}</td>
                <td style="padding:6px 8px;color:{gap_color};text-align:right;font-weight:600;">{gap_sign}{g.gap_percent:.2f}%</td>
            </tr>'''
        
        gaps_table_html = f'''<div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px;margin-bottom:8px;">
            <div style="font-size:0.85rem;color:#8b949e;margin-bottom:8px;">📈 현선갭 상세 <span style="color:#4a5568;font-size:0.75rem;">(현물/선물/갭)</span></div>
            <table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
            <tr style="color:#6b7280;background:#0d1117;">
                <th style="text-align:left;padding:6px 8px;">거래소</th>
                <th style="padding:6px 8px;text-align:right;">현물가</th>
                <th style="padding:6px 8px;text-align:right;">선물가</th>
                <th style="padding:6px 8px;text-align:right;">갭</th>
            </tr>
            {gap_rows}
            </table>
        </div>'''
    else:
        gaps_table_html = '''<div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px;margin-bottom:8px;">
            <div style="font-size:0.85rem;color:#8b949e;margin-bottom:8px;">📈 현선갭</div>
            <div style="color:#6b7280;font-size:0.85rem;">데이터 없음 (선물 미상장)</div>
        </div>'''
    
    render_html(gaps_table_html)
    
    # 론 HTML
    if rec.loan_available and loan_details:
        loan_items = []
        for ld in loan_details:
            if ld.available:
                is_best = ld.exchange == rec.best_loan_exchange
                color = "#3fb950" if is_best else "#d1d5db"
                rate_str = f" {ld.hourly_rate:.3f}%/h" if ld.hourly_rate else ""
                loan_items.append(f'<span style="color:{color};">{ld.exchange}{rate_str}{"✅" if is_best else ""}</span>')
        loans_html = " · ".join(loan_items) if loan_items else "없음"
    else:
        loans_html = '<span style="color:#f85149;">없음</span>'
    
    # 유사 케이스 HTML
    if similar_cases:
        label_map = {'heung': '🔥', 'heung_big': '🔥🔥', '흥따리': '🔥', '대흥따리': '🔥🔥', 'mang': '💀', '망따리': '💀', 'neutral': '😐', '보통': '😐'}
        cases_items = [f'{label_map.get(c.result_label, "❓")}{c.symbol}{f" +{c.max_premium_pct:.0f}%" if c.max_premium_pct else ""}' for c in similar_cases[:3]]
        cases_html = " · ".join(cases_items)
    else:
        cases_html = "데이터 없음"
    
    # 론 + 네트워크 + 유사 케이스 (3컬럼)
    render_html(
        f'''<div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:8px;margin-bottom:8px;">
            <div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px;">
                <div style="font-size:0.75rem;color:#8b949e;margin-bottom:6px;">💰 론 가능</div>
                <div style="font-size:0.9rem;">{loans_html}</div>
            </div>
            <div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px;">
                <div style="font-size:0.75rem;color:#8b949e;margin-bottom:6px;">⚡ 네트워크</div>
                <div style="font-size:0.9rem;"><span style="color:#58a6ff;">{chain_display}</span> <span style="color:#6b7280;">({network_time})</span></div>
            </div>
            <div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px;">
                <div style="font-size:0.75rem;color:#8b949e;margin-bottom:6px;">📊 유사 케이스</div>
                <div style="font-size:0.9rem;color:#d1d5db;">{cases_html}</div>
            </div>
        </div>'''
    )
    
    # === 액션 플랜 ===
    if rec.actions:
        actions_html = "".join([f'<div style="padding:4px 0;color:#d1d5db;font-size:0.9rem;">{action}</div>' for action in rec.actions[:5]])
        render_html(
            f'''<div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px;margin-bottom:8px;">
            <div style="font-size:0.85rem;color:#8b949e;margin-bottom:8px;">📋 액션 플랜</div>{actions_html}
            </div>'''
        )
    
    # === 경고 ===
    if rec.warnings:
        warnings_html = "".join([f'<div style="padding:4px 0;color:#f0883e;font-size:0.85rem;">{w}</div>' for w in rec.warnings[:3]])
        render_html(f'''<div style="background:#2d1b0e;border:1px solid #9e6a03;border-radius:8px;padding:12px;">{warnings_html}</div>''')


def render_gap_monitor_section():
    """갭 모니터링 섹션 렌더링 (가이드는 ddari_analysis_center.py에서 통합 제공)"""
    import streamlit as st
    
    # 활성 모니터링 상태 표시
    render_html('''<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:1rem;"><div style="color:#6b7280;font-size:0.85rem;text-align:center;padding:0.75rem;background:#1f2937;border-radius:8px;">🔄 활성 모니터링 없음<br><span style="font-size:0.75rem;color:#4b5563;">상장 공지 감지 시 자동 시작됩니다</span></div></div>''')
