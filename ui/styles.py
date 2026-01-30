"""UI 스타일 상수 (Phase 7 리팩토링).

ddari_tab.py의 인라인 CSS를 재사용 가능한 상수로 추출.
"""

# =============================================================================
# 기본 컬러 팔레트
# =============================================================================

COLORS = {
    # 상태 색상
    "success": "#22c55e",      # 초록 (GO, 흥따리)
    "success_dark": "#059669", # 진한 초록
    "warning": "#f59e0b",      # 주황 (경고)
    "warning_dark": "#d97706", # 진한 주황
    "danger": "#ef4444",       # 빨강 (NO-GO, 망따리)
    "danger_dark": "#dc2626",  # 진한 빨강
    "danger_orange": "#ea580c", # 주황빨강
    "info": "#3b82f6",         # 파랑 (정보)
    "purple": "#8b5cf6",       # 보라 (TGE)
    "neutral": "#6b7280",      # 회색 (중립)
    "neutral_light": "#a3a3a3", # 밝은 회색
    # 배경/테두리
    "card_bg": "rgba(255,255,255,0.03)",
    "card_border": "rgba(255,255,255,0.08)",
    "card_border_hover": "rgba(255,255,255,0.1)",
    "bg_dark": "#1f1f1f",
    "bg_card": "#1f2937",
    "border_dark": "#333",
    "border_gray": "#374151",
    "border_light": "#4b5563",
    # 텍스트
    "text_primary": "#fff",
    "text_secondary": "#a0a0a0",
    "text_tertiary": "#8b8b8b",
    "text_muted": "#6b7280",
    "text_dim": "#9ca3af",
    "text_accent": "#00d4ff",
    "text_profit": "#10b981",
    # 리스크 레벨
    "risk_very_low": "#22c55e",
    "risk_low": "#84cc16",
    "risk_medium": "#f59e0b",
    "risk_high": "#f97316",
    "risk_very_high": "#ef4444",
}

# =============================================================================
# 공통 스타일 상수
# =============================================================================

# 카드 컨테이너
CARD_STYLE = (
    f"background:{COLORS['card_bg']};"
    f"border:1px solid {COLORS['card_border']};"
    "border-radius:12px;padding:1rem;margin-bottom:0.75rem;"
)

# 테이블 컨테이너
TABLE_CONTAINER_STYLE = (
    f"background:{COLORS['card_bg']};"
    f"border:1px solid {COLORS['card_border']};"
    "border-radius:8px;overflow:hidden;"
)

# 섹션 헤더
SECTION_HEADER_STYLE = (
    f"font-size:1rem;font-weight:600;color:{COLORS['text_primary']};"
    "margin-top:1.5rem;margin-bottom:0.75rem;"
)

# 서브헤더
SUB_HEADER_STYLE = (
    f"font-size:0.85rem;font-weight:500;color:{COLORS['text_secondary']};"
    "margin-top:0.5rem;"
)

# =============================================================================
# 배지 스타일 생성 함수
# =============================================================================


def badge_style(bg_color: str, text_color: str = "#fff", size: str = "0.75rem") -> str:
    """배지 인라인 스타일 생성."""
    return (
        f"background:{bg_color};color:{text_color};"
        f"padding:2px 8px;border-radius:4px;font-size:{size};"
    )


def status_badge(status: str) -> str:
    """상태별 배지 HTML 생성 (GO/NO-GO 등)."""
    configs = {
        "go": (COLORS["success"], "GO"),
        "nogo": (COLORS["danger"], "NO-GO"),
        "warning": (COLORS["warning"], "WARNING"),
    }
    bg, text = configs.get(status.lower(), (COLORS["neutral"], status.upper()))
    return f'<span style="{badge_style(bg)};font-weight:600;">{text}</span>'


def risk_badge(level: str, show_emoji: bool = True) -> str:
    """리스크 레벨 배지 HTML 생성."""
    configs = {
        "VERY_LOW": (COLORS["risk_very_low"], "🟢" if show_emoji else ""),
        "LOW": (COLORS["risk_low"], "🟢" if show_emoji else ""),
        "MEDIUM": (COLORS["risk_medium"], "🟡" if show_emoji else ""),
        "HIGH": (COLORS["risk_high"], "🟠" if show_emoji else ""),
        "VERY_HIGH": (COLORS["risk_very_high"], "🔴" if show_emoji else ""),
    }
    color, emoji = configs.get(level.upper(), (COLORS["neutral"], ""))
    prefix = f"{emoji} " if emoji else ""
    return f'<span style="color:{color};">{prefix}{level}</span>'


