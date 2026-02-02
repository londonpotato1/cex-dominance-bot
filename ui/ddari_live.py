"""따리분석 실시간 현황 탭 (Tab 1).

시간이 중요한 정보: Gate 분석, 통계, 프리미엄 차트, 현선갭 모니터.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime

from ui.ddari_common import (
    CARD_STYLE,
    COLORS,
    PREMIUM_THRESHOLDS,
    SECTION_HEADER_STYLE,
    PHASE8_AVAILABLE,
    badge_style,
    get_read_conn,
    load_vasp_matrix_cached,
    fetch_recent_analyses_cached,
    fetch_stats_cached,
    fetch_premium_history_cached,
    fetch_recent_trend_cached,
    render_degradation_badges,
    render_vasp_badge,
    render_vcmm_badge,
    get_market_mood_cached,
    fetch_funding_rates_cached,
    render_html,
)

# v2: 바이낸스 공지 수집기 import
try:
    from collectors.binance_notice import BinanceNoticeFetcher, BinanceListingStrategy
    _HAS_BINANCE = True
except ImportError:
    _HAS_BINANCE = False
    BinanceNoticeFetcher = None
    BinanceListingStrategy = None

# v3: 상장 인텔리전스 수집기
try:
    from collectors.listing_intel import ListingIntelCollector, ListingIntel
    _HAS_INTEL = True
except ImportError:
    _HAS_INTEL = False
    ListingIntelCollector = None
    ListingIntel = None


# ------------------------------------------------------------------
# v2: 바이낸스 상장 알림 섹션
# ------------------------------------------------------------------

def _render_binance_alerts_section() -> None:
    """바이낸스 상장 알림 섹션 렌더링 (v3: 종합 인텔리전스 포함)."""
    import streamlit as st
    import asyncio
    
    if not _HAS_BINANCE:
        return
    
    # 캐싱: 5분마다 갱신
    @st.cache_data(ttl=300)
    def fetch_binance_notices():
        async def _fetch():
            fetcher = BinanceNoticeFetcher()
            try:
                notices = await fetcher.fetch_all_listings(page_size=5)
                return notices
            finally:
                await fetcher.close()
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_fetch())
        except Exception as e:
            return []
    
    @st.cache_data(ttl=300)
    def fetch_listing_intel(symbol: str):
        if not _HAS_INTEL or not ListingIntelCollector:
            return None
        
        async def _fetch():
            collector = ListingIntelCollector()
            try:
                return await collector.collect(symbol)
            finally:
                await collector.close()
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_fetch())
        except Exception as e:
            return None
    
    notices = fetch_binance_notices()
    
    # 중요한 공지만 필터 (Seed Tag, 현물 상장)
    important = [n for n in notices if n.seed_tag or n.has_spot]
    
    if not important:
        return  # 중요 공지 없으면 표시 안함
    
    # 최신 공지만 표시
    latest = important[0]
    symbol = latest.symbols[0] if latest.symbols else None
    
    # 전략 분석
    strategy = None
    if symbol and BinanceListingStrategy:
        strategy = BinanceListingStrategy(symbol=symbol, notice=latest).analyze()
    
    # 종합 인텔리전스 수집
    intel = fetch_listing_intel(symbol) if symbol else None
    
    # 유형별 색상
    if latest.seed_tag:
        badge_color = "#f59e0b"
        badge_text = "🌱 Seed Tag"
        border_color = "#f59e0b"
    elif latest.has_spot:
        badge_color = "#3b82f6"
        badge_text = "📈 현물 상장"
        border_color = "#3b82f6"
    else:
        badge_color = "#6b7280"
        badge_text = "📢 공지"
        border_color = "#6b7280"
    
    # 거래소 상태 HTML 생성
    exchange_html = ""
    if intel and intel.exchanges:
        ex_items = []
        for ex_name, ex_status in intel.exchanges.items():
            spot_icon = "✅" if ex_status.has_spot else "❌"
            futures_icon = "✅" if ex_status.has_futures else "❌"
            ex_items.append(f"<span style='margin-right:8px;'>{ex_name.upper()}: S{spot_icon} F{futures_icon}</span>")
        exchange_html = " ".join(ex_items)
    
    # 토크노믹스 HTML
    tokenomics_html = ""
    if intel:
        parts = []
        if intel.total_supply:
            parts.append(f"Total: {intel.total_supply/1e9:.1f}B")
        if intel.circulating_percent:
            parts.append(f"Circ: {intel.circulating_percent:.0f}%")
        if intel.futures_price_usd:
            parts.append(f"Price: ${intel.futures_price_usd:.4f}")
        tokenomics_html = " · ".join(parts)
    
    # 체인/플랫폼 HTML
    platforms_html = ""
    if intel and intel.platforms:
        platform_short = {"ethereum": "ETH", "binance-smart-chain": "BSC", "solana": "SOL", "arbitrum": "ARB", "polygon": "MATIC"}
        platforms = [platform_short.get(p, p.upper()[:4]) for p in intel.platforms[:4]]
        platforms_html = " · ".join(platforms)
    
    # 전략 액션
    actions_html = ""
    if strategy and strategy.actions:
        actions_html = " | ".join([f"{a}" for a in strategy.actions[:2]])
    
    render_html(f'''
    <div style="background:linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border:2px solid {border_color};border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        
        <!-- 헤더 -->
        <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.75rem;">
            <div style="flex:1;">
                <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;">
                    <span style="background:{badge_color};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.7rem;font-weight:600;">
                        {badge_text}
                    </span>
                    <span style="font-size:0.7rem;color:#6b7280;">바이낸스</span>
                </div>
                <div style="font-size:1.1rem;font-weight:700;color:#fff;">
                    {symbol if symbol else 'N/A'} {f'<span style="font-size:0.75rem;font-weight:400;color:#9ca3af;">({intel.name})</span>' if intel and intel.name else ''}
                </div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:1.4rem;font-weight:700;color:{border_color};">
                    {strategy.score if strategy else 0}점
                </div>
                <div style="font-size:0.7rem;color:#6b7280;">따리 스코어</div>
            </div>
        </div>
        
        <!-- 토크노믹스 & 체인 -->
        {f'<div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:0.5rem;font-size:0.75rem;"><span style="color:#60a5fa;">📊 {tokenomics_html}</span><span style="color:#a78bfa;">🔗 {platforms_html}</span></div>' if tokenomics_html or platforms_html else ''}
        
        <!-- 거래소 상태 -->
        {f'<div style="background:rgba(0,0,0,0.3);border-radius:8px;padding:0.5rem;margin-bottom:0.5rem;font-size:0.7rem;color:#9ca3af;">🏦 {exchange_html}</div>' if exchange_html else ''}
        
        <!-- 전략 액션 -->
        {f'<div style="border-top:1px solid rgba(255,255,255,0.1);padding-top:0.5rem;color:#fbbf24;font-size:0.75rem;">🎯 {actions_html}</div>' if actions_html else ''}
    </div>
    ''')


# ------------------------------------------------------------------
# GO 스코어 계산 (통합 점수)
# ------------------------------------------------------------------


def _calculate_go_score(row: dict, trend: dict = None) -> tuple[int, list[tuple[str, int, str]]]:
    """통합 GO 스코어 계산 (0-100).
    
    Args:
        row: Gate 분석 결과
        trend: 직전 상장 트렌드 (optional)
    
    Returns:
        tuple: (총점, [(항목, 점수, 이유), ...])
    """
    score = 50  # 기본 점수
    breakdown = []
    
    # 1. 프리미엄 (+/- 20점)
    premium = row.get("premium_pct")
    if premium is not None:
        if premium >= 10:
            score += 20
            breakdown.append(("프리미엄", 20, f"{premium:+.1f}% (매우 높음)"))
        elif premium >= 5:
            score += 15
            breakdown.append(("프리미엄", 15, f"{premium:+.1f}% (높음)"))
        elif premium >= 3:
            score += 10
            breakdown.append(("프리미엄", 10, f"{premium:+.1f}% (양호)"))
        elif premium >= 0:
            score += 5
            breakdown.append(("프리미엄", 5, f"{premium:+.1f}% (낮음)"))
        else:
            score -= 10
            breakdown.append(("프리미엄", -10, f"{premium:+.1f}% (역프!)"))
    
    # 2. 순수익 (+/- 15점)
    net_profit = row.get("net_profit_pct")
    if net_profit is not None:
        if net_profit >= 5:
            score += 15
            breakdown.append(("순수익", 15, f"{net_profit:+.1f}% (높음)"))
        elif net_profit >= 2:
            score += 10
            breakdown.append(("순수익", 10, f"{net_profit:+.1f}% (양호)"))
        elif net_profit >= 0:
            score += 5
            breakdown.append(("순수익", 5, f"{net_profit:+.1f}% (낮음)"))
        else:
            score -= 15
            breakdown.append(("순수익", -15, f"{net_profit:+.1f}% (손실)"))
    
    # 3. 직전 상장 트렌드 (+/- 10점)
    if trend:
        heung_rate = trend.get("heung_rate", 50)
        if heung_rate >= 60:
            score += 10
            breakdown.append(("직전상장", 10, f"{heung_rate:.0f}% 흥행 (좋음)"))
        elif heung_rate >= 40:
            score += 0
            breakdown.append(("직전상장", 0, f"{heung_rate:.0f}% 흥행 (보통)"))
        else:
            score -= 10
            breakdown.append(("직전상장", -10, f"{heung_rate:.0f}% 흥행 (냉각)"))
    
    # 4. 헤지 가능 여부 (+/- 10점)
    hedge_type = row.get("hedge_type", "")
    if hedge_type and hedge_type != "none":
        score += 10
        breakdown.append(("헤지", 10, f"{hedge_type} 가능"))
    elif hedge_type == "none":
        score -= 10
        breakdown.append(("헤지", -10, "불가 (리스크!)"))
    
    # 5. FX 신뢰도 (+/- 5점)
    fx_source = row.get("fx_source", "")
    if fx_source in ("btc_implied", "eth_implied"):
        score += 5
        breakdown.append(("FX 신뢰도", 5, "정확한 소스"))
    elif fx_source == "hardcoded_fallback":
        score -= 10
        breakdown.append(("FX 신뢰도", -10, "기본값 사용"))
    
    # 범위 제한 (0-100)
    score = max(0, min(100, score))
    
    return score, breakdown


# ------------------------------------------------------------------
# Gate 분석 카드 (Phase 2.2: GO 스코어 포함)
# ------------------------------------------------------------------


def _calculate_confidence_score(row: dict) -> tuple[int, str]:
    """신뢰도 점수 계산 (0-100).
    
    Returns:
        tuple: (점수, 주요 감점 사유)
    """
    score = 100
    reasons = []
    
    # 1. FX 소스 신뢰도 (-20점)
    fx_source = row.get("fx_source", "")
    if fx_source == "hardcoded_fallback":
        score -= 30
        reasons.append("FX 기본값")
    elif fx_source == "cache":
        score -= 10
        reasons.append("캐시 FX")
    
    # 2. 프리미엄 정보 유무 (-15점)
    if row.get("premium_pct") is None:
        score -= 15
        reasons.append("프리미엄 없음")
    
    # 3. 순수익 마진 (마이너스면 감점)
    net_profit = row.get("net_profit_pct")
    if net_profit is not None:
        if net_profit < 0:
            score -= 20
            reasons.append("순수익 마이너스")
        elif net_profit < 1:
            score -= 10
            reasons.append("순수익 낮음")
    
    # 4. Blockers/Warnings 개수
    blockers = json.loads(row.get("blockers_json", "[]") or "[]")
    warnings = json.loads(row.get("warnings_json", "[]") or "[]")
    
    if blockers:
        score -= len(blockers) * 10
        reasons.append(f"차단 {len(blockers)}건")
    if warnings:
        score -= len(warnings) * 5
    
    # 5. 분석 속도 (느리면 감점)
    duration_ms = row.get("gate_duration_ms")
    if duration_ms and duration_ms > 5000:
        score -= 10
        reasons.append("분석 지연")
    
    score = max(0, min(100, score))
    reason = reasons[0] if reasons else ""
    
    return score, reason


def _render_confidence_bar(score: int) -> str:
    """신뢰도 바 HTML 생성."""
    filled = score // 10
    empty = 10 - filled
    
    if score >= 70:
        color = "#4ade80"  # 녹색
    elif score >= 40:
        color = "#fbbf24"  # 노랑
    else:
        color = "#f87171"  # 빨강
    
    bar = f'<span style="color:{color};">{"█" * filled}</span>'
    bar += f'<span style="color:#374151;">{"░" * empty}</span>'
    
    return f'{bar} <span style="color:{color};font-weight:600;">{score}%</span>'


def _render_traffic_light(can_proceed: bool, score: int, has_warnings: bool) -> str:
    """신호등 HTML 생성."""
    if can_proceed:
        if score >= 70 and not has_warnings:
            # 🟢 GO - 높은 신뢰도
            return '<span style="font-size:1.8rem;">🟢</span> <span style="font-size:1.4rem;font-weight:700;color:#4ade80;">GO</span>'
        else:
            # 🟡 GO - 주의 필요
            return '<span style="font-size:1.8rem;">🟡</span> <span style="font-size:1.4rem;font-weight:700;color:#fbbf24;">GO</span>'
    else:
        # 🔴 NO-GO
        return '<span style="font-size:1.8rem;">🔴</span> <span style="font-size:1.4rem;font-weight:700;color:#f87171;">NO-GO</span>'


def _build_strategy_summary_html(row: dict) -> str:
    """GO 카드용 전략 요약 HTML 생성.
    
    row에서 관련 필드를 가져와 간단한 전략 추천을 생성.
    
    Args:
        row: Gate 분석 결과 데이터
        
    Returns:
        전략 요약 HTML 문자열
    """
    # === 데이터 추출 ===
    # 현선갭: spot_futures_gap_pct 또는 premium_pct 기반으로 추정
    spot_futures_gap = row.get("spot_futures_gap_pct")
    premium_pct = row.get("premium_pct") or 0
    
    # 현선갭이 없으면 프리미엄 기반으로 간접 추정 (실제로는 다름)
    gap_pct = spot_futures_gap if spot_futures_gap is not None else None
    
    # 론 정보
    loan_available = row.get("loan_available", False)
    best_loan_exchange = row.get("best_loan_exchange")
    best_loan_rate = row.get("best_loan_rate")  # 시간당 이자율 (%)
    
    # DEX 유동성
    dex_liquidity_usd = row.get("dex_liquidity_usd")
    
    # 네트워크 정보
    network_chain = row.get("network_chain") or row.get("best_network")
    network_speed = row.get("network_speed")
    
    # 헤지 타입
    hedge_type = row.get("hedge_type", "")
    hedge_exchange = row.get("hedge_exchange", "")
    
    # === 전략 결정 로직 ===
    strategy_text = ""
    strategy_color = "#4ade80"  # 기본 녹색
    
    if gap_pct is not None:
        if gap_pct < 2:
            if loan_available:
                strategy_text = "헷지 갭익절 (론 빌려서 헷지)"
                strategy_color = "#4ade80"  # 녹색
            else:
                strategy_text = "현물 선따리 (헷지 불가)"
                strategy_color = "#60a5fa"  # 파랑
        elif gap_pct < 5:
            strategy_text = "헷지 비용 고려 필요"
            strategy_color = "#fbbf24"  # 노랑
        else:
            strategy_text = "후따리 대기 (갭 높음)"
            strategy_color = "#f87171"  # 빨강
    else:
        # 갭 정보 없으면 론/헤지 기반으로 추천
        if loan_available and hedge_type and hedge_type != "none":
            strategy_text = "헷지 갭익절 권장"
            strategy_color = "#4ade80"
        elif hedge_type and hedge_type != "none":
            strategy_text = "헷지 가능 (론 없음)"
            strategy_color = "#60a5fa"
        else:
            strategy_text = "현물 선따리 (헷지 불가)"
            strategy_color = "#fbbf24"
    
    # === 개별 항목 HTML 생성 ===
    items_html = []
    
    # 1. 추천 전략
    items_html.append(
        f'<div>🎯 추천: <b style="color:{strategy_color};">{strategy_text}</b></div>'
    )
    
    # 2. 현선갭 (있을 때만)
    if gap_pct is not None:
        gap_status = "낮음 ✅" if gap_pct < 2 else "보통" if gap_pct < 5 else "높음 ⚠️"
        hedge_info = ""
        if hedge_type and hedge_type != "none":
            # 헷지 방향 표시 (예: 바낸롱-바빗숏)
            if hedge_exchange:
                hedge_info = f" · {hedge_exchange}"
            else:
                hedge_info = f" · {hedge_type}"
        items_html.append(
            f'<div>📈 현선갭: {gap_pct:.1f}% ({gap_status}){hedge_info}</div>'
        )
    
    # 3. 론 정보
    if loan_available and best_loan_exchange:
        rate_str = f" ({best_loan_rate:.4f}%/h)" if best_loan_rate else ""
        items_html.append(
            f'<div>💰 론: {best_loan_exchange} 가능{rate_str}</div>'
        )
    elif loan_available:
        items_html.append('<div>💰 론: 가능</div>')
    else:
        items_html.append('<div style="color:#9ca3af;">💰 론: 불가</div>')
    
    # 4. DEX 유동성 (있을 때만)
    if dex_liquidity_usd is not None:
        if dex_liquidity_usd >= 1_000_000:
            liq_str = f"${dex_liquidity_usd/1_000_000:.1f}M"
            liq_status = "많음 ⚠️"
            liq_color = "#fbbf24"
        elif dex_liquidity_usd >= 200_000:
            liq_str = f"${dex_liquidity_usd/1000:.0f}K"
            liq_status = "보통"
            liq_color = "#d1d5db"
        else:
            liq_str = f"${dex_liquidity_usd/1000:.0f}K"
            liq_status = "적음 ✅"
            liq_color = "#4ade80"
        items_html.append(
            f'<div>💧 DEX: <span style="color:{liq_color};">{liq_str} ({liq_status})</span></div>'
        )
    
    # 5. 네트워크 (있을 때만)
    if network_chain:
        speed_emoji = "⚡"
        speed_text = ""
        if network_speed:
            speed_map = {
                "very_fast": "매우 빠름",
                "fast": "빠름", 
                "medium": "보통",
                "slow": "느림"
            }
            speed_text = f" ({speed_map.get(network_speed, network_speed)})"
        items_html.append(
            f'<div>{speed_emoji} 네트워크: {network_chain.upper()}{speed_text}</div>'
        )
    
    # 아무 정보도 없으면 빈 문자열 반환
    if len(items_html) <= 1:  # 추천 전략만 있으면
        # 최소한의 정보라도 표시
        pass
    
    # === 최종 HTML 조립 ===
    items_joined = "\n            ".join(items_html)
    
    return f'''
            <div style="background:#1f2937;border-radius:8px;padding:0.75rem;margin-bottom:0.75rem;">
                <div style="font-size:0.8rem;font-weight:600;color:#60a5fa;margin-bottom:0.5rem;">
                    📋 전략 요약
                </div>
                <div style="font-size:0.75rem;color:#d1d5db;line-height:1.6;">
                    {items_joined}
                </div>
            </div>
    '''


def _render_analysis_card(row: dict, vasp_matrix: dict, highlight: bool = False) -> None:
    """개별 분석 결과 카드 렌더링 (Phase 2.2: 개선된 UI).
    
    GO 카드: 크고 눈에 띄게, 핵심 정보 강조
    NO-GO 카드: 컴팩트하게
    
    Args:
        row: 분석 결과 데이터.
        vasp_matrix: VASP 매트릭스.
        highlight: True면 GO 강조 스타일 적용.
    """
    import streamlit as st

    symbol = row.get("symbol", "?")
    exchange = row.get("exchange", "?")
    can_proceed = row.get("can_proceed", 0)
    premium = row.get("premium_pct") or 0
    net_profit = row.get("net_profit_pct") or 0
    total_cost = row.get("total_cost_pct") or 0
    duration_ms = row.get("gate_duration_ms") or 0
    ts = row.get("timestamp", 0)

    # Blockers/Warnings
    blockers = json.loads(row.get("blockers_json", "[]") or "[]")
    warnings = json.loads(row.get("warnings_json", "[]") or "[]")
    
    # 신뢰도 계산
    confidence_score, confidence_reason = _calculate_confidence_score(row)

    # 시간 포맷
    time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
    
    # 예상 수익 계산 ($1,000 기준)
    base_usd = 1000
    profit_usd = base_usd * (net_profit or 0) / 100
    
    # 흥/망따리 분류
    supply_score = row.get("supply_score")
    if supply_score is not None:
        if supply_score > 6:
            supply_emoji, supply_text = "🔥", "흥따리"
        elif supply_score < 3:
            supply_emoji, supply_text = "💀", "망따리"
        else:
            supply_emoji, supply_text = "😐", "보통"
    elif net_profit is not None:
        if net_profit > 3:
            supply_emoji, supply_text = "🔥", "흥따리"
        elif net_profit < 0:
            supply_emoji, supply_text = "💀", "망따리"
        else:
            supply_emoji, supply_text = "😐", "보통"
    else:
        supply_emoji, supply_text = "", ""

    # ============================================================
    # GO 카드: 크고 눈에 띄게 (히어로 스타일) + GO 스코어
    # ============================================================
    if highlight and can_proceed:
        # GO 스코어 계산
        go_score, score_breakdown = _calculate_go_score(row)
        
        # 프리미엄 바 (시각화)
        premium_val = premium or 0
        premium_bar_width = min(max(premium_val * 10, 5), 100)  # 5-100% 범위
        premium_color = "#4ade80" if premium_val > 0 else "#f87171"
        
        # GO 스코어 색상
        if go_score >= 70:
            score_color = "#4ade80"
            score_label = "STRONG"
        elif go_score >= 50:
            score_color = "#60a5fa"
            score_label = "GOOD"
        elif go_score >= 30:
            score_color = "#fbbf24"
            score_label = "FAIR"
        else:
            score_color = "#f87171"
            score_label = "WEAK"
        
        # =========================================================
        # 전략 요약 섹션 생성
        # =========================================================
        strategy_summary_html = _build_strategy_summary_html(row)
        
        card_html = f"""
        <div style="background:linear-gradient(135deg, #0a2e1a 0%, #1a4a2a 50%, #0d3d1d 100%);
            border:2px solid #4ade80;border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
            
            <!-- 헤더: 심볼 + GO 스코어 -->
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;">
                <div>
                    <div style="display:flex;align-items:center;gap:0.5rem;">
                        <span style="font-size:1.3rem;font-weight:700;color:#fff;">{symbol}</span>
                        <span style="background:#166534;color:#4ade80;padding:3px 8px;border-radius:10px;font-size:0.7rem;font-weight:600;">
                            {supply_emoji} {supply_text}
                        </span>
                    </div>
                    <span style="color:#86efac;font-size:0.75rem;">@{exchange} · {time_str}</span>
                </div>
                <div style="text-align:center;background:rgba(0,0,0,0.3);padding:0.4rem 0.6rem;border-radius:8px;border:1px solid {score_color};">
                    <div style="font-size:1.2rem;font-weight:700;color:{score_color};line-height:1;">{go_score}</div>
                    <div style="font-size:0.55rem;color:{score_color};">{score_label}</div>
                </div>
            </div>
            
            <!-- 메인: 순수익 (초대형) -->
            <div style="text-align:center;padding:0.75rem 0;border-top:1px solid rgba(74,222,128,0.2);
                border-bottom:1px solid rgba(74,222,128,0.2);margin-bottom:0.75rem;">
                <div style="font-size:0.75rem;color:#86efac;margin-bottom:0.15rem;">예상 순수익</div>
                <div style="font-size:2rem;font-weight:800;color:#4ade80;line-height:1;">
                    +{net_profit:.2f}%
                </div>
                <div style="font-size:0.85rem;color:#86efac;margin-top:0.15rem;">
                    ≈ ${profit_usd:.1f} <span style="font-size:0.7rem;color:#6b7280;">($1K 기준)</span>
                </div>
            </div>
            
            <!-- 프리미엄 바 (시각화) -->
            <div style="margin-bottom:0.75rem;">
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:0.3rem;">
                    <span style="color:#9ca3af;">📈 김치프리미엄</span>
                    <span style="color:{premium_color};font-weight:700;">{premium:+.2f}%</span>
                </div>
                <div style="background:#1f2937;border-radius:4px;height:8px;overflow:hidden;">
                    <div style="background:linear-gradient(90deg, {premium_color}, {premium_color}88);
                        width:{premium_bar_width}%;height:100%;border-radius:4px;
                        box-shadow:0 0 10px {premium_color}66;"></div>
                </div>
            </div>
            
            <!-- 전략 요약 섹션 -->
            {strategy_summary_html}
            
            <!-- 하단: 비용/속도/스코어 -->
            <div style="display:flex;justify-content:space-around;font-size:0.85rem;color:#9ca3af;">
                <div style="text-align:center;">
                    <div style="color:#6b7280;font-size:0.7rem;">총 비용</div>
                    <div style="font-weight:600;color:#fbbf24;">{total_cost:.2f}%</div>
                </div>
                <div style="width:1px;background:#374151;"></div>
                <div style="text-align:center;">
                    <div style="color:#6b7280;font-size:0.7rem;">분석 속도</div>
                    <div style="font-weight:600;color:#60a5fa;">{duration_ms:.0f}ms</div>
                </div>
                <div style="width:1px;background:#374151;"></div>
                <div style="text-align:center;">
                    <div style="color:#6b7280;font-size:0.7rem;">GO 스코어</div>
                    <div style="font-weight:600;color:{score_color};">{go_score}/100</div>
                </div>
            </div>
        </div>
        """
        
        render_html(card_html)
        
        # 상세 정보 접이식 (스코어 breakdown 포함)
        with st.expander(f"📋 {symbol} 상세 정보 & GO 스코어 분석", expanded=False):
            detail_cols = st.columns(2)
            with detail_cols[0]:
                st.markdown("**⚠️ 주의사항**")
                if blockers:
                    for b in blockers[:3]:
                        st.markdown(f"🚫 {b}")
                if warnings:
                    for w in warnings[:3]:
                        st.markdown(f"⚠️ {w}")
                if not blockers and not warnings:
                    st.markdown("✅ 특이사항 없음")
            with detail_cols[1]:
                st.markdown("**📊 GO 스코어 분석**")
                st.markdown(f"**총점: {go_score}/100** ({score_label})")
                for item, points, reason in score_breakdown:
                    color = "🟢" if points > 0 else "🔴" if points < 0 else "⚪"
                    sign = "+" if points > 0 else ""
                    st.markdown(f"{color} {item}: {sign}{points}점 ({reason})")
        
        return

    # ============================================================
    # NO-GO 카드: 컴팩트 (또는 일반 GO)
    # ============================================================
    traffic_light = _render_traffic_light(can_proceed, confidence_score, len(warnings) > 0)
    confidence_bar = _render_confidence_bar(confidence_score)
    
    premium_text = f"{premium:+.2f}%" if premium is not None else "N/A"
    cost_text = f"{total_cost:.2f}%" if total_cost is not None else "N/A"
    
    if net_profit is not None:
        if net_profit > 0:
            profit_display = f'<span style="color:#4ade80;font-weight:700;">+{net_profit:.2f}%</span>'
        else:
            profit_display = f'<span style="color:#f87171;font-weight:700;">{net_profit:.2f}%</span>'
    else:
        profit_display = '<span style="color:#6b7280;">N/A</span>'

    # 경고사항 (간결하게)
    alert_text = ""
    if blockers:
        alert_text = f'<span style="color:#f87171;font-size:0.75rem;">🚫 {blockers[0][:30]}</span>'
    elif warnings:
        alert_text = f'<span style="color:#fbbf24;font-size:0.75rem;">⚠️ {warnings[0][:30]}</span>'

    card_style = """background:linear-gradient(135deg, #1f1f1f 0%, #2a2a2a 100%);
        border:1px solid #374151;border-radius:12px;padding:0.85rem;margin-bottom:0.5rem;"""

    card_html = f"""
    <div style="{card_style}">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="display:flex;align-items:center;gap:0.5rem;">
                {traffic_light}
                <span style="font-size:1rem;font-weight:600;color:#fff;">{symbol}</span>
                <span style="color:#6b7280;font-size:0.8rem;">@{exchange}</span>
            </div>
            <div style="text-align:right;">
                <div>{profit_display} <span style="color:#6b7280;font-size:0.75rem;">순수익</span></div>
                <div style="font-size:0.7rem;color:#6b7280;">{time_str}</div>
            </div>
        </div>
        <div style="display:flex;justify-content:space-between;margin-top:0.5rem;font-size:0.8rem;">
            <div style="color:#9ca3af;">
                김프 <b style="color:#60a5fa;">{premium_text}</b> · 비용 <b style="color:#fbbf24;">{cost_text}</b>
            </div>
            {alert_text}
        </div>
    </div>
    """
    
    render_html(card_html)


# ------------------------------------------------------------------
# 프리미엄 차트 섹션
# ------------------------------------------------------------------


def _render_premium_chart_section(conn_id: int) -> None:
    """실시간 프리미엄 차트 섹션 (Phase 7 Week 4)."""
    import streamlit as st

    render_html(f'<p style="{SECTION_HEADER_STYLE}">📈 프리미엄 추이 차트</p>')

    # 최근 24시간 프리미엄 히스토리 조회
    premium_history = fetch_premium_history_cached(conn_id, hours=24)

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
        key="premium_chart_symbol_live",
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
    render_html(PREMIUM_THRESHOLDS)


# ------------------------------------------------------------------
# 현선갭 모니터 섹션 (Phase 8)
# ------------------------------------------------------------------


def _fetch_spot_futures_gap_cached(conn_id: int, limit: int = 5) -> list[dict]:
    """현선갭 데이터 조회 (30초 캐시)."""
    import streamlit as st

    @st.cache_data(ttl=30)
    def _inner(_conn_id: int, _limit: int) -> list[dict]:
        conn = get_read_conn()
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

    render_html(f'<p style="{SECTION_HEADER_STYLE}">📊 현선갭 모니터</p>')

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
        render_html(info_html)
        return

    # 갭 카드들
    for data in gap_data:
        card_html = _render_spot_futures_gap_card_html(data)
        render_html(card_html)


# ------------------------------------------------------------------
# 펀딩비 섹션
# ------------------------------------------------------------------


def _render_funding_rate_section() -> None:
    """펀딩비 섹션 렌더링."""
    import streamlit as st

    render_html(f'<p style="{SECTION_HEADER_STYLE}">💹 펀딩비 (Funding Rate)</p>')

    funding_data = fetch_funding_rates_cached()

    if funding_data.get("status") == "error" or funding_data.get("status") == "no_data":
        info_html = f"""
        <div style="{CARD_STYLE}">
            <p style="font-size:0.9rem;font-weight:600;color:{COLORS["info"]};margin-bottom:0.5rem;">
                📊 펀딩비란?
            </p>
            <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};margin-bottom:0.75rem;">
                선물 거래소에서 롱/숏 포지션 밸런스를 맞추기 위해 8시간마다 지불하는 수수료입니다.
            </p>
            <div style="display:flex;gap:1rem;font-size:0.8rem;margin-bottom:0.5rem;">
                <div>
                    <span style="color:{COLORS["success"]};">양수</span>
                    <span style="color:{COLORS["text_muted"]};"> = 롱 과다 (롱이 숏에 지불)</span>
                </div>
                <div>
                    <span style="color:{COLORS["danger"]};">음수</span>
                    <span style="color:{COLORS["text_muted"]};"> = 숏 과다 (숏이 롱에 지불)</span>
                </div>
            </div>
            <p style="font-size:0.75rem;color:{COLORS["text_muted"]};">
                ⚠️ 펀딩비 데이터를 불러오지 못했습니다.
            </p>
        </div>
        """
        render_html(info_html)
        return

    # 펀딩비 요약
    avg_rate = funding_data.get("avg_funding_rate_pct", 0)
    position_bias = funding_data.get("position_bias", "neutral")
    symbols_data = funding_data.get("symbols", {})

    # 쏠림 방향에 따른 스타일
    if position_bias == "long_heavy":
        bias_color = COLORS["success"]
        bias_emoji = "📈"
        bias_text = "롱 과다"
        bias_hint = "시장이 상승을 기대 중"
    elif position_bias == "short_heavy":
        bias_color = COLORS["danger"]
        bias_emoji = "📉"
        bias_text = "숏 과다"
        bias_hint = "시장이 하락을 기대 중"
    else:
        bias_color = COLORS["neutral"]
        bias_emoji = "➖"
        bias_text = "중립"
        bias_hint = "롱/숏 균형"

    # 요약 카드
    summary_html = f"""
    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;">
            <div>
                <span style="font-size:1rem;font-weight:600;color:{COLORS["text_primary"]};">
                    평균 펀딩비
                </span>
                <span style="font-size:1.2rem;font-weight:700;color:{bias_color};margin-left:0.75rem;">
                    {avg_rate:+.4f}%
                </span>
            </div>
            <div style="background:rgba(0,0,0,0.3);border:1px solid {bias_color};
                        padding:4px 12px;border-radius:8px;font-size:0.85rem;">
                {bias_emoji} <span style="color:{bias_color};font-weight:600;">{bias_text}</span>
            </div>
        </div>
        <p style="font-size:0.8rem;color:{COLORS["text_muted"]};margin-bottom:0.75rem;">
            💡 {bias_hint}
        </p>
        <div style="display:flex;flex-wrap:wrap;gap:0.75rem;">
    """

    for symbol, data in symbols_data.items():
        rate_pct = data.get("rate_pct", 0)
        sym_bias = data.get("bias", "neutral")
        
        if sym_bias == "long_heavy":
            sym_color = COLORS["success"]
        elif sym_bias == "short_heavy":
            sym_color = COLORS["danger"]
        else:
            sym_color = COLORS["text_secondary"]

        summary_html += f"""
            <div style="background:{COLORS["bg_card"]};border:1px solid {COLORS["border_gray"]};
                        padding:8px 12px;border-radius:8px;min-width:100px;">
                <div style="font-size:0.85rem;font-weight:600;color:{COLORS["text_primary"]};">
                    {symbol.replace('USDT', '')}
                </div>
                <div style="font-size:0.9rem;font-weight:700;color:{sym_color};">
                    {rate_pct:+.4f}%
                </div>
            </div>
        """

    summary_html += """
        </div>
    </div>
    """

    render_html(summary_html)


# ------------------------------------------------------------------
# 실시간 현선갭 조회 섹션
# ------------------------------------------------------------------


def _render_realtime_gap_section() -> None:
    """실시간 현선갭 조회 섹션."""
    import streamlit as st

    render_html(f'<p style="{SECTION_HEADER_STYLE}">📊 실시간 현선갭 조회</p>')

    col1, col2 = st.columns([3, 1])
    with col1:
        symbol = st.text_input(
            "심볼",
            placeholder="예: BTC, ETH, SOL",
            key="gap_symbol",
            label_visibility="collapsed",
        )
    with col2:
        search_btn = st.button("🔍 조회", key="gap_search", use_container_width=True)

    if search_btn and symbol:
        symbol = symbol.upper().strip()
        
        with st.spinner(f"{symbol} 현선갭 조회 중..."):
            try:
                from collectors.exchange_service import ExchangeService
                from collectors.gap_calculator import GapCalculator

                service = ExchangeService()
                
                # 모든 거래소에서 가격 조회
                spot_exchanges = ['binance', 'bybit', 'okx', 'upbit', 'bithumb']
                futures_exchanges = ['binance', 'bybit', 'okx', 'hyperliquid']
                
                prices = service.fetch_all_prices(symbol, spot_exchanges, futures_exchanges)
                
                # 현선갭 계산
                gaps = GapCalculator.calculate_all_gaps(prices, symbol)
                
                if not gaps:
                    st.warning(f"{symbol}: 데이터를 찾을 수 없습니다.")
                else:
                    # 결과 표시
                    result_html = f"""
                    <div style="background:{COLORS["card_bg"]};border:1px solid {COLORS["card_border"]};
                                border-radius:12px;padding:1rem;margin-top:0.75rem;">
                        <p style="font-size:1rem;font-weight:600;color:{COLORS["text_primary"]};margin-bottom:0.75rem;">
                            {symbol} 현선갭 (상위 5개)
                        </p>
                        <div style="display:flex;flex-direction:column;gap:0.5rem;">
                    """
                    
                    for gap in gaps[:5]:
                        gap_color = COLORS["success"] if gap.gap_percent > 0 else COLORS["danger"]
                        funding_text = f" | 펀딩: {gap.funding_rate*100:.4f}%" if gap.funding_rate else ""
                        krw_text = f" (₩{gap.spot_krw_price:,.0f})" if gap.spot_krw_price else ""
                        
                        result_html += f"""
                            <div style="display:flex;justify-content:space-between;align-items:center;
                                        background:{COLORS["bg_card"]};padding:0.5rem 0.75rem;border-radius:6px;">
                                <div>
                                    <span style="color:{COLORS["text_secondary"]};">{gap.spot_exchange}</span>
                                    <span style="color:{COLORS["text_muted"]};"> → </span>
                                    <span style="color:{COLORS["text_secondary"]};">{gap.futures_exchange}</span>
                                    {krw_text}
                                </div>
                                <div>
                                    <span style="font-weight:600;color:{gap_color};">{gap.gap_percent:+.3f}%</span>
                                    <span style="color:{COLORS["text_muted"]};font-size:0.8rem;">{funding_text}</span>
                                </div>
                            </div>
                        """
                    
                    # 가격 정보
                    spot_prices = prices.get('spot', {})
                    futures_prices = prices.get('futures', {})
                    
                    if spot_prices or futures_prices:
                        result_html += f"""
                            <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid {COLORS["border_gray"]};">
                                <p style="font-size:0.8rem;color:{COLORS["text_muted"]};margin-bottom:0.5rem;">가격 정보</p>
                                <div style="display:flex;gap:1rem;flex-wrap:wrap;font-size:0.85rem;">
                        """
                        for ex, data in spot_prices.items():
                            krw = f" (₩{data.krw_price:,.0f})" if data.krw_price else ""
                            result_html += f'<span style="color:{COLORS["text_secondary"]};">{ex}: ${data.price:.4f}{krw}</span>'
                        for ex, data in futures_prices.items():
                            result_html += f'<span style="color:{COLORS["info"]};">{ex}(F): ${data.price:.4f}</span>'
                        result_html += "</div></div>"
                    
                    result_html += """
                        </div>
                    </div>
                    """
                    
                    render_html(result_html)

            except Exception as e:
                st.error(f"조회 실패: {e}")

    # 설명
    info_html = f"""
    <div style="{CARD_STYLE}margin-top:0.75rem;">
        <p style="font-size:0.8rem;color:{COLORS["text_secondary"]};">
            💡 <b>현선갭</b> = (선물가격 - 현물가격) / 현물가격 × 100
        </p>
        <p style="font-size:0.75rem;color:{COLORS["text_muted"]};margin-top:0.25rem;">
            양수: 선물 프리미엄 | 음수: 선물 디스카운트 | 갭이 클수록 헷징 어려움 → GO 신호
        </p>
    </div>
    """
    render_html(info_html)


# ------------------------------------------------------------------
# 🔍 빠른 분석 통합 섹션 (현선갭 + DEX 유동성 통합)
# ------------------------------------------------------------------


def _render_quick_analysis_section() -> None:
    """빠른 분석 통합 섹션 (현선갭 + DEX 유동성 한번에 조회)."""
    import streamlit as st
    import asyncio

    # 헤더 (완전한 HTML 블록)
    header_html = '''
    <div style="background:linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border:1px solid #3b82f6;border-radius:16px 16px 0 0;padding:1rem 1.25rem 0.75rem 1.25rem;">
        <div style="display:flex;align-items:center;gap:0.5rem;">
            <span style="font-size:1.3rem;">🔍</span>
            <span style="font-size:1.1rem;font-weight:700;color:#fff;">빠른 분석</span>
            <span style="font-size:0.75rem;color:#6b7280;margin-left:0.5rem;">현선갭 + DEX 유동성 통합 조회</span>
        </div>
    </div>
    '''
    render_html(header_html)

    # 입력 필드 (Streamlit 컴포넌트)
    col1, col2 = st.columns([4, 1])
    with col1:
        symbol = st.text_input(
            "심볼 입력",
            placeholder="심볼 입력 (예: SOL, AVAIL, ME)",
            key="quick_analysis_symbol",
            label_visibility="collapsed",
        )
    with col2:
        search_btn = st.button("🚀 분석", key="quick_analysis_btn", use_container_width=True)

    if search_btn and symbol:
        symbol = symbol.upper().strip()
        
        with st.spinner(f"🔄 {symbol} 통합 분석 중..."):
            results = {
                "gap": None, "dex": None, "orderbook": None, "deposit": None,
                "gap_error": None, "dex_error": None, "orderbook_error": None, "deposit_error": None
            }
            
            # 1. 현선갭 조회
            try:
                from collectors.exchange_service import ExchangeService
                from collectors.gap_calculator import GapCalculator

                service = ExchangeService()
                spot_exchanges = ['binance', 'bybit', 'okx', 'upbit', 'bithumb']
                futures_exchanges = ['binance', 'bybit', 'okx', 'hyperliquid']
                
                prices = service.fetch_all_prices(symbol, spot_exchanges, futures_exchanges)
                gaps = GapCalculator.calculate_all_gaps(prices, symbol)
                results["gap"] = {"prices": prices, "gaps": gaps}
            except Exception as e:
                results["gap_error"] = str(e)
            
            # 2. DEX 유동성 조회
            try:
                from collectors.dex_liquidity import get_dex_liquidity
                dex_result = asyncio.run(get_dex_liquidity(symbol))
                results["dex"] = dex_result
            except Exception as e:
                results["dex_error"] = str(e)
            
            # 3. 오더북 기반 프리미엄 조회 (NEW!)
            try:
                from collectors.exchange_service import ExchangeService, MarketType
                from collectors.gap_calculator import GapCalculator
                
                service = ExchangeService()
                orderbooks = service.fetch_orderbooks_parallel(
                    symbol,
                    spot_exchanges=['binance', 'bybit', 'upbit', 'bithumb'],
                    futures_exchanges=[],
                    limit=20
                )
                ob_gaps = GapCalculator.calculate_all_orderbook_gaps(
                    orderbooks, symbol, amount_usd=10000
                )
                results["orderbook"] = ob_gaps
            except Exception as e:
                results["orderbook_error"] = str(e)
            
            # 4. 입금 상태 조회 (NEW!)
            try:
                from collectors.deposit_status import check_all_exchanges
                deposit_info = asyncio.run(check_all_exchanges(symbol))
                results["deposit"] = deposit_info
            except Exception as e:
                results["deposit_error"] = str(e)
            
            # 결과 렌더링
            _render_quick_analysis_results(symbol, results)


def _render_quick_analysis_results(symbol: str, results: dict) -> None:
    """빠른 분석 결과 렌더링 (현선갭 + DEX + 네트워크 속도)."""
    import streamlit as st
    
    # 네트워크 정보 가져오기
    try:
        from collectors.network_speed import get_network_by_symbol, get_network_info
        network_info = get_network_by_symbol(symbol)
    except Exception:
        network_info = None

    gap_data = results.get("gap")
    dex_data = results.get("dex")
    
    # DEX에서 체인 정보 추출 (네트워크 정보 없을 때)
    detected_chain = None
    if dex_data and dex_data.best_pair:
        detected_chain = dex_data.best_pair.chain
        if not network_info:
            try:
                from collectors.network_speed import get_network_info
                network_info = get_network_info(detected_chain)
            except Exception:
                pass
    
    # 각 요소별 신호
    gap_signal = None
    dex_signal = None
    network_signal = None
    
    if gap_data and gap_data.get("gaps"):
        best_gap = gap_data["gaps"][0].gap_percent if gap_data["gaps"] else 0
        if best_gap > 3:
            gap_signal = "GO"
        elif best_gap > 1:
            gap_signal = "CAUTION"
        else:
            gap_signal = "NO_GO"
    
    if dex_data:
        dex_signal = dex_data.go_signal
    
    if network_info:
        network_signal = network_info.go_signal
    
    # 프리미엄 계산 (김프/역프 판단)
    spot_premium = None
    is_reverse = False
    orderbook_data = results.get("orderbook")
    
    if orderbook_data and len(orderbook_data) > 0:
        best_ob = orderbook_data[0]
        spot_premium = best_ob.premium_percent
        is_reverse = spot_premium < -1.0  # 역프 1% 이상
    elif gap_data and gap_data.get("prices"):
        # 오더북 없으면 가격으로 계산
        spot_prices = gap_data.get("prices", {}).get("spot", {})
        kr_price = next((p.price for ex, p in spot_prices.items() if ex in ['upbit', 'bithumb']), None)
        global_price = next((p.price for ex, p in spot_prices.items() if ex in ['binance', 'bybit']), None)
        if kr_price and global_price:
            spot_premium = (kr_price - global_price) / global_price * 100
            is_reverse = spot_premium < -1.0
    
    # 종합 판정 로직 (역프 전략 포함)
    go_count = sum(1 for s in [gap_signal, dex_signal, network_signal] if s in ["GO", "STRONG_GO"])
    nogo_count = sum(1 for s in [gap_signal, dex_signal, network_signal] if s == "NO_GO")
    
    if is_reverse and spot_premium is not None:
        # 역프 상황 - 역따리 전략 추천
        if spot_premium < -3.0:
            overall_signal = "🔄🟢 역따리 GO"
            signal_color = "#8b5cf6"  # 보라색
        elif spot_premium < -1.5:
            overall_signal = "🔄 역따리 검토"
            signal_color = "#a78bfa"
        else:
            overall_signal = "🔄⚠️ 역프 주의"
            signal_color = "#fbbf24"
    elif go_count >= 2 and nogo_count == 0:
        overall_signal = "🟢🟢 STRONG GO"
        signal_color = "#4ade80"
    elif go_count >= 1 and nogo_count == 0:
        overall_signal = "🟢 GO"
        signal_color = "#4ade80"
    elif nogo_count >= 2:
        overall_signal = "🔴 NO-GO"
        signal_color = "#f87171"
    else:
        overall_signal = "🟡 CAUTION"
        signal_color = "#fbbf24"

    # 메인 결과 카드
    result_html = f"""
    <div style="background:linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        border:2px solid {signal_color};border-radius:16px;padding:1.25rem;margin-top:0.5rem;">
        
        <!-- 헤더: 심볼 + 종합 판정 -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;
            padding-bottom:0.75rem;border-bottom:1px solid #374151;">
            <span style="font-size:1.5rem;font-weight:800;color:#fff;">{symbol}</span>
            <div style="background:{signal_color};color:#000;padding:8px 16px;border-radius:10px;
                font-weight:700;font-size:0.9rem;">{overall_signal}</div>
        </div>
        
        <!-- 3컬럼: 현선갭 | DEX 유동성 | 네트워크 -->
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.75rem;">
    """
    
    # 1. 현선갭 결과
    result_html += '<div style="background:#1f2937;border-radius:12px;padding:0.85rem;">'
    result_html += '<div style="font-size:0.8rem;font-weight:600;color:#60a5fa;margin-bottom:0.6rem;">📊 현선갭</div>'
    
    if results.get("gap_error"):
        result_html += f'<div style="color:#f87171;font-size:0.75rem;">❌ 에러</div>'
    elif gap_data and gap_data.get("gaps"):
        for gap in gap_data["gaps"][:2]:
            gap_color = "#4ade80" if gap.gap_percent > 0 else "#f87171"
            result_html += f'''
            <div style="display:flex;justify-content:space-between;padding:0.3rem 0;font-size:0.75rem;">
                <span style="color:#9ca3af;">{gap.spot_exchange}→{gap.futures_exchange}</span>
                <span style="color:{gap_color};font-weight:600;">{gap.gap_percent:+.2f}%</span>
            </div>
            '''
        spot_prices = gap_data.get("prices", {}).get("spot", {})
        if spot_prices:
            first_price = list(spot_prices.values())[0] if spot_prices else None
            if first_price and first_price.krw_price:
                result_html += f'<div style="font-size:0.7rem;color:#6b7280;margin-top:0.3rem;">₩{first_price.krw_price:,.0f}</div>'
    else:
        result_html += '<div style="color:#6b7280;font-size:0.75rem;">데이터 없음</div>'
    
    result_html += '</div>'
    
    # 2. DEX 유동성 결과
    result_html += '<div style="background:#1f2937;border-radius:12px;padding:0.85rem;">'
    result_html += '<div style="font-size:0.8rem;font-weight:600;color:#a78bfa;margin-bottom:0.6rem;">💧 DEX 유동성</div>'
    
    if results.get("dex_error"):
        result_html += f'<div style="color:#f87171;font-size:0.75rem;">❌ 에러</div>'
    elif dex_data:
        dex_color = "#4ade80" if dex_data.go_signal in ["STRONG_GO", "GO"] else "#fbbf24" if dex_data.go_signal == "CAUTION" else "#f87171"
        result_html += f'''
        <div style="font-size:1rem;font-weight:700;color:{dex_color};margin-bottom:0.3rem;">
            ${dex_data.total_liquidity_usd:,.0f}
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.7rem;">
            <span style="color:#9ca3af;">24h</span>
            <span style="color:#fff;">${dex_data.total_volume_24h:,.0f}</span>
        </div>
        <div style="margin-top:0.4rem;">
            <span style="background:{dex_color};color:#000;padding:2px 6px;border-radius:4px;
                font-size:0.65rem;font-weight:600;">{dex_data.go_emoji} {dex_data.go_signal}</span>
        </div>
        '''
    else:
        result_html += '<div style="color:#6b7280;font-size:0.75rem;">데이터 없음</div>'
    
    result_html += '</div>'
    
    # 3. 네트워크 속도 결과 (NEW!)
    result_html += '<div style="background:#1f2937;border-radius:12px;padding:0.85rem;">'
    result_html += '<div style="font-size:0.8rem;font-weight:600;color:#f59e0b;margin-bottom:0.6rem;">⚡ 네트워크</div>'
    
    if network_info:
        net_color = "#4ade80" if network_info.go_signal == "GO" else "#fbbf24" if network_info.go_signal == "CAUTION" else "#f87171"
        result_html += f'''
        <div style="font-size:0.9rem;font-weight:700;color:#fff;margin-bottom:0.3rem;">
            {network_info.emoji} {network_info.chain}
        </div>
        <div style="font-size:0.75rem;color:#9ca3af;margin-bottom:0.3rem;">
            {network_info.estimated_time}
        </div>
        <div style="margin-top:0.4rem;">
            <span style="background:{net_color};color:#000;padding:2px 6px;border-radius:4px;
                font-size:0.65rem;font-weight:600;">{network_info.go_signal}</span>
        </div>
        '''
        if network_info.risk_note:
            result_html += f'<div style="font-size:0.65rem;color:#fbbf24;margin-top:0.3rem;">{network_info.risk_note}</div>'
    else:
        chain_text = detected_chain or "알 수 없음"
        result_html += f'''
        <div style="font-size:0.85rem;color:#9ca3af;margin-bottom:0.3rem;">
            {chain_text}
        </div>
        <div style="color:#6b7280;font-size:0.7rem;">속도 정보 없음</div>
        '''
    
    result_html += '</div>'
    
    result_html += """
        </div>
    """
    
    # 추가 정보 섹션 (오더북 프리미엄 + 입금 상태)
    orderbook_data = results.get("orderbook")
    deposit_data = results.get("deposit")
    
    if orderbook_data or deposit_data:
        result_html += """
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-top:0.75rem;">
        """
        
        # 오더북 기반 프리미엄 (10K USD 기준)
        result_html += '<div style="background:#1f2937;border-radius:12px;padding:0.85rem;">'
        result_html += '<div style="font-size:0.8rem;font-weight:600;color:#10b981;margin-bottom:0.6rem;">📈 오더북 프리미엄 (10K)</div>'
        
        if results.get("orderbook_error"):
            result_html += f'<div style="color:#f87171;font-size:0.75rem;">❌ 에러</div>'
        elif orderbook_data and len(orderbook_data) > 0:
            for ob in orderbook_data[:2]:
                prem_color = "#4ade80" if ob.net_premium > 0 else "#f87171"
                result_html += f'''
                <div style="display:flex;justify-content:space-between;padding:0.3rem 0;font-size:0.75rem;">
                    <span style="color:#9ca3af;">{ob.buy_exchange}→{ob.sell_exchange}</span>
                    <span style="color:{prem_color};font-weight:600;">{ob.net_premium:+.2f}%</span>
                </div>
                '''
            best = orderbook_data[0]
            result_html += f'''
            <div style="font-size:0.65rem;color:#6b7280;margin-top:0.4rem;border-top:1px solid #374151;padding-top:0.4rem;">
                슬리피지: {best.total_slippage:.3f}% | 예상: ${best.estimated_pnl_usd:+.0f}
            </div>
            '''
        else:
            result_html += '<div style="color:#6b7280;font-size:0.75rem;">데이터 없음</div>'
        
        result_html += '</div>'
        
        # 입금 상태
        result_html += '<div style="background:#1f2937;border-radius:12px;padding:0.85rem;">'
        result_html += '<div style="font-size:0.8rem;font-weight:600;color:#ec4899;margin-bottom:0.6rem;">🔄 입출금 상태</div>'
        
        if results.get("deposit_error"):
            result_html += f'<div style="color:#f87171;font-size:0.75rem;">❌ 에러</div>'
        elif deposit_data:
            for exchange, info in list(deposit_data.items())[:3]:
                signal_color = "#4ade80" if info.go_signal == "GO" else "#fbbf24" if info.go_signal == "CAUTION" else "#f87171"
                dep_count = sum(1 for n in info.networks if n.deposit_enabled)
                wth_count = sum(1 for n in info.networks if n.withdraw_enabled)
                result_html += f'''
                <div style="display:flex;justify-content:space-between;align-items:center;padding:0.3rem 0;font-size:0.75rem;">
                    <span style="color:#fff;font-weight:500;">{exchange.upper()}</span>
                    <div style="display:flex;gap:0.5rem;align-items:center;">
                        <span style="color:#9ca3af;">D:{dep_count} W:{wth_count}</span>
                        <span style="background:{signal_color};color:#000;padding:1px 5px;border-radius:3px;
                            font-size:0.6rem;font-weight:600;">{info.go_signal}</span>
                    </div>
                </div>
                '''
        else:
            result_html += '<div style="color:#6b7280;font-size:0.75rem;">데이터 없음</div>'
        
        result_html += '</div>'
        result_html += '</div>'
    
    # 역프 전략 박스 (역프일 때만 표시)
    if is_reverse and spot_premium is not None:
        reverse_premium = abs(spot_premium)
        # 대략적인 비용 계산
        fee_estimate = 0.3  # 거래수수료 + 전송수수료
        futures_gap = 0.5  # 현선갭 추정
        net_estimate = reverse_premium - fee_estimate - futures_gap
        
        result_html += f'''
        <div style="background:linear-gradient(135deg, #1e3a5f 0%, #2d1f47 100%);
            border:1px solid #8b5cf6;border-radius:12px;padding:1rem;margin-top:0.75rem;">
            <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem;">
                <span style="font-size:1.2rem;">🔄</span>
                <span style="font-size:0.9rem;font-weight:700;color:#a78bfa;">역따리 전략 분석</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
                <div>
                    <p style="font-size:0.7rem;color:#9ca3af;margin-bottom:0.25rem;">현재 역프</p>
                    <p style="font-size:1.1rem;font-weight:700;color:#f87171;">{spot_premium:+.2f}%</p>
                </div>
                <div>
                    <p style="font-size:0.7rem;color:#9ca3af;margin-bottom:0.25rem;">예상 순익 (추정)</p>
                    <p style="font-size:1.1rem;font-weight:700;color:{"#4ade80" if net_estimate > 0 else "#f87171"};">{net_estimate:+.2f}%</p>
                </div>
            </div>
            <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid #374151;">
                <p style="font-size:0.7rem;font-weight:600;color:#fff;margin-bottom:0.4rem;">💡 추천 전략:</p>
                <ol style="font-size:0.65rem;color:#9ca3af;margin:0;padding-left:1.2rem;">
                    <li>국내 현물 매수 (업비트/빗썸)</li>
                    <li>해외 선물 숏 진입 (헷징)</li>
                    <li>국내→해외 전송</li>
                    <li>해외 현물 매도 + 숏 청산</li>
                </ol>
            </div>
        </div>
        '''
    
    result_html += """
    </div>
    """
    
    render_html(result_html)

    # 판정 기준 설명 (접이식)
    with st.expander("💡 판정 기준", expanded=False):
        st.markdown("""
        **현선갭 (Spot-Futures Gap)**
        - 🟢 +3% 이상: GO (헷징 어려움 → 공급 제약)
        - 🟡 +1~3%: CAUTION
        - 🔴 +1% 미만: NO-GO
        
        **DEX 유동성**
        - 🟢🟢 $200K 이하: STRONG GO
        - 🟢 $500K 이하: GO
        - 🟡 $1M 이하: CAUTION
        - 🔴 $1M 초과: NO-GO
        
        **네트워크 속도**
        - 🟢 느림 (BTC, ETH, L2): GO - 선따리 유리
        - 🟡 보통 (Polygon, BSC): CAUTION
        - 🔴 빠름 (SOL, SUI, APT): NO-GO - 후따리 쉬움
        
        **오더북 프리미엄** (NEW!)
        - 10K USD 거래 기준 실제 체결 가능한 가격
        - 슬리피지 차감 후 순 프리미엄 표시
        - 예상 손익도 함께 계산
        
        **입출금 상태** (NEW!)
        - D: 입금 가능 네트워크 수
        - W: 출금 가능 네트워크 수
        - Gate, Bitget API 기준
        
        **종합 판정**: 2개 이상 GO면 STRONG GO, NO-GO가 2개 이상이면 NO-GO
        """)


# ------------------------------------------------------------------
# 메인 렌더 함수 (Phase 2.2: 개선된 레이아웃)
# ------------------------------------------------------------------


def render_live_tab() -> None:
    """실시간 현황 탭 렌더링.
    
    레이아웃 구조:
    1. GO 카드 (최상단, 크게)
    2. 2컬럼: [실시간 정보 | 빠른 분석]
    3. 차트/통계 (접이식)
    4. NO-GO (접이식)
    """
    import streamlit as st

    conn = get_read_conn()
    conn_id = id(conn)

    vasp_matrix = load_vasp_matrix_cached()
    analyses = fetch_recent_analyses_cached(conn_id, limit=20)

    # ============================================================
    # 섹션 0: 바이낸스 상장 알림 (v2: 2026-02-02)
    # ============================================================
    _render_binance_alerts_section()

    # ============================================================
    # 섹션 1: GO 카드 (최상단, 눈에 띄게)
    # ============================================================
    go_analyses = [r for r in analyses if r.get("can_proceed", 0)] if analyses else []
    nogo_analyses = [r for r in analyses if not r.get("can_proceed", 0)] if analyses else []

    if go_analyses:
        # 시장 분위기 가져오기
        mood = get_market_mood_cached()
        kr_dom = mood.get("kr_dominance") or 0
        mood_color = mood.get("color", "#9ca3af")
        mood_emoji = mood.get("emoji", "❓")
        mood_text = mood.get("text", "확인중")
        
        # 직전 상장 트렌드 가져오기
        trend = fetch_recent_trend_cached(conn_id, count=5)
        trend_signal = trend.get("trend_signal", "CAUTION")
        trend_color = "#4ade80" if trend_signal == "GO" else "#fbbf24" if trend_signal == "CAUTION" else "#f87171"
        heung_rate = trend.get("heung_rate") or 0
        trend_emoji = trend.get("trend_emoji", "😐")
        trend_total = trend.get("total", 0)
        trend_emojis = trend.get("result_emojis", "")
        
        # 최고 수익 GO 찾기
        best_go = max(go_analyses, key=lambda x: x.get("net_profit_pct") or -999)
        best_profit = best_go.get("net_profit_pct") or 0
        best_profit_text = f"+{best_profit:.1f}%" if best_profit > 0 else ""

        render_html(
            f'''<div style="background:linear-gradient(135deg, #0d3320 0%, #166534 50%, #15803d 100%);
                border:2px solid #4ade80;border-radius:12px;padding:0.75rem 1rem;margin-bottom:0.75rem;">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
                    <div style="display:flex;align-items:center;gap:0.75rem;">
                        <span style="font-size:1.5rem;">🚀</span>
                        <div>
                            <span style="font-size:1.2rem;font-weight:700;color:#4ade80;">GO! {len(go_analyses)}건</span>
                            <span style="font-size:0.8rem;color:#86efac;margin-left:0.5rem;">최고 {best_profit_text}</span>
                        </div>
                    </div>
                    <div style="display:flex;gap:0.5rem;font-size:0.75rem;">
                        <span style="background:rgba(0,0,0,0.3);border:1px solid {mood_color};padding:3px 8px;border-radius:6px;">
                            {mood_emoji} {mood_text} <span style="color:#6b7280;">KR {kr_dom:.1f}%</span>
                        </span>
                        <span style="background:rgba(0,0,0,0.3);border:1px solid {trend_color};padding:3px 8px;border-radius:6px;">
                            {trend_emoji} 직전{trend_total}건 {trend_emojis} <span style="color:{trend_color};">{heung_rate:.0f}%</span>
                        </span>
                    </div>
                </div>
            </div>'''
        )
        
        # GO 카드들 렌더링
        for row in go_analyses:
            _render_analysis_card(row, vasp_matrix, highlight=True)

    elif not analyses:
        # 데이터 없음 상태
        render_html(
            f'''<div style="background:linear-gradient(135deg, #1f1f1f 0%, #2a2a2a 100%);
                border:1px dashed #374151;border-radius:16px;padding:2.5rem;text-align:center;margin-bottom:1rem;">
                <div style="font-size:2.5rem;margin-bottom:0.75rem;">⏳</div>
                <div style="font-size:1.2rem;color:#9ca3af;margin-bottom:0.5rem;">분석 기록 없음</div>
                <div style="font-size:0.85rem;color:#6b7280;">
                    수집 데몬이 실행 중이고 새 상장이 감지되면<br>여기에 GO/NO-GO 분석 결과가 표시됩니다.
                </div>
            </div>'''
        )

    else:
        # GO 없음 - 대기 상태
        render_html(
            f'''<div style="background:linear-gradient(135deg, #1a1a1a 0%, #262626 100%);
                border:2px dashed #374151;border-radius:16px;padding:1.5rem;text-align:center;margin-bottom:1rem;">
                <div style="font-size:1.8rem;margin-bottom:0.5rem;">😴</div>
                <div style="font-size:1.1rem;color:#9ca3af;">현재 GO 기회 없음</div>
                <div style="font-size:0.8rem;color:#6b7280;">대기 중... 새 상장 감지 시 알림</div>
            </div>'''
        )

    # ============================================================
    # 섹션 2: 2컬럼 레이아웃 (실시간 정보 | 빠른 분석)
    # ============================================================
    col_left, col_right = st.columns([1, 1])

    with col_left:
        # 📊 실시간 시장 정보 - 전체를 하나의 HTML 블록으로
        stats = fetch_stats_cached(conn_id)
        
        # 통계 그리드 HTML
        if stats["total"] > 0:
            stats_grid = f'''
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:0.5rem;">
                <div style="background:#1f2937;padding:0.6rem;border-radius:8px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:700;color:#4ade80;">{stats['go_count']}</div>
                    <div style="font-size:0.7rem;color:#6b7280;">GO</div>
                </div>
                <div style="background:#1f2937;padding:0.6rem;border-radius:8px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:700;color:#f87171;">{stats['nogo_count']}</div>
                    <div style="font-size:0.7rem;color:#6b7280;">NO-GO</div>
                </div>
                <div style="background:#1f2937;padding:0.6rem;border-radius:8px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:700;color:#60a5fa;">{stats['avg_premium']:.1f}%</div>
                    <div style="font-size:0.7rem;color:#6b7280;">평균 김프</div>
                </div>
                <div style="background:#1f2937;padding:0.6rem;border-radius:8px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:700;color:#fff;">{stats['total']}</div>
                    <div style="font-size:0.7rem;color:#6b7280;">총 분석</div>
                </div>
            </div>
            '''
        else:
            stats_grid = '''
            <div style="color:#6b7280;font-size:0.85rem;text-align:center;padding:1rem 0;">
                분석 데이터 없음
            </div>
            '''
        
        market_info_html = f'''
        <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
            border-radius:12px;padding:1rem;margin-bottom:0.75rem;">
            <div style="font-size:0.9rem;font-weight:600;color:#fff;margin-bottom:0.75rem;">
                📊 실시간 시장 정보
            </div>
            {stats_grid}
        </div>
        '''
        
        render_html(market_info_html)
        
    with col_right:
        # 🎯 분석센터 안내 (빠른 분석은 분석센터 탭으로 통합됨)
        render_html('''
        <div style="background:linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border:1px solid #3b82f6;border-radius:12px;padding:1rem;">
            <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem;">
                <span style="font-size:1.2rem;">🎯</span>
                <span style="font-size:1rem;font-weight:700;color:#fff;">전략 분석</span>
            </div>
            <p style="font-size:0.8rem;color:#9ca3af;margin-bottom:0.75rem;">
                상장 코인 분석, 현선갭, 론 가능 거래소, 
                전략 추천은 <b style="color:#60a5fa;">분석센터</b> 탭에서 확인하세요.
            </p>
            <div style="background:#1f2937;border-radius:8px;padding:0.75rem;font-size:0.75rem;">
                <div style="color:#4ade80;margin-bottom:0.3rem;">✅ 통합 전략 분석</div>
                <div style="color:#d1d5db;">• 거래소별 현선갭 비교</div>
                <div style="color:#d1d5db;">• 론 가능 거래소 스캔</div>
                <div style="color:#d1d5db;">• 흥/망따리 예측</div>
                <div style="color:#d1d5db;">• 전략 추천 (헷지/후따리)</div>
            </div>
        </div>
        ''')

    # ============================================================
    # 섹션 3: 차트/상세 정보 (접이식)
    # ============================================================
    with st.expander("📈 차트 & 상세 분석", expanded=False):
        _render_premium_chart_section(conn_id)
        _render_spot_futures_gap_section(conn_id)

    # ============================================================
    # 섹션 4: NO-GO 목록 (접이식)
    # ============================================================
    if nogo_analyses:
        avg_profit = sum(r.get("net_profit_pct") or 0 for r in nogo_analyses) / len(nogo_analyses)
        nogo_header = f"🔴 NO-GO ({len(nogo_analyses)}건) · 평균 {avg_profit:.1f}%"
    else:
        nogo_header = "🔴 NO-GO (0건)"
    
    with st.expander(nogo_header, expanded=False):
        if nogo_analyses:
            for row in nogo_analyses:
                _render_analysis_card(row, vasp_matrix, highlight=False)
        else:
            st.info("NO-GO 분석 기록이 없습니다.")

    # 펀딩비 하단 바는 app.py의 _render_market_status_bar에서 통합 렌더링


def _render_funding_rate_bottom_bar() -> None:
    """펀딩비 하단 고정 바."""
    import streamlit as st

    funding_data = fetch_funding_rates_cached()
    
    if funding_data.get("status") in ["error", "no_data"]:
        return  # 데이터 없으면 바 표시 안함

    avg_rate = funding_data.get("avg_funding_rate_pct", 0)
    position_bias = funding_data.get("position_bias", "neutral")
    symbols_data = funding_data.get("symbols", {})

    # 쏠림 방향 & 설명
    if position_bias == "long_heavy":
        bias_color = "#4ade80"
        bias_text = "롱↑"
        meaning = "롱 과열 → 선물 > 현물"
    elif position_bias == "short_heavy":
        bias_color = "#f87171"
        bias_text = "숏↑"
        meaning = "숏 과열 → 선물 < 현물"
    else:
        bias_color = "#9ca3af"
        bias_text = "중립"
        meaning = "롱/숏 균형"

    # 심볼별 펀딩비
    symbols_parts = []
    for symbol, data in list(symbols_data.items())[:3]:
        rate_pct = data.get("rate_pct", 0)
        sym_color = "#4ade80" if rate_pct > 0 else "#f87171" if rate_pct < 0 else "#9ca3af"
        sym_name = symbol.replace('USDT', '')
        symbols_parts.append(
            f'<span style="color:#888;">{sym_name}</span>'
            f'<span style="color:{sym_color};margin-left:3px;">{rate_pct:+.3f}%</span>'
        )
    symbols_html = " &nbsp;·&nbsp; ".join(symbols_parts)

    avg_color = "#4ade80" if avg_rate > 0 else "#f87171" if avg_rate < 0 else "#9ca3af"

    # 하단 고정 바 HTML (position: fixed)
    bottom_bar_html = f'''
    <div style="position:fixed;bottom:0;left:0;right:0;z-index:999;
        background:linear-gradient(180deg, rgba(17,17,27,0.95) 0%, rgba(17,17,27,1) 100%);
        border-top:1px solid rgba(255,255,255,0.1);
        padding:10px 20px;
        display:flex;align-items:center;justify-content:center;gap:16px;
        backdrop-filter:blur(10px);">
        <span style="font-size:0.85rem;color:#9ca3af;">💹 펀딩비</span>
        <span style="font-size:1rem;font-weight:700;color:{avg_color};">{avg_rate:+.4f}%</span>
        <span style="font-size:0.75rem;color:{bias_color};background:{bias_color}18;
            padding:3px 8px;border-radius:4px;font-weight:600;">{bias_text}</span>
        <span style="font-size:0.8rem;color:#666;">│</span>
        <span style="font-size:0.8rem;">{symbols_html}</span>
        <span style="font-size:0.8rem;color:#666;">│</span>
        <span style="font-size:0.75rem;color:#888;font-style:italic;">{meaning}</span>
    </div>
    <div style="height:50px;"></div>
    '''
    
    render_html(bottom_bar_html)


def _render_funding_rate_compact() -> None:
    """펀딩비 상단 바 형태 (컴팩트)."""
    import streamlit as st

    funding_data = fetch_funding_rates_cached()
    
    if funding_data.get("status") in ["error", "no_data"]:
        no_data_html = '''
        <div style="background:rgba(255,255,255,0.02);border-bottom:1px solid rgba(255,255,255,0.06);
            padding:8px 12px;display:flex;align-items:center;gap:12px;">
            <span style="font-size:0.8rem;color:#6b7280;">💹 펀딩비 로딩 중...</span>
        </div>
        '''
        render_html(no_data_html)
        return

    avg_rate = funding_data.get("avg_funding_rate_pct", 0)
    position_bias = funding_data.get("position_bias", "neutral")
    symbols_data = funding_data.get("symbols", {})

    # 쏠림 방향 & 설명
    if position_bias == "long_heavy":
        bias_color = "#4ade80"
        bias_text = "롱↑"
        meaning = "롱 과열 → 선물가 > 현물가"
    elif position_bias == "short_heavy":
        bias_color = "#f87171"
        bias_text = "숏↑"
        meaning = "숏 과열 → 선물가 < 현물가"
    else:
        bias_color = "#9ca3af"
        bias_text = "중립"
        meaning = "롱/숏 균형"

    # 심볼별 펀딩비 (한 줄에)
    symbols_parts = []
    for symbol, data in list(symbols_data.items())[:3]:
        rate_pct = data.get("rate_pct", 0)
        sym_color = "#4ade80" if rate_pct > 0 else "#f87171" if rate_pct < 0 else "#9ca3af"
        sym_name = symbol.replace('USDT', '')
        symbols_parts.append(
            f'<span style="color:#9ca3af;">{sym_name}</span>'
            f'<span style="color:{sym_color};margin-left:2px;">{rate_pct:+.3f}%</span>'
        )
    symbols_html = " &nbsp;│&nbsp; ".join(symbols_parts)

    # 평균 색상
    avg_color = "#4ade80" if avg_rate > 0 else "#f87171" if avg_rate < 0 else "#9ca3af"

    funding_html = f'''
    <div style="background:rgba(255,255,255,0.02);border-bottom:1px solid rgba(255,255,255,0.06);
        padding:8px 12px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
        <div style="display:flex;align-items:center;gap:10px;">
            <span style="font-size:0.8rem;color:#9ca3af;">💹</span>
            <span style="font-size:0.95rem;font-weight:700;color:{avg_color};">{avg_rate:+.4f}%</span>
            <span style="font-size:0.75rem;color:{bias_color};background:{bias_color}15;
                padding:2px 6px;border-radius:4px;">{bias_text}</span>
            <span style="font-size:0.75rem;color:#6b7280;">│</span>
            <span style="font-size:0.75rem;">{symbols_html}</span>
        </div>
        <div style="font-size:0.7rem;color:#6b7280;font-style:italic;">
            {meaning}
        </div>
    </div>
    '''
    
    render_html(funding_html)
