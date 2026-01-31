"""따리분석 사용자 가이드 모듈.

김치 프리미엄 따리 전략에 대한 용어, 워크플로우, 리스크 안내.
"""

from __future__ import annotations

from ui.ddari_common import COLORS, CARD_STYLE, render_html


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
                        <td style="padding:8px;text-align:center;"><span style="color:{COLORS["info"]};">🔄 역따리</span></td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">반대 전략 검토 (아래 참조)</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- 7. 역프 전략 (NEW!) -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                🔄 역프 상황 전략 (역따리)
            </h3>
            <div style="background:linear-gradient(135deg, #1e3a5f 0%, #2d1f47 100%);padding:1rem;border-radius:8px;border:1px solid {COLORS["info"]};">
                <p style="font-size:0.85rem;color:{COLORS["text_secondary"]};margin-bottom:0.75rem;">
                    <b style="color:{COLORS["info"]};">역프 = 국내 가격 < 해외 가격</b><br>
                    일반 따리(해외→국내)는 손실이지만, <b>반대 방향</b>으로 수익 가능!
                </p>
                
                <div style="background:rgba(0,0,0,0.2);padding:0.75rem;border-radius:6px;margin-bottom:0.75rem;">
                    <p style="font-size:0.8rem;font-weight:600;color:{COLORS["success"]};margin-bottom:0.5rem;">✅ 역따리 전략</p>
                    <ol style="color:{COLORS["text_secondary"]};font-size:0.75rem;padding-left:1.2rem;margin:0;">
                        <li><b>국내 현물 매수</b> (업비트/빗썸)</li>
                        <li><b>해외 선물 숏</b> (바이낸스/바이비트) - 가격 변동 헷징</li>
                        <li><b>국내→해외 전송</b> (네트워크 확인)</li>
                        <li><b>해외 현물 매도</b> + <b>숏 청산</b></li>
                    </ol>
                </div>
                
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-bottom:0.5rem;">
                    <div style="background:rgba(74,222,128,0.1);padding:0.5rem;border-radius:4px;">
                        <p style="font-size:0.7rem;color:{COLORS["success"]};font-weight:600;">수익 = 역프 - 수수료</p>
                        <p style="font-size:0.65rem;color:{COLORS["text_muted"]};">역프 3% - 수수료 0.5% = 순익 2.5%</p>
                    </div>
                    <div style="background:rgba(248,113,113,0.1);padding:0.5rem;border-radius:4px;">
                        <p style="font-size:0.7rem;color:{COLORS["danger"]};font-weight:600;">주의사항</p>
                        <p style="font-size:0.65rem;color:{COLORS["text_muted"]};">현선갭, 펀딩비, 전송 시간 고려</p>
                    </div>
                </div>
                
                <p style="font-size:0.7rem;color:{COLORS["text_muted"]};margin-top:0.5rem;">
                    💡 <b>역프 3% 이상</b>일 때 검토 권장 | 헷징 비용(현선갭+펀딩비) 차감 후 순익 계산
                </p>
            </div>
        </div>

        <!-- 8. 탭별 활용법 -->
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


