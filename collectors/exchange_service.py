#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
거래소 서비스
- CCXT 기반 REST API + 콜백 시스템
- 병렬 조회 지원
"""
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional, Dict, List, Callable, Any
from enum import Enum

try:
    import ccxt
except ImportError:
    ccxt = None


class MarketType(Enum):
    SPOT = "spot"
    FUTURES = "futures"


@dataclass
class PriceData:
    """가격 데이터"""
    exchange: str
    symbol: str
    price: float
    market_type: MarketType
    timestamp: float
    funding_rate: Optional[float] = None
    latency_ms: Optional[float] = None
    krw_price: Optional[float] = None  # 원화 가격 (업비트/빗썸용)
    next_funding_time: Optional[float] = None  # 다음 펀딩 시간 (Unix timestamp)


@dataclass
class ExchangeStatus:
    """거래소 상태"""
    exchange: str
    connected: bool
    last_update: float
    error: Optional[str] = None


class ExchangeService:
    """거래소 서비스"""

    # 거래소별 설정
    EXCHANGE_CONFIG = {
        'binance': {
            'spot_class': 'binance',
            'futures_class': 'binanceusdm',
            'spot_suffix': '/USDT',
            'futures_suffix': '/USDT:USDT',
        },
        'bybit': {
            'spot_class': 'bybit',
            'futures_class': 'bybit',
            'spot_suffix': '/USDT',
            'futures_suffix': '/USDT:USDT',
            'futures_options': {'defaultType': 'swap'},
        },
        'okx': {
            'spot_class': 'okx',
            'futures_class': 'okx',
            'spot_suffix': '/USDT',
            'futures_suffix': '/USDT:USDT',
            'futures_options': {'defaultType': 'swap'},
        },
        'gate': {
            'spot_class': 'gateio',
            'futures_class': 'gateio',
            'spot_suffix': '/USDT',
            'futures_suffix': '/USDT:USDT',
            'futures_options': {'defaultType': 'swap'},
        },
        'bitget': {
            'spot_class': 'bitget',
            'futures_class': 'bitget',
            'spot_suffix': '/USDT',
            'futures_suffix': '/USDT:USDT',
            'futures_options': {'defaultType': 'swap'},
        },
        'mexc': {
            'spot_class': 'mexc',
            'futures_class': 'mexc',
            'spot_suffix': '/USDT',
            'futures_suffix': '/USDT:USDT',
            'futures_options': {'defaultType': 'swap'},
        },
        'kucoin': {
            'spot_class': 'kucoin',
            'futures_class': 'kucoinfutures',
            'spot_suffix': '/USDT',
            'futures_suffix': '/USDT:USDT',
        },
        'htx': {
            'spot_class': 'htx',
            'futures_class': 'htx',
            'spot_suffix': '/USDT',
            'futures_suffix': '/USDT:USDT',
            'futures_options': {'defaultType': 'swap'},
        },
        'hyperliquid': {
            'futures_only': True,
            'custom': True,
        },
        'lighter': {
            'futures_only': True,
            'custom': True,
        },
        'aster': {
            'futures_only': True,
            'custom': True,
        },
        'upbit': {
            'spot_class': 'upbit',
            'spot_only': True,
            'spot_suffix': '/KRW',
            'krw': True,  # 원화 거래소
        },
        'bithumb': {
            'spot_class': 'bithumb',
            'spot_only': True,
            'spot_suffix': '/KRW',
            'krw': True,  # 원화 거래소
        },
    }

    # Lighter 마켓 ID 매핑 (심볼 -> 마켓 ID) - perp 마켓
    LIGHTER_MARKETS = {
        'BTC': 1,
        'SOL': 2,
        'ETH': 3,
        '1000PEPE': 4,
        'WLD': 6,
        'XRP': 7,
        'AVAX': 9,
        'NEAR': 10,
        'DOT': 11,
        'TAO': 13,
        'POL': 14,
        'TRUMP': 15,
        'SUI': 16,
        '1000SHIB': 17,
        '1000BONK': 18,
        '1000FLOKI': 19,
        'HYPE': 24,
        'BNB': 25,
        'JUP': 26,
        'AAVE': 27,
        'ENA': 29,
        'UNI': 30,
        'SEI': 32,
        'IP': 34,
        'LTC': 35,
        'CRV': 36,
        'PENDLE': 37,
        'ONDO': 38,
        'S': 40,
        'VIRTUAL': 41,
        'SYRUP': 44,
        'PUMP': 45,
        'LDO': 46,
        'PENGU': 47,
        'PAXG': 48,
        'EIGEN': 49,
        'ARB': 50,
        'RESOLV': 51,
        'GRASS': 52,
        'ZORA': 53,
        'OP': 55,
        'ZK': 56,
        'BCH': 58,
        'HBAR': 59,
        'GMX': 61,
        'DYDX': 62,
        'AERO': 65,
        'USELESS': 66,
        'MORPHO': 68,
        'YZY': 70,
        'XPL': 71,
        'WLFI': 72,
        'CRO': 73,
        'DOLO': 75,
        'LINEA': 76,
        'XMR': 77,
        'PYTH': 78,
        '1000TOSHI': 81,
        'AVNT': 82,
        'ASTER': 83,
        '0G': 84,
        'STBL': 85,
        '2Z': 88,
        'MON': 91,
        'XAU': 92,
        'XAG': 93,
        'MEGA': 94,
        'MET': 95,
        'EURUSD': 96,
        'GBPUSD': 97,
        'USDCAD': 100,
        'ICP': 102,
        'FIL': 103,
        'STRK': 104,
        'USDKRW': 105,
        'AUDUSD': 106,
        'NZDUSD': 107,
        'HOOD': 108,
        'PLTR': 111,
        'TSLA': 112,
        'AAPL': 113,
        'AMZN': 114,
        'MSFT': 115,
        'GOOGL': 116,
        'META': 117,
        'STABLE': 118,
        'XLM': 119,
        'LIT': 120,
        'CRCL': 121,
        'MSTR': 122,
        'BMNR': 123,
    }

    # 심볼별 거래소 제한 (동명이인 토큰 문제 해결)
    # 특정 심볼은 특정 거래소에서만 조회
    SYMBOL_EXCHANGE_MAP = {
        'LIT': {
            'spot': ['lighter'],           # LIT Spot은 Lighter에서만
            'futures': ['hyperliquid'],    # LIT Futures는 Hyperliquid에서만
        },
        # 필요시 다른 심볼 추가 가능
    }

    @classmethod
    def get_allowed_exchanges(cls, symbol: str, market_type: str) -> List[str]:
        """심볼별 허용된 거래소 목록 반환"""
        symbol = symbol.upper()
        if symbol in cls.SYMBOL_EXCHANGE_MAP:
            return cls.SYMBOL_EXCHANGE_MAP[symbol].get(market_type, [])
        return None  # None이면 모든 거래소 허용

    def __init__(self):
        self._spot_exchanges: Dict[str, Any] = {}
        self._futures_exchanges: Dict[str, Any] = {}
        self._executor = ThreadPoolExecutor(max_workers=20)
        self._running = False
        self._prices: Dict[str, Dict[str, PriceData]] = {'spot': {}, 'futures': {}}
        self._status: Dict[str, ExchangeStatus] = {}
        self._callbacks: List[Callable] = []
        self._event_callbacks: List[Callable] = []
        self._lock = threading.Lock()

        # KRW 환율 캐시 (거래소별 USDT/KRW)
        self._krw_rates: Dict[str, float] = {}
        self._krw_rates_timestamp: Dict[str, float] = {}
        self._krw_rate_ttl = 30  # 30초 캐시

        self._init_exchanges()

    def _init_exchanges(self):
        """거래소 초기화"""
        if ccxt is None:
            self._emit_event("CCXT not installed", "error")
            return

        for ex_id, config in self.EXCHANGE_CONFIG.items():
            if config.get('custom'):
                continue

            try:
                # Spot 거래소
                if not config.get('futures_only'):
                    spot_class = getattr(ccxt, config['spot_class'])
                    self._spot_exchanges[ex_id] = spot_class({
                        'enableRateLimit': True,
                        'timeout': 10000,
                    })

                # Futures 거래소
                if not config.get('spot_only'):
                    futures_class_name = config.get('futures_class', config.get('spot_class'))
                    futures_class = getattr(ccxt, futures_class_name)
                    options = config.get('futures_options', {})
                    self._futures_exchanges[ex_id] = futures_class({
                        'enableRateLimit': True,
                        'timeout': 10000,
                        'options': options,
                    })

                self._status[ex_id] = ExchangeStatus(
                    exchange=ex_id,
                    connected=True,
                    last_update=time.time()
                )

            except Exception as e:
                self._emit_event(f"Failed to init {ex_id}: {e}", "error")
                self._status[ex_id] = ExchangeStatus(
                    exchange=ex_id,
                    connected=False,
                    last_update=time.time(),
                    error=str(e)
                )

    def add_price_callback(self, callback: Callable):
        """가격 업데이트 콜백 추가"""
        self._callbacks.append(callback)

    def add_event_callback(self, callback: Callable):
        """이벤트 로그 콜백 추가"""
        self._event_callbacks.append(callback)

    def _emit_event(self, message: str, level: str = "info"):
        """이벤트 발생"""
        for callback in self._event_callbacks:
            try:
                callback(message, level)
            except:
                pass

    def _emit_prices(self, prices: Dict[str, Dict[str, PriceData]]):
        """가격 업데이트 발생"""
        for callback in self._callbacks:
            try:
                callback(prices)
            except:
                pass

    def _get_krw_rate(self, exchange: str) -> Optional[float]:
        """KRW 거래소의 USDT/KRW 환율 조회 (캐시 사용)"""
        now = time.time()

        # 캐시 확인
        if exchange in self._krw_rates:
            if now - self._krw_rates_timestamp.get(exchange, 0) < self._krw_rate_ttl:
                return self._krw_rates[exchange]

        # 환율 조회
        if exchange not in self._spot_exchanges:
            return None

        try:
            ex = self._spot_exchanges[exchange]
            ticker = ex.fetch_ticker('USDT/KRW')
            rate = ticker.get('last') or ticker.get('close')
            if rate:
                self._krw_rates[exchange] = float(rate)
                self._krw_rates_timestamp[exchange] = now
                return float(rate)
        except Exception as e:
            self._emit_event(f"{exchange} USDT/KRW 조회 실패: {e}", "warning")

        return self._krw_rates.get(exchange)  # 이전 캐시 반환

    def _fetch_funding_info(self, exchange: str, symbol: str) -> tuple:
        """거래소별 API로 펀딩비 및 다음 펀딩 시간 직접 조회

        Returns:
            (funding_rate, next_funding_time) 튜플
        """
        import requests

        funding_rate = None
        next_funding_time = None

        try:
            if exchange == 'binance':
                # Binance: GET /fapi/v1/premiumIndex
                resp = requests.get(
                    f"https://fapi.binance.com/fapi/v1/premiumIndex",
                    params={"symbol": f"{symbol}USDT"},
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if 'lastFundingRate' in data:
                        funding_rate = float(data['lastFundingRate'])
                    if 'nextFundingTime' in data:
                        next_funding_time = data['nextFundingTime'] / 1000  # ms -> s

            elif exchange == 'bybit':
                # Bybit: GET /v5/market/tickers
                resp = requests.get(
                    f"https://api.bybit.com/v5/market/tickers",
                    params={"category": "linear", "symbol": f"{symbol}USDT"},
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('retCode') == 0 and data.get('result', {}).get('list'):
                        item = data['result']['list'][0]
                        if 'fundingRate' in item:
                            funding_rate = float(item['fundingRate'])
                        if 'nextFundingTime' in item:
                            next_funding_time = int(item['nextFundingTime']) / 1000

            elif exchange == 'okx':
                # OKX: GET /api/v5/public/funding-rate
                resp = requests.get(
                    f"https://www.okx.com/api/v5/public/funding-rate",
                    params={"instId": f"{symbol}-USDT-SWAP"},
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('code') == '0' and data.get('data'):
                        item = data['data'][0]
                        if 'fundingRate' in item:
                            funding_rate = float(item['fundingRate'])
                        if 'nextFundingTime' in item:
                            next_funding_time = int(item['nextFundingTime']) / 1000

            elif exchange == 'gate':
                # Gate.io: GET /api/v4/futures/usdt/contracts/{contract}
                resp = requests.get(
                    f"https://api.gateio.ws/api/v4/futures/usdt/contracts/{symbol}_USDT",
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if 'funding_rate' in data:
                        funding_rate = float(data['funding_rate'])
                    if 'funding_next_apply' in data:
                        next_funding_time = float(data['funding_next_apply'])

            elif exchange == 'bitget':
                # Bitget: GET /api/v2/mix/market/current-fund-rate
                resp = requests.get(
                    f"https://api.bitget.com/api/v2/mix/market/current-fund-rate",
                    params={"symbol": f"{symbol}USDT", "productType": "USDT-FUTURES"},
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('code') == '00000' and data.get('data'):
                        item = data['data']
                        if 'fundingRate' in item:
                            funding_rate = float(item['fundingRate'])
                        # Bitget은 nextFundingTime이 없을 수 있음

            else:
                # 기타 거래소는 CCXT 사용
                if exchange in self._futures_exchanges:
                    ex = self._futures_exchanges[exchange]
                    config = self.EXCHANGE_CONFIG.get(exchange, {})
                    full_symbol = f"{symbol}{config.get('futures_suffix', '/USDT:USDT')}"
                    funding = ex.fetch_funding_rate(full_symbol)
                    funding_rate = funding.get('fundingRate')
                    funding_ts = funding.get('fundingTimestamp') or funding.get('nextFundingTime')
                    if funding_ts:
                        if funding_ts > 1e12:
                            next_funding_time = funding_ts / 1000
                        else:
                            next_funding_time = funding_ts

        except Exception as e:
            self._emit_event(f"{exchange} funding API error: {str(e)[:30]}", "warning")

        return funding_rate, next_funding_time

    def get_spot_price(self, exchange: str, symbol: str) -> Optional[PriceData]:
        """현물 가격 조회"""
        # Lighter 특별 처리
        if exchange == 'lighter':
            return self._get_lighter_price(symbol)

        if exchange not in self._spot_exchanges:
            return None

        config = self.EXCHANGE_CONFIG.get(exchange, {})
        is_krw = config.get('krw', False)
        full_symbol = f"{symbol}{config.get('spot_suffix', '/USDT')}"

        try:
            start_time = time.time()
            ex = self._spot_exchanges[exchange]
            ticker = ex.fetch_ticker(full_symbol)
            latency = (time.time() - start_time) * 1000

            # last > close > (bid+ask)/2 순서로 가격 확보
            price = ticker.get('last') or ticker.get('close')
            if not price:
                bid = ticker.get('bid')
                ask = ticker.get('ask')
                if bid and ask:
                    price = (bid + ask) / 2
                elif ask:
                    price = ask
                elif bid:
                    price = bid

            if price:
                price = float(price)
                krw_price = None

                # KRW 거래소는 USDT로 환산
                if is_krw:
                    krw_price = price  # 원화 가격 저장
                    krw_rate = self._get_krw_rate(exchange)
                    if krw_rate and krw_rate > 0:
                        price = price / krw_rate
                    else:
                        # 환율 조회 실패 시 None 반환
                        self._emit_event(f"{exchange} 환율 조회 실패로 {symbol} 스킵", "warning")
                        return None

                return PriceData(
                    exchange=exchange,
                    symbol=symbol,
                    price=price,
                    market_type=MarketType.SPOT,
                    timestamp=time.time(),
                    latency_ms=latency,
                    krw_price=krw_price
                )
        except Exception as e:
            self._status[exchange] = ExchangeStatus(
                exchange=exchange,
                connected=False,
                last_update=time.time(),
                error=str(e)
            )
        return None

    def get_futures_price(self, exchange: str, symbol: str) -> Optional[PriceData]:
        """선물 가격 조회"""
        # Hyperliquid 특별 처리
        if exchange == 'hyperliquid':
            return self._get_hyperliquid_price(symbol)

        # Lighter 특별 처리
        if exchange == 'lighter':
            return self._get_lighter_price(symbol)

        # Aster 특별 처리
        if exchange == 'aster':
            return self._get_aster_price(symbol)

        if exchange not in self._futures_exchanges:
            return None

        config = self.EXCHANGE_CONFIG.get(exchange, {})
        full_symbol = f"{symbol}{config.get('futures_suffix', '/USDT:USDT')}"

        try:
            start_time = time.time()
            ex = self._futures_exchanges[exchange]
            ticker = ex.fetch_ticker(full_symbol)
            latency = (time.time() - start_time) * 1000

            # last > close > (bid+ask)/2 순서로 가격 확보
            price = ticker.get('last') or ticker.get('close')
            if not price:
                bid = ticker.get('bid')
                ask = ticker.get('ask')
                if bid and ask:
                    price = (bid + ask) / 2
                elif ask:
                    price = ask
                elif bid:
                    price = bid

            funding_rate = None
            next_funding_time = None

            # 펀딩비 및 다음 펀딩 시간 조회 (거래소별 API 직접 호출)
            try:
                funding_rate, next_funding_time = self._fetch_funding_info(exchange, symbol)
            except Exception as funding_err:
                self._emit_event(f"{exchange} funding error: {str(funding_err)[:50]}", "warning")

            if price:
                return PriceData(
                    exchange=exchange,
                    symbol=symbol,
                    price=float(price),
                    market_type=MarketType.FUTURES,
                    timestamp=time.time(),
                    funding_rate=funding_rate,
                    latency_ms=latency,
                    next_funding_time=next_funding_time
                )
        except Exception as e:
            self._status[exchange] = ExchangeStatus(
                exchange=exchange,
                connected=False,
                last_update=time.time(),
                error=str(e)
            )
        return None

    def _get_hyperliquid_price(self, symbol: str) -> Optional[PriceData]:
        """Hyperliquid 가격 및 펀딩비 조회"""
        import requests

        try:
            start_time = time.time()

            # 가격 조회
            price_response = requests.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "allMids"},
                timeout=10
            )

            price = None
            if price_response.status_code == 200:
                price_data = price_response.json()
                price_str = price_data.get(symbol)
                if price_str:
                    price = float(price_str)

            if not price:
                return None

            # 펀딩비 조회
            funding_rate = None
            try:
                funding_response = requests.post(
                    "https://api.hyperliquid.xyz/info",
                    json={"type": "metaAndAssetCtxs"},
                    timeout=10
                )
                if funding_response.status_code == 200:
                    funding_data = funding_response.json()
                    # [0]: meta (universe 정보), [1]: assetCtxs (펀딩비 등)
                    if len(funding_data) >= 2:
                        universe = funding_data[0].get('universe', [])
                        asset_ctxs = funding_data[1]

                        # 심볼 인덱스 찾기
                        for idx, asset in enumerate(universe):
                            if asset.get('name') == symbol:
                                if idx < len(asset_ctxs):
                                    funding_str = asset_ctxs[idx].get('funding')
                                    if funding_str:
                                        funding_rate = float(funding_str)
                                break
            except:
                pass

            latency = (time.time() - start_time) * 1000

            self._status['hyperliquid'] = ExchangeStatus(
                exchange='hyperliquid',
                connected=True,
                last_update=time.time()
            )
            return PriceData(
                exchange='hyperliquid',
                symbol=symbol,
                price=price,
                market_type=MarketType.FUTURES,
                timestamp=time.time(),
                funding_rate=funding_rate,
                latency_ms=latency
            )
        except Exception as e:
            self._status['hyperliquid'] = ExchangeStatus(
                exchange='hyperliquid',
                connected=False,
                last_update=time.time(),
                error=str(e)
            )
        return None

    def _get_lighter_price(self, symbol: str) -> Optional[PriceData]:
        """Lighter 선물 가격 및 펀딩비 조회 (REST API)"""
        import requests

        # 심볼 -> 마켓 ID 변환
        market_id = self.LIGHTER_MARKETS.get(symbol.upper())
        if not market_id:
            return None

        try:
            start_time = time.time()

            # 가격 조회 (orderBookDetails API)
            price_resp = requests.get(
                "https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails",
                params={"order_book_id": market_id},
                timeout=10
            )

            if price_resp.status_code != 200:
                return None

            data = price_resp.json()
            details = data.get('order_book_details', [])
            if not details:
                return None

            # market_id로 해당 마켓 찾기
            price = None
            for detail in details:
                if detail.get('market_id') == market_id:
                    price = detail.get('last_trade_price')
                    break

            if not price:
                return None

            # 펀딩비 조회
            funding_rate = None
            try:
                funding_resp = requests.get(
                    "https://mainnet.zklighter.elliot.ai/api/v1/funding-rates",
                    timeout=10
                )
                if funding_resp.status_code == 200:
                    funding_data = funding_resp.json()
                    for item in funding_data.get('funding_rates', []):
                        if item.get('market_id') == market_id:
                            funding_rate = item.get('rate')
                            break
            except:
                pass

            latency = (time.time() - start_time) * 1000

            self._status['lighter'] = ExchangeStatus(
                exchange='lighter',
                connected=True,
                last_update=time.time()
            )
            return PriceData(
                exchange='lighter',
                symbol=symbol,
                price=float(price),
                market_type=MarketType.FUTURES,
                timestamp=time.time(),
                funding_rate=funding_rate,
                latency_ms=latency
            )

        except Exception as e:
            self._status['lighter'] = ExchangeStatus(
                exchange='lighter',
                connected=False,
                last_update=time.time(),
                error=str(e)
            )
        return None

    def _get_aster_price(self, symbol: str) -> Optional[PriceData]:
        """Aster DEX 선물 가격 및 펀딩비 조회 (Binance-compatible REST API)"""
        import requests

        try:
            start_time = time.time()
            aster_symbol = f"{symbol.upper()}USDT"

            # 가격 조회
            price_resp = requests.get(
                "https://fapi.asterdex.com/fapi/v1/ticker/price",
                params={"symbol": aster_symbol},
                timeout=10
            )

            if price_resp.status_code != 200:
                return None

            price_data = price_resp.json()
            price = price_data.get('price')

            if not price:
                return None

            # 펀딩비 조회
            funding_rate = None
            try:
                funding_resp = requests.get(
                    "https://fapi.asterdex.com/fapi/v1/premiumIndex",
                    params={"symbol": aster_symbol},
                    timeout=10
                )
                if funding_resp.status_code == 200:
                    funding_data = funding_resp.json()
                    funding_str = funding_data.get('lastFundingRate')
                    if funding_str:
                        funding_rate = float(funding_str)
            except:
                pass

            latency = (time.time() - start_time) * 1000

            self._status['aster'] = ExchangeStatus(
                exchange='aster',
                connected=True,
                last_update=time.time()
            )
            return PriceData(
                exchange='aster',
                symbol=symbol,
                price=float(price),
                market_type=MarketType.FUTURES,
                timestamp=time.time(),
                funding_rate=funding_rate,
                latency_ms=latency
            )

        except Exception as e:
            self._status['aster'] = ExchangeStatus(
                exchange='aster',
                connected=False,
                last_update=time.time(),
                error=str(e)
            )
        return None

    def fetch_all_prices(
        self,
        symbol: str,
        spot_exchanges: List[str],
        futures_exchanges: List[str]
    ) -> Dict[str, Dict[str, PriceData]]:
        """모든 거래소 가격 병렬 조회"""
        result = {'spot': {}, 'futures': {}}
        futures_list = []

        # 심볼별 거래소 제한 확인
        allowed_spot = self.get_allowed_exchanges(symbol, 'spot')
        allowed_futures = self.get_allowed_exchanges(symbol, 'futures')

        # 허용된 거래소만 필터링
        if allowed_spot is not None:
            spot_exchanges = [ex for ex in spot_exchanges if ex in allowed_spot]
        if allowed_futures is not None:
            futures_exchanges = [ex for ex in futures_exchanges if ex in allowed_futures]

        # Spot 가격 조회 태스크
        for ex in spot_exchanges:
            futures_list.append(
                self._executor.submit(self.get_spot_price, ex, symbol)
            )

        # Futures 가격 조회 태스크
        for ex in futures_exchanges:
            futures_list.append(
                self._executor.submit(self.get_futures_price, ex, symbol)
            )

        # 결과 수집
        for future in as_completed(futures_list, timeout=15):
            try:
                price_data = future.result()
                if price_data:
                    category = 'spot' if price_data.market_type == MarketType.SPOT else 'futures'
                    result[category][price_data.exchange] = price_data
            except Exception:
                pass

        with self._lock:
            self._prices = result

        return result

    def get_cached_prices(self) -> Dict[str, Dict[str, PriceData]]:
        """캐시된 가격 반환"""
        with self._lock:
            return self._prices.copy()

    def get_status(self) -> Dict[str, ExchangeStatus]:
        """거래소 상태 반환"""
        return self._status.copy()

    def shutdown(self):
        """서비스 종료"""
        self._running = False
        self._executor.shutdown(wait=False)


# 싱글톤 인스턴스
exchange_service = ExchangeService()
