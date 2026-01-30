"""따리분석 탭 (Phase 4 + Phase 8).

gate_analysis_log DB에서 최근 분석 결과를 조회하여 표시.

섹션:
  1. 최근 분석 카드 — GO/NO-GO 배지, 프리미엄, 순수익, blockers/warnings
  2. Gate 열화 UI — FX 소스 신뢰도, 헤지 상태, 네트워크 기본값
  3. VASP alt_note 배지
  4. 통계 요약 — GO/NO-GO 건수, 평균 프리미엄, FX 소스 분포
  5. (Phase 8) 후따리 분석 — 2차 펌핑 기회 분석
  6. (Phase 8) 현선갭 모니터 — 국내 현물 vs 글로벌 선물 갭
  7. (Phase 8) 매도 타이밍 — Exit Trigger 상태 및 권장
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections import defaultdict
from pathlib import Path

import yaml

from ui.styles import (
    CARD_STYLE,
    COLORS,
    PREMIUM_THRESHOLDS,
    SECTION_HEADER_STYLE,
    TGE_RISK_GUIDE,
    badge_style,
    result_label_badge,
    RESULT_LABEL_COLORS,
    LISTING_TYPE_COLORS,
)

# Phase 8 모듈 (lazy import for optional dependencies)
try:
    from analysis.post_listing import (
        PostListingPhase,
        PostListingSignal,
        PostListingAnalysis,
    )
    from analysis.spot_futures_gap import (
        HedgeStrategy,
        SpotFuturesGap,
    )
    from analysis.exit_timing import (
        ExitTriggerType,
        ExitUrgency,
        ExitDecision,
    )
    PHASE8_AVAILABLE = True
except ImportError:
    PHASE8_AVAILABLE = False

logger = logging.getLogger(__name__)

# Railway Volume 지원: DATABASE_URL 환경변수 우선
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "ddari.db"
_DB_PATH = Path(os.environ.get("DATABASE_URL", str(_DEFAULT_DB_PATH)))
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


# ------------------------------------------------------------------
# 순수 로직 함수 (streamlit 의존 없음 — 테스트 가능)
# ------------------------------------------------------------------


def _render_degradation_badges(row: dict) -> str:
    """Gate 열화 배지 HTML 생성 (v9)."""
    badges = []

    fx_source = row.get("fx_source", "")
    if fx_source == "hardcoded_fallback":
        badges.append(
            f'<span style="{badge_style(COLORS["danger_dark"])}">FX 기본값 사용</span>'
        )
    elif fx_source and fx_source not in ("btc_implied", "eth_implied"):
        badges.append(
            f'<span style="{badge_style(COLORS["warning_dark"])}">FX 2차 소스</span>'
        )

    hedge = row.get("hedge_type", "")
    if hedge == "none":
        badges.append(
            f'<span style="{badge_style(COLORS["danger_orange"])}">헤지 불가</span>'
        )

    network = row.get("network", "")
    if network == "ethereum":
        badges.append(
            f'<span style="{badge_style(COLORS["neutral"])}">네트워크 기본값</span>'
        )

    return " ".join(badges)


def _render_vasp_badge(exchange: str, vasp_matrix: dict) -> str:
    """VASP alt_note 배지 HTML 생성 (v15)."""
    matrix = vasp_matrix.get("vasp_matrix", {})
    from_routes = matrix.get(exchange, {})
    badges = []

    for to_exchange, route in from_routes.items():
        status = route.get("status", "unknown")
        alt_note = route.get("alt_note", "")

        if status == "blocked":
            badges.append(
                f'<span style="color:{COLORS["danger"]};font-size:0.75rem;">'
                f'{to_exchange}: blocked</span>'
            )
        elif status == "partial":
            note_text = f" — {alt_note}" if alt_note else ""
            badges.append(
                f'<span style="color:{COLORS["warning"]};font-size:0.75rem;">'
                f'{to_exchange}: 일부제한{note_text}</span>'
            )
        elif alt_note:
            badges.append(
                f'<span style="color:{COLORS["neutral"]};font-size:0.75rem;">'
                f'{to_exchange}: {alt_note}</span>'
            )

    return "<br>".join(badges) if badges else ""


# ------------------------------------------------------------------
# Streamlit UI 함수 (lazy import)
# ------------------------------------------------------------------


def _get_read_conn() -> sqlite3.Connection:
    """읽기 전용 DB 커넥션 (세션 수명)."""
    import streamlit as st

    @st.cache_resource
    def _inner():
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    return _inner()


def _load_vasp_matrix_cached() -> dict:
    """VASP 매트릭스 (5분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=300)
    def _inner():
        path = _CONFIG_DIR / "vasp_matrix.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    return _inner()


def _load_vc_tiers_cached() -> dict:
    """VC 티어 데이터 (1시간 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=3600)
    def _inner():
        vc_path = Path(__file__).parent.parent / "data" / "vc_mm_info" / "vc_tiers.yaml"
        if vc_path.exists():
            with open(vc_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    return _inner()


def _load_backtest_results_cached() -> dict:
    """백테스트 결과 (5분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=300)
    def _inner():
        # 백테스트 결과 JSON 파일 경로
        results_path = Path(__file__).parent.parent / "data" / "backtest_results.json"
        if results_path.exists():
            with open(results_path, encoding="utf-8") as f:
                return json.load(f)
        # 파일 없으면 기본값 (WORK_LOG.md 기준)
        return {
            "overall": {"accuracy": 73.1, "count": 67},
            "categories": {
                "heung_big": {"accuracy": 90.5, "count": 21, "label": "대흥따리"},
                "heung": {"accuracy": 76.9, "count": 13, "label": "흥따리"},
                "neutral": {"accuracy": 46.2, "count": 13, "label": "보통"},
                "mang": {"accuracy": 70.0, "count": 20, "label": "망따리"},
            },
            "updated_at": "2026-01-30",
        }

    return _inner()


