"""학습가이드 탭 (따리 기초부터 고급 전략까지).

섹션 구성 (모두 접이식):
  1. 따리란? - 기초 개념
  2. 전략별 가이드 - 선따리/후따리/역따리/헷지 갭익절
  3. 시스템 작동 방식 - Gate, 분석기, 알림 등
  4. FAQ - 자주 묻는 질문
"""

from __future__ import annotations

from ui.ddari_common import COLORS


def _html(content: str) -> None:
    """HTML 렌더링 헬퍼 (st.html 우선 사용)."""
    import streamlit as st
    if hasattr(st, 'html'):
        st.html(content)
    else:
        st.markdown(content, unsafe_allow_html=True)


def render_learning_guide_tab() -> None:
    """학습가이드 탭 렌더링."""
    import streamlit as st
    
    bg = COLORS["card_bg"]
    border = COLORS["card_border"]
    
    # ========================================
    # 1. 따리란? (기초 개념)
    # ========================================
    with st.expander("🥢 따리란? (기초 개념)", expanded=True):
        _html(f'''<div style="background:{bg};border:1px solid {border};border-radius:12px;padding:1.25rem;">
<div style="margin-bottom:1.5rem;">
<div style="font-size:1.1rem;font-weight:700;color:#fff;margin-bottom:0.75rem;">📦 따리 = 상장 보따리</div>
<p style="font-size:0.9rem;color:#d1d5db;line-height:1.7;">해외 거래소에서 코인을 매수하여 국내 거래소(업비트/빗썸)에 입금 후 매도하는 차익거래 전략입니다.<br>국내 가격이 해외보다 높을 때(김치 프리미엄) 수익이 발생합니다.</p>
</div>
<div style="background:#1f2937;border-radius:8px;padding:1rem;margin-bottom:1.5rem;">
<div style="font-size:0.9rem;font-weight:600;color:#60a5fa;margin-bottom:0.5rem;">💡 핵심 공식</div>
<div style="font-family:monospace;font-size:0.95rem;color:#4ade80;">따리 수익 = 입금액 vs 거래량의 싸움</div>
<div style="margin-top:0.75rem;font-size:0.85rem;color:#9ca3af;line-height:1.6;">• 거래량 &gt; 입금액 → 김프 형성 (흥따리) 🔥<br>• 거래량 &lt; 입금액 → 가격 하락 (망따리) 💀</div>
</div>
<div style="margin-bottom:1rem;">
<div style="font-size:1rem;font-weight:600;color:#fff;margin-bottom:0.75rem;">📖 핵심 용어</div>
<div style="display:grid;grid-template-columns:1fr 2fr;gap:0.5rem;font-size:0.85rem;">
<div style="color:#60a5fa;font-weight:600;">김프</div><div style="color:#d1d5db;">김치프리미엄 — 국내 &gt; 해외</div>
<div style="color:#f87171;font-weight:600;">역프</div><div style="color:#d1d5db;">역프리미엄 — 국내 &lt; 해외</div>
<div style="color:#4ade80;font-weight:600;">흥따리</div><div style="color:#d1d5db;">성공적인 따리 (수익 발생)</div>
<div style="color:#f87171;font-weight:600;">망따리</div><div style="color:#d1d5db;">실패한 따리 (손실 발생)</div>
<div style="color:#fbbf24;font-weight:600;">현선갭</div><div style="color:#d1d5db;">현물가격 - 선물가격 차이 (헷지 비용)</div>
<div style="color:#a78bfa;font-weight:600;">손바뀜</div><div style="color:#d1d5db;">거래량 ÷ 입금액 (높을수록 흥행)</div>
</div>
</div>
<div style="background:rgba(74,222,128,0.1);border:1px solid rgba(74,222,128,0.3);border-radius:8px;padding:1rem;">
<div style="font-size:0.9rem;font-weight:600;color:#4ade80;margin-bottom:0.5rem;">🥬 김프 발생 조건</div>
<div style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">1. 🇰🇷 국내에서 과매수 (신규상장, 큰 호재)<br>2. 🌐 해외에서 급락 (LUNA 사태 등)<br>3. 🌐 해외 특정 코인 급등으로 역프 발생</div>
</div>
</div>''')
    
    # ========================================
    # 2. 전략별 가이드
    # ========================================
    with st.expander("🎯 전략별 가이드 (선따리/후따리/역따리/헷지)", expanded=False):
        _html(f'''<div style="background:{bg};border:1px solid {border};border-radius:12px;padding:1.25rem;">
<div style="background:#1f2937;border-radius:12px;padding:1rem;margin-bottom:1rem;border-left:4px solid #4ade80;">
<div style="font-size:1rem;font-weight:700;color:#4ade80;margin-bottom:0.5rem;">📦 선따리 (Pre-Listing)</div>
<p style="font-size:0.85rem;color:#d1d5db;margin-bottom:0.75rem;">상장 <b>전</b>에 물량을 확보하여 상장 시점에 매도</p>
<div style="font-size:0.8rem;color:#9ca3af;line-height:1.7;"><b>전략:</b><br>1. 상장 예상 코인 사전 분석<br>2. 핫월렛, DEX 유동성 파악<br>3. 헷징 (현물 매수 + 선물 숏)<br>4. 국내 거래소로 입금<br>5. 상장 시점에 김프에 매도</div>
<div style="margin-top:0.75rem;display:flex;gap:0.5rem;flex-wrap:wrap;">
<span style="background:#4ade8020;color:#4ade80;padding:4px 8px;border-radius:4px;font-size:0.75rem;">장점: 헷지로 리스크 최소화</span>
<span style="background:#f8717120;color:#f87171;padding:4px 8px;border-radius:4px;font-size:0.75rem;">단점: 물량 확보 경쟁</span>
</div>
</div>
<div style="background:#1f2937;border-radius:12px;padding:1rem;margin-bottom:1rem;border-left:4px solid #60a5fa;">
<div style="font-size:1rem;font-weight:700;color:#60a5fa;margin-bottom:0.5rem;">🔄 후따리 (Post-Listing)</div>
<p style="font-size:0.85rem;color:#d1d5db;margin-bottom:0.75rem;">상장 <b>후</b> 김프가 유지될 때 추가 물량 입금</p>
<div style="font-size:0.8rem;color:#9ca3af;line-height:1.7;"><b>전략:</b><br>1. 상장 후 김프 모니터링<br>2. 김프 유지 시 추가 물량 매수<br>3. 빠른 입금 (체인 속도 고려)<br>4. 김프에 매도</div>
<div style="margin-top:0.75rem;display:flex;gap:0.5rem;flex-wrap:wrap;">
<span style="background:#60a5fa20;color:#60a5fa;padding:4px 8px;border-radius:4px;font-size:0.75rem;">장점: 상황 보고 진입</span>
<span style="background:#f8717120;color:#f87171;padding:4px 8px;border-radius:4px;font-size:0.75rem;">단점: 가격 변동 리스크</span>
</div>
<div style="margin-top:0.5rem;font-size:0.75rem;color:#fbbf24;">💡 유동성 500k 이하 + 네트워크 느림 = 후따리 유리</div>
</div>
<div style="background:#1f2937;border-radius:12px;padding:1rem;margin-bottom:1rem;border-left:4px solid #a78bfa;">
<div style="font-size:1rem;font-weight:700;color:#a78bfa;margin-bottom:0.5rem;">🔄 역따리 (Reverse Arbitrage)</div>
<p style="font-size:0.85rem;color:#d1d5db;margin-bottom:0.75rem;">역프(국내 &lt; 해외) 발생 시 반대 방향으로 차익거래</p>
<div style="font-size:0.8rem;color:#9ca3af;line-height:1.7;"><b>전략:</b><br>1. 국내(업비트/빗썸) 현물 매수<br>2. 해외 선물 숏 (가격 변동 헷지)<br>3. 국내 → 해외 전송<br>4. 해외 현물 매도 + 숏 청산</div>
<div style="margin-top:0.75rem;font-size:0.8rem;color:#4ade80;">💰 수익 = 역프% - 수수료 (역프 3% 이상에서 검토)</div>
</div>
<div style="background:#1f2937;border-radius:12px;padding:1rem;border-left:4px solid #fbbf24;">
<div style="font-size:1rem;font-weight:700;color:#fbbf24;margin-bottom:0.5rem;">🎯 헷지 갭익절 전략</div>
<p style="font-size:0.85rem;color:#d1d5db;margin-bottom:0.75rem;">현선갭이 낮을 때 헷지하고, 갭이 벌어지면 단계별 익절</p>
<div style="font-size:0.8rem;color:#9ca3af;line-height:1.7;"><b>최적 조건:</b> 현선갭 1-2% + 론 가능<br><br><b>전략:</b><br>1. 론 빌리기 (이자 낮은 거래소)<br>2. 현물 매수 + 선물 숏 헷지<br>3. 국내 입금<br>4. 갭 벌어지면 단계별 익절</div>
<div style="margin-top:0.75rem;display:flex;gap:0.5rem;flex-wrap:wrap;font-size:0.75rem;">
<span style="background:#4ade8020;color:#4ade80;padding:4px 8px;border-radius:4px;">5% → 모니터링</span>
<span style="background:#fbbf2420;color:#fbbf24;padding:4px 8px;border-radius:4px;">10% → 1/3 익절</span>
<span style="background:#f8717120;color:#f87171;padding:4px 8px;border-radius:4px;">20% → 2/3 익절</span>
<span style="background:#a78bfa20;color:#a78bfa;padding:4px 8px;border-radius:4px;">30%+ → 전량 익절</span>
</div>
</div>
</div>''')
    
    # ========================================
    # 3. GO/NO-GO 판단 기준
    # ========================================
    with st.expander("🚦 GO/NO-GO 판단 기준", expanded=False):
        _html(f'''<div style="background:{bg};border:1px solid {border};border-radius:12px;padding:1.25rem;">
<p style="font-size:0.9rem;color:#fbbf24;margin-bottom:1rem;">⚠️ 핵심: 상장 전 가격은 없다. GO/NO-GO는 <b>가격 외 요소</b>로 판단해야 한다.</p>
<div style="background:rgba(74,222,128,0.1);border:1px solid rgba(74,222,128,0.3);border-radius:12px;padding:1rem;margin-bottom:1rem;">
<div style="font-size:1rem;font-weight:700;color:#4ade80;margin-bottom:0.75rem;">🟢 GO 조건 (참여 권장)</div>
<table style="width:100%;font-size:0.8rem;color:#d1d5db;">
<tr style="border-bottom:1px solid #374151;"><td style="padding:6px 0;color:#60a5fa;width:30%;">핫월렛 물량</td><td style="padding:6px 0;">20억 미만 (적음)</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:6px 0;color:#60a5fa;">DEX 유동성</td><td style="padding:6px 0;">$500K 이하</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:6px 0;color:#60a5fa;">현선갭</td><td style="padding:6px 0;">5% 이하 (낮음)</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:6px 0;color:#60a5fa;">네트워크</td><td style="padding:6px 0;">느림 (POW, 자체메인넷)</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:6px 0;color:#60a5fa;">직전 상장</td><td style="padding:6px 0;">흥행</td></tr>
<tr><td style="padding:6px 0;color:#60a5fa;">시황</td><td style="padding:6px 0;">상승장, 거래량 활발</td></tr>
</table>
</div>
<div style="background:rgba(248,113,113,0.1);border:1px solid rgba(248,113,113,0.3);border-radius:12px;padding:1rem;">
<div style="font-size:1rem;font-weight:700;color:#f87171;margin-bottom:0.75rem;">🔴 NO-GO 조건 (패스 권장)</div>
<table style="width:100%;font-size:0.8rem;color:#d1d5db;">
<tr style="border-bottom:1px solid #374151;"><td style="padding:6px 0;color:#f87171;width:30%;">핫월렛 물량</td><td style="padding:6px 0;">무한 (바이낸스 등)</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:6px 0;color:#f87171;">DEX 유동성</td><td style="padding:6px 0;">$1M 이상</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:6px 0;color:#f87171;">현선갭</td><td style="padding:6px 0;">10% 이상 (높음)</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:6px 0;color:#f87171;">네트워크</td><td style="padding:6px 0;">빠름 (솔라나, 베이스)</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:6px 0;color:#f87171;">직전 상장</td><td style="padding:6px 0;">망따리</td></tr>
<tr><td style="padding:6px 0;color:#f87171;">시황</td><td style="padding:6px 0;">하락장, 거래량 저조</td></tr>
</table>
</div>
</div>''')
    
    # ========================================
    # 4. 시스템 작동 방식
    # ========================================
    with st.expander("🤖 시스템 작동 방식", expanded=False):
        _html(f'''<div style="background:{bg};border:1px solid {border};border-radius:12px;padding:1.25rem;">
<div style="margin-bottom:1.5rem;">
<div style="font-size:1rem;font-weight:700;color:#fff;margin-bottom:0.75rem;">📡 시스템 개요</div>
<p style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">이 봇은 한국 거래소와 글로벌 거래소의 가격 차이를 실시간으로 모니터링하고, 신규 상장 시 자동으로 분석하여 GO/NO-GO 판정을 내립니다.</p>
<div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-top:0.75rem;font-size:0.8rem;">
<span style="background:#1f2937;padding:4px 10px;border-radius:6px;color:#60a5fa;">📡 실시간 WebSocket</span>
<span style="background:#1f2937;padding:4px 10px;border-radius:6px;color:#a78bfa;">🔍 상장 자동 감지</span>
<span style="background:#1f2937;padding:4px 10px;border-radius:6px;color:#4ade80;">🚦 GO/NO-GO 판정</span>
<span style="background:#1f2937;padding:4px 10px;border-radius:6px;color:#fbbf24;">🔔 텔레그램 알림</span>
</div>
</div>
<div style="background:#1f2937;border-radius:8px;padding:1rem;margin-bottom:1rem;">
<div style="font-size:0.9rem;font-weight:600;color:#60a5fa;margin-bottom:0.5rem;">🔍 상장 감지 로직</div>
<ol style="font-size:0.8rem;color:#d1d5db;padding-left:1.2rem;line-height:1.8;margin:0;">
<li>마켓 Diff 모니터링 (30~60초마다)</li>
<li>새 심볼 감지 → 상장으로 판단</li>
<li>Gate 분석 시작 (글로벌 가격/입출금 확인)</li>
<li>GO/NO-GO 결과 → 텔레그램 즉시 전송</li>
</ol>
</div>
<div style="background:#1f2937;border-radius:8px;padding:1rem;margin-bottom:1rem;">
<div style="font-size:0.9rem;font-weight:600;color:#a78bfa;margin-bottom:0.5rem;">📊 데이터 수집</div>
<div style="font-size:0.8rem;color:#d1d5db;line-height:1.6;">• <b>업비트/빗썸</b>: WebSocket (~100-200ms)<br>• <b>바이낸스/바이빗</b>: REST API (~500ms)<br>• <b>환율</b>: API 캐시 (5분)</div>
</div>
<div style="background:#1f2937;border-radius:8px;padding:1rem;">
<div style="font-size:0.9rem;font-weight:600;color:#4ade80;margin-bottom:0.5rem;">📈 프리미엄 계산</div>
<div style="font-family:monospace;font-size:0.8rem;color:#d1d5db;line-height:1.8;">프리미엄(%) = (국내가격 - 글로벌가격×환율) / (글로벌가격×환율) × 100<br>순수익(%) = 프리미엄 - 총비용<br>총비용 = 출금수수료 + 거래수수료 + 슬리피지</div>
</div>
</div>''')
    
    # ========================================
    # 5. FAQ (자주 묻는 질문)
    # ========================================
    with st.expander("❓ FAQ (자주 묻는 질문)", expanded=False):
        _html(f'''<div style="background:{bg};border:1px solid {border};border-radius:12px;padding:1.25rem;">
<div style="margin-bottom:1.25rem;">
<div style="font-size:0.9rem;font-weight:700;color:#60a5fa;margin-bottom:0.5rem;">Q. 따리는 언제 수익이 나나요?</div>
<div style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">A. 김치프리미엄(국내 &gt; 해외)이 있을 때 수익이 납니다.<br><b>수익 = 김프 - 비용(수수료, 현선갭, 슬리피지)</b><br>보통 순수익 3% 이상일 때 진입을 검토합니다.</div>
</div>
<div style="margin-bottom:1.25rem;">
<div style="font-size:0.9rem;font-weight:700;color:#60a5fa;margin-bottom:0.5rem;">Q. 헷지란 무엇인가요?</div>
<div style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">A. 현물 매수 + 선물 숏을 동시에 잡아 가격 변동 리스크를 제거하는 것입니다.<br>가격이 오르거나 내려도 현물과 선물이 서로 상쇄되어 손익이 0이 됩니다.<br>따라서 순수하게 <b>김프 차익만</b> 남길 수 있습니다.</div>
</div>
<div style="margin-bottom:1.25rem;">
<div style="font-size:0.9rem;font-weight:700;color:#60a5fa;margin-bottom:0.5rem;">Q. 현선갭이 높으면 왜 불리한가요?</div>
<div style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">A. 현선갭 = 헷지 비용입니다.<br>예를 들어 현선갭이 5%면, 헷지만 잡아도 5% 비용이 발생합니다.<br>김프가 8%여도 순수익은 3%밖에 안 됩니다.<br><b>현선갭 1-2%가 이상적</b>이며, 4% 이상이면 리스크가 높습니다.</div>
</div>
<div style="margin-bottom:1.25rem;">
<div style="font-size:0.9rem;font-weight:700;color:#60a5fa;margin-bottom:0.5rem;">Q. 핫월렛 물량이 왜 중요한가요?</div>
<div style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">A. 핫월렛 물량 = 거래소가 즉시 출금 가능한 코인량입니다.<br><b>물량 적음</b> → 입금 어려움 → 공급 부족 → 김프 유지<br><b>물량 많음</b> → 입금 쉬움 → 공급 과잉 → 김프 하락<br>핫월렛 20억 미만이면 흥따리 확률이 높습니다.</div>
</div>
<div style="margin-bottom:1.25rem;">
<div style="font-size:0.9rem;font-weight:700;color:#60a5fa;margin-bottom:0.5rem;">Q. 선따리와 후따리 중 뭐가 더 좋나요?</div>
<div style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">A. 상황에 따라 다릅니다.<br>• <b>선따리</b>: 헷지로 리스크 최소화, 안정적 수익<br>• <b>후따리</b>: 상황 보고 진입, 높은 수익 가능성 but 리스크<br>DEX 유동성이 적고 네트워크가 느리면 선따리 유리,<br>유동성 충분하고 네트워크 빠르면 후따리 대기가 나을 수 있습니다.</div>
</div>
<div style="margin-bottom:1.25rem;">
<div style="font-size:0.9rem;font-weight:700;color:#60a5fa;margin-bottom:0.5rem;">Q. 역프가 발생하면 어떻게 해야 하나요?</div>
<div style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">A. 역프(국내 &lt; 해외)가 3% 이상이면 <b>역따리</b>를 검토합니다.<br>1. 국내에서 현물 매수<br>2. 해외에서 선물 숏 (헷지)<br>3. 국내 → 해외로 전송<br>4. 해외에서 매도 + 숏 청산<br>수익 = 역프% - 수수료</div>
</div>
<div>
<div style="font-size:0.9rem;font-weight:700;color:#60a5fa;margin-bottom:0.5rem;">Q. GO 판정이 나왔는데 망따리가 됐어요. 왜 그런가요?</div>
<div style="font-size:0.85rem;color:#d1d5db;line-height:1.6;">A. GO 판정은 <b>조건이 유리하다</b>는 의미이지, 100% 성공을 보장하지 않습니다.<br>예상치 못한 변수(시장 급락, 대량 덤핑, 네트워크 지연 등)가 발생할 수 있습니다.<br>GO 스코어가 높을수록 성공 확률이 높지만, 항상 리스크 관리가 필요합니다.</div>
</div>
</div>''')
    
    # ========================================
    # 6. 리스크 경고
    # ========================================
    with st.expander("⚠️ 리스크 경고", expanded=False):
        _html('''<div style="background:rgba(239,68,68,0.1);border:2px solid #f87171;border-radius:12px;padding:1.25rem;">
<div style="font-size:1rem;font-weight:700;color:#f87171;margin-bottom:1rem;">⚠️ 반드시 숙지하세요!</div>
<table style="width:100%;font-size:0.85rem;border-collapse:collapse;">
<tr style="border-bottom:1px solid #374151;"><td style="padding:8px;color:#d1d5db;width:35%;">TGE 15%+</td><td style="padding:8px;color:#f87171;font-weight:600;">🔴 높음</td><td style="padding:8px;color:#9ca3af;">대량 덤핑 주의</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:8px;color:#d1d5db;">헤지 불가 (none)</td><td style="padding:8px;color:#f87171;font-weight:600;">🔴 높음</td><td style="padding:8px;color:#9ca3af;">손실 무제한 가능</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:8px;color:#d1d5db;">MM 리스크 &gt; 7</td><td style="padding:8px;color:#fbbf24;font-weight:600;">🟡 중간</td><td style="padding:8px;color:#9ca3af;">조작 가능성</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:8px;color:#d1d5db;">VC Tier1 없음</td><td style="padding:8px;color:#fbbf24;font-weight:600;">🟡 중간</td><td style="padding:8px;color:#9ca3af;">품질 의심</td></tr>
<tr style="border-bottom:1px solid #374151;"><td style="padding:8px;color:#d1d5db;">핫월렛 100억+</td><td style="padding:8px;color:#fbbf24;font-weight:600;">🟡 중간</td><td style="padding:8px;color:#9ca3af;">입금 경쟁 치열</td></tr>
<tr><td style="padding:8px;color:#d1d5db;">직전 상장 망따리</td><td style="padding:8px;color:#fbbf24;font-weight:600;">🟡 중간</td><td style="padding:8px;color:#9ca3af;">시장 심리 냉각</td></tr>
</table>
<div style="margin-top:1rem;padding:0.75rem;background:#7f1d1d;border-radius:8px;">
<div style="font-size:0.85rem;color:#fca5a5;line-height:1.6;">💀 <b>망따리 패턴</b>: 핫월렛 많음 + 네트워크 빠름 + DEX 유동성 충분 + 직전 망따리<br>→ 이 조합이면 무조건 패스하세요!</div>
</div>
</div>''')
