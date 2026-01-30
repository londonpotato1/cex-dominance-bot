"""따리분석 인텔리전스 탭 (Tab 2).

심층 분석 정보: 상장 히스토리, 시나리오, 백테스트, VC/MM, 토크노믹스, 핫월렛.
"""

from __future__ import annotations

import os
from datetime import datetime

from ui.ddari_common import (
    CARD_STYLE,
    COLORS,
    TGE_RISK_GUIDE,
    SECTION_HEADER_STYLE,
    LISTING_TYPE_COLORS,
    badge_style,
    get_read_conn,
    load_vc_tiers_cached,
    load_backtest_results_cached,
    load_unlock_schedules_cached,
    load_hot_wallets_cached,
    fetch_listing_history_cached,
    fetch_scenario_data_cached,
    render_result_label_badge,
)


# ------------------------------------------------------------------
# 상장 히스토리 카드
# ------------------------------------------------------------------


def _render_listing_history_card(row: dict) -> None:
    """상장 히스토리 카드 렌더링."""
    import streamlit as st

    symbol = row.get("symbol", "?")
    exchange = row.get("exchange", "?")
    listing_time = row.get("listing_time", "")
    listing_type = row.get("listing_type", "UNKNOWN")
    result_label = row.get("result_label")
    gate_can_proceed = row.get("gate_can_proceed", 0)

    # 상장 시간 포맷
    try:
        if listing_time:
            dt = datetime.fromisoformat(listing_time.replace("Z", "+00:00"))
            time_str = dt.strftime("%m/%d %H:%M")
        else:
            time_str = "-"
    except (ValueError, TypeError):
        time_str = listing_time[:16] if listing_time else "-"

    # Gate 결과 배지
    gate_badge = (
        f'<span style="{badge_style(COLORS["success"], size="0.7rem")}">GO</span>'
        if gate_can_proceed
        else f'<span style="{badge_style(COLORS["danger"], size="0.7rem")}">NO-GO</span>'
    )

    # 유형 배지 (LISTING_TYPE_COLORS 사용)
    type_bg = LISTING_TYPE_COLORS.get(listing_type, COLORS["neutral"])
    type_badge = f'<span style="{badge_style(type_bg, size="0.7rem")}">{listing_type}</span>'

    # 결과 라벨 배지
    result_badge = render_result_label_badge(result_label)

    # 프리미엄 정보
    premium = row.get("premium_pct")
    max_premium = row.get("max_premium_pct")
    premium_str = f"{premium:+.1f}%" if premium is not None else "-"
    max_premium_str = f"최대 {max_premium:+.1f}%" if max_premium is not None else ""

    card_html = f"""
    <div style="background:{COLORS["bg_dark"]};border:1px solid {COLORS["border_dark"]};border-radius:8px;padding:12px;margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
                <span style="font-weight:600;font-size:1.1rem;color:{COLORS["text_primary"]};">{symbol}</span>
                <span style="color:{COLORS["text_tertiary"]};font-size:0.85rem;margin-left:8px;">@ {exchange.upper()}</span>
                <span style="color:{COLORS["text_muted"]};font-size:0.8rem;margin-left:12px;">{time_str}</span>
            </div>
            <div>{type_badge} {gate_badge} {result_badge}</div>
        </div>
        <div style="margin-top:8px;color:{COLORS["text_secondary"]};font-size:0.85rem;">
            진입 프리미엄: {premium_str}
            {f'<span style="margin-left:12px;">{max_premium_str}</span>' if max_premium_str else ''}
        </div>
    </div>
    """

    if hasattr(st, 'html'):
        st.html(card_html)
    else:
        st.markdown(card_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 시나리오 카드
# ------------------------------------------------------------------


def _render_scenario_card_html(
    symbol: str,
    exchange: str,
    predicted_outcome: str,
    heung_probability: float,
    supply_class: str,
    hedge_type: str,
    market_condition: str,
    factors: list[str],
    warnings: list[str],
    confidence: float,
    scenario_type: str = "likely",
) -> str:
    """시나리오 카드 HTML 생성."""
    # Outcome별 스타일 (COLORS 사용)
    outcome_styles = {
        "heung_big": {"bg": COLORS["success"], "emoji": "🔥", "name": "대흥따리"},
        "heung": {"bg": COLORS["info"], "emoji": "✨", "name": "흥따리"},
        "neutral": {"bg": COLORS["neutral"], "emoji": "➖", "name": "보통"},
        "mang": {"bg": COLORS["danger"], "emoji": "💀", "name": "망따리"},
    }
    style = outcome_styles.get(predicted_outcome, outcome_styles["neutral"])

    # 시나리오 타입별 라벨
    type_labels = {
        "best": ("✨ BEST", COLORS["success"]),
        "likely": ("📊 LIKELY", COLORS["info"]),
        "worst": ("💀 WORST", COLORS["danger"]),
    }
    type_label, type_color = type_labels.get(scenario_type, ("", COLORS["neutral"]))

    # 공급/헤지/시장 배지
    supply_badge = {
        "constrained": ("공급 제약", COLORS["danger_dark"]),
        "smooth": ("공급 원활", COLORS["success_dark"]),
        "unknown": ("공급 미확인", COLORS["neutral"]),
    }.get(supply_class, ("?", COLORS["neutral"]))

    hedge_badge = {
        "cex": ("CEX 헤지", COLORS["info"]),
        "dex_only": ("DEX만", COLORS["warning"]),
        "none": ("헤지 불가", COLORS["danger_dark"]),
    }.get(hedge_type, ("?", COLORS["neutral"]))

    market_badge = {
        "bull": ("불장", COLORS["success"]),
        "neutral": ("중립", COLORS["neutral"]),
        "bear": ("약세", COLORS["danger"]),
    }.get(market_condition, ("?", COLORS["neutral"]))

    # Factors HTML
    factors_html = ""
    if factors:
        items = "".join(
            f'<li style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin-bottom:2px;">{f}</li>'
            for f in factors[:4]  # 최대 4개
        )
        factors_html = f'<ul style="margin:0.3rem 0;padding-left:1.2rem;">{items}</ul>'

    # Warnings HTML
    warnings_html = ""
    if warnings:
        items = "".join(
            f'<li style="font-size:0.8rem;color:{COLORS["warning"]};">{w}</li>'
            for w in warnings[:3]  # 최대 3개
        )
        warnings_html = f'<ul style="margin:0.3rem 0;padding-left:1.2rem;">{items}</ul>'

    return f"""
    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border_hover"]};
                border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <div>
                <span style="font-size:1.1rem;font-weight:600;color:{COLORS["text_primary"]};">{style['emoji']} {symbol}</span>
                <span style="color:{COLORS["text_tertiary"]};font-size:0.8rem;margin-left:0.5rem;">@{exchange}</span>
                {f'<span style="{badge_style(type_color, size="0.7rem")}margin-left:8px;">{type_label}</span>' if type_label else ''}
            </div>
            <span style="background:{style['bg']};color:{COLORS["text_primary"]};padding:4px 12px;border-radius:6px;font-weight:600;font-size:0.9rem;">
                {style['name']} {heung_probability*100:.0f}%
            </span>
        </div>
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.5rem;">
            <span style="{badge_style(supply_badge[1], size="0.7rem")}">{supply_badge[0]}</span>
            <span style="{badge_style(hedge_badge[1], size="0.7rem")}">{hedge_badge[0]}</span>
            <span style="{badge_style(market_badge[1], size="0.7rem")}">{market_badge[0]}</span>
        </div>
        {factors_html}
        {warnings_html}
        <div style="margin-top:0.5rem;font-size:0.75rem;color:{COLORS["text_muted"]};">
            신뢰도: {confidence*100:.0f}%
        </div>
    </div>
    """


def _render_scenario_section(conn_id: int) -> None:
    """시나리오 예측 섹션 렌더링."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">🎯 시나리오 예측</p>',
        unsafe_allow_html=True,
    )

    # 최근 상장 데이터 조회
    recent_listings = fetch_scenario_data_cached(conn_id, limit=5)

    if not recent_listings:
        st.markdown(
            f'<p style="color:{COLORS["text_muted"]};font-size:0.85rem;">시나리오 데이터 없음</p>',
            unsafe_allow_html=True,
        )
        return

    # 각 상장에 대해 시나리오 카드 생성
    for listing in recent_listings:
        symbol = listing.get("symbol", "?")
        exchange = listing.get("exchange", "?")
        listing_type = listing.get("listing_type", "UNKNOWN")
        hedge_type = listing.get("hedge_type", "cex")
        result_label = listing.get("result_label")
        premium = listing.get("premium_pct")
        max_premium = listing.get("max_premium_pct")

        # 실제 결과가 있으면 그것을 표시, 없으면 예측
        if result_label:
            predicted_outcome = result_label
            prob_map = {"heung_big": 0.95, "heung": 0.80, "neutral": 0.50, "mang": 0.30}
            heung_prob = prob_map.get(result_label, 0.5)
        else:
            if hedge_type == "none":
                predicted_outcome = "heung"
                heung_prob = 0.70
            elif listing_type == "TGE":
                predicted_outcome = "heung"
                heung_prob = 0.60
            else:
                predicted_outcome = "neutral"
                heung_prob = 0.50

        supply_class = "constrained" if hedge_type == "none" else "smooth"

        factors = []
        if listing_type:
            type_names = {"TGE": "세계 최초 상장", "DIRECT": "직상장", "SIDE": "옆상장"}
            factors.append(f"상장 유형: {type_names.get(listing_type, listing_type)}")
        if premium is not None:
            factors.append(f"진입 프리미엄: {premium:+.1f}%")
        if max_premium is not None:
            factors.append(f"최대 프리미엄: {max_premium:+.1f}%")

        warnings = []
        if result_label is None:
            warnings.append("결과 미확정 (예측값)")
        if hedge_type == "none":
            warnings.append("헤징 불가 - 리스크 주의")

        card_html = _render_scenario_card_html(
            symbol=symbol,
            exchange=exchange,
            predicted_outcome=predicted_outcome,
            heung_probability=heung_prob,
            supply_class=supply_class,
            hedge_type=hedge_type or "cex",
            market_condition="neutral",
            factors=factors,
            warnings=warnings,
            confidence=0.73 if result_label else 0.60,
            scenario_type="likely",
        )

        if hasattr(st, 'html'):
            st.html(card_html)
        else:
            st.markdown(card_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 백테스트 정확도 섹션
# ------------------------------------------------------------------


def _render_backtest_accuracy_section() -> None:
    """백테스트 정확도 섹션 렌더링."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">📊 백테스트 정확도</p>',
        unsafe_allow_html=True,
    )

    backtest_data = load_backtest_results_cached()
    overall = backtest_data.get("overall", {"accuracy": 0, "count": 0})
    categories = backtest_data.get("categories", {})
    updated_at = backtest_data.get("updated_at", "N/A")

    color_map = {
        "heung_big": COLORS["success"],
        "heung": COLORS["info"],
        "neutral": COLORS["warning"],
        "mang": COLORS["danger"],
    }

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("전체 정확도", f"{overall['accuracy']:.1f}%")
    with col2:
        heung_big = categories.get("heung_big", {"accuracy": 0})
        st.metric("대흥따리", f"{heung_big['accuracy']:.1f}%")
    with col3:
        heung = categories.get("heung", {"accuracy": 0})
        st.metric("흥따리", f"{heung['accuracy']:.1f}%")
    with col4:
        mang = categories.get("mang", {"accuracy": 0})
        st.metric("망따리", f"{mang['accuracy']:.1f}%")

    bars_html = ""
    for cat_key, cat_data in categories.items():
        label = cat_data.get("label", cat_key)
        accuracy = cat_data.get("accuracy", 0)
        count = cat_data.get("count", 0)
        color = color_map.get(cat_key, COLORS["neutral"])
        width = min(accuracy, 100)

        bars_html += f"""
        <div style="margin-bottom:0.5rem;">
            <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
                <span style="font-size:0.8rem;color:{COLORS["text_secondary"]};">{label}</span>
                <span style="font-size:0.8rem;color:{COLORS["text_primary"]};">{accuracy:.1f}% ({count}건)</span>
            </div>
            <div style="background:#2d2d2d;border-radius:4px;height:8px;overflow:hidden;">
                <div style="background:{color};width:{width}%;height:100%;"></div>
            </div>
        </div>
        """

    target_accuracy = 70.0
    achieved = overall['accuracy'] >= target_accuracy
    status_text = f"{overall['accuracy']:.1f}% ✅" if achieved else f"{overall['accuracy']:.1f}% ❌"
    status_color = COLORS["success"] if achieved else COLORS["danger"]

    accuracy_html = f"""
    <div style="{CARD_STYLE}margin-top:0.5rem;">
        <div style="margin-bottom:1rem;">
            <span style="font-size:0.85rem;color:{COLORS["text_tertiary"]};">목표: {target_accuracy:.0f}% | 달성: </span>
            <span style="color:{status_color};font-weight:600;">{status_text}</span>
        </div>
        {bars_html}
        <div style="margin-top:1rem;font-size:0.75rem;color:{COLORS["text_muted"]};">
            📁 데이터: listing_data.csv ({overall['count']}건) | 📅 업데이트: {updated_at}
        </div>
    </div>
    """

    if hasattr(st, 'html'):
        st.html(accuracy_html)
    else:
        st.markdown(accuracy_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# VC/MM 정보 섹션
# ------------------------------------------------------------------


def _render_vc_mm_section() -> None:
    """VC/MM 정보 섹션 렌더링."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">💼 VC/MM 인텔리전스</p>',
        unsafe_allow_html=True,
    )

    vc_data = load_vc_tiers_cached()

    tier1_vcs = []
    for vc in vc_data.get("tier1", []):
        tier1_vcs.append({
            "name": vc.get("name", "Unknown"),
            "roi": vc.get("avg_listing_roi", 0),
            "portfolio": vc.get("portfolio_size", 0),
        })

    mms = []
    for tier_key in ["tier1", "tier2"]:
        mm_tier = vc_data.get("market_makers", {}).get(tier_key, [])
        tier_label = "Tier 1" if tier_key == "tier1" else "Tier 2"
        for mm in mm_tier:
            mms.append({
                "name": mm.get("name", "Unknown"),
                "risk": mm.get("risk_score", 0),
                "tier": tier_label,
            })

    metadata = vc_data.get("metadata", {})
    total_tier1 = metadata.get("total_tier1_vcs", len(tier1_vcs))
    updated_at = metadata.get("updated_at", "N/A")

    display_vcs = tier1_vcs[:8]
    remaining_count = len(tier1_vcs) - 8 if len(tier1_vcs) > 8 else 0

    vc_html = f"""
    <div style="{CARD_STYLE}">
        <p style="font-size:0.9rem;font-weight:600;color:{COLORS["success"]};margin-bottom:0.5rem;">
            ⭐ Tier 1 VC (평균 ROI 50%+)
        </p>
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
    """
    for vc in display_vcs:
        vc_html += f"""
            <span style="background:{COLORS["bg_card"]};border:1px solid {COLORS["border_gray"]};padding:4px 10px;
                        border-radius:6px;font-size:0.8rem;color:{COLORS["text_primary"]};">
                {vc['name']} <span style="color:{COLORS["success"]};">{vc['roi']:.0f}%</span>
            </span>
        """
    if remaining_count > 0:
        vc_html += f"""
            <span style="background:{COLORS["border_gray"]};border:1px solid {COLORS["border_light"]};padding:4px 10px;
                        border-radius:6px;font-size:0.8rem;color:{COLORS["text_dim"]};">
                +{remaining_count} more
            </span>
        """
    vc_html += f"""
        </div>
        <p style="font-size:0.75rem;color:{COLORS["text_muted"]};margin-top:0.75rem;">
            💡 Tier 1 VC 투자 = 상장 성공률 높음 (데이터: {total_tier1}개 VC, {updated_at})
        </p>
    </div>
    """

    mm_html = f"""
    <div style="{CARD_STYLE}">
        <p style="font-size:0.9rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">
            🏦 마켓 메이커 리스크
        </p>
        <div style="display:flex;flex-direction:column;gap:0.4rem;">
    """
    for mm in mms:
        risk_color = COLORS["success"] if mm["risk"] < 4 else COLORS["warning"] if mm["risk"] < 7 else COLORS["danger"]
        risk_emoji = "🟢" if mm["risk"] < 4 else "🟡" if mm["risk"] < 7 else "🔴"
        mm_html += f"""
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:0.85rem;color:{COLORS["text_primary"]};">{mm['name']}</span>
                <span style="font-size:0.8rem;">
                    <span style="color:{COLORS["text_muted"]};">{mm['tier']}</span>
                    <span style="color:{risk_color};margin-left:8px;">{risk_emoji} {mm['risk']:.1f}</span>
                </span>
            </div>
        """
    mm_html += f"""
        </div>
        <p style="font-size:0.75rem;color:{COLORS["text_muted"]};margin-top:0.75rem;">
            ⚠️ 리스크 > 5.0 = 조작 가능성 주의 (워시트레이딩, 펌핑덤핑)
        </p>
    </div>
    """

    if hasattr(st, 'html'):
        st.html(vc_html)
        st.html(mm_html)
    else:
        st.markdown(vc_html, unsafe_allow_html=True)
        st.markdown(mm_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 토크노믹스 (TGE 언락) 섹션
# ------------------------------------------------------------------


def _render_tokenomics_section() -> None:
    """토크노믹스 (TGE 언락) 섹션 렌더링."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">🔓 TGE 언락 분석</p>',
        unsafe_allow_html=True,
    )

    unlock_data = load_unlock_schedules_cached()
    tokens = unlock_data.get("tokens", {})

    if not tokens:
        st.info("언락 스케줄 데이터가 없습니다.")
        return

    risk_colors = {
        "VERY_LOW": COLORS["risk_very_low"],
        "LOW": COLORS["risk_low"],
        "MEDIUM": COLORS["risk_medium"],
        "HIGH": COLORS["risk_high"],
        "VERY_HIGH": COLORS["risk_very_high"],
    }

    risk_emoji = {
        "VERY_LOW": "🟢",
        "LOW": "🟢",
        "MEDIUM": "🟡",
        "HIGH": "🟠",
        "VERY_HIGH": "🔴",
    }

    risk_groups = {"VERY_HIGH": [], "HIGH": [], "MEDIUM": [], "LOW": [], "VERY_LOW": []}
    for symbol, data in tokens.items():
        risk = data.get("risk_assessment", "MEDIUM")
        if risk in risk_groups:
            risk_groups[risk].append((symbol, data))

    high_risk_tokens = risk_groups.get("VERY_HIGH", []) + risk_groups.get("HIGH", [])
    if high_risk_tokens:
        high_risk_html = f"""
        <div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);
                    border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["danger"]};margin-bottom:0.5rem;">
                ⚠️ 고위험 TGE 토큰 (덤핑 주의)
            </p>
            <div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
        """
        for symbol, data in high_risk_tokens[:6]:
            tge_pct = data.get("tge_unlock_pct", 0)
            risk = data.get("risk_assessment", "HIGH")
            color = risk_colors.get(risk, COLORS["risk_high"])
            emoji = risk_emoji.get(risk, "🟠")
            high_risk_html += f"""
                <span style="background:{COLORS["bg_card"]};border:1px solid {color};padding:4px 10px;
                            border-radius:6px;font-size:0.8rem;color:{COLORS["text_primary"]};">
                    {emoji} {symbol} <span style="color:{color};">TGE {tge_pct:.0f}%</span>
                </span>
            """
        high_risk_html += f"""
            </div>
            <p style="font-size:0.75rem;color:{COLORS["danger"]};margin-top:0.5rem;">
                💡 TGE 10%+ = 상장 직후 대량 덤핑 가능성
            </p>
        </div>
        """
        if hasattr(st, 'html'):
            st.html(high_risk_html)
        else:
            st.markdown(high_risk_html, unsafe_allow_html=True)

    with st.expander("📋 전체 토큰 언락 스케줄", expanded=False):
        table_html = f"""
        <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                    border-radius:8px;overflow:hidden;">
            <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
                <thead>
                    <tr style="background:rgba(255,255,255,0.05);">
                        <th style="padding:8px;text-align:left;color:{COLORS["text_dim"]};border-bottom:1px solid {COLORS["card_border_hover"]};">토큰</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};border-bottom:1px solid {COLORS["card_border_hover"]};">TGE 언락</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};border-bottom:1px solid {COLORS["card_border_hover"]};">Cliff</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};border-bottom:1px solid {COLORS["card_border_hover"]};">베스팅</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};border-bottom:1px solid {COLORS["card_border_hover"]};">리스크</th>
                    </tr>
                </thead>
                <tbody>
        """

        sorted_tokens = []
        for risk_level in ["VERY_HIGH", "HIGH", "MEDIUM", "LOW", "VERY_LOW"]:
            sorted_tokens.extend(risk_groups.get(risk_level, []))

        for symbol, data in sorted_tokens:
            name = data.get("name", symbol)
            tge_pct = data.get("tge_unlock_pct", 0)
            cliff = data.get("cliff_months", 0)
            vesting = data.get("vesting_months", 0)
            risk = data.get("risk_assessment", "MEDIUM")

            color = risk_colors.get(risk, COLORS["warning"])
            emoji = risk_emoji.get(risk, "🟡")
            tge_color = COLORS["success"] if tge_pct < 5 else COLORS["warning"] if tge_pct < 10 else COLORS["danger"]

            table_html += f"""
                <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                    <td style="padding:8px;color:{COLORS["text_primary"]};">
                        <span style="font-weight:600;">{symbol}</span>
                        <span style="color:{COLORS["text_muted"]};font-size:0.7rem;"> {name}</span>
                    </td>
                    <td style="padding:8px;text-align:center;">
                        <span style="color:{tge_color};font-weight:600;">{tge_pct:.1f}%</span>
                    </td>
                    <td style="padding:8px;text-align:center;color:{COLORS["text_dim"]};">
                        {cliff}개월
                    </td>
                    <td style="padding:8px;text-align:center;color:{COLORS["text_dim"]};">
                        {vesting}개월
                    </td>
                    <td style="padding:8px;text-align:center;">
                        <span style="color:{color};">{emoji} {risk}</span>
                    </td>
                </tr>
            """

        table_html += """
                </tbody>
            </table>
        </div>
        """

        if hasattr(st, 'html'):
            st.html(table_html)
        else:
            st.markdown(table_html, unsafe_allow_html=True)

    if hasattr(st, 'html'):
        st.html(TGE_RISK_GUIDE)
    else:
        st.markdown(TGE_RISK_GUIDE, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 핫월렛 모니터링 섹션
# ------------------------------------------------------------------


def _render_hot_wallet_section() -> None:
    """핫월렛 모니터링 섹션 렌더링."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">🔥 핫월렛 모니터링</p>',
        unsafe_allow_html=True,
    )

    hw_data = load_hot_wallets_cached()
    exchanges = hw_data.get("exchanges", {})
    common_tokens = hw_data.get("common_tokens", {})

    if not exchanges:
        st.info("핫월렛 데이터가 없습니다.")
        return

    alchemy_key = os.environ.get("ALCHEMY_API_KEY", "")
    api_status = "🟢 연결됨" if alchemy_key else "🔴 API 키 없음"
    api_color = COLORS["success"] if alchemy_key else COLORS["danger"]

    header_html = f"""
    <div style="{CARD_STYLE}">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
                <p style="font-size:0.9rem;font-weight:600;color:{COLORS["risk_high"]};margin:0;">
                    ⛓️ 온체인 핫월렛 추적
                </p>
                <p style="font-size:0.75rem;color:{COLORS["text_muted"]};margin-top:0.25rem;">
                    Alchemy RPC 기반 EVM 4체인 지원
                </p>
            </div>
            <span style="color:{api_color};font-size:0.8rem;font-weight:600;">{api_status}</span>
        </div>
    </div>
    """

    if hasattr(st, 'html'):
        st.html(header_html)
    else:
        st.markdown(header_html, unsafe_allow_html=True)

    with st.expander("📋 등록된 거래소 핫월렛", expanded=False):
        exchange_stats = []
        for ex_id, ex_data in exchanges.items():
            label = ex_data.get("label", ex_id)
            wallets = ex_data.get("wallets", {})
            total_wallets = sum(len(w) for w in wallets.values())
            chains = list(wallets.keys())
            exchange_stats.append({
                "id": ex_id,
                "label": label,
                "total_wallets": total_wallets,
                "chains": chains,
            })

        table_html = f"""
        <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                    border-radius:8px;overflow:hidden;">
            <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
                <thead>
                    <tr style="background:rgba(255,255,255,0.05);">
                        <th style="padding:8px;text-align:left;color:{COLORS["text_dim"]};border-bottom:1px solid {COLORS["card_border_hover"]};">거래소</th>
                        <th style="padding:8px;text-align:center;color:{COLORS["text_dim"]};border-bottom:1px solid {COLORS["card_border_hover"]};">지갑 수</th>
                        <th style="padding:8px;text-align:left;color:{COLORS["text_dim"]};border-bottom:1px solid {COLORS["card_border_hover"]};">체인</th>
                    </tr>
                </thead>
                <tbody>
        """

        for ex in sorted(exchange_stats, key=lambda x: x["total_wallets"], reverse=True):
            chains_str = ", ".join(ex["chains"][:4])
            if len(ex["chains"]) > 4:
                chains_str += f" +{len(ex['chains'])-4}"

            table_html += f"""
                <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                    <td style="padding:8px;color:{COLORS["text_primary"]};font-weight:600;">{ex['label']}</td>
                    <td style="padding:8px;text-align:center;color:{COLORS["success"]};">{ex['total_wallets']}</td>
                    <td style="padding:8px;color:{COLORS["text_dim"]};font-size:0.75rem;">{chains_str}</td>
                </tr>
            """

        table_html += """
                </tbody>
            </table>
        </div>
        """

        if hasattr(st, 'html'):
            st.html(table_html)
        else:
            st.markdown(table_html, unsafe_allow_html=True)

    tokens_html = f"""
    <div style="{CARD_STYLE}margin-top:0.75rem;">
        <p style="font-size:0.85rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">
            🪙 추적 가능 토큰
        </p>
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
    """

    for token_symbol in common_tokens.keys():
        chains_count = len(common_tokens[token_symbol])
        tokens_html += f"""
            <span style="background:{COLORS["bg_card"]};border:1px solid {COLORS["border_gray"]};padding:4px 10px;
                        border-radius:6px;font-size:0.8rem;color:{COLORS["text_primary"]};">
                {token_symbol} <span style="color:{COLORS["text_muted"]};">({chains_count} chains)</span>
            </span>
        """

    tokens_html += f"""
        </div>
        <p style="font-size:0.7rem;color:{COLORS["text_muted"]};margin-top:0.75rem;">
            💡 핫월렛 대량 입금 = 상장 전 토큰 유입 시그널
        </p>
    </div>
    """

    if hasattr(st, 'html'):
        st.html(tokens_html)
    else:
        st.markdown(tokens_html, unsafe_allow_html=True)

    if not alchemy_key:
        st.warning(
            "⚠️ ALCHEMY_API_KEY 환경변수가 설정되지 않았습니다. "
            "핫월렛 잔액 조회를 위해 [Alchemy](https://www.alchemy.com/)에서 무료 API 키를 발급받으세요."
        )


# ------------------------------------------------------------------
# 메인 렌더 함수
# ------------------------------------------------------------------


def render_intel_tab() -> None:
    """분석 인텔리전스 탭 렌더링."""
    import streamlit as st

    conn = get_read_conn()
    conn_id = id(conn)

    # ------------------------------------------------------------------
    # 상장 히스토리 섹션
    # ------------------------------------------------------------------
    listing_history = fetch_listing_history_cached(conn_id, limit=10)
    if listing_history:
        st.markdown(
            '<p style="font-size:1rem;font-weight:600;color:#fff;'
            'margin-bottom:0.75rem;">📋 상장 히스토리 (최근 10건)</p>',
            unsafe_allow_html=True,
        )

        for row in listing_history:
            _render_listing_history_card(row)

        labeled_count = sum(1 for r in listing_history if r.get("result_label"))
        if labeled_count > 0:
            heung_count = sum(
                1 for r in listing_history
                if r.get("result_label") in ("heung", "heung_big")
            )
            mang_count = sum(
                1 for r in listing_history
                if r.get("result_label") == "mang"
            )
            st.markdown(
                f'<p style="font-size:0.85rem;color:#888;margin-top:0.5rem;">'
                f'라벨링: {labeled_count}/{len(listing_history)}건 | '
                f'흥따리: {heung_count}건 | 망따리: {mang_count}건</p>',
                unsafe_allow_html=True,
            )

    # ------------------------------------------------------------------
    # 시나리오 예측 섹션
    # ------------------------------------------------------------------
    _render_scenario_section(conn_id)

    # ------------------------------------------------------------------
    # 백테스트 정확도 섹션
    # ------------------------------------------------------------------
    _render_backtest_accuracy_section()

    # ------------------------------------------------------------------
    # VC/MM 정보 섹션
    # ------------------------------------------------------------------
    _render_vc_mm_section()

    # ------------------------------------------------------------------
    # 토크노믹스 (TGE 언락) 섹션
    # ------------------------------------------------------------------
    _render_tokenomics_section()

    # ------------------------------------------------------------------
    # 핫월렛 모니터링 섹션
    # ------------------------------------------------------------------
    _render_hot_wallet_section()