def _load_unlock_schedules_cached() -> dict:
    """TGE 언락 스케줄 데이터 (1시간 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=3600)
    def _inner():
        unlock_path = Path(__file__).parent.parent / "data" / "tokenomics" / "unlock_schedules.yaml"
        if unlock_path.exists():
            with open(unlock_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    return _inner()


def _load_hot_wallets_cached() -> dict:
    """핫월렛 설정 데이터 (1시간 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=3600)
    def _inner():
        hw_path = Path(__file__).parent.parent / "config" / "hot_wallets.yaml"
        if hw_path.exists():
            with open(hw_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    return _inner()


def _fetch_premium_history_cached(conn_id: int, hours: int = 24) -> list[dict]:
    """프리미엄 히스토리 조회 (차트용, 5분 캐시)."""
    import streamlit as st
    import time

    @st.cache_data(ttl=300)
    def _inner(_conn_id: int, _hours: int) -> list[dict]:
        conn = _get_read_conn()
        try:
            # 최근 N시간 데이터 (심볼별 프리미엄 추이)
            cutoff = time.time() - (_hours * 3600)
            rows = conn.execute(
                """
                SELECT
                    timestamp, symbol, exchange, premium_pct,
                    can_proceed, alert_level
                FROM gate_analysis_log
                WHERE timestamp > ? AND premium_pct IS NOT NULL
                ORDER BY timestamp ASC
                """,
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, hours)


def _fetch_recent_analyses_cached(conn_id: int, limit: int = 20) -> list[dict]:
    """최근 Gate 분석 결과 조회 (1분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=60)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = _get_read_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM gate_analysis_log ORDER BY timestamp DESC LIMIT ?",
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, limit)


def _fetch_stats_cached(conn_id: int) -> dict:
    """통계 요약 (1시간 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=3600)
    def _inner(_conn_id: int) -> dict:
        conn = _get_read_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM gate_analysis_log"
            ).fetchone()["cnt"]

            go_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM gate_analysis_log WHERE can_proceed = 1"
            ).fetchone()["cnt"]

            avg_premium = conn.execute(
                "SELECT AVG(premium_pct) as avg_p FROM gate_analysis_log "
                "WHERE premium_pct IS NOT NULL"
            ).fetchone()["avg_p"]

            fx_dist = conn.execute(
                "SELECT fx_source, COUNT(*) as cnt FROM gate_analysis_log "
                "WHERE fx_source IS NOT NULL GROUP BY fx_source ORDER BY cnt DESC"
            ).fetchall()

            return {
                "total": total,
                "go_count": go_count,
                "nogo_count": total - go_count,
                "avg_premium": avg_premium or 0.0,
                "fx_distribution": {r["fx_source"]: r["cnt"] for r in fx_dist},
            }
        except sqlite3.OperationalError:
            return {"total": 0, "go_count": 0, "nogo_count": 0,
                    "avg_premium": 0.0, "fx_distribution": {}}

    return _inner(conn_id)


def _fetch_listing_history_cached(conn_id: int, limit: int = 20) -> list[dict]:
    """상장 히스토리 조회 (5분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=300)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = _get_read_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM listing_history ORDER BY listing_time DESC LIMIT ?",
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            # 테이블 없을 수 있음
            return []

    return _inner(conn_id, limit)


def _render_result_label_badge(label: str | None) -> str:
    """결과 라벨 배지 HTML 생성 (styles.py 위임)."""
    return result_label_badge(label)


def _render_listing_history_card(row: dict) -> None:
    """상장 히스토리 카드 렌더링."""
    import streamlit as st
    from datetime import datetime

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
    result_badge = _render_result_label_badge(result_label)

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
# 시나리오 카드 렌더링 함수 (Phase 7)
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


def _fetch_scenario_data_cached(conn_id: int, limit: int = 5) -> list[dict]:
    """최근 상장에 대한 시나리오 데이터 조회 (1분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=60)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = _get_read_conn()
        try:
            # listing_history에서 최근 데이터 조회
            rows = conn.execute(
                """
                SELECT symbol, exchange, listing_type, hedge_type, result_label,
                       premium_pct, max_premium_pct, listing_time
                FROM listing_history
                ORDER BY listing_time DESC
                LIMIT ?
                """,
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, limit)


def _render_scenario_section(conn_id: int) -> None:
    """시나리오 예측 섹션 렌더링."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">🎯 시나리오 예측</p>',
        unsafe_allow_html=True,
    )

    # 최근 상장 데이터 조회
    recent_listings = _fetch_scenario_data_cached(conn_id, limit=5)

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
            # 실제 결과 기반 확률 (후행 정보)
            prob_map = {"heung_big": 0.95, "heung": 0.80, "neutral": 0.50, "mang": 0.30}
            heung_prob = prob_map.get(result_label, 0.5)
        else:
            # 간단한 휴리스틱 예측 (실제로는 ScenarioPlanner 사용)
            if hedge_type == "none":
                predicted_outcome = "heung"
                heung_prob = 0.70
            elif listing_type == "TGE":
                predicted_outcome = "heung"
                heung_prob = 0.60
            else:
                predicted_outcome = "neutral"
                heung_prob = 0.50

        # Supply class 추정 (hedge_type 기반)
        supply_class = "constrained" if hedge_type == "none" else "smooth"

        # Factors 생성
        factors = []
        if listing_type:
            type_names = {"TGE": "세계 최초 상장", "DIRECT": "직상장", "SIDE": "옆상장"}
            factors.append(f"상장 유형: {type_names.get(listing_type, listing_type)}")
        if premium is not None:
            factors.append(f"진입 프리미엄: {premium:+.1f}%")
        if max_premium is not None:
            factors.append(f"최대 프리미엄: {max_premium:+.1f}%")

        # Warnings
        warnings = []
        if result_label is None:
            warnings.append("결과 미확정 (예측값)")
        if hedge_type == "none":
            warnings.append("헤징 불가 - 리스크 주의")

        # 시나리오 카드 렌더링
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
            confidence=0.73 if result_label else 0.60,  # 백테스트 정확도
            scenario_type="likely",
        )

        if hasattr(st, 'html'):
            st.html(card_html)
        else:
            st.markdown(card_html, unsafe_allow_html=True)


def _render_vc_mm_section() -> None:
    """VC/MM 정보 섹션 렌더링 (YAML에서 동적 로드)."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">💼 VC/MM 인텔리전스</p>',
        unsafe_allow_html=True,
    )

    # YAML에서 VC/MM 데이터 로드
    vc_data = _load_vc_tiers_cached()

    # Tier 1 VC 리스트 (YAML에서 동적 로드)
    tier1_vcs = []
    for vc in vc_data.get("tier1", []):
        tier1_vcs.append({
            "name": vc.get("name", "Unknown"),
            "roi": vc.get("avg_listing_roi", 0),
            "portfolio": vc.get("portfolio_size", 0),
        })

    # MM 리스트 (YAML에서 동적 로드)
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

    # 메타데이터
    metadata = vc_data.get("metadata", {})
    total_tier1 = metadata.get("total_tier1_vcs", len(tier1_vcs))
    updated_at = metadata.get("updated_at", "N/A")

    # Tier 1 VC 카드 (상위 8개만 표시, 나머지는 +N)
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

    # MM 리스크 카드
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


