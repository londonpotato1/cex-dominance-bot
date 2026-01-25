"""
CEX Dominance Dashboard
Modern Compact UI
"""

import streamlit as st
import asyncio
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from pathlib import Path

from dominance import DominanceCalculator, DominanceResult

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
        padding: 0.5rem 2rem 1rem 2rem !important;
        max-width: 1400px;
    }

    /* Remove top padding */
    .block-container { padding-top: 0 !important; }
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

    /* Total Market Banner */
    .market-banner {
        background: linear-gradient(135deg, rgba(0, 212, 255, 0.08), rgba(168, 85, 247, 0.08));
        border: 1px solid rgba(0, 212, 255, 0.15);
        border-radius: 16px;
        padding: 1rem 1.5rem;
        margin-bottom: 1rem;
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

    /* Ticker Section */
    .ticker-section {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 16px;
        padding: 1rem;
        margin-bottom: 1rem;
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
    config = load_config()

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
            options=["1h", "4h", "24h", "7d"],
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
            ticker_input = st.text_input("", value="SOL", placeholder="SOL, XRP...", label_visibility="collapsed", key="search")
        with col_btn:
            search = st.button("Go", use_container_width=True)

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
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    with col2:
        st.markdown('<p class="chart-title" style="margin:1rem 0 0.5rem 0;">📈 Korean vs Global Volume</p>', unsafe_allow_html=True)
        fig = create_bar_comparison(total, height=220)
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

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