# =============================================================================
# 결과 라벨 (따리 분류)
# =============================================================================

RESULT_LABEL_COLORS = {
    "heung_big": (COLORS["success"], "대흥따리"),
    "heung": (COLORS["info"], "흥따리"),
    "neutral": (COLORS["neutral"], "보통"),
    "mang": (COLORS["danger"], "망따리"),
}


def result_label_badge(label: str | None) -> str:
    """결과 라벨 배지 HTML 생성."""
    if not label:
        return f'<span style="{badge_style(COLORS["neutral"])}">미분류</span>'
    bg, text = RESULT_LABEL_COLORS.get(label, (COLORS["neutral"], label))
    return f'<span style="{badge_style(bg)}">{text}</span>'


# =============================================================================
# 상장 유형
# =============================================================================

LISTING_TYPE_COLORS = {
    "TGE": "#8b5cf6",       # 보라
    "DIRECT": "#3b82f6",    # 파랑
    "SIDE": "#f59e0b",      # 주황
    "UNKNOWN": "#6b7280",   # 회색
}


def listing_type_badge(listing_type: str) -> str:
    """상장 유형 배지 HTML 생성."""
    bg = LISTING_TYPE_COLORS.get(listing_type, COLORS["neutral"])
    return f'<span style="{badge_style(bg, size="0.7rem")}">{listing_type}</span>'


# =============================================================================
# 프리미엄 기준 테이블
# =============================================================================

PREMIUM_THRESHOLDS = """
<div style="{card}">
    <p style="font-size:0.85rem;font-weight:600;color:{info};margin-bottom:0.5rem;">
        📖 프리미엄 기준 (따리 판정)
    </p>
    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:0.5rem;font-size:0.75rem;">
        <div><span style="color:{success};">🟢 대흥따리:</span> 프리미엄 15%+</div>
        <div><span style="color:{info};">🔵 흥따리:</span> 프리미엄 8-15%</div>
        <div><span style="color:{warning};">🟡 보통:</span> 프리미엄 3-8%</div>
        <div><span style="color:{danger};">🔴 망따리:</span> 프리미엄 3% 미만</div>
    </div>
    <p style="font-size:0.7rem;color:{muted};margin-top:0.5rem;">
        💡 프리미엄 = (국내가격 - 글로벌가격) / 글로벌가격 × 100
    </p>
</div>
""".format(
    card=CARD_STYLE,
    info=COLORS["info"],
    success=COLORS["success"],
    warning=COLORS["warning"],
    danger=COLORS["danger"],
    muted=COLORS["text_muted"],
)


# =============================================================================
# TGE 리스크 기준 테이블
# =============================================================================

TGE_RISK_GUIDE = """
<div style="{card}">
    <p style="font-size:0.85rem;font-weight:600;color:{info};margin-bottom:0.5rem;">
        📖 TGE 리스크 기준
    </p>
    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:0.5rem;font-size:0.75rem;">
        <div><span style="color:{danger};">🔴 매우 높음:</span> TGE 15%+</div>
        <div><span style="color:{high};">🟠 높음:</span> TGE 10-15%</div>
        <div><span style="color:{warning};">🟡 보통:</span> TGE 5-10%</div>
        <div><span style="color:{success};">🟢 낮음:</span> TGE 5% 미만</div>
    </div>
    <p style="font-size:0.7rem;color:{muted};margin-top:0.5rem;">
        💡 TGE 언락 = 상장 당일 시장에 풀리는 물량 비율. 높을수록 덤핑 압력 ↑
    </p>
</div>
""".format(
    card=CARD_STYLE,
    info=COLORS["info"],
    success=COLORS["success"],
    warning=COLORS["warning"],
    high=COLORS["risk_high"],
    danger=COLORS["danger"],
    muted=COLORS["text_muted"],
)