def _render_backtest_accuracy_section() -> None:
    """백테스트 정확도 섹션 렌더링 (동적 로드)."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">📊 백테스트 정확도</p>',
        unsafe_allow_html=True,
    )

    # 백테스트 결과 동적 로드
    backtest_data = _load_backtest_results_cached()
    overall = backtest_data.get("overall", {"accuracy": 0, "count": 0})
    categories = backtest_data.get("categories", {})
    updated_at = backtest_data.get("updated_at", "N/A")

    # 카테고리별 색상 매핑 (COLORS 사용)
    color_map = {
        "heung_big": COLORS["success"],
        "heung": COLORS["info"],
        "neutral": COLORS["warning"],
        "mang": COLORS["danger"],
    }

    # 메트릭 카드
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

    # 상세 바 차트 (HTML)
    bars_html = ""
    for cat_key, cat_data in categories.items():
        label = cat_data.get("label", cat_key)
        accuracy = cat_data.get("accuracy", 0)
        count = cat_data.get("count", 0)
        color = color_map.get(cat_key, COLORS["neutral"])
        width = min(accuracy, 100)  # 100% 초과 방지

        bars_html += f"""
        <div style="margin-bottom:0.5rem;">
            <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
                <span style="font-size:0.8rem;color:{COLORS["text_secondary"]};">{label}</span>
                <span style="font-size:0.8rem;color:{COLORS["text_primary"]};">{accuracy:.1f}% ({count}건)</span>
            </div>
            <div style="background:#2d2d2d;border-radius:4px;height:8px;overflow:hidden;"><!-- progress bar bg -->
                <div style="background:{color};width:{width}%;height:100%;"></div>
            </div>
        </div>
        """

    # 달성 상태 표시
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


def _render_tokenomics_section() -> None:
    """토크노믹스 (TGE 언락) 섹션 렌더링 (Phase 7 Quick Win #1)."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">🔓 TGE 언락 분석</p>',
        unsafe_allow_html=True,
    )

    # 언락 스케줄 데이터 로드
    unlock_data = _load_unlock_schedules_cached()
    tokens = unlock_data.get("tokens", {})
    risk_scoring = unlock_data.get("risk_scoring", {})
    category_risk = unlock_data.get("category_risk", {})

    if not tokens:
        st.info("언락 스케줄 데이터가 없습니다.")
        return

    # 리스크 레벨별 색상 (COLORS 사용)
    risk_colors = {
        "VERY_LOW": COLORS["risk_very_low"],
        "LOW": COLORS["risk_low"],
        "MEDIUM": COLORS["risk_medium"],
        "HIGH": COLORS["risk_high"],
        "VERY_HIGH": COLORS["risk_very_high"],
    }

    # 리스크 레벨별 이모지
    risk_emoji = {
        "VERY_LOW": "🟢",
        "LOW": "🟢",
        "MEDIUM": "🟡",
        "HIGH": "🟠",
        "VERY_HIGH": "🔴",
    }

    # 토큰을 리스크별로 그룹화
    risk_groups = {"VERY_HIGH": [], "HIGH": [], "MEDIUM": [], "LOW": [], "VERY_LOW": []}
    for symbol, data in tokens.items():
        risk = data.get("risk_assessment", "MEDIUM")
        if risk in risk_groups:
            risk_groups[risk].append((symbol, data))

    # 고위험 토큰 경고 카드
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
        for symbol, data in high_risk_tokens[:6]:  # 최대 6개
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

    # 토큰 상세 테이블 (확장 가능)
    with st.expander("📋 전체 토큰 언락 스케줄", expanded=False):
        # 테이블 헤더
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

        # 리스크 순으로 정렬 (높은 것 먼저)
        sorted_tokens = []
        for risk_level in ["VERY_HIGH", "HIGH", "MEDIUM", "LOW", "VERY_LOW"]:
            sorted_tokens.extend(risk_groups.get(risk_level, []))

        for symbol, data in sorted_tokens:
            name = data.get("name", symbol)
            tge_pct = data.get("tge_unlock_pct", 0)
            cliff = data.get("cliff_months", 0)
            vesting = data.get("vesting_months", 0)
            risk = data.get("risk_assessment", "MEDIUM")
            reason = data.get("reason", "")

            color = risk_colors.get(risk, COLORS["warning"])
            emoji = risk_emoji.get(risk, "🟡")

            # TGE 색상 (높을수록 빨강)
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

    # TGE 리스크 기준 안내 (styles.py에서 import)
    if hasattr(st, 'html'):
        st.html(TGE_RISK_GUIDE)
    else:
        st.markdown(TGE_RISK_GUIDE, unsafe_allow_html=True)


def _render_premium_chart_section(conn_id: int) -> None:
    """실시간 프리미엄 차트 섹션 (Phase 7 Week 4)."""
    import streamlit as st
    from datetime import datetime

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">📈 프리미엄 추이 차트</p>',
        unsafe_allow_html=True,
    )

    # 최근 24시간 프리미엄 히스토리 조회
    premium_history = _fetch_premium_history_cached(conn_id, hours=24)

    if not premium_history:
        st.info("프리미엄 데이터가 없습니다. Gate 분석이 실행되면 차트가 표시됩니다.")
        return

    # 심볼별로 데이터 그룹화 (defaultdict로 간소화)
    symbols_data = defaultdict(lambda: {"timestamps": [], "premiums": []})
    for row in premium_history:
        symbol = row.get("symbol", "unknown")
        symbols_data[symbol]["timestamps"].append(row["timestamp"])
        symbols_data[symbol]["premiums"].append(row["premium_pct"] or 0)

    if not symbols_data:
        st.info("차트에 표시할 데이터가 없습니다.")
        return

    # 심볼 선택 (최근 활성 심볼 기준)
    recent_symbols = list(symbols_data.keys())[-10:]  # 최근 10개 심볼
    selected_symbol = st.selectbox(
        "심볼 선택",
        recent_symbols,
        index=len(recent_symbols) - 1 if recent_symbols else 0,
        key="premium_chart_symbol",
    )

    if selected_symbol and selected_symbol in symbols_data:
        data = symbols_data[selected_symbol]

        # pandas 없이 간단한 차트 구현
        try:
            import pandas as pd

            df = pd.DataFrame({
                "시간": [datetime.fromtimestamp(ts) for ts in data["timestamps"]],
                "프리미엄 (%)": data["premiums"],
            })
            df = df.set_index("시간")

            # 라인 차트
            st.line_chart(df, use_container_width=True)

            # 통계 표시
            premiums = data["premiums"]
            if premiums:
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("현재", f"{premiums[-1]:.2f}%")
                with col2:
                    st.metric("최고", f"{max(premiums):.2f}%")
                with col3:
                    st.metric("최저", f"{min(premiums):.2f}%")
                with col4:
                    avg_premium = sum(premiums) / len(premiums)
                    st.metric("평균", f"{avg_premium:.2f}%")

        except ImportError:
            # pandas 없으면 간단한 텍스트 표시
            st.warning("pandas 미설치 — 차트 대신 텍스트로 표시합니다.")
            premiums = data["premiums"]
            if premiums:
                st.write(f"**{selected_symbol}** 프리미엄 데이터 ({len(premiums)}건)")
                st.write(f"- 현재: {premiums[-1]:.2f}%")
                st.write(f"- 최고: {max(premiums):.2f}%")
                st.write(f"- 최저: {min(premiums):.2f}%")

    # 프리미엄 임계값 안내 (styles.py에서 import)
    if hasattr(st, 'html'):
        st.html(PREMIUM_THRESHOLDS)
    else:
        st.markdown(PREMIUM_THRESHOLDS, unsafe_allow_html=True)