def _get_system_guide_html() -> str:
    """시스템 작동 방식 가이드 HTML 생성."""
    return f"""
    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                border-radius:12px;padding:1.5rem;margin-top:1rem;">

        <!-- 1. 시스템 개요 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                🤖 시스템 개요
            </h3>
            <p style="color:{COLORS["text_secondary"]};font-size:0.85rem;line-height:1.6;">
                이 봇은 한국 거래소(업비트/빗썸)와 글로벌 거래소의 가격 차이를 실시간으로 모니터링하고,
                신규 상장 시 자동으로 분석하여 GO/NO-GO 판정을 내립니다.
            </p>
            <div style="background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;margin-top:0.75rem;">
                <div style="display:flex;flex-wrap:wrap;gap:0.75rem;font-size:0.8rem;">
                    <span style="background:#1f2937;padding:4px 10px;border-radius:6px;color:#60a5fa;">
                        📡 실시간 WebSocket
                    </span>
                    <span style="background:#1f2937;padding:4px 10px;border-radius:6px;color:#a78bfa;">
                        🔍 상장 자동 감지
                    </span>
                    <span style="background:#1f2937;padding:4px 10px;border-radius:6px;color:#4ade80;">
                        🚦 GO/NO-GO 판정
                    </span>
                    <span style="background:#1f2937;padding:4px 10px;border-radius:6px;color:#fbbf24;">
                        🔔 텔레그램 알림
                    </span>
                </div>
            </div>
        </div>

        <!-- 2. 데이터 수집 방식 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                📡 데이터 수집 방식
            </h3>
            <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
                <thead>
                    <tr style="background:rgba(255,255,255,0.05);">
                        <th style="padding:8px;text-align:left;color:{COLORS["text_dim"]};">거래소</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};">방식</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};">지연</th>
                        <th style="padding:8px;text-align:left;color:{COLORS["text_dim"]};">수집 데이터</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["info"]};font-weight:600;">업비트</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["success"]};">WebSocket</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["text_secondary"]};">~100ms</td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">실시간 체결가, 마켓 목록</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["info"]};font-weight:600;">빗썸</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["success"]};">WebSocket</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["text_secondary"]};">~200ms</td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">실시간 체결가, 마켓 목록</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["warning"]};font-weight:600;">바이낸스</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["info"]};">REST API</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["text_secondary"]};">~500ms</td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">현물/선물 가격, 펀딩비</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["warning"]};font-weight:600;">바이빗</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["info"]};">REST API</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["text_secondary"]};">~500ms</td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">현물/선물 가격, 펀딩비</td>
                    </tr>
                    <tr>
                        <td style="padding:8px;color:{COLORS["text_muted"]};font-weight:600;">환율 (FX)</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["neutral"]};">API 캐시</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["text_secondary"]};">5분</td>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">USD/KRW 환율</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- 3. 상장 감지 로직 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                🔍 상장 감지 로직
            </h3>
            <div style="background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;">
                <ol style="color:{COLORS["text_secondary"]};font-size:0.85rem;line-height:1.8;padding-left:1.2rem;margin:0;">
                    <li><span style="color:{COLORS["info"]};">마켓 Diff 모니터링</span> — 30~60초마다 마켓 목록 비교</li>
                    <li><span style="color:{COLORS["warning"]};">새 심볼 감지</span> — 이전에 없던 마켓이 등장하면 상장으로 판단</li>
                    <li><span style="color:{COLORS["success"]};">Gate 분석 시작</span> — 글로벌 거래소 가격/입출금 상태 확인</li>
                    <li><span style="color:{COLORS["danger"]};">텔레그램 알림</span> — GO/NO-GO 결과 즉시 전송</li>
                </ol>
            </div>
            <div style="margin-top:0.75rem;padding:0.75rem;background:rgba(251,191,36,0.1);border-radius:8px;border-left:4px solid {COLORS["warning"]};">
                <p style="color:{COLORS["warning"]};font-size:0.8rem;margin:0;">
                    💡 <b>Tip:</b> 공지 크롤링도 함께 실행되어 상장 예정 정보도 미리 파악합니다.
                </p>
            </div>
        </div>

        <!-- 4. GO/NO-GO 판정 기준 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                🚦 GO/NO-GO 판정 기준
            </h3>
            <div style="display:flex;gap:1rem;flex-wrap:wrap;">
                <div style="flex:1;min-width:250px;background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;border:1px solid {COLORS["success"]};">
                    <p style="font-size:0.9rem;font-weight:600;color:{COLORS["success"]};margin-bottom:0.75rem;">🟢 GO 조건 (모두 충족)</p>
                    <ul style="color:{COLORS["text_secondary"]};font-size:0.8rem;padding-left:1.2rem;margin:0;line-height:1.8;">
                        <li>글로벌 거래소에 상장됨</li>
                        <li>입출금 가능 (Deposit/Withdraw)</li>
                        <li>순수익 > 0% (프리미엄 - 비용)</li>
                        <li>가격 데이터 정상 수집</li>
                    </ul>
                </div>
                <div style="flex:1;min-width:250px;background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;border:1px solid {COLORS["danger"]};">
                    <p style="font-size:0.9rem;font-weight:600;color:{COLORS["danger"]};margin-bottom:0.75rem;">🔴 NO-GO 조건 (하나라도)</p>
                    <ul style="color:{COLORS["text_secondary"]};font-size:0.8rem;padding-left:1.2rem;margin:0;line-height:1.8;">
                        <li>글로벌 거래소 미상장</li>
                        <li>입출금 중지 (Suspended)</li>
                        <li>순수익 ≤ 0% (적자)</li>
                        <li>네트워크 지원 안 함</li>
                    </ul>
                </div>
            </div>
        </div>

        <!-- 5. 프리미엄 계산 방식 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                📊 프리미엄 계산 방식
            </h3>
            <div style="background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;font-family:monospace;font-size:0.85rem;">
                <p style="color:{COLORS["info"]};margin-bottom:0.5rem;">// 기본 공식</p>
                <p style="color:{COLORS["text_primary"]};margin-bottom:1rem;">
                    프리미엄(%) = (국내가격 - 글로벌가격×환율) / (글로벌가격×환율) × 100
                </p>
                <p style="color:{COLORS["info"]};margin-bottom:0.5rem;">// 순수익 계산</p>
                <p style="color:{COLORS["text_primary"]};margin-bottom:0.5rem;">
                    순수익(%) = 프리미엄 - 총비용
                </p>
                <p style="color:{COLORS["warning"]};margin-bottom:0;">
                    총비용 = 출금수수료 + 거래수수료(양쪽) + 슬리피지(예상)
                </p>
            </div>
            <div style="margin-top:0.75rem;display:flex;gap:0.5rem;flex-wrap:wrap;">
                <span style="background:#1f2937;padding:4px 10px;border-radius:6px;font-size:0.75rem;color:{COLORS["text_secondary"]};">
                    업비트 거래수수료: 0.05%
                </span>
                <span style="background:#1f2937;padding:4px 10px;border-radius:6px;font-size:0.75rem;color:{COLORS["text_secondary"]};">
                    빗썸 거래수수료: 0.04%
                </span>
                <span style="background:#1f2937;padding:4px 10px;border-radius:6px;font-size:0.75rem;color:{COLORS["text_secondary"]};">
                    출금수수료: 코인별 상이
                </span>
            </div>
        </div>

        <!-- 6. 신뢰도 점수 -->
        <div style="margin-bottom:1.5rem;">
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                📈 신뢰도 점수 (Confidence Score)
            </h3>
            <p style="color:{COLORS["text_secondary"]};font-size:0.85rem;margin-bottom:0.75rem;">
                분석 결과의 신뢰도를 0-100%로 표시합니다. 높을수록 정확한 데이터입니다.
            </p>
            <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
                <thead>
                    <tr style="background:rgba(255,255,255,0.05);">
                        <th style="padding:8px;text-align:left;color:{COLORS["text_dim"]};">감점 요인</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};">감점</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">환율 기본값 사용 (API 실패)</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["danger"]};">-30점</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">순수익 마이너스</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["danger"]};">-20점</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">프리미엄 데이터 없음</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["warning"]};">-15점</td>
                    </tr>
                    <tr style="border-bottom:1px solid {COLORS["card_border_hover"]};">
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">환율 캐시 사용 (5분 이상)</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["warning"]};">-10점</td>
                    </tr>
                    <tr>
                        <td style="padding:8px;color:{COLORS["text_secondary"]};">분석 지연 (5초+)</td>
                        <td style="padding:8px;text-align:center;color:{COLORS["warning"]};">-10점</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- 7. 텔레그램 알림 -->
        <div>
            <h3 style="color:{COLORS["text_primary"]};font-size:1.1rem;margin-bottom:0.75rem;">
                🔔 텔레그램 알림 시스템
            </h3>
            <div style="background:{COLORS["bg_dark"]};padding:1rem;border-radius:8px;">
                <p style="color:{COLORS["text_secondary"]};font-size:0.85rem;margin-bottom:0.75rem;">
                    GO 판정 시 자동으로 텔레그램 알림이 전송됩니다.
                </p>
                <div style="display:flex;flex-direction:column;gap:0.5rem;font-size:0.8rem;">
                    <div style="display:flex;align-items:center;gap:0.5rem;">
                        <span style="color:{COLORS["success"]};">✅</span>
                        <span style="color:{COLORS["text_secondary"]};">GO 알림: 심볼, 프리미엄, 예상 수익, 거래소 정보</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.5rem;">
                        <span style="color:{COLORS["info"]};">📊</span>
                        <span style="color:{COLORS["text_secondary"]};">상세 정보: 네트워크, 헤지 가능 여부, VC/MM 정보</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.5rem;">
                        <span style="color:{COLORS["warning"]};">🔗</span>
                        <span style="color:{COLORS["text_secondary"]};">바로가기 링크: 업비트, 바이낸스 직접 접속</span>
                    </div>
                </div>
            </div>
        </div>

    </div>
    """


def render_user_guide() -> None:
    """사용자 가이드 렌더링 (탭 분리 버전)."""
    import streamlit as st

    # 가이드 서브탭
    strategy_tab, system_tab = st.tabs(["📖 전략 가이드", "🤖 시스템 작동 방식"])

    with strategy_tab:
        guide_html = _get_guide_html()
        render_html(guide_html)

    with system_tab:
        system_html = _get_system_guide_html()
        render_html(system_html)
