"""따리분석 공통 유틸리티 모듈.

DB 연결, 캐시된 로더, 배지 헬퍼 등 공통 함수들.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
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

logger = logging.getLogger(__name__)

# Railway Volume 지원: DATABASE_URL 환경변수 우선
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "ddari.db"
_DB_PATH = Path(os.environ.get("DATABASE_URL", str(_DEFAULT_DB_PATH)))
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

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
except ImportError as e:
    logger.warning(f"Phase 8 모듈 로드 실패: {e}")
    PHASE8_AVAILABLE = False


# ------------------------------------------------------------------
# DB 연결
# ------------------------------------------------------------------


def get_read_conn() -> sqlite3.Connection:
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


# ------------------------------------------------------------------
# 캐시된 데이터 로더 (YAML)
# ------------------------------------------------------------------


def load_vasp_matrix_cached() -> dict:
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


def load_vc_tiers_cached() -> dict:
    """VC 티어 데이터 (1시간 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=3600)
    def _inner():
        vc_path = _DATA_DIR / "vc_mm_info" / "vc_tiers.yaml"
        if vc_path.exists():
            with open(vc_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    return _inner()


def load_backtest_results_cached() -> dict:
    """백테스트 결과 (5분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=300)
    def _inner():
        results_path = _DATA_DIR / "backtest_results.json"
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


def load_unlock_schedules_cached() -> dict:
    """TGE 언락 스케줄 데이터 (1시간 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=3600)
    def _inner():
        unlock_path = _DATA_DIR / "tokenomics" / "unlock_schedules.yaml"
        if unlock_path.exists():
            with open(unlock_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    return _inner()


def load_hot_wallets_cached() -> dict:
    """핫월렛 설정 데이터 (1시간 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=3600)
    def _inner():
        hw_path = _CONFIG_DIR / "hot_wallets.yaml"
        if hw_path.exists():
            with open(hw_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    return _inner()


# ------------------------------------------------------------------
# 캐시된 DB 쿼리
# ------------------------------------------------------------------


def fetch_recent_analyses_cached(conn_id: int, limit: int = 20) -> list[dict]:
    """최근 Gate 분석 결과 조회 (1분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=60)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = get_read_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM gate_analysis_log ORDER BY timestamp DESC LIMIT ?",
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, limit)


def fetch_stats_cached(conn_id: int) -> dict:
    """통계 요약 (1시간 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=3600)
    def _inner(_conn_id: int) -> dict:
        conn = get_read_conn()
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


def fetch_premium_history_cached(conn_id: int, hours: int = 24) -> list[dict]:
    """프리미엄 히스토리 조회 (차트용, 5분 캐시)."""
    import streamlit as st
    import time

    @st.cache_data(ttl=300)
    def _inner(_conn_id: int, _hours: int) -> list[dict]:
        conn = get_read_conn()
        try:
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


def fetch_listing_history_cached(conn_id: int, limit: int = 20) -> list[dict]:
    """상장 히스토리 조회 (5분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=300)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = get_read_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM listing_history ORDER BY listing_time DESC LIMIT ?",
                (_limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    return _inner(conn_id, limit)


def fetch_scenario_data_cached(conn_id: int, limit: int = 5) -> list[dict]:
    """최근 상장에 대한 시나리오 데이터 조회 (1분 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=60)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = get_read_conn()
        try:
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


# ------------------------------------------------------------------
# 순수 로직 함수 (배지 렌더링)
# ------------------------------------------------------------------


def render_degradation_badges(row: dict) -> str:
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


def render_vasp_badge(exchange: str, vasp_matrix: dict) -> str:
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


def render_vcmm_badge(row: dict) -> str:
    """VC/MM 정보 배지 HTML 생성 (v10)."""
    badges = []

    # VC Tier 1 투자자
    vc_tier1_json = row.get("vc_tier1_investors")
    if vc_tier1_json:
        try:
            tier1_list = json.loads(vc_tier1_json)
            if tier1_list:
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


def render_result_label_badge(label: str | None) -> str:
    """결과 라벨 배지 HTML 생성 (styles.py 위임)."""
    return result_label_badge(label)


def get_market_mood_cached() -> dict:
    """시장 분위기 데이터 (1분 캐시).

    Returns:
        dict: {emoji, text, color, kr_dominance, kr_volume, gl_volume}
    """
    import streamlit as st
    import asyncio

    @st.cache_data(ttl=60)
    def _inner() -> dict:
        try:
            # app.py의 fetch_all_data와 동일한 로직
            config_path = Path(__file__).resolve().parent.parent / "config.yaml"
            if not config_path.exists():
                return _default_mood()

            import yaml
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)

            from dominance import DominanceCalculator

            async def _fetch():
                calc = DominanceCalculator(config)
                await calc.initialize()
                total = await calc.calculate_total_market(
                    ["BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT"], "24h"
                )
                await calc.close()
                return total

            total = asyncio.run(_fetch())
            if not total:
                return _default_mood()

            kr_dom = total.korean_dominance
            kr_vol = total.korean_volume_usd
            gl_vol = total.global_volume_usd

            # 분위기 판단
            if kr_dom > 5:
                emoji, text, color = "🔥", "활발", "#4ade80"
            elif kr_dom > 2:
                emoji, text, color = "✨", "양호", "#60a5fa"
            elif kr_dom > 0.5:
                emoji, text, color = "😐", "보통", "#fbbf24"
            else:
                emoji, text, color = "😴", "한산", "#94a3b8"

            return {
                "emoji": emoji,
                "text": text,
                "color": color,
                "kr_dominance": kr_dom,
                "kr_volume": kr_vol,
                "gl_volume": gl_vol,
            }

        except Exception as e:
            logger.warning(f"Market mood fetch error: {e}")
            return _default_mood()

    return _inner()


def _default_mood() -> dict:
    """기본 시장 분위기 (데이터 없을 때)."""
    return {
        "emoji": "❓",
        "text": "확인중",
        "color": "#6b7280",
        "kr_dominance": None,
        "kr_volume": None,
        "gl_volume": None,
    }


# Re-export for convenience
__all__ = [
    # Constants
    "CARD_STYLE",
    "COLORS",
    "PREMIUM_THRESHOLDS",
    "SECTION_HEADER_STYLE",
    "TGE_RISK_GUIDE",
    "RESULT_LABEL_COLORS",
    "LISTING_TYPE_COLORS",
    "PHASE8_AVAILABLE",
    # Functions
    "badge_style",
    "get_read_conn",
    "load_vasp_matrix_cached",
    "load_vc_tiers_cached",
    "load_backtest_results_cached",
    "load_unlock_schedules_cached",
    "load_hot_wallets_cached",
    "fetch_recent_analyses_cached",
    "fetch_stats_cached",
    "fetch_premium_history_cached",
    "fetch_listing_history_cached",
    "fetch_scenario_data_cached",
    "render_degradation_badges",
    "render_vasp_badge",
    "render_vcmm_badge",
    "render_result_label_badge",
    "get_market_mood_cached",
]