def _render_hot_wallet_section() -> None:
    """핫월렛 모니터링 섹션 (Phase 7 Week 5)."""
    import streamlit as st

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">🔥 핫월렛 모니터링</p>',
        unsafe_allow_html=True,
    )

    # 핫월렛 설정 로드
    hw_data = _load_hot_wallets_cached()
    exchanges = hw_data.get("exchanges", {})
    common_tokens = hw_data.get("common_tokens", {})

    if not exchanges:
        st.info("핫월렛 데이터가 없습니다.")
        return

    # API 키 상태 확인
    import os
    alchemy_key = os.environ.get("ALCHEMY_API_KEY", "")
    api_status = "🟢 연결됨" if alchemy_key else "🔴 API 키 없음"
    api_color = COLORS["success"] if alchemy_key else COLORS["danger"]

    # 헤더 카드
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

    # 거래소별 핫월렛 현황 (확장 가능)
    with st.expander("📋 등록된 거래소 핫월렛", expanded=False):
        # 거래소별 지갑 수 집계
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

        # 테이블 HTML
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

    # 지원 토큰 카드
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

    # API 키 없으면 안내
    if not alchemy_key:
        st.warning(
            "⚠️ ALCHEMY_API_KEY 환경변수가 설정되지 않았습니다. "
            "핫월렛 잔액 조회를 위해 [Alchemy](https://www.alchemy.com/)에서 무료 API 키를 발급받으세요."
        )


# ------------------------------------------------------------------
# Phase 8: 후따리 분석 섹션
# ------------------------------------------------------------------


