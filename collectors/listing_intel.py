#!/usr/bin/env python3
"""상장 인텔리전스 수집기.

바이낸스 상장 공지 시 종합 분석 데이터 수집:
- MC / FDV / 공급량
- 거래소별 상장 현황 (현물/선물)
- 거래소별 네트워크/체인 지원
- 입출금 상태 (핫월렛)
- 현재 가격 (선물/DEX)

v1: 2026-02-02
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)

# HTTP 설정
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15)
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class ExchangeStatus:
    """거래소별 상장 상태."""
    exchange: str
    has_spot: bool = False
    has_futures: bool = False
    spot_pairs: List[str] = field(default_factory=list)
    futures_pairs: List[str] = field(default_factory=list)
    
    # 네트워크/체인 지원
    networks: List[str] = field(default_factory=list)
    
    # 입출금 상태
    deposit_enabled: bool = False
    withdraw_enabled: bool = False
    deposit_networks: List[str] = field(default_factory=list)
    withdraw_networks: List[str] = field(default_factory=list)


@dataclass
class ListingIntel:
    """상장 인텔리전스 데이터."""
    symbol: str
    name: str = ""
    
    # 토크노믹스
    market_cap_usd: Optional[float] = None
    fdv_usd: Optional[float] = None
    total_supply: Optional[float] = None
    circulating_supply: Optional[float] = None
    circulating_percent: Optional[float] = None
    
    # 가격
    current_price_usd: Optional[float] = None
    futures_price_usd: Optional[float] = None
    dex_price_usd: Optional[float] = None
    price_change_24h_pct: Optional[float] = None  # 24시간 등락률
    
    # 거래량
    volume_24h_usd: Optional[float] = None  # 24시간 거래량
    
    # 체인/네트워크
    platforms: List[str] = field(default_factory=list)
    
    # 거래소별 상태
    exchanges: Dict[str, ExchangeStatus] = field(default_factory=dict)
    
    # 메타
    fetched_at: datetime = field(default_factory=datetime.now)
    
    def get_summary(self) -> Dict[str, Any]:
        """요약 딕셔너리 반환."""
        spot_exchanges = [e for e, s in self.exchanges.items() if s.has_spot]
        futures_exchanges = [e for e, s in self.exchanges.items() if s.has_futures]
        
        return {
            "symbol": self.symbol,
            "name": self.name,
            "market_cap": self.market_cap_usd,
            "fdv": self.fdv_usd,
            "circulating_percent": self.circulating_percent,
            "platforms": self.platforms,
            "spot_exchanges": spot_exchanges,
            "futures_exchanges": futures_exchanges,
            "futures_price": self.futures_price_usd,
        }


class ListingIntelCollector:
    """상장 인텔리전스 수집기."""
    
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=_HTTP_TIMEOUT,
                headers=_HTTP_HEADERS,
            )
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def collect(self, symbol: str) -> ListingIntel:
        """심볼에 대한 종합 인텔리전스 수집."""
        intel = ListingIntel(symbol=symbol.upper())
        
        # 병렬로 데이터 수집
        await asyncio.gather(
            self._fetch_coingecko(intel),
            self._fetch_binance_status(intel),
            self._fetch_okx_status(intel),
            self._fetch_bybit_status(intel),
            self._fetch_gate_status(intel),
            return_exceptions=True,
        )
        
        # Circulating % 계산
        if intel.total_supply and intel.circulating_supply:
            intel.circulating_percent = (intel.circulating_supply / intel.total_supply) * 100
        
        return intel
    
    async def _fetch_coingecko(self, intel: ListingIntel) -> None:
        """CoinGecko에서 기본 정보 수집."""
        session = await self._get_session()
        symbol_lower = intel.symbol.lower()
        
        try:
            # 검색으로 coin_id 찾기 (여러 후보 중 가장 적합한 것 선택)
            async with session.get(
                "https://api.coingecko.com/api/v3/search",
                params={"query": intel.symbol},
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"[Intel] CoinGecko search failed: {resp.status}")
                    return
                data = await resp.json()
                coins = data.get("coins", [])
                
                coin_id = None
                # 1. 정확히 symbol 일치하는 것 우선
                for c in coins:
                    if c.get("symbol", "").lower() == symbol_lower:
                        coin_id = c.get("id")
                        intel.name = c.get("name", "")
                        break
                
                # 2. 못 찾으면 name에 symbol이 포함된 것
                if not coin_id:
                    for c in coins:
                        if symbol_lower in c.get("name", "").lower():
                            coin_id = c.get("id")
                            intel.name = c.get("name", "")
                            break
                
                # 3. 그래도 못 찾으면 첫 번째 결과
                if not coin_id and coins:
                    coin_id = coins[0].get("id")
                    intel.name = coins[0].get("name", "")
                
                if not coin_id:
                    logger.warning(f"[Intel] CoinGecko: {intel.symbol} not found")
                    return
            
            # 상세 정보 가져오기
            async with session.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
            ) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
                
                intel.name = data.get("name", "")
                
                # 마켓 데이터
                md = data.get("market_data", {})
                intel.market_cap_usd = md.get("market_cap", {}).get("usd")
                intel.fdv_usd = md.get("fully_diluted_valuation", {}).get("usd")
                intel.current_price_usd = md.get("current_price", {}).get("usd")
                intel.total_supply = md.get("total_supply")
                intel.circulating_supply = md.get("circulating_supply")
                
                # 24시간 거래량 & 등락률
                intel.volume_24h_usd = md.get("total_volume", {}).get("usd")
                intel.price_change_24h_pct = md.get("price_change_percentage_24h")
                
                # 플랫폼
                platforms = data.get("platforms", {})
                intel.platforms = [p for p in platforms.keys() if p]
                
        except Exception as e:
            logger.warning("[Intel] CoinGecko 에러: %s", e)
    
    async def _fetch_binance_status(self, intel: ListingIntel) -> None:
        """바이낸스 상장 상태 수집."""
        session = await self._get_session()
        status = ExchangeStatus(exchange="binance")
        
        try:
            # 현물 체크 (정확한 매칭: ZAMAUSDT, ZAMABTC 등)
            async with session.get("https://api.binance.com/api/v3/exchangeInfo") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for s in data.get("symbols", []):
                        sym = s.get("symbol", "")
                        base = s.get("baseAsset", "")
                        # baseAsset가 정확히 일치하거나, 심볼이 SYMBOL+USDT/BTC 형태
                        if base.upper() == intel.symbol or sym.upper().startswith(intel.symbol + "USDT") or sym.upper().startswith(intel.symbol + "BTC"):
                            status.has_spot = True
                            status.spot_pairs.append(sym)
            
            # 선물 체크 (정확한 매칭)
            async with session.get("https://fapi.binance.com/fapi/v1/exchangeInfo") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for s in data.get("symbols", []):
                        sym = s.get("symbol", "")
                        if sym.upper().startswith(intel.symbol + "USDT") or sym.upper() == intel.symbol + "PERP":
                            status.has_futures = True
                            status.futures_pairs.append(sym)
            
            # 선물 가격
            if status.futures_pairs:
                pair = status.futures_pairs[0]
                async with session.get(
                    f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={pair}"
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        intel.futures_price_usd = float(data.get("price", 0))
            
            # 입출금 상태 (capital API)
            async with session.get(
                "https://api.binance.com/sapi/v1/capital/config/getall",
            ) as resp:
                # 이 API는 인증이 필요할 수 있음 - 공개 API로 대체 필요
                pass
            
            # 네트워크 정보 (coins info - 공개)
            try:
                async with session.get(
                    f"https://www.binance.com/bapi/asset/v1/public/asset-service/product/currency?currency={intel.symbol}"
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        networks = data.get("data", {}).get("networkList", [])
                        for n in networks:
                            net_name = n.get("network", "")
                            status.networks.append(net_name)
                            if n.get("depositEnable"):
                                status.deposit_enabled = True
                                status.deposit_networks.append(net_name)
                            if n.get("withdrawEnable"):
                                status.withdraw_enabled = True
                                status.withdraw_networks.append(net_name)
            except:
                pass
            
        except Exception as e:
            logger.warning("[Intel] Binance 에러: %s", e)
        
        intel.exchanges["binance"] = status
    
    async def _fetch_okx_status(self, intel: ListingIntel) -> None:
        """OKX 상장 상태 수집."""
        session = await self._get_session()
        status = ExchangeStatus(exchange="okx")
        
        try:
            # 현물 체크 (정확한 매칭 + 거래 가능 상태 확인)
            async with session.get(
                f"https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId={intel.symbol}-USDT"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for s in data.get("data", []):
                        inst_id = s.get("instId", "")
                        state = s.get("state", "")
                        base_ccy = s.get("baseCcy", "")
                        # 정확한 매칭 + state가 live여야 실제 거래 가능
                        if base_ccy.upper() == intel.symbol and state == "live":
                            status.has_spot = True
                            status.spot_pairs.append(inst_id)
            
            # 선물 체크 (정확한 매칭 + 거래 가능 상태)
            async with session.get(
                f"https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId={intel.symbol}-USDT-SWAP"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for s in data.get("data", []):
                        inst_id = s.get("instId", "")
                        state = s.get("state", "")
                        if state == "live":
                            status.has_futures = True
                            status.futures_pairs.append(inst_id)
            
            # 네트워크/입출금 상태
            async with session.get(
                f"https://www.okx.com/api/v5/asset/currencies?ccy={intel.symbol}"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for c in data.get("data", []):
                        chain = c.get("chain", "")
                        status.networks.append(chain)
                        if c.get("canDep"):
                            status.deposit_enabled = True
                            status.deposit_networks.append(chain)
                        if c.get("canWd"):
                            status.withdraw_enabled = True
                            status.withdraw_networks.append(chain)
                            
        except Exception as e:
            logger.warning("[Intel] OKX 에러: %s", e)
        
        intel.exchanges["okx"] = status
    
    async def _fetch_bybit_status(self, intel: ListingIntel) -> None:
        """Bybit 상장 상태 수집."""
        session = await self._get_session()
        status = ExchangeStatus(exchange="bybit")
        
        try:
            # 현물 체크
            async with session.get(
                f"https://api.bybit.com/v5/market/instruments-info?category=spot&symbol={intel.symbol}USDT"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("result", {}).get("list", [])
                    if items:
                        status.has_spot = True
                        status.spot_pairs = [i["symbol"] for i in items]
            
            # 선물 체크
            async with session.get(
                f"https://api.bybit.com/v5/market/instruments-info?category=linear&symbol={intel.symbol}USDT"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("result", {}).get("list", [])
                    if items:
                        status.has_futures = True
                        status.futures_pairs = [i["symbol"] for i in items]
                        
        except Exception as e:
            logger.warning("[Intel] Bybit 에러: %s", e)
        
        intel.exchanges["bybit"] = status
    
    async def _fetch_gate_status(self, intel: ListingIntel) -> None:
        """Gate.io 상장 상태 수집."""
        session = await self._get_session()
        status = ExchangeStatus(exchange="gate")
        
        try:
            # 현물 체크 (trade_status가 tradable이어야 양방향 거래 가능)
            async with session.get(
                f"https://api.gateio.ws/api/v4/spot/currency_pairs/{intel.symbol}_USDT"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    trade_status = data.get("trade_status", "")
                    # tradable = 양방향 거래 가능, sellable = 매도만 가능
                    if trade_status == "tradable":
                        status.has_spot = True
                        status.spot_pairs.append(f"{intel.symbol}_USDT")
            
            # 선물 체크
            async with session.get(
                f"https://api.gateio.ws/api/v4/futures/usdt/contracts/{intel.symbol}_USDT"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # in_delisting이 아니어야 거래 가능
                    if not data.get("in_delisting", False):
                        status.has_futures = True
                        status.futures_pairs.append(f"{intel.symbol}_USDT")
                    
        except Exception as e:
            logger.warning("[Intel] Gate 에러: %s", e)
        
        intel.exchanges["gate"] = status


async def collect_listing_intel(symbol: str) -> ListingIntel:
    """상장 인텔리전스 수집 (유틸리티 함수)."""
    collector = ListingIntelCollector()
    try:
        return await collector.collect(symbol)
    finally:
        await collector.close()


# CLI 테스트
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    async def main():
        symbol = sys.argv[1] if len(sys.argv) > 1 else "ZAMA"
        
        print(f"=== {symbol} Listing Intelligence ===\n")
        
        collector = ListingIntelCollector()
        try:
            intel = await collector.collect(symbol)
            
            print(f"Name: {intel.name}")
            print(f"Platforms: {', '.join(intel.platforms) if intel.platforms else 'N/A'}")
            print()
            
            print("📊 Tokenomics:")
            print(f"  Market Cap: ${intel.market_cap_usd:,.0f}" if intel.market_cap_usd else "  Market Cap: N/A")
            print(f"  FDV: ${intel.fdv_usd:,.0f}" if intel.fdv_usd else "  FDV: N/A")
            print(f"  Total Supply: {intel.total_supply:,.0f}" if intel.total_supply else "  Total Supply: N/A")
            print(f"  Circulating: {intel.circulating_supply:,.0f} ({intel.circulating_percent:.1f}%)" if intel.circulating_supply else "  Circulating: N/A")
            print()
            
            print("💰 Prices:")
            print(f"  Futures: ${intel.futures_price_usd:.4f}" if intel.futures_price_usd else "  Futures: N/A")
            print()
            
            print("🏦 Exchange Status:")
            for ex_name, ex_status in intel.exchanges.items():
                spot = "✅" if ex_status.has_spot else "❌"
                futures = "✅" if ex_status.has_futures else "❌"
                deposit = "✅" if ex_status.deposit_enabled else "❌"
                withdraw = "✅" if ex_status.withdraw_enabled else "❌"
                
                print(f"  {ex_name.upper()}:")
                print(f"    Spot: {spot} {ex_status.spot_pairs}")
                print(f"    Futures: {futures} {ex_status.futures_pairs}")
                print(f"    Networks: {ex_status.networks if ex_status.networks else 'N/A'}")
                print(f"    Deposit: {deposit} {ex_status.deposit_networks}")
                print(f"    Withdraw: {withdraw} {ex_status.withdraw_networks}")
                
        finally:
            await collector.close()
    
    asyncio.run(main())
