"""
CEX Dominance Module
거래소별 거래량 지배력 계산
"""

import asyncio
import ccxt.async_support as ccxt
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExchangeVolume:
    """거래소별 거래량 데이터"""
    exchange: str
    ticker: str
    volume_24h: float  # 24시간 거래량 (base currency)
    volume_usd: float  # USD 환산 거래량
    price: float       # 현재가
    region: str        # korean / global


@dataclass
class DominanceResult:
    """지배력 계산 결과"""
    ticker: str
    total_volume_usd: float
    korean_volume_usd: float
    global_volume_usd: float
    korean_dominance: float  # 한국 지배력 (%)
    exchanges: list[ExchangeVolume]
    timestamp: float


class DominanceCalculator:
    """거래소 지배력 계산기"""

    # 한국 거래소 목록 (KRW 페어 사용)
    KOREAN_EXCHANGES = {"upbit", "bithumb"}

    def __init__(self, config: dict):
        self.config = config
        self.exchanges: dict[str, ccxt.Exchange] = {}
        self._krw_rate: Optional[float] = None

    async def initialize(self):
        """거래소 연결 초기화"""
        all_exchanges = (
            self.config["exchanges"]["korean"] +
            self.config["exchanges"]["global"]
        )

        for ex_config in all_exchanges:
            if not ex_config.get("enabled", True):
                continue

            name = ex_config["name"]
            try:
                exchange_class = getattr(ccxt, name)
                exchange = exchange_class({
                    "enableRateLimit": True,
                    "timeout": 30000,
                })
                # 마켓 정보 로드
                await exchange.load_markets()
                self.exchanges[name] = exchange
                logger.info(f"거래소 연결 성공: {name} ({len(exchange.markets)} markets)")
            except Exception as e:
                logger.warning(f"거래소 연결 실패 ({name}): {e}")

        # KRW/USD 환율 조회 (업비트 USDT/KRW 기준)
        await self._fetch_krw_rate()

    async def _fetch_krw_rate(self):
        """KRW/USD 환율 조회"""
        try:
            if "upbit" in self.exchanges:
                ticker = await self.exchanges["upbit"].fetch_ticker("USDT/KRW")
                self._krw_rate = ticker["last"]
                logger.info(f"KRW 환율: {self._krw_rate:.2f}")
            else:
                # 기본값 사용
                self._krw_rate = 1350.0
                logger.warning(f"KRW 환율 기본값 사용: {self._krw_rate}")
        except Exception as e:
            self._krw_rate = 1350.0
            logger.warning(f"KRW 환율 조회 실패, 기본값 사용: {e}")

    def _get_ticker_for_exchange(self, exchange: str, ticker: str) -> str:
        """거래소별 티커 변환 (한국 거래소는 자동으로 KRW 페어로 변환)"""
        if exchange in self.KOREAN_EXCHANGES:
            # X/USDT -> X/KRW 자동 변환
            if ticker.endswith("/USDT"):
                return ticker.replace("/USDT", "/KRW")
            elif ticker.endswith("/BUSD"):
                return ticker.replace("/BUSD", "/KRW")
        return ticker

    async def _fetch_volume(
        self,
        exchange_name: str,
        ticker: str,
        region: str
    ) -> Optional[ExchangeVolume]:
        """개별 거래소 거래량 조회"""
        if exchange_name not in self.exchanges:
            return None

        exchange = self.exchanges[exchange_name]
        actual_ticker = self._get_ticker_for_exchange(exchange_name, ticker)

        try:
            data = await exchange.fetch_ticker(actual_ticker)
            volume_24h = data.get("quoteVolume") or data.get("baseVolume", 0) * data.get("last", 0)
            price = data.get("last", 0)

            # USD 환산
            if region == "korean":
                volume_usd = volume_24h / self._krw_rate if self._krw_rate else 0
            else:
                volume_usd = volume_24h

            return ExchangeVolume(
                exchange=exchange_name,
                ticker=ticker,
                volume_24h=volume_24h,
                volume_usd=volume_usd,
                price=price,
                region=region,
            )

        except Exception as e:
            logger.warning(f"거래량 조회 실패 ({exchange_name}/{actual_ticker}): {e}")
            return None

    async def _fetch_volume_ohlcv(
        self,
        exchange_name: str,
        ticker: str,
        region: str,
        timeframe: str,
        limit: int
    ) -> Optional[ExchangeVolume]:
        """OHLCV 기반 거래량 조회 (기간별)"""
        if exchange_name not in self.exchanges:
            return None

        exchange = self.exchanges[exchange_name]
        actual_ticker = self._get_ticker_for_exchange(exchange_name, ticker)

        try:
            ohlcv = await exchange.fetch_ohlcv(actual_ticker, timeframe, limit=limit)
            if not ohlcv:
                return None

            # OHLCV: [timestamp, open, high, low, close, volume]
            total_volume = sum(candle[5] for candle in ohlcv)
            last_price = ohlcv[-1][4] if ohlcv else 0

            # Quote volume 계산 (volume * price)
            volume_quote = sum(candle[5] * candle[4] for candle in ohlcv)

            # USD 환산
            if region == "korean":
                volume_usd = volume_quote / self._krw_rate if self._krw_rate else 0
            else:
                volume_usd = volume_quote

            return ExchangeVolume(
                exchange=exchange_name,
                ticker=ticker,
                volume_24h=total_volume,
                volume_usd=volume_usd,
                price=last_price,
                region=region,
            )

        except Exception as e:
            logger.warning(f"OHLCV 조회 실패 ({exchange_name}/{actual_ticker}): {e}")
            return None

    async def calculate(self, ticker: str, period: str = "24h") -> Optional[DominanceResult]:
        """지배력 계산 (period: 1h, 4h, 24h, 7d)"""
        import time

        # 기간별 OHLCV 설정
        period_config = {
            "1h": ("1m", 60),      # 1분봉 60개
            "4h": ("5m", 48),      # 5분봉 48개
            "24h": ("1h", 24),     # 1시간봉 24개
            "7d": ("4h", 42),      # 4시간봉 42개
        }

        tasks = []
        use_ohlcv = period != "24h"
        timeframe, limit = period_config.get(period, ("1h", 24))

        # 한국 거래소
        for ex in self.config["exchanges"]["korean"]:
            if ex.get("enabled", True):
                if use_ohlcv:
                    tasks.append(self._fetch_volume_ohlcv(ex["name"], ticker, "korean", timeframe, limit))
                else:
                    tasks.append(self._fetch_volume(ex["name"], ticker, "korean"))

        # 글로벌 거래소
        for ex in self.config["exchanges"]["global"]:
            if ex.get("enabled", True):
                if use_ohlcv:
                    tasks.append(self._fetch_volume_ohlcv(ex["name"], ticker, "global", timeframe, limit))
                else:
                    tasks.append(self._fetch_volume(ex["name"], ticker, "global"))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 유효한 결과만 필터링
        volumes: list[ExchangeVolume] = [
            r for r in results
            if isinstance(r, ExchangeVolume) and r.volume_usd > 0
        ]

        if not volumes:
            logger.warning(f"유효한 거래량 데이터 없음: {ticker}")
            return None

        # 지배력 계산
        korean_volume = sum(v.volume_usd for v in volumes if v.region == "korean")
        global_volume = sum(v.volume_usd for v in volumes if v.region == "global")
        total_volume = korean_volume + global_volume

        korean_dominance = (korean_volume / total_volume * 100) if total_volume > 0 else 0

        return DominanceResult(
            ticker=ticker,
            total_volume_usd=total_volume,
            korean_volume_usd=korean_volume,
            global_volume_usd=global_volume,
            korean_dominance=korean_dominance,
            exchanges=sorted(volumes, key=lambda x: x.volume_usd, reverse=True),
            timestamp=time.time(),
        )

    async def calculate_total_market(self, tickers: list[str] = None, period: str = "24h") -> Optional[DominanceResult]:
        """전체 마켓 지배력 계산 (여러 티커 합산)"""
        import time

        if tickers is None:
            tickers = ["BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT", "DOGE/USDT"]

        all_volumes: list[ExchangeVolume] = []

        for ticker in tickers:
            result = await self.calculate(ticker, period)
            if result:
                all_volumes.extend(result.exchanges)

        if not all_volumes:
            return None

        # 거래소별 합산
        exchange_totals: dict[str, ExchangeVolume] = {}
        for v in all_volumes:
            key = v.exchange
            if key in exchange_totals:
                exchange_totals[key] = ExchangeVolume(
                    exchange=v.exchange,
                    ticker="TOTAL",
                    volume_24h=exchange_totals[key].volume_24h + v.volume_24h,
                    volume_usd=exchange_totals[key].volume_usd + v.volume_usd,
                    price=0,
                    region=v.region,
                )
            else:
                exchange_totals[key] = ExchangeVolume(
                    exchange=v.exchange,
                    ticker="TOTAL",
                    volume_24h=v.volume_24h,
                    volume_usd=v.volume_usd,
                    price=0,
                    region=v.region,
                )

        volumes = list(exchange_totals.values())
        korean_volume = sum(v.volume_usd for v in volumes if v.region == "korean")
        global_volume = sum(v.volume_usd for v in volumes if v.region == "global")
        total_volume = korean_volume + global_volume
        korean_dominance = (korean_volume / total_volume * 100) if total_volume > 0 else 0

        return DominanceResult(
            ticker="TOTAL MARKET",
            total_volume_usd=total_volume,
            korean_volume_usd=korean_volume,
            global_volume_usd=global_volume,
            korean_dominance=korean_dominance,
            exchanges=sorted(volumes, key=lambda x: x.volume_usd, reverse=True),
            timestamp=time.time(),
        )

    async def close(self):
        """연결 종료"""
        for exchange in self.exchanges.values():
            try:
                await exchange.close()
            except Exception:
                pass