def _fetch_post_listing_data_cached(conn_id: int, limit: int = 5) -> list[dict]:
    """후따리 분석 데이터 조회 (1분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=60)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = _get_read_conn()
        try:
            # post_listing_analysis 테이블에서 조회 (없으면 listing_history 기반)
            rows = conn.execute(
                """
                SELECT symbol, exchange, listing_time, phase, signal,
                       time_score, price_score, volume_score, premium_score,
                       total_score, confidence, reason
                FROM post_listing_analysis
                ORDER BY analyzed_at DESC
                LIMIT ?
                """,
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            # 테이블 없으면 빈 리스트
            return []

    return _inner(conn_id, limit)


def _render_post_listing_card_html(data: dict) -> str:
    """후따리 분석 카드 HTML 생성."""
    symbol = data.get("symbol", "?")
    exchange = data.get("exchange", "?")
    phase = data.get("phase", "unknown")
    signal = data.get("signal", "hold")
    total_score = data.get("total_score", 0)
    confidence = data.get("confidence", 0)
    reason = data.get("reason", "")

    # Phase별 스타일
    phase_styles = {
        "initial_pump": {"emoji": "🚀", "name": "초기 펌핑", "color": COLORS["success"]},
        "first_dump": {"emoji": "📉", "name": "1차 덤핑", "color": COLORS["danger"]},
        "consolidation": {"emoji": "📊", "name": "횡보 구간", "color": COLORS["neutral"]},
        "second_pump": {"emoji": "🔥", "name": "2차 펌핑", "color": COLORS["warning"]},
        "fade_out": {"emoji": "💤", "name": "소강 국면", "color": COLORS["text_muted"]},
    }
    phase_style = phase_styles.get(phase, {"emoji": "❓", "name": phase, "color": COLORS["neutral"]})

    # Signal별 스타일
    signal_styles = {
        "strong_buy": {"emoji": "🔥🔥", "name": "강력 매수", "bg": COLORS["success"]},
        "buy": {"emoji": "✨", "name": "매수", "bg": COLORS["info"]},
        "hold": {"emoji": "⏸️", "name": "관망", "bg": COLORS["neutral"]},
        "avoid": {"emoji": "🚫", "name": "회피", "bg": COLORS["danger"]},
    }
    signal_style = signal_styles.get(signal, {"emoji": "❓", "name": signal, "bg": COLORS["neutral"]})

    # 점수 바
    score_width = min(total_score * 10, 100)  # 0-10 → 0-100%
    score_color = (
        COLORS["success"] if total_score >= 7 else
        COLORS["info"] if total_score >= 5 else
        COLORS["warning"] if total_score >= 3 else
        COLORS["danger"]
    )

    # 개별 점수
    time_score = data.get("time_score", 0)
    price_score = data.get("price_score", 0)
    volume_score = data.get("volume_score", 0)
    premium_score = data.get("premium_score", 0)

    return f"""
    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <div>
                <span style="font-size:1.1rem;font-weight:600;color:{COLORS["text_primary"]};">{symbol}</span>
                <span style="color:{COLORS["text_tertiary"]};font-size:0.8rem;margin-left:0.5rem;">@{exchange}</span>
            </div>
            <div style="display:flex;gap:0.5rem;align-items:center;">
                <span style="{badge_style(phase_style['color'], size='0.75rem')}">{phase_style['emoji']} {phase_style['name']}</span>
                <span style="background:{signal_style['bg']};color:{COLORS["text_primary"]};padding:4px 12px;
                            border-radius:6px;font-weight:600;font-size:0.85rem;">
                    {signal_style['emoji']} {signal_style['name']}
                </span>
            </div>
        </div>
        <div style="margin:0.75rem 0;">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                <span style="font-size:0.8rem;color:{COLORS["text_secondary"]};">종합 점수</span>
                <span style="font-size:0.8rem;color:{score_color};font-weight:600;">{total_score:.1f}/10</span>
            </div>
            <div style="background:#2d2d2d;border-radius:4px;height:8px;overflow:hidden;">
                <div style="background:{score_color};width:{score_width}%;height:100%;"></div>
            </div>
        </div>
        <div style="display:flex;gap:1rem;font-size:0.75rem;color:{COLORS["text_tertiary"]};margin-bottom:0.5rem;">
            <span>시간: {time_score:.1f}</span>
            <span>가격: {price_score:.1f}</span>
            <span>거래량: {volume_score:.1f}</span>
            <span>프리미엄: {premium_score:.1f}</span>
        </div>
        {f'<p style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin:0;">{reason}</p>' if reason else ''}
        <div style="margin-top:0.5rem;font-size:0.7rem;color:{COLORS["text_muted"]};">
            신뢰도: {confidence*100:.0f}%
        </div>
    </div>
    """


def _render_post_listing_section(conn_id: int) -> None:
    """후따리 분석 섹션 렌더링 (Phase 8)."""
    import streamlit as st

    if not PHASE8_AVAILABLE:
        return

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">🔥 후따리 분석 (2차 펌핑 기회)</p>',
        unsafe_allow_html=True,
    )

    # 데이터 조회
    post_listing_data = _fetch_post_listing_data_cached(conn_id, limit=5)

    if not post_listing_data:
        # 데이터 없으면 설명 카드 표시
        info_html = f"""
        <div style="{CARD_STYLE}">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">
                📊 후따리 전략이란?
            </p>
            <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin-bottom:0.75rem;">
                상장 직후 초기 펌핑 → 1차 덤핑 후 발생하는 <b>2차 펌핑 기회</b>를 포착하는 전략입니다.
            </p>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.5rem;">
                <span style="{badge_style(COLORS["success"], size="0.7rem")}">🚀 초기 펌핑 (0-10분)</span>
                <span style="{badge_style(COLORS["danger"], size="0.7rem")}">📉 1차 덤핑 (10-30분)</span>
                <span style="{badge_style(COLORS["neutral"], size="0.7rem")}">📊 횡보 (30분-2시간)</span>
                <span style="{badge_style(COLORS["warning"], size="0.7rem")}">🔥 2차 펌핑 (기회)</span>
            </div>
            <p style="font-size:0.75rem;color:{COLORS["text_muted"]};">
                💡 상장 감지 시 자동으로 분석이 시작됩니다.
            </p>
        </div>
        """
        if hasattr(st, 'html'):
            st.html(info_html)
        else:
            st.markdown(info_html, unsafe_allow_html=True)
        return

    # 분석 결과 카드들
    for data in post_listing_data:
        card_html = _render_post_listing_card_html(data)
        if hasattr(st, 'html'):
            st.html(card_html)
        else:
            st.markdown(card_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# Phase 8: 현선갭 모니터 섹션
# ------------------------------------------------------------------


def _fetch_spot_futures_gap_cached(conn_id: int, limit: int = 5) -> list[dict]:
    """현선갭 데이터 조회 (30초 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=30)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = _get_read_conn()
        try:
            rows = conn.execute(
                """
                SELECT symbol, domestic_exchange, global_exchange,
                       domestic_price_krw, global_price_usd, fx_rate,
                       gap_pct, hedge_strategy, is_profitable,
                       estimated_profit_pct, created_at
                FROM spot_futures_gap
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, limit)


def _render_spot_futures_gap_card_html(data: dict) -> str:
    """현선갭 카드 HTML 생성."""
    symbol = data.get("symbol", "?")
    domestic_ex = data.get("domestic_exchange", "upbit")
    global_ex = data.get("global_exchange", "binance")
    domestic_price = data.get("domestic_price_krw", 0)
    global_price = data.get("global_price_usd", 0)
    fx_rate = data.get("fx_rate", 1350)
    gap_pct = data.get("gap_pct", 0)
    hedge_strategy = data.get("hedge_strategy", "no_hedge")
    is_profitable = data.get("is_profitable", False)
    profit_pct = data.get("estimated_profit_pct", 0)

    # 갭 색상
    if gap_pct > 3:
        gap_color = COLORS["success"]
        gap_emoji = "🔥"
    elif gap_pct > 1:
        gap_color = COLORS["info"]
        gap_emoji = "✨"
    elif gap_pct < -1:
        gap_color = COLORS["danger"]
        gap_emoji = "📉"
    else:
        gap_color = COLORS["neutral"]
        gap_emoji = "➖"

    # 헤지 전략 스타일
    hedge_styles = {
        "long_global_short_domestic": {"name": "해외 롱 / 국내 숏", "emoji": "🔄"},
        "short_global_long_domestic": {"name": "해외 숏 / 국내 롱", "emoji": "🔄"},
        "no_hedge": {"name": "헤지 불가", "emoji": "🚫"},
    }
    hedge_style = hedge_styles.get(hedge_strategy, {"name": hedge_strategy, "emoji": "❓"})

    # 수익성 배지
    profit_badge = ""
    if is_profitable:
        profit_badge = f'<span style="{badge_style(COLORS["success"], size="0.7rem")}">💰 +{profit_pct:.2f}%</span>'

    # 가격 포맷
    domestic_str = f"₩{domestic_price:,.0f}" if domestic_price else "-"
    global_str = f"${global_price:,.4f}" if global_price else "-"

    return f"""
    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <div>
                <span style="font-size:1.1rem;font-weight:600;color:{COLORS["text_primary"]};">{symbol}</span>
                <span style="color:{gap_color};font-size:1rem;font-weight:600;margin-left:0.75rem;">
                    {gap_emoji} {gap_pct:+.2f}%
                </span>
            </div>
            {profit_badge}
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.85rem;margin-bottom:0.5rem;">
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">{domestic_ex.upper()}</span>
                <span style="margin-left:0.5rem;font-weight:600;color:{COLORS["warning"]};">{domestic_str}</span>
            </div>
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">{global_ex.upper()}</span>
                <span style="margin-left:0.5rem;font-weight:600;color:{COLORS["info"]};">{global_str}</span>
            </div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:{COLORS["text_muted"]};">
            <span>FX: ₩{fx_rate:,.0f}/USD</span>
            <span>{hedge_style['emoji']} {hedge_style['name']}</span>
        </div>
    </div>
    """


def _render_spot_futures_gap_section(conn_id: int) -> None:
    """현선갭 모니터 섹션 렌더링 (Phase 8)."""
    import streamlit as st

    if not PHASE8_AVAILABLE:
        return

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">📊 현선갭 모니터</p>',
        unsafe_allow_html=True,
    )

    # 데이터 조회
    gap_data = _fetch_spot_futures_gap_cached(conn_id, limit=5)

    if not gap_data:
        info_html = f"""
        <div style="{CARD_STYLE}">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">
                🔄 현선갭 (Spot-Futures Gap)이란?
            </p>
            <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin-bottom:0.75rem;">
                국내 거래소(업비트/빗썸) 현물 가격과 해외 거래소(바이낸스/바이빗) 선물 가격의 차이입니다.
                갭이 크면 아비트라지 기회가 발생합니다.
            </p>
            <div style="display:flex;gap:1rem;font-size:0.8rem;margin-bottom:0.5rem;">
                <div>
                    <span style="color:{COLORS["success"]};">+3% 이상</span>
                    <span style="color:{COLORS["text_muted"]};"> = 강한 김프</span>
                </div>
                <div>
                    <span style="color:{COLORS["danger"]};">-3% 이하</span>
                    <span style="color:{COLORS["text_muted"]};"> = 역프</span>
                </div>
            </div>
            <p style="font-size:0.75rem;color:{COLORS["text_muted"]};">
                💡 상장 감지 시 자동으로 갭 계산이 시작됩니다.
            </p>
        </div>
        """
        if hasattr(st, 'html'):
            st.html(info_html)
        else:
            st.markdown(info_html, unsafe_allow_html=True)
        return

    # 갭 카드들
    for data in gap_data:
        card_html = _render_spot_futures_gap_card_html(data)
        if hasattr(st, 'html'):
            st.html(card_html)
        else:
            st.markdown(card_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# Phase 8: 매도 타이밍 섹션
# ------------------------------------------------------------------


def _fetch_exit_timing_cached(conn_id: int, limit: int = 5) -> list[dict]:
    """매도 타이밍 데이터 조회 (15초 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=15)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = _get_read_conn()
        try:
            rows = conn.execute(
                """
                SELECT symbol, exchange, should_exit, trigger_type, urgency,
                       reason, current_premium_pct, entry_premium_pct,
                       peak_premium_pct, position_duration_min, created_at
                FROM exit_timing
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, limit)


def _render_exit_timing_card_html(data: dict) -> str:
    """매도 타이밍 카드 HTML 생성."""
    symbol = data.get("symbol", "?")
    exchange = data.get("exchange", "?")
    should_exit = data.get("should_exit", False)
    trigger_type = data.get("trigger_type", "none")
    urgency = data.get("urgency", "low")
    reason = data.get("reason", "")
    current_prem = data.get("current_premium_pct", 0)
    entry_prem = data.get("entry_premium_pct", 0)
    peak_prem = data.get("peak_premium_pct", 0)
    duration_min = data.get("position_duration_min", 0)

    # Urgency 스타일
    urgency_styles = {
        "critical": {"emoji": "🚨", "name": "즉시 청산", "bg": COLORS["danger"], "border": COLORS["danger"]},
        "high": {"emoji": "⚠️", "name": "긴급", "bg": COLORS["warning"], "border": COLORS["warning"]},
        "medium": {"emoji": "📊", "name": "주의", "bg": COLORS["info"], "border": COLORS["info"]},
        "low": {"emoji": "✅", "name": "정상", "bg": COLORS["success"], "border": COLORS["success"]},
    }
    urg_style = urgency_styles.get(urgency, urgency_styles["low"])

    # Trigger 타입 스타일
    trigger_styles = {
        "premium_target": {"emoji": "🎯", "name": "목표가 도달"},
        "premium_floor": {"emoji": "🔻", "name": "손절선 이탈"},
        "time_limit": {"emoji": "⏰", "name": "시간 초과"},
        "volume_spike": {"emoji": "📈", "name": "거래량 급증"},
        "premium_reversal": {"emoji": "↩️", "name": "프리미엄 반전"},
        "trailing_stop": {"emoji": "📉", "name": "추적 손절"},
        "manual": {"emoji": "✋", "name": "수동"},
        "none": {"emoji": "➖", "name": "없음"},
    }
    trig_style = trigger_styles.get(trigger_type, {"emoji": "❓", "name": trigger_type})

    # 카드 테두리 색상 (should_exit이면 강조)
    border_color = urg_style["border"] if should_exit else COLORS["card_border"]

    # 프리미엄 변화
    prem_change = current_prem - entry_prem
    prem_change_color = COLORS["success"] if prem_change > 0 else COLORS["danger"]

    # 시간 포맷
    if duration_min >= 60:
        duration_str = f"{duration_min // 60}시간 {duration_min % 60}분"
    else:
        duration_str = f"{duration_min}분"

    return f"""
    <div style="background:{COLORS["card_bg"]};border:2px solid {border_color};
                border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <div>
                <span style="font-size:1.1rem;font-weight:600;color:{COLORS["text_primary"]};">{symbol}</span>
                <span style="color:{COLORS["text_tertiary"]};font-size:0.8rem;margin-left:0.5rem;">@{exchange}</span>
            </div>
            <div style="display:flex;gap:0.5rem;align-items:center;">
                <span style="{badge_style(COLORS["neutral"] if not should_exit else urg_style["bg"], size="0.75rem")}">{trig_style['emoji']} {trig_style['name']}</span>
                {f'<span style="background:{urg_style["bg"]};color:{COLORS["text_primary"]};padding:4px 12px;border-radius:6px;font-weight:600;font-size:0.85rem;">{urg_style["emoji"]} {urg_style["name"]}</span>' if should_exit else ''}
            </div>
        </div>
        <div style="display:flex;gap:1.5rem;font-size:0.85rem;margin-bottom:0.5rem;">
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">현재</span>
                <span style="margin-left:4px;font-weight:600;color:{COLORS["text_accent"]};">{current_prem:+.2f}%</span>
            </div>
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">진입</span>
                <span style="margin-left:4px;">{entry_prem:+.2f}%</span>
            </div>
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">최고</span>
                <span style="margin-left:4px;color:{COLORS["success"]};">{peak_prem:+.2f}%</span>
            </div>
            <div style="color:{COLORS["text_secondary"]};">
                <span style="color:{COLORS["text_muted"]};">변화</span>
                <span style="margin-left:4px;color:{prem_change_color};">{prem_change:+.2f}%</span>
            </div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:{COLORS["text_muted"]};">
            <span>포지션 유지: {duration_str}</span>
            {f'<span style="color:{urg_style["border"]};">{reason}</span>' if reason else ''}
        </div>
    </div>
    """


def _render_exit_timing_section(conn_id: int) -> None:
    """매도 타이밍 섹션 렌더링 (Phase 8)."""
    import streamlit as st

    if not PHASE8_AVAILABLE:
        return

    st.markdown(
        f'<p style="{SECTION_HEADER_STYLE}">⏰ 매도 타이밍</p>',
        unsafe_allow_html=True,
    )

    # 데이터 조회
    exit_data = _fetch_exit_timing_cached(conn_id, limit=5)

    if not exit_data:
        info_html = f"""
        <div style="{CARD_STYLE}">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">
                ⏰ 매도 타이밍 엔진
            </p>
            <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin-bottom:0.75rem;">
                포지션 진입 후 최적의 청산 시점을 자동으로 감지합니다.
            </p>
            <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.5rem;">
                <span style="{badge_style(COLORS["success"], size="0.7rem")}">🎯 목표가 도달</span>
                <span style="{badge_style(COLORS["danger"], size="0.7rem")}">🔻 손절선 이탈</span>
                <span style="{badge_style(COLORS["warning"], size="0.7rem")}">⏰ 시간 초과</span>
                <span style="{badge_style(COLORS["info"], size="0.7rem")}">📈 거래량 급증</span>
                <span style="{badge_style(COLORS["neutral"], size="0.7rem")}">↩️ 프리미엄 반전</span>
            </div>
            <p style="font-size:0.75rem;color:{COLORS["text_muted"]};">
                💡 포지션 진입 시 자동으로 모니터링이 시작됩니다.
            </p>
        </div>
        """
        if hasattr(st, 'html'):
            st.html(info_html)
        else:
            st.markdown(info_html, unsafe_allow_html=True)
        return

    # 긴급 청산 알림 (critical/high urgency)
    urgent_positions = [d for d in exit_data if d.get("should_exit") and d.get("urgency") in ("critical", "high")]
    if urgent_positions:
        alert_html = f"""
        <div style="background:rgba(239,68,68,0.15);border:1px solid {COLORS["danger"]};
                    border-radius:12px;padding:1rem;margin-bottom:1rem;">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["danger"]};margin-bottom:0.5rem;">
                🚨 긴급 청산 필요: {len(urgent_positions)}건
            </p>
            <div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
        """
        for pos in urgent_positions:
            alert_html += f"""
                <span style="{badge_style(COLORS["danger_dark"], size="0.8rem")}">{pos.get("symbol", "?")} {pos.get("current_premium_pct", 0):+.1f}%</span>
            """
        alert_html += """
            </div>
        </div>
        """
        if hasattr(st, 'html'):
            st.html(alert_html)
        else:
            st.markdown(alert_html, unsafe_allow_html=True)

    # 타이밍 카드들
    for data in exit_data:
        card_html = _render_exit_timing_card_html(data)
        if hasattr(st, 'html'):
            st.html(card_html)
        else:
            st.markdown(card_html, unsafe_allow_html=True)


def _render_vcmm_badge(row: dict) -> str:
    """VC/MM 정보 배지 HTML 생성 (v10)."""
    badges = []

    # VC Tier 1 투자자
    vc_tier1_json = row.get("vc_tier1_investors")
    if vc_tier1_json:
        try:
            tier1_list = json.loads(vc_tier1_json)
            if tier1_list:
                # 최대 3개만 표시
                display_vcs = tier1_list[:3]
                vc_text = ", ".join(display_vcs)
                if len(tier1_list) > 3:
                    vc_text += f" +{len(tier1_list)-3}"
                badges.append(
                    f'<span style="{badge_style(COLORS["success_dark"], size="0.7rem")}">⭐ {vc_text}</span>'
                )
        except (json.JSONDecodeError, TypeError):
            pass

    # VC 리스크 레벨
    vc_risk = row.get("vc_risk_level")
    if vc_risk == "high":
        badges.append(
            f'<span style="{badge_style(COLORS["danger_dark"], size="0.7rem")}">VC 리스크 높음</span>'
        )

    # MM 정보
    mm_name = row.get("mm_name")
    mm_risk = row.get("mm_risk_score")
    if mm_name:
        if mm_risk is not None and mm_risk >= 7:
            mm_color = COLORS["danger_dark"]
            mm_emoji = "🔴"
        elif mm_risk is not None and mm_risk >= 4:
            mm_color = COLORS["warning"]
            mm_emoji = "🟡"
        else:
            mm_color = COLORS["success_dark"]
            mm_emoji = "🟢"

        risk_text = f" ({mm_risk:.1f})" if mm_risk is not None else ""
        badges.append(
            f'<span style="{badge_style(mm_color, size="0.7rem")}">{mm_emoji} MM: {mm_name}{risk_text}</span>'
        )

    # 펀딩 정보
    funding = row.get("vc_total_funding_usd")
    if funding and funding > 0:
        if funding >= 100_000_000:
            funding_text = f"${funding/1_000_000:.0f}M"
        elif funding >= 1_000_000:
            funding_text = f"${funding/1_000_000:.1f}M"
        else:
            funding_text = f"${funding/1_000:.0f}K"
        badges.append(
            f'<span style="{badge_style(COLORS["info"], size="0.7rem")}">💰 {funding_text}</span>'
        )

    return " ".join(badges)


def _render_analysis_card(row: dict, vasp_matrix: dict) -> None:
    """개별 분석 결과 카드 렌더링."""
    import streamlit as st
    from datetime import datetime

    symbol = row.get("symbol", "?")
    exchange = row.get("exchange", "?")
    can_proceed = row.get("can_proceed", 0)
    alert_level = row.get("alert_level", "INFO")
    premium = row.get("premium_pct")
    net_profit = row.get("net_profit_pct")
    total_cost = row.get("total_cost_pct")
    fx_source = row.get("fx_source", "")
    duration_ms = row.get("gate_duration_ms")
    ts = row.get("timestamp", 0)

    # GO/NO-GO 배지
    if can_proceed:
        status_badge = (
            f'<span style="background:{COLORS["success_dark"]};color:{COLORS["text_primary"]};padding:3px 10px;'
            'border-radius:6px;font-weight:600;">GO</span>'
        )
    else:
        status_badge = (
            f'<span style="background:{COLORS["danger_dark"]};color:{COLORS["text_primary"]};padding:3px 10px;'
            'border-radius:6px;font-weight:600;">NO-GO</span>'
        )

    # 시간 포맷
    time_str = datetime.fromtimestamp(ts).strftime("%m/%d %H:%M:%S") if ts else "?"

    # 메트릭 텍스트
    premium_text = f"{premium:.2f}%" if premium is not None else "N/A"
    profit_text = f"{net_profit:.2f}%" if net_profit is not None else "N/A"
    cost_text = f"{total_cost:.2f}%" if total_cost is not None else "N/A"
    duration_text = f"{duration_ms:.0f}ms" if duration_ms is not None else "N/A"

    # Blockers/Warnings
    blockers = json.loads(row.get("blockers_json", "[]") or "[]")
    warnings = json.loads(row.get("warnings_json", "[]") or "[]")

    blockers_html = ""
    if blockers:
        items = "".join(
            f'<li style="color:{COLORS["danger"]};font-size:0.8rem;">{b}</li>'
            for b in blockers
        )
        blockers_html = f'<ul style="margin:0.3rem 0;padding-left:1.2rem;">{items}</ul>'

    warnings_html = ""
    if warnings:
        items = "".join(
            f'<li style="color:{COLORS["warning"]};font-size:0.8rem;">{w}</li>'
            for w in warnings
        )
        warnings_html = f'<ul style="margin:0.3rem 0;padding-left:1.2rem;">{items}</ul>'

    # 열화 배지
    degradation = _render_degradation_badges(row)
    degradation_html = f'<div style="margin-top:0.3rem;">{degradation}</div>' if degradation else ""

    # VASP 배지
    vasp = _render_vasp_badge(exchange, vasp_matrix)
    vasp_html = f'<div style="margin-top:0.3rem;">{vasp}</div>' if vasp else ""

    # VC/MM 배지 (Phase 7)
    vcmm = _render_vcmm_badge(row)
    vcmm_html = f'<div style="margin-top:0.4rem;display:flex;gap:0.4rem;flex-wrap:wrap;">{vcmm}</div>' if vcmm else ""

    card_html = f"""
    <div style="{CARD_STYLE}">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <div>
                <span style="font-size:1.1rem;font-weight:600;color:{COLORS["text_primary"]};">{symbol}</span>
                <span style="color:{COLORS["text_tertiary"]};font-size:0.8rem;margin-left:0.5rem;">@{exchange}</span>
                <span style="color:{COLORS["text_muted"]};font-size:0.75rem;margin-left:0.5rem;">[{alert_level}]</span>
            </div>
            <div>
                {status_badge}
                <span style="color:{COLORS["text_muted"]};font-size:0.75rem;margin-left:0.5rem;">{time_str}</span>
            </div>
        </div>
        <div style="display:flex;gap:1.5rem;font-size:0.85rem;color:{COLORS["text_secondary"]};margin-bottom:0.3rem;">
            <span>프리미엄: <b style="color:{COLORS["text_accent"]};">{premium_text}</b></span>
            <span>순수익: <b style="color:{COLORS["text_profit"]};">{profit_text}</b></span>
            <span>비용: <b style="color:{COLORS["warning"]};">{cost_text}</b></span>
            <span>FX: <b>{fx_source or 'N/A'}</b></span>
            <span>소요: <b>{duration_text}</b></span>
        </div>
        {vcmm_html}
        {blockers_html}
        {warnings_html}
        {degradation_html}
        {vasp_html}
    </div>
    """
    # st.html()이 있으면 사용, 없으면 markdown 사용
    if hasattr(st, 'html'):
        st.html(card_html)
    else:
        st.markdown(card_html, unsafe_allow_html=True)


def render_ddari_tab() -> None:
    """따리분석 탭 렌더링 (app.py에서 호출)."""
    import streamlit as st

    conn = _get_read_conn()
    conn_id = id(conn)

    vasp_matrix = _load_vasp_matrix_cached()
    analyses = _fetch_recent_analyses_cached(conn_id, limit=20)

    if not analyses:
        st.markdown(
            f'<div style="text-align:center;padding:3rem;color:{COLORS["text_muted"]};">'
            '<p style="font-size:1.2rem;">분석 기록 없음</p>'
            '<p style="font-size:0.85rem;">수집 데몬이 실행 중이고 새 상장이 감지되면 '
            '여기에 Gate 분석 결과가 표시됩니다.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # 헤더
    st.markdown(
        '<p style="font-size:1rem;font-weight:600;color:#fff;margin-bottom:0.75rem;">'
        'Gate 분석 결과 (최근 20건)</p>',
        unsafe_allow_html=True,
    )

    # 분석 카드 목록
    for row in analyses:
        _render_analysis_card(row, vasp_matrix)

    # 통계 요약
    stats = _fetch_stats_cached(conn_id)
    if stats["total"] > 0:
        st.markdown(
            '<p style="font-size:1rem;font-weight:600;color:#fff;'
            'margin-top:1.5rem;margin-bottom:0.75rem;">통계 요약</p>',
            unsafe_allow_html=True,
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("전체 분석", f"{stats['total']}건")
        with col2:
            st.metric("GO", f"{stats['go_count']}건")
        with col3:
            st.metric("NO-GO", f"{stats['nogo_count']}건")
        with col4:
            st.metric("평균 프리미엄", f"{stats['avg_premium']:.2f}%")

        # FX 소스 분포
        if stats["fx_distribution"]:
            st.markdown(
                f'<p style="font-size:0.85rem;font-weight:500;color:{COLORS["text_secondary"]};'
                'margin-top:0.5rem;">FX 소스 분포</p>',
                unsafe_allow_html=True,
            )
            dist_items = []
            for source, count in stats["fx_distribution"].items():
                pct = count / stats["total"] * 100
                dist_items.append(
                    f'<span style="color:{COLORS["text_tertiary"]};font-size:0.8rem;">'
                    f'{source}: {count}건 ({pct:.0f}%)</span>'
                )
            st.markdown(
                " &nbsp;|&nbsp; ".join(dist_items),
                unsafe_allow_html=True,
            )

    # ------------------------------------------------------------------
    # 상장 히스토리 섹션 (Phase 5a)
    # ------------------------------------------------------------------
    listing_history = _fetch_listing_history_cached(conn_id, limit=10)
    if listing_history:
        st.markdown(
            '<p style="font-size:1rem;font-weight:600;color:#fff;'
            'margin-top:1.5rem;margin-bottom:0.75rem;">📋 상장 히스토리 (최근 10건)</p>',
            unsafe_allow_html=True,
        )

        for row in listing_history:
            _render_listing_history_card(row)

        # 라벨별 통계
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
    # 시나리오 예측 섹션 (Phase 7 Quick Win)
    # ------------------------------------------------------------------
    _render_scenario_section(conn_id)

    # ------------------------------------------------------------------
    # 백테스트 정확도 섹션
    # ------------------------------------------------------------------
    _render_backtest_accuracy_section()

    # ------------------------------------------------------------------
    # VC/MM 정보 섹션 (Phase 7 Week 3)
    # ------------------------------------------------------------------
    _render_vc_mm_section()

    # ------------------------------------------------------------------
    # 토크노믹스 (TGE 언락) 섹션 (Phase 7 Quick Win #1)
    # ------------------------------------------------------------------
    _render_tokenomics_section()

    # ------------------------------------------------------------------
    # 실시간 프리미엄 차트 (Phase 7 Week 4)
    # ------------------------------------------------------------------
    _render_premium_chart_section(conn_id)

    # ------------------------------------------------------------------
    # 핫월렛 모니터링 (Phase 7 Week 5)
    # ------------------------------------------------------------------
    _render_hot_wallet_section()

    # ------------------------------------------------------------------
    # Phase 8: 후따리 / 현선갭 / 매도 타이밍 (Week 7-8)
    # ------------------------------------------------------------------
    if PHASE8_AVAILABLE:
        st.markdown(
            '<p style="font-size:1.2rem;font-weight:700;color:#fff;'
            'margin-top:2rem;margin-bottom:1rem;border-bottom:1px solid #333;'
            'padding-bottom:0.5rem;">🎯 Phase 8: 후따리 전략</p>',
            unsafe_allow_html=True,
        )

        # 후따리 분석
        _render_post_listing_section(conn_id)

        # 현선갭 모니터
        _render_spot_futures_gap_section(conn_id)

        # 매도 타이밍
        _render_exit_timing_section(conn_id)
