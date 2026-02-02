"""
CEX Dominance Dashboard
Modern Compact UI

Railway 단일 서비스 모드:
  - Streamlit web (메인)
  - collector_daemon (백그라운드 스레드)
"""

import streamlit as st
import asyncio
import os
import sys
import threading
import logging
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from pathlib import Path

# ============================================================
# Railway 로깅 설정 (stderr + 파일)
# ============================================================
_LOG_FILE = Path(os.environ.get("DATA_DIR", "/data")) / "daemon.log"

# 파일 핸들러 추가 (Railway 로그가 안 뜰 때 대비)
handlers = [logging.StreamHandler(sys.stderr)]
try:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(_LOG_FILE, mode='a', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))
    handlers.append(file_handler)
except Exception:
    pass  # 파일 로깅 실패 시 무시

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=handlers
)
logger = logging.getLogger("cex-bot")
logger.info("=== CEX Dominance Bot Starting ===")

from dominance import DominanceCalculator, DominanceResult
from ui.health_display import render_health_banner
from ui.ddari_tab import render_ddari_tab

logger.info("Imports completed successfully")


# ============================================================
# 백그라운드 데몬 (Railway 단일 서비스용)
# ============================================================
_DAEMON_RESTART_DELAY = 5  # 재시작 전 대기 시간 (초)
_DAEMON_MAX_RESTARTS = 10  # 최대 재시작 횟수 (무한 루프 방지)

