#!/usr/bin/env python3
"""
CEX Dominance Bot
거래소별 거래량 지배력 실시간 모니터링

사용법:
    python main.py              # 실시간 모니터링
    python main.py --once       # 1회 조회
    python main.py --ticker BTC # 특정 티커만
"""

import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Windows 콘솔 UTF-8 설정
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import yaml

from dominance import DominanceCalculator, DominanceResult

# 로깅 설정
def setup_logging(config: dict):
    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO"))

    # 로그 디렉토리 생성
    log_file = log_config.get("file")
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def format_volume(volume: float) -> str:
    """거래량 포맷팅"""
    if volume >= 1_000_000_000:
        return f"${volume / 1_000_000_000:.2f}B"
    elif volume >= 1_000_000:
        return f"${volume / 1_000_000:.2f}M"
    elif volume >= 1_000:
        return f"${volume / 1_000:.2f}K"
    return f"${volume:.2f}"


def print_result(result: DominanceResult):
    """결과 출력"""
    timestamp = datetime.fromtimestamp(result.timestamp).strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "=" * 60)
    print(f"  CEX DOMINANCE - {result.ticker}")
    print(f"  {timestamp}")
    print("=" * 60)

    # 지배력 바 그래프
    bar_width = 40
    korean_bar = int(result.korean_dominance / 100 * bar_width)
    global_bar = bar_width - korean_bar

    print(f"\n  한국 지배력: {result.korean_dominance:.2f}%")
    print(f"  [{'█' * korean_bar}{'░' * global_bar}]")
    print(f"   한국 {format_volume(result.korean_volume_usd)} | 글로벌 {format_volume(result.global_volume_usd)}")

    # 거래소별 상세
    print(f"\n  {'거래소':<12} {'지역':<8} {'거래량(USD)':<15} {'점유율':<10}")
    print("  " + "-" * 50)

    for vol in result.exchanges:
        share = vol.volume_usd / result.total_volume_usd * 100 if result.total_volume_usd > 0 else 0
        region_kr = "한국" if vol.region == "korean" else "글로벌"
        print(f"  {vol.exchange:<12} {region_kr:<8} {format_volume(vol.volume_usd):<15} {share:.1f}%")

    print("=" * 60)


async def send_telegram_alert(config: dict, result: DominanceResult, message: str):
    """텔레그램 알림 전송"""
    telegram_config = config.get("telegram", {})
    if not telegram_config.get("enabled"):
        return

    bot_token = telegram_config.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = telegram_config.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        return

    try:
        import aiohttp
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }
        async with aiohttp.ClientSession() as session:
            await session.post(url, json=payload)
    except Exception as e:
        logging.warning(f"텔레그램 전송 실패: {e}")


class DominanceBot:
    """지배력 모니터링 봇"""

    def __init__(self, config: dict):
        self.config = config
        self.calculator = DominanceCalculator(config)
        self.last_results: dict[str, DominanceResult] = {}
        self.last_alert_time: dict[str, float] = {}

    async def start(self):
        """봇 시작"""
        await self.calculator.initialize()

    async def stop(self):
        """봇 종료"""
        await self.calculator.close()

    async def check_alerts(self, result: DominanceResult):
        """알림 조건 체크"""
        import time

        alerts_config = self.config.get("alerts", {})
        cooldown = alerts_config.get("cooldown_seconds", 300)
        threshold = alerts_config.get("korean_dominance_threshold", 25.0)
        change_threshold = alerts_config.get("dominance_change_threshold", 5.0)

        ticker = result.ticker
        now = time.time()

        # 쿨다운 체크
        if ticker in self.last_alert_time:
            if now - self.last_alert_time[ticker] < cooldown:
                return

        messages = []

        # 한국 지배력 임계값 초과
        if result.korean_dominance >= threshold:
            messages.append(
                f"🇰🇷 <b>{ticker} 한국 지배력 {result.korean_dominance:.1f}%</b>\n"
                f"임계값 {threshold}% 초과!"
            )

        # 지배력 급변 감지
        if ticker in self.last_results:
            prev = self.last_results[ticker]
            change = abs(result.korean_dominance - prev.korean_dominance)
            if change >= change_threshold:
                direction = "📈" if result.korean_dominance > prev.korean_dominance else "📉"
                messages.append(
                    f"{direction} <b>{ticker} 지배력 급변</b>\n"
                    f"{prev.korean_dominance:.1f}% → {result.korean_dominance:.1f}% "
                    f"({'+' if change > 0 else ''}{change:.1f}%)"
                )

        # 알림 전송
        for msg in messages:
            print(f"\n⚠️  알림: {msg.replace('<b>', '').replace('</b>', '')}")
            await send_telegram_alert(self.config, result, msg)
            self.last_alert_time[ticker] = now

        self.last_results[ticker] = result

    async def run_once(self, tickers: list[str] = None):
        """1회 조회"""
        tickers = tickers or self.config.get("tickers", ["BTC/USDT"])

        for ticker in tickers:
            result = await self.calculator.calculate(ticker)
            if result:
                print_result(result)
                await self.check_alerts(result)

    async def run_loop(self):
        """실시간 모니터링 루프"""
        interval = self.config.get("update_interval", 60)
        tickers = self.config.get("tickers", ["BTC/USDT"])

        print(f"\n🚀 CEX Dominance Bot 시작")
        print(f"   티커: {', '.join(tickers)}")
        print(f"   업데이트 주기: {interval}초")
        print(f"   종료: Ctrl+C\n")

        try:
            while True:
                await self.run_once(tickers)
                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            print("\n\n👋 봇 종료")


async def main():
    parser = argparse.ArgumentParser(description="CEX Dominance Bot")
    parser.add_argument("--once", action="store_true", help="1회만 조회")
    parser.add_argument("--ticker", type=str, help="특정 티커만 조회 (예: BTC)")
    parser.add_argument("--config", type=str, default="config.yaml", help="설정 파일 경로")
    args = parser.parse_args()

    # 설정 로드
    config_path = Path(__file__).parent / args.config
    if not config_path.exists():
        print(f"설정 파일 없음: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    setup_logging(config)

    # 티커 오버라이드
    if args.ticker:
        ticker = args.ticker.upper()
        if "/" not in ticker:
            ticker = f"{ticker}/USDT"
        config["tickers"] = [ticker]

    # 봇 실행
    bot = DominanceBot(config)
    await bot.start()

    try:
        if args.once:
            await bot.run_once()
        else:
            await bot.run_loop()
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
