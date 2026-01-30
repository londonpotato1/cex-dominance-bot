"""따리분석 사용자 가이드 모듈.

김치 프리미엄 따리 전략에 대한 용어, 워크플로우, 리스크 안내.
"""

from __future__ import annotations

from ui.ddari_common import COLORS, CARD_STYLE


def _get_guide_html() -> str:
    """사용자 가이드 HTML 생성."""
    return f"""
    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                border-radius:12px;padding:1.5rem;margin-top:1rem;">

        <!-- 1. 김치 프리미엄 따리란? -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                🥢 김치 프리미엄 따리란?
            </h3>
            <p style="color:{COLORS["text_secondary"]};font-size:0.85rem;line-height:1.6;">
                한국 거래소(업비트/빗썸)와 글로벌 거래소(바이낸스/바이빗) 간의 가격 차이를 활용한 차익거래 전략입니다.
                신규 상장 시 일시적으로 발생하는 높은 프리미엄을 포착하여 수익을 창출합니다.
            </p>
        </div>

        <!-- 2. 핵심 용어 사전 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                📖 핵심 용어 사전
            </h3>
            <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
                <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                    <td style="padding:8px;color:{COLORS["info"]};font-weight:600;width:25%;">김프</td>
                    <td style="padding:8px;color:{COLORS["text_secondary"]};">김치 프리미엄 — 국내 가격 > 글로벌 가격</td>
                </tr>
                <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                    <td style="padding:8px;color:{COLORS["danger"]};font-weight:600;">역프</td>
                    <td style="padding:8px;color:{COLORS["text_secondary"]};">역프리미엄 — 국내 가격 < 글로벌 가격</td>
                </tr>
                <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                    <td style="padding:8px;color:{COLORS["success"]};font-weight:600;">흥따리</td>
                    <td style="padding:8px;color:{COLORS["text_secondary"]};">성공적인 따리 (수익 발생)</td>
                </tr>
                <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                    <td style="padding:8px;color:{COLORS["danger"]};font-weight:600;">망따리</td>
                    <td style="padding:8px;color:{COLORS["text_secondary"]};">실패한 따리 (손실 발생)</td>
                </tr>
                <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                    <td style="padding:8px;color:{COLORS["warning"]};font-weight:600;">Gate</td>
                    <td style="padding:8px;color:{COLORS["text_secondary"]};">자동 GO/NO-GO 판정 시스템</td>
                </tr>
                <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                    <td style="padding:8px;color:{COLORS["text_primary"]};font-weight:600;">TGE</td>
                    <td style="padding:8px;color:{COLORS["text_secondary"]};">Token Generation Event — 토큰 최초 발행</td>
                </tr>
                <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                    <td style="padding:8px;color:{COLORS["text_primary"]};font-weight:600;">Cliff</td>
                    <td style="padding:8px;color:{COLORS["text_secondary"]};">토큰 락업 기간 (언락 전까지 판매 불가)</td>
                </tr>
                <tr>
                    <td style="padding:8px;color:{COLORS["text_primary"]};font-weight:600;">Vesting</td>
                    <td style="padding:8px;color:{COLORS["text_secondary"]};">점진적 토큰 언락 기간</td>
                </tr>
            </table>
        </div>

        <!-- 3. GO/NO-GO 신호 해석 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                🚦 GO/NO-GO 신호 해석
            </h3>
            <div style="display:flex;gap:1rem;flex-wrap:wrap;">
                <div style="flex:1;min-width:200px;background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;border-left:4px solid {COLORS["success"]};">
                    <p style="font-size:0.9rem;font-weight:600;color:{COLORS["success"]};margin-bottom:0.5rem;">🟢 GO</p>
                    <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};">모든 조건 충족</p>
                    <p style="font-size:0.75rem;color:{COLORS["text_muted"]};margin-top:0.25rem;">→ 진입 검토</p>
                </div>
                <div style="flex:1;min-width:200px;background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;border-left:4px solid {COLORS["danger"]};">
                    <p style="font-size:0.9rem;font-weight:600;color:{COLORS["danger"]};margin-bottom:0.5rem;">🔴 NO-GO</p>
                    <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};">조건 불충족</p>
                    <p style="font-size:0.75rem;color:{COLORS["text_muted"]};margin-top:0.25rem;">→ 진입 금지</p>
                </div>
            </div>
        </div>

        <!-- 4. 프리미엄 레벨 가이드 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                📊 프리미엄 레벨 가이드
            </h3>
            <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
                <thead>
                    <tr style="background:rgba(255,255,255,0.05);">
                        <th style="padding:8px;text-align:left;color:{COLORS["text_dim"]};">레벨</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};">프리미엄</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};">기대</th>
                        <th style="padding:8px;text-align:left;color:{COLORS["text_dim"]};">전략</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["success"]};">🔥 대흥따리</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["text_primary"]};font-weight:600;">15%+</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["success"]};">높은 수익</td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">적극 진입</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["info"]};">✨ 흥따리</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["text_primary"]};font-weight:600;">8-15%</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["info"]};">중간 수익</td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">선별 진입</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["neutral"]};">➖ 보통</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["text_primary"]};font-weight:600;">3-8%</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["neutral"]};">낮은 수익</td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">신중</td>
                    </tr>
                    <tr>
                        <td style="padding:8px;color:{COLORS["danger"]};">💀 망따리</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["text_primary"]};font-weight:600;">&lt;3%</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["danger"]};">손실 가능</td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">진입 금지</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- 5. 트레이딩 워크플로우 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                🔄 트레이딩 워크플로우
            </h3>
            <div style="background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;">
                <ol style="color:{COLORS["text_secondary"]};font-size:0.85rem;line-height:1.8;padding-left:1.2rem;margin:0;">
                    <li><span style="color:{COLORS["info"]};">상장 감지</span> → 텔레그램 알림 수신</li>
                    <li><span style="color:{COLORS["warning"]};">Gate 확인</span> → GO/NO-GO 배지 확인</li>
                    <li><span style="color:{COLORS["success"]};">프리미엄 확인</span> → 현재 vs 예상 수익</li>
                    <li><span style="color:{COLORS["info"]};">진입 결정</span> → 헤지 가능 여부 확인</li>
                    <li><span style="color:{COLORS["neutral"]};">포지션 관리</span> → 후따리 분석 모니터링</li>
                    <li><span style="color:{COLORS["danger"]};">청산</span> → Exit Trigger 신호에 따라</li>
                </ol>
            </div>
        </div>

        <!-- 6. 리스크 경고 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                ⚠️ 리스크 경고
            </h3>
            <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
                <thead>
                    <tr style="background:rgba(255,255,255,0.05);">
                        <th style="padding:8px;text-align:left;color:{COLORS["text_dim"]};">조건</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};">경고</th>
                        <th style="padding:8px;text-align:left;color:{COLORS["text_dim"]};">대응</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["text_primary"]};">TGE 15%+</td>
                        <td style="padding:8px;text-align:center;"><span style="color:{COLORS["danger"]};">🔴 높음</span></td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">대량 덤핑 주의</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["text_primary"]};">헤지 불가 (none)</td>
                        <td style="padding:8px;text-align:center;"><span style="color:{COLORS["danger"]};">🔴 높음</span></td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">손실 무제한</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["text_primary"]};">MM 리스크 > 7</td>
                        <td style="padding:8px;text-align:center;"><span style="color:{COLORS["warning"]};">🟡 중간</span></td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">조작 가능성</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["text_primary"]};">VC Tier1 없음</td>
                        <td style="padding:8px;text-align:center;"><span style="color:{COLORS["warning"]};">🟡 중간</span></td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">품질 의심</td>
                    </tr>
                    <tr>
                        <td style="padding:8px;color:{COLORS["text_primary"]};">역프 상황</td>
                        <td style="padding:8px;text-align:center;"><span style="color:{COLORS["danger"]};">🔴 높음</span></td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">절대 진입 금지</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- 7. 탭별 활용법 -->
        <div>
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                📑 탭별 활용법
            </h3>
            <div style="display:flex;flex-direction:column;gap:1rem;">
                <div style="background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;border-left:4px solid {COLORS["danger"]};">
                    <p style="font-size:0.9rem;font-weight:600;color:{COLORS["danger"]};margin-bottom:0.5rem;">🔥 실시간 현황</p>
                    <ul style="color:{COLORS["text_secondary"]};font-size:0.8rem;padding-left:1.2rem;margin:0;">
                        <li><b>Gate 분석:</b> 상장 즉시 확인, GO면 다음 단계</li>
                        <li><b>프리미엄 차트:</b> 추세 확인, 상승 중이면 진입</li>
                        <li><b>현선갭:</b> +3%+ = 강한 김프, 아비트라지 기회</li>
                    </ul>
                </div>
                <div style="background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;border-left:4px solid {COLORS["info"]};">
                    <p style="font-size:0.9rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">📊 분석 인텔리전스</p>
                    <ul style="color:{COLORS["text_secondary"]};font-size:0.8rem;padding-left:1.2rem;margin:0;">
                        <li><b>상장 히스토리:</b> 비슷한 토큰 성과 확인</li>
                        <li><b>시나리오 예측:</b> AI 예측 참고 (70%+ 정확도)</li>
                        <li><b>VC/MM:</b> Tier1 VC 있으면 +신뢰, DWF Labs면 주의</li>
                        <li><b>TGE 언락:</b> 15%+ 위험, 5% 미만 안전</li>
                    </ul>
                </div>
                <div style="background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;border-left:4px solid {COLORS["warning"]};">
                    <p style="font-size:0.9rem;font-weight:600;color:{COLORS["warning"]};margin-bottom:0.5rem;">🎯 후따리 전략</p>
                    <ul style="color:{COLORS["text_secondary"]};font-size:0.8rem;padding-left:1.2rem;margin:0;">
                        <li><b>후따리 분석:</b> 초기 덤프 후 2차 펌핑 기회</li>
                        <li><b>매도 타이밍:</b> Exit Trigger 신호 따라 청산</li>
                    </ul>
                </div>
            </div>
        </div>

    </div>
    """


def render_user_guide() -> None:
    """사용자 가이드 렌더링 (접이식 expander)."""
    import streamlit as st

    with st.expander("📖 사용자 가이드 — 따리 전략 완벽 가이드", expanded=False):
        guide_html = _get_guide_html()
        if hasattr(st, 'html'):
            st.html(guide_html)
        else:
            st.markdown(guide_html, unsafe_allow_html=True)