def _run_daemon_in_thread():
    """별도 스레드에서 collector_daemon 실행 (자동 재시작 포함)."""
    import traceback
    import time as _time

    logger.info("[Daemon] Thread function started")
    logger.info(f"[Daemon] sys.path: {sys.path[:3]}...")  # 경로 확인

    try:
        logger.info("[Daemon] Importing collector_daemon...")
        # 개별 모듈 임포트 확인 (어디서 멈추는지 디버깅)
        logger.info("[Daemon] import store.database...")
        from store import database
        logger.info("[Daemon] import store.writer...")
        from store import writer
        logger.info("[Daemon] import store.token_registry...")
        from store import token_registry
        logger.info("[Daemon] import collectors.upbit_ws...")
        from collectors import upbit_ws
        logger.info("[Daemon] import collectors.bithumb_ws...")
        from collectors import bithumb_ws
        logger.info("[Daemon] import collectors.aggregator...")
        from collectors import aggregator
        logger.info("[Daemon] All sub-imports OK, importing collector_daemon...")
        import collector_daemon
        logger.info("[Daemon] collector_daemon imported successfully")
    except Exception as e:
        logger.error(f"[Daemon] Import error: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        return

    restart_count = 0

    while restart_count < _DAEMON_MAX_RESTARTS:
        logger.info(f"[Daemon] Creating event loop (restart #{restart_count})...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logger.info(f"[Daemon] Event loop created (restart #{restart_count})")

        start_time = _time.time()
        try:
            logger.info("[Daemon] Calling collector_daemon.main()...")
            loop.run_until_complete(collector_daemon.main())
            elapsed = _time.time() - start_time
            logger.warning(f"[Daemon] main() completed normally after {elapsed:.1f}s — unexpected!")
        except Exception as e:
            elapsed = _time.time() - start_time
            logger.error(f"[Daemon] CRASH after {elapsed:.1f}s: {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())
        finally:
            try:
                loop.close()
                logger.info("[Daemon] Event loop closed")
            except Exception as ce:
                logger.error(f"[Daemon] Error closing loop: {ce}")

        restart_count += 1
        logger.warning(f"[Daemon] Restarting in {_DAEMON_RESTART_DELAY}s... (attempt {restart_count}/{_DAEMON_MAX_RESTARTS})")
        _time.sleep(_DAEMON_RESTART_DELAY)

        # 모듈 리로드하여 fresh 상태로 시작
        try:
            import importlib
            importlib.reload(collector_daemon)
            logger.info("[Daemon] Module reloaded")
        except Exception as re:
            logger.error(f"[Daemon] Reload error: {re}")

    logger.error(f"[Daemon] Max restarts ({_DAEMON_MAX_RESTARTS}) exceeded — giving up")


@st.cache_resource
def start_background_daemon():
    """데몬을 백그라운드 스레드로 시작 (앱 시작 시 1회만 실행)."""
    # 환경변수 디버깅
    railway_env = os.environ.get("RAILWAY_ENVIRONMENT")
    daemon_enabled = os.environ.get("DAEMON_ENABLED")
    logger.info(f"[Daemon Check] RAILWAY_ENVIRONMENT={railway_env}, DAEMON_ENABLED={daemon_enabled}")

    # RAILWAY_ENVIRONMENT 또는 DAEMON_ENABLED=true 일 때만 실행
    if railway_env or daemon_enabled == "true":
        logger.info("[Daemon] Starting background daemon thread...")
        daemon_thread = threading.Thread(target=_run_daemon_in_thread, daemon=True)
        daemon_thread.start()
        logger.info("[Daemon] Thread started successfully")
        return {"status": "started", "thread": daemon_thread}
    logger.info("[Daemon] Disabled - conditions not met")
    return {"status": "disabled"}

st.set_page_config(
    page_title="CEX Dominance",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Compact Modern CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');

    :root {
        --bg-dark: #06060a;
        --card-bg: rgba(255, 255, 255, 0.03);
        --card-border: rgba(255, 255, 255, 0.08);
        --text-white: #ffffff;
        --text-gray: #8b8b8b;
        --text-dim: #4a4a4a;
        --accent-cyan: #00d4ff;
        --accent-purple: #a855f7;
        --accent-pink: #ec4899;
        --korean-color: #00d4ff;
        --global-color: #a855f7;
    }

    * { font-family: 'Space Grotesk', sans-serif; }

    .stApp {
        background: var(--bg-dark);
        background-image:
            radial-gradient(ellipse 80% 50% at 50% -20%, rgba(120, 0, 255, 0.12), transparent),
            radial-gradient(ellipse 60% 40% at 80% 100%, rgba(0, 212, 255, 0.08), transparent);
    }

    .main .block-container {
        padding: 0.25rem 1rem 0.5rem 1rem !important;
        max-width: 1600px;
    }

    /* Remove top padding + Compact layout */
    .block-container { padding-top: 0 !important; }
    
    /* 전역 폰트 사이즈 증가 */
    html, body, .stApp { font-size: 15px !important; }
    
    /* 마진/패딩 축소 */
    .element-container { margin-bottom: 0.25rem !important; }
    .stMarkdown { margin-bottom: 0 !important; }
    div[data-testid="column"] { padding: 0 0.25rem !important; }
    
    /* Streamlit 기본 여백 제거 */
    .st-emotion-cache-1y4p8pa { padding: 0 !important; }
    .st-emotion-cache-z5fcl4 { padding: 0.5rem 1rem !important; }
    .stApp > header { display: none !important; }
    section[data-testid="stSidebar"] { display: none !important; }
    div[data-testid="stToolbar"] { display: none !important; }
    div[data-testid="stDecoration"] { display: none !important; }

    #MainMenu, footer, header, .stDeployButton {display: none !important;}

    /* Compact Header */
    .header-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.75rem 0;
        border-bottom: 1px solid var(--card-border);
        margin-bottom: 1rem;
    }

    .logo {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .logo-icon {
        font-size: 1.5rem;
    }

    .logo-text {
        font-size: 1.25rem;
        font-weight: 700;
        color: var(--text-white);
    }

    .logo-badge {
        background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 0.6rem;
        font-weight: 600;
        letter-spacing: 0.1em;
        text-transform: uppercase;
    }

    /* Total Market Banner - 컴팩트 */
    .market-banner {
        background: linear-gradient(135deg, rgba(0, 212, 255, 0.08), rgba(168, 85, 247, 0.08));
        border: 1px solid rgba(0, 212, 255, 0.15);
        border-radius: 12px;
        padding: 0.75rem 1rem;
        margin-bottom: 0.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }

    .market-banner-left {
        display: flex;
        align-items: center;
        gap: 2rem;
    }

    .market-main {
        display: flex;
        align-items: baseline;
        gap: 0.5rem;
    }

    .market-value {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    .market-label {
        font-size: 0.7rem;
        color: var(--text-gray);
        text-transform: uppercase;
        letter-spacing: 0.1em;
    }

    .market-stats {
        display: flex;
        gap: 2rem;
    }

    .market-stat {
        text-align: center;
    }

    .market-stat-value {
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--text-white);
    }

    .market-stat-value.cyan { color: var(--accent-cyan); }
    .market-stat-value.purple { color: var(--accent-purple); }

    .market-stat-label {
        font-size: 0.65rem;
        color: var(--text-dim);
        text-transform: uppercase;
    }

    /* Ticker Section - 컴팩트 */
    .ticker-section {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 12px;
        padding: 0.75rem;
        margin-bottom: 0.5rem;
    }

    .ticker-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.75rem;
    }

    .ticker-title {
        font-size: 1rem;
        font-weight: 600;
        color: var(--text-white);
    }

    .ticker-dominance {
        font-size: 1.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    /* Mini Stats */
    .mini-stats {
        display: flex;
        gap: 1rem;
        margin-bottom: 0.75rem;
    }

    .mini-stat {
        flex: 1;
        background: rgba(255, 255, 255, 0.02);
        border-radius: 10px;
        padding: 0.6rem 0.8rem;
    }

    .mini-stat-value {
        font-size: 1rem;
        font-weight: 600;
        color: var(--text-white);
    }

    .mini-stat-label {
        font-size: 0.6rem;
        color: var(--text-dim);
        text-transform: uppercase;
    }

    /* Exchange Mini List */
    .exchange-mini-list {
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
    }

    .exchange-mini-row {
        display: flex;
        align-items: center;
        padding: 0.5rem 0.75rem;
        background: rgba(255, 255, 255, 0.02);
        border-radius: 8px;
        font-size: 0.85rem;
    }

    .exchange-mini-rank {
        width: 20px;
        color: var(--text-dim);
        font-weight: 500;
    }

    .exchange-mini-name {
        flex: 1;
        color: var(--text-white);
        font-weight: 500;
    }

    .exchange-mini-region {
        width: 60px;
        font-size: 0.7rem;
    }

    .exchange-mini-region.korean { color: var(--korean-color); }
    .exchange-mini-region.global { color: var(--global-color); }

    .exchange-mini-volume {
        width: 80px;
        text-align: right;
        color: var(--text-gray);
    }

    .exchange-mini-share {
        width: 50px;
        text-align: right;
        color: var(--text-white);
        font-weight: 500;
    }

    /* Charts Row */
    .chart-container {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 16px;
        padding: 1rem;
    }

    .chart-title {
        font-size: 0.8rem;
        font-weight: 600;
        color: var(--text-white);
        margin-bottom: 0.5rem;
    }

    /* Input Styles */
    .stTextInput > div > div > input {
        background: #1a1a1a !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        color: #ffffff !important;
        border-radius: 10px !important;
        padding: 0.5rem 0.75rem !important;
        font-size: 0.85rem !important;
    }

    .stTextInput > div > div > input::placeholder {
        color: #666666 !important;
    }

    .stTextInput > div > div > input:focus {
        border-color: var(--accent-cyan) !important;
        background: #222222 !important;
    }

    .stSelectbox > div > div {
        background: #1a1a1a !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        border-radius: 10px !important;
    }

    .stSelectbox > div > div > div {
        color: #ffffff !important;
    }

    /* Period selector pills style */
    div[data-testid="stHorizontalBlock"]:first-child .stSelectbox {
        margin-top: 0.5rem;
    }

    .stButton > button {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        color: var(--text-white) !important;
        border-radius: 10px !important;
        padding: 0.5rem 1rem !important;
        font-size: 0.8rem !important;
    }

    .stButton > button:hover {
        background: rgba(255, 255, 255, 0.1) !important;
    }

    /* Footer */
    .footer {
        text-align: center;
        padding: 1rem 0;
        margin-top: 1rem;
        border-top: 1px solid var(--card-border);
        font-size: 0.7rem;
        color: var(--text-dim);
    }

    /* Reduce Streamlit spacing */
    .element-container { margin-bottom: 0.5rem !important; }
    .stMarkdown { margin-bottom: 0 !important; }
    div[data-testid="column"] { padding: 0 0.5rem !important; }

    /* Market Status Bar (Fixed Bottom) */
    .market-status-bar {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: linear-gradient(135deg, rgba(10, 10, 15, 0.98), rgba(20, 20, 30, 0.98));
        border-top: 1px solid rgba(255, 255, 255, 0.1);
        padding: 0.6rem 1.5rem;
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 1.5rem;
        z-index: 1000;
        backdrop-filter: blur(10px);
    }

    .status-item {
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }

    .status-emoji {
        font-size: 1.1rem;
    }

    .status-label {
        font-size: 0.7rem;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .status-value {
        font-size: 0.85rem;
        font-weight: 600;
        color: #ffffff;
    }

    .status-divider {
        width: 1px;
        height: 20px;
        background: rgba(255, 255, 255, 0.15);
    }

    /* Add bottom padding to main content for status bar */
    .main .block-container {
        padding-bottom: 4rem !important;
    }

    /* ============================================
       MOBILE RESPONSIVE STYLES (Enhanced)
       ============================================ */
    @media (max-width: 768px) {
        .main .block-container {
            padding: 0.5rem 0.75rem 5rem 0.75rem !important;
        }

        /* Status bar mobile */
        .market-status-bar {
            padding: 0.5rem 0.75rem;
            gap: 0.5rem;
            flex-wrap: wrap;
            justify-content: space-around;
        }

        .status-item {
            flex-direction: column;
            gap: 0.1rem;
            min-width: 60px;
        }

        .status-label {
            font-size: 0.6rem;
        }

        .status-value {
            font-size: 0.75rem;
        }

        .status-divider {
            display: none;
        }

        /* Columns stack vertically on mobile */
        div[data-testid="stHorizontalBlock"] {
            flex-direction: column !important;
            gap: 0.75rem !important;
        }

        div[data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            padding: 0 !important;
        }

        /* GO Hero Card - mobile */
        [style*="font-size:3rem"] {
            font-size: 2.2rem !important;
        }
        
        [style*="font-size:2rem"] {
            font-size: 1.5rem !important;
        }
        
        [style*="font-size:2.5rem"] {
            font-size: 1.8rem !important;
        }

        /* Touch-friendly buttons */
        .stButton > button {
            min-height: 44px !important;
            font-size: 0.9rem !important;
        }

        /* Larger touch targets for inputs */
        .stTextInput > div > div > input {
            min-height: 44px !important;
            font-size: 1rem !important;
        }

        /* Compact cards */
        .ticker-section {
            padding: 0.75rem;
            margin-bottom: 0.75rem;
        }

        .ticker-title {
            font-size: 0.9rem;
        }

        .ticker-dominance {
            font-size: 1.2rem;
        }

        .mini-stats {
            gap: 0.5rem;
        }

        .mini-stat {
            padding: 0.4rem 0.5rem;
        }

        .mini-stat-value {
            font-size: 0.85rem;
        }

        .mini-stat-label {
            font-size: 0.55rem;
        }

        .exchange-mini-row {
            padding: 0.4rem 0.5rem;
            font-size: 0.75rem;
        }

        /* 2-column grid to 1-column on mobile */
        [style*="grid-template-columns:1fr 1fr"],
        [style*="grid-template-columns: 1fr 1fr"] {
            grid-template-columns: 1fr !important;
        }

        /* Charts smaller on mobile */
        .chart-container {
            padding: 0.75rem;
        }

        .chart-title {
            font-size: 0.75rem;
        }

        /* Market banner compact */
        .market-banner {
            padding: 0.75rem 1rem;
            flex-direction: column;
            gap: 0.75rem;
        }

        .market-banner-left {
            flex-direction: column;
            gap: 0.75rem;
            align-items: flex-start;
        }

        .market-value {
            font-size: 1.8rem;
        }

        .market-stats {
            gap: 1rem;
            flex-wrap: wrap;
        }

        .market-stat-value {
            font-size: 0.95rem;
        }

        /* GO card mobile */
        [style*="linear-gradient(135deg, #1a3a2a"] {
            padding: 1rem !important;
        }

        /* Expander mobile */
        .streamlit-expanderHeader {
            font-size: 0.9rem !important;
        }
    }

    /* Small phones */
    @media (max-width: 480px) {
        .market-status-bar {
            padding: 0.4rem 0.5rem;
        }

        .status-item {
            min-width: 50px;
        }

        .status-emoji {
            font-size: 0.9rem;
        }

        .status-label {
            font-size: 0.5rem;
        }

        .status-value {
            font-size: 0.65rem;
        }

        .market-value {
            font-size: 1.5rem;
        }
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def load_config():
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {
        "tickers": ["BTC/USDT", "ETH/USDT"],
        "exchanges": {
            "korean": [{"name": "upbit", "enabled": True}, {"name": "bithumb", "enabled": True}],
            "global": [{"name": "binance", "enabled": True}, {"name": "bybit", "enabled": True}, {"name": "okx", "enabled": True}]
        }
    }


@st.cache_data(ttl=60)
def fetch_all_data(_config, period: str = "24h"):
    """전체 마켓 + 주요 티커 데이터 조회"""
    async def _fetch():
        calc = DominanceCalculator(_config)
        await calc.initialize()

        # 연결된 거래소 목록
        connected = list(calc.exchanges.keys())

        # 전체 마켓
        total = await calc.calculate_total_market(["BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT"], period)

        # 개별 티커
        btc = await calc.calculate("BTC/USDT", period)
        eth = await calc.calculate("ETH/USDT", period)

        await calc.close()
        return {"total": total, "BTC": btc, "ETH": eth, "connected_exchanges": connected}

    return asyncio.run(_fetch())


@st.cache_data(ttl=60)
def fetch_ticker_data(_config, ticker: str, period: str = "24h"):
    async def _fetch():
        calc = DominanceCalculator(_config)
        await calc.initialize()
        result = await calc.calculate(ticker, period)
        await calc.close()
        return result
    return asyncio.run(_fetch())


def format_volume(volume: float) -> str:
    if volume >= 1_000_000_000:
        return f"${volume / 1_000_000_000:.2f}B"
    elif volume >= 1_000_000:
        return f"${volume / 1_000_000:.1f}M"
    elif volume >= 1_000:
        return f"${volume / 1_000:.1f}K"
    return f"${volume:.0f}"


def create_mini_donut(result: DominanceResult, height: int = 250):
    colors = ['#00d4ff', '#a855f7', '#ec4899', '#f59e0b', '#10b981']
    labels = [v.exchange.capitalize() for v in result.exchanges]
    values = [v.volume_usd for v in result.exchanges]

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.65,
        marker=dict(colors=colors[:len(labels)], line=dict(color='#06060a', width=2)),
        textposition='outside',
        textinfo='label+percent',
        textfont=dict(size=10, color='#a0a0a0'),
        hovertemplate="<b>%{label}</b><br>%{percent}<extra></extra>",
        pull=[0.02] * len(labels),
    )])

    fig.update_layout(
        showlegend=False,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(t=30, b=30, l=30, r=30),
        height=height,
        annotations=[dict(
            text=f"<b>{result.korean_dominance:.1f}%</b><br><span style='font-size:10px;color:#666;'>KR Share</span>",
            x=0.5, y=0.5,
            font=dict(size=20, color='#ffffff'),
            showarrow=False,
        )]
    )
    return fig


def create_bar_comparison(result: DominanceResult, height: int = 280):
    kr_pct = result.korean_volume_usd / result.total_volume_usd * 100 if result.total_volume_usd > 0 else 0
    gl_pct = result.global_volume_usd / result.total_volume_usd * 100 if result.total_volume_usd > 0 else 0

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=['Korean', 'Global'],
        y=[result.korean_volume_usd, result.global_volume_usd],
        marker=dict(color=['#00d4ff', '#a855f7'], cornerradius=8),
        text=[f"{format_volume(result.korean_volume_usd)} ({kr_pct:.1f}%)",
              f"{format_volume(result.global_volume_usd)} ({gl_pct:.1f}%)"],
        textposition='outside',
        textfont=dict(color='#ffffff', size=11),
        width=0.5,
        hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
        cliponaxis=False,
    ))

    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(t=60, b=30, l=20, r=20),
        height=height,
        xaxis=dict(tickfont=dict(color='#a0a0a0', size=12), showgrid=False),
        yaxis=dict(showgrid=False, showticklabels=False, range=[0, result.global_volume_usd * 1.25]),
        bargap=0.4,
    )
    return fig


def render_ticker_card(result: DominanceResult, title: str):
    """티커 카드 렌더링"""
    exchange_rows = []
    for i, v in enumerate(result.exchanges[:5], 1):
        share = v.volume_usd / result.total_volume_usd * 100 if result.total_volume_usd > 0 else 0
        region_class = "korean" if v.region == "korean" else "global"
        region_text = "KR" if v.region == "korean" else "GL"
        exchange_rows.append(f'<div class="exchange-mini-row"><span class="exchange-mini-rank">{i}</span><span class="exchange-mini-name">{v.exchange.capitalize()}</span><span class="exchange-mini-region {region_class}">{region_text}</span><span class="exchange-mini-volume">{format_volume(v.volume_usd)}</span><span class="exchange-mini-share">{share:.1f}%</span></div>')

    html = f'''<div class="ticker-section"><div class="ticker-header"><span class="ticker-title">{title}</span><span class="ticker-dominance">{result.korean_dominance:.2f}%</span></div><div class="mini-stats"><div class="mini-stat"><div class="mini-stat-value" style="color: #00d4ff;">{format_volume(result.korean_volume_usd)}</div><div class="mini-stat-label">Korean</div></div><div class="mini-stat"><div class="mini-stat-value" style="color: #a855f7;">{format_volume(result.global_volume_usd)}</div><div class="mini-stat-label">Global</div></div><div class="mini-stat"><div class="mini-stat-value">{format_volume(result.total_volume_usd)}</div><div class="mini-stat-label">Total</div></div></div><div class="exchange-mini-list">{"".join(exchange_rows)}</div></div>'''

    st.markdown(html, unsafe_allow_html=True)


def main():
    # Railway 환경에서 데몬 자동 시작
    daemon_info = start_background_daemon()

    config = load_config()

    # 메인 컨텐츠: 따리분석 (탭 없이 바로)
    render_ddari_tab()

    # 하단 시장 상태바 (CEX Dominance 요약)
    _render_market_status_bar(config)
    
    # Health 배너 (하단으로 이동)
    render_health_banner(st)


def _render_market_status_bar(config):
    """하단 시장 상태바 (CEX Dominance + 펀딩비 통합)."""
    try:
        data = fetch_all_data(config, "24h")
        if not data or not data.get("total"):
            return

        total = data["total"]
        kr_dom = total.korean_dominance
        kr_vol = total.korean_volume_usd
        gl_vol = total.global_volume_usd

        # 시장 분위기 판단
        if kr_dom > 5:
            mood_emoji = "🔥"
            mood_text = "활발"
            mood_color = "#4ade80"
        elif kr_dom > 2:
            mood_emoji = "✨"
            mood_text = "양호"
            mood_color = "#60a5fa"
        elif kr_dom > 0.5:
            mood_emoji = "😐"
            mood_text = "보통"
            mood_color = "#fbbf24"
        else:
            mood_emoji = "😴"
            mood_text = "한산"
            mood_color = "#94a3b8"

        # 펀딩비 데이터 가져오기
        funding_html = ""
        try:
            from ui.ddari_common import fetch_funding_rates_cached
            funding_data = fetch_funding_rates_cached()
            
            if funding_data.get("status") not in ["error", "no_data"]:
                avg_rate = funding_data.get("avg_funding_rate_pct", 0)
                position_bias = funding_data.get("position_bias", "neutral")
                
                # 펀딩비 색상 & 의미
                if position_bias == "long_heavy":
                    funding_color = "#4ade80"
                    funding_text = "롱↑"
                elif position_bias == "short_heavy":
                    funding_color = "#f87171"
                    funding_text = "숏↑"
                else:
                    funding_color = "#9ca3af"
                    funding_text = "중립"
                
                avg_color = "#4ade80" if avg_rate > 0 else "#f87171" if avg_rate < 0 else "#9ca3af"
                
                # 배경색 투명도 처리 (rgba 사용)
                if funding_color == "#4ade80":
                    bg_rgba = "rgba(74,222,128,0.15)"
                elif funding_color == "#f87171":
                    bg_rgba = "rgba(248,113,113,0.15)"
                else:
                    bg_rgba = "rgba(156,163,175,0.15)"
                
                funding_html = f'<div class="status-divider"></div><div class="status-item"><span class="status-label">💹펀딩비</span><span class="status-value" style="color:{avg_color};">{avg_rate:+.4f}%</span></div><div class="status-item"><span class="status-value" style="color:{funding_color};font-size:0.75rem;background:{bg_rgba};padding:2px 6px;border-radius:4px;">{funding_text}</span></div>'
        except Exception as fe:
            logger.debug(f"Funding rate fetch skipped: {fe}")

        status_html = f'''
        <div class="market-status-bar">
            <div class="status-item">
                <span class="status-emoji">{mood_emoji}</span>
                <span class="status-label">시장</span>
                <span class="status-value" style="color:{mood_color};">{mood_text}</span>
            </div>
            <div class="status-divider"></div>
            <div class="status-item">
                <span class="status-label">KR점유율</span>
                <span class="status-value" style="color:#00d4ff;">{kr_dom:.1f}%</span>
            </div>
            <div class="status-divider"></div>
            <div class="status-item">
                <span class="status-label">KR거래량</span>
                <span class="status-value">{format_volume(kr_vol)}</span>
            </div>
            <div class="status-divider"></div>
            <div class="status-item">
                <span class="status-label">GL거래량</span>
                <span class="status-value" style="color:#a855f7;">{format_volume(gl_vol)}</span>
            </div>
            {funding_html}
        </div>
        '''
        st.markdown(status_html, unsafe_allow_html=True)

    except Exception as e:
        logger.warning(f"Market status bar error: {e}")


def _render_dominance_tab(config):
    """CEX Dominance 탭 (기존 기능 100% 보존) - 백업용."""

    # Header with period selector
    header_col1, header_col2 = st.columns([4, 1])

    with header_col1:
        st.markdown("""
        <div class="header-row" style="border:none;padding-bottom:0;">
            <div class="logo">
                <span class="logo-icon">⚡</span>
                <span class="logo-text">CEX Dominance</span>
                <span class="logo-badge">LIVE</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with header_col2:
        period = st.selectbox(
            "Period",
            options=["1h", "4h", "24h", "7d", "30d"],
            index=2,  # Default to 24h
            label_visibility="collapsed",
            key="period_select"
        )

    # Fetch all data
    with st.spinner(""):
        data = fetch_all_data(config, period)

    if not data.get("total"):
        st.error("Failed to fetch market data")
        return

    total = data["total"]

    # Total Market Banner
    st.markdown(f"""
    <div class="market-banner">
        <div class="market-banner-left">
            <div>
                <div class="market-main">
                    <span class="market-value">{total.korean_dominance:.2f}%</span>
                </div>
                <div class="market-label">Total Korean Market Dominance</div>
            </div>
            <div class="market-stats">
                <div class="market-stat">
                    <div class="market-stat-value cyan">{format_volume(total.korean_volume_usd)}</div>
                    <div class="market-stat-label">Korean Vol</div>
                </div>
                <div class="market-stat">
                    <div class="market-stat-value purple">{format_volume(total.global_volume_usd)}</div>
                    <div class="market-stat-label">Global Vol</div>
                </div>
                <div class="market-stat">
                    <div class="market-stat-value">{format_volume(total.total_volume_usd)}</div>
                    <div class="market-stat-label">Total Vol</div>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Main Content: 3 columns
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        if data.get("BTC"):
            render_ticker_card(data["BTC"], "BTC/USDT")

    with col2:
        if data.get("ETH"):
            render_ticker_card(data["ETH"], "ETH/USDT")

    with col3:
        # Custom ticker search
        st.markdown('<div class="ticker-section"><div class="ticker-header"><span class="ticker-title">🔍 Search Ticker</span></div>', unsafe_allow_html=True)

        col_input, col_btn = st.columns([3, 1])
        with col_input:
            ticker_input = st.text_input("Search Ticker", value="SOL", placeholder="SOL, XRP...", label_visibility="collapsed", key="search")
        with col_btn:
            search = st.button("Go", width="stretch")

        ticker = f"{ticker_input.upper()}/USDT" if "/" not in ticker_input else ticker_input.upper()

        if ticker_input:
            custom_result = fetch_ticker_data(config, ticker, period)
            if custom_result and custom_result.total_volume_usd > 0:
                kr_vol = custom_result.korean_volume_usd
                kr_display = format_volume(kr_vol)
                kr_pct = f"{custom_result.korean_dominance:.2f}%"

                # Build exchange rows
                ex_rows = []
                for i, v in enumerate(custom_result.exchanges[:3], 1):
                    share = v.volume_usd / custom_result.total_volume_usd * 100 if custom_result.total_volume_usd > 0 else 0
                    region_class = "korean" if v.region == "korean" else "global"
                    ex_rows.append(f'<div class="exchange-mini-row"><span class="exchange-mini-rank">{i}</span><span class="exchange-mini-name">{v.exchange.capitalize()}</span><span class="exchange-mini-region {region_class}">{"KR" if v.region == "korean" else "GL"}</span><span class="exchange-mini-share">{share:.1f}%</span></div>')

                search_html = f'<div style="margin-top:0.5rem;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;"><span style="color:#8b8b8b;font-size:0.8rem;">{ticker}</span><span class="ticker-dominance">{kr_pct}</span></div><div class="mini-stats"><div class="mini-stat"><div class="mini-stat-value" style="color:#00d4ff;">{kr_display}</div><div class="mini-stat-label">KR</div></div><div class="mini-stat"><div class="mini-stat-value" style="color:#a855f7;">{format_volume(custom_result.global_volume_usd)}</div><div class="mini-stat-label">GL</div></div></div>{"".join(ex_rows)}</div>'
                st.markdown(search_html, unsafe_allow_html=True)
            else:
                st.markdown('<p style="color:#666;font-size:0.8rem;margin-top:1rem;">No data found for this ticker</p>', unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # Charts Row
    col1, col2 = st.columns(2)

    with col1:
        st.markdown('<p class="chart-title" style="margin:1rem 0 0.5rem 0;">📊 Total Market Distribution</p>', unsafe_allow_html=True)
        fig = create_mini_donut(total, height=220)
        st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})

    with col2:
        st.markdown('<p class="chart-title" style="margin:1rem 0 0.5rem 0;">📈 Korean vs Global Volume</p>', unsafe_allow_html=True)
        fig = create_bar_comparison(total, height=220)
        st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})

    # Exchange Rankings (Compact)
    st.markdown('<p class="chart-title" style="margin:1rem 0 0.5rem 0;">🏆 Exchange Rankings (Total Market)</p>', unsafe_allow_html=True)

    ranking_html = '<div style="display:flex;justify-content:space-around;background:rgba(255,255,255,0.02);border-radius:12px;padding:1rem;">'
    for i, v in enumerate(total.exchanges[:5]):
        share = v.volume_usd / total.total_volume_usd * 100 if total.total_volume_usd > 0 else 0
        region_color = "#00d4ff" if v.region == "korean" else "#a855f7"
        ranking_html += f'<div style="text-align:center;"><div style="font-size:1.5rem;font-weight:700;color:{region_color};">#{i+1}</div><div style="font-size:0.9rem;font-weight:600;color:#fff;">{v.exchange.capitalize()}</div><div style="font-size:0.8rem;color:#8b8b8b;">{format_volume(v.volume_usd)}</div><div style="font-size:0.75rem;color:#666;">{share:.1f}%</div></div>'
    ranking_html += '</div>'
    st.markdown(ranking_html, unsafe_allow_html=True)

    # Footer
    update_time = datetime.fromtimestamp(total.timestamp).strftime("%H:%M:%S")
    connected = data.get("connected_exchanges", [])
    exchanges_str = ", ".join([ex.capitalize() for ex in connected]) if connected else "None"
    st.markdown(f'<div class="footer">Updated {update_time} · Connected: {exchanges_str} · Auto-refresh 60s</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
