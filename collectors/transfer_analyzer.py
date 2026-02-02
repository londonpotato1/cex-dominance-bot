#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
전송 분석 통합 모듈

기능:
- 브릿지 필요 여부 판단
- 최적 전송 경로 추천
- 예상 도착 시간 계산
- 거래소별 출금 가능 네트워크 조회
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

import aiohttp

logger = logging.getLogger(__name__)


# ============================================================
# 국내 거래소 지원 체인 (하드코딩 - 자주 바뀌지 않음)
# ============================================================

# 업비트 지원 체인 (대표적인 것들)
UPBIT_SUPPORTED_CHAINS = {
    "ethereum", "eth", "erc20",
    "tron", "trc20", "trx",
    "solana", "sol",
    "polygon", "matic",
    "avalanche", "avax", "avaxc",
    "arbitrum", "arb",
    "optimism", "op",
    "bsc", "bnb", "bep20",
    "base",
    "klaytn", "klay",
    "cosmos", "atom",
    "ripple", "xrp",
    "bitcoin", "btc",
}

# 빗썸 지원 체인
BITHUMB_SUPPORTED_CHAINS = {
    "ethereum", "eth", "erc20",
    "tron", "trc20", "trx",
    "solana", "sol",
    "polygon", "matic",
    "avalanche", "avax",
    "arbitrum", "arb",
    "bsc", "bnb", "bep20",
    "klaytn", "klay",
    "cosmos", "atom",
    "ripple", "xrp",
    "bitcoin", "btc",
}

# 국내 거래소 지원 체인 통합
KOREAN_EXCHANGE_CHAINS = UPBIT_SUPPORTED_CHAINS | BITHUMB_SUPPORTED_CHAINS


# ============================================================
# 브릿지 정보
# ============================================================

@dataclass
class BridgeInfo:
    """브릿지 정보"""
    name: str
    url: str
    from_chains: List[str]
    to_chains: List[str]
    estimated_time: str
    fee_estimate: str


BRIDGES = [
    BridgeInfo(
        name="Stargate",
        url="https://stargate.finance",
        from_chains=["ethereum", "bsc", "polygon", "arbitrum", "optimism", "avalanche", "base"],
        to_chains=["ethereum", "bsc", "polygon", "arbitrum", "optimism", "avalanche", "base"],
        estimated_time="~2분",
        fee_estimate="~$1-5"
    ),
    BridgeInfo(
        name="Wormhole",
        url="https://wormhole.com",
        from_chains=["ethereum", "solana", "bsc", "polygon", "avalanche", "arbitrum"],
        to_chains=["ethereum", "solana", "bsc", "polygon", "avalanche", "arbitrum"],
        estimated_time="~5분",
        fee_estimate="~$2-10"
    ),
    BridgeInfo(
        name="Orbiter",
        url="https://orbiter.finance",
        from_chains=["ethereum", "arbitrum", "optimism", "base", "zksync", "polygon"],
        to_chains=["ethereum", "arbitrum", "optimism", "base", "zksync", "polygon"],
        estimated_time="~1분",
        fee_estimate="~$0.5-2"
    ),
    BridgeInfo(
        name="Synapse",
        url="https://synapseprotocol.com",
        from_chains=["ethereum", "bsc", "polygon", "arbitrum", "optimism", "avalanche"],
        to_chains=["ethereum", "bsc", "polygon", "arbitrum", "optimism", "avalanche"],
        estimated_time="~5분",
        fee_estimate="~$2-5"
    ),
]


# ============================================================
# 전송 분석 결과
# ============================================================

@dataclass
class TransferRoute:
    """전송 경로"""
    from_exchange: str
    to_exchange: str
    network: str
    estimated_time: str
    confirmations: Optional[int]
    withdraw_fee: Optional[float]
    is_direct: bool  # 브릿지 없이 직접 전송 가능
    bridge_info: Optional[BridgeInfo] = None


@dataclass
class TransferAnalysis:
    """전송 분석 결과"""
    symbol: str
    
    # 브릿지 필요 여부
    bridge_required: bool
    bridge_reason: Optional[str] = None
    recommended_bridge: Optional[BridgeInfo] = None
    
    # 최적 전송 경로
    best_route: Optional[TransferRoute] = None
    all_routes: List[TransferRoute] = field(default_factory=list)
    
    # 거래소별 출금 가능 네트워크
    exchange_networks: Dict[str, List[str]] = field(default_factory=dict)
    
    # 국내 거래소 입금 가능 네트워크
    korean_deposit_networks: List[str] = field(default_factory=list)
    
    # 예상 시간
    fastest_time: Optional[str] = None
    
    # 경고
    warnings: List[str] = field(default_factory=list)


class TransferAnalyzer:
    """전송 분석기"""
    
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
    
    async def analyze(self, symbol: str, source_exchanges: List[str] = None) -> TransferAnalysis:
        """전송 분석 실행
        
        Args:
            symbol: 심볼 (예: BTC, ETH)
            source_exchanges: 출금 가능한 해외 거래소 목록
            
        Returns:
            TransferAnalysis
        """
        if source_exchanges is None:
            source_exchanges = ["binance", "bybit", "okx", "gate"]
        
        symbol = symbol.upper()
        result = TransferAnalysis(symbol=symbol)
        
        # 1. 거래소별 출금 가능 네트워크 조회
        result.exchange_networks = await self._get_exchange_networks(symbol, source_exchanges)
        
        # 2. 국내 거래소 입금 가능 네트워크 조회
        result.korean_deposit_networks = await self._get_korean_deposit_networks(symbol)
        
        # 3. 브릿지 필요 여부 판단
        self._check_bridge_required(result)
        
        # 4. 최적 전송 경로 계산
        self._calculate_best_route(result)
        
        return result
    
    async def _get_exchange_networks(self, symbol: str, exchanges: List[str]) -> Dict[str, List[str]]:
        """거래소별 출금 가능 네트워크 조회"""
        networks = {}
        
        tasks = []
        for ex in exchanges:
            tasks.append(self._get_single_exchange_networks(symbol, ex))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for ex, result in zip(exchanges, results):
            if isinstance(result, Exception):
                logger.warning(f"{ex} 네트워크 조회 실패: {result}")
                networks[ex] = []
            else:
                networks[ex] = result
        
        return networks
    
    async def _get_single_exchange_networks(self, symbol: str, exchange: str) -> List[str]:
        """단일 거래소 출금 가능 네트워크 조회"""
        try:
            if exchange == "binance":
                return await self._get_binance_networks(symbol)
            elif exchange == "bybit":
                return await self._get_bybit_networks(symbol)
            elif exchange == "okx":
                return await self._get_okx_networks(symbol)
            elif exchange == "gate":
                return await self._get_gate_networks(symbol)
            else:
                return []
        except Exception as e:
            logger.error(f"{exchange} 네트워크 조회 에러: {e}")
            return []
    
    async def _get_binance_networks(self, symbol: str) -> List[str]:
        """Binance 출금 가능 네트워크"""
        try:
            url = "https://api.binance.com/sapi/v1/capital/config/getall"
            # 인증 없이는 전체 목록 조회 불가 - 공개 API 대안 사용
            # exchangeInfo에서 간접적으로 추론
            
            # 일반적인 네트워크 반환 (실제로는 API 키 필요)
            common_networks = ["eth", "bsc", "trc20", "sol", "arb", "matic", "avaxc", "op"]
            return common_networks
        except Exception as e:
            logger.error(f"Binance 네트워크 조회 에러: {e}")
            return []
    
    async def _get_bybit_networks(self, symbol: str) -> List[str]:
        """Bybit 출금 가능 네트워크"""
        try:
            if not self._session:
                return []
            
            url = f"https://api.bybit.com/v5/asset/coin/query-info?coin={symbol}"
            async with self._session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("retCode") == 0:
                        rows = data.get("result", {}).get("rows", [])
                        networks = []
                        for coin in rows:
                            if coin.get("coin") == symbol:
                                for chain in coin.get("chains", []):
                                    chain_type = chain.get("chainType", "").lower()
                                    if chain.get("chainWithdraw") == "1":
                                        networks.append(chain_type)
                        return networks
            return []
        except Exception as e:
            logger.error(f"Bybit 네트워크 조회 에러: {e}")
            return []
    
    async def _get_okx_networks(self, symbol: str) -> List[str]:
        """OKX 출금 가능 네트워크"""
        try:
            if not self._session:
                return []
            
            url = f"https://www.okx.com/api/v5/asset/currencies?ccy={symbol}"
            async with self._session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == "0":
                        networks = []
                        for item in data.get("data", []):
                            if item.get("canWd"):
                                chain = item.get("chain", "").lower()
                                # OKX 체인명 정규화 (예: ETH-Ethereum -> eth)
                                chain_parts = chain.split("-")
                                networks.append(chain_parts[0] if chain_parts else chain)
                        return networks
            return []
        except Exception as e:
            logger.error(f"OKX 네트워크 조회 에러: {e}")
            return []
    
    async def _get_gate_networks(self, symbol: str) -> List[str]:
        """Gate.io 출금 가능 네트워크"""
        try:
            if not self._session:
                return []
            
            url = f"https://api.gateio.ws/api/v4/spot/currencies/{symbol.lower()}"
            async with self._session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    chains = data.get("chain_of", "") or data.get("chain", "")
                    if chains:
                        return [c.strip().lower() for c in chains.split(",")]
            return []
        except Exception as e:
            logger.error(f"Gate 네트워크 조회 에러: {e}")
            return []
    
    async def _get_korean_deposit_networks(self, symbol: str) -> List[str]:
        """국내 거래소 입금 가능 네트워크 조회"""
        try:
            from collectors.deposit_status import check_all_exchanges
            
            # 업비트/빗썸 입금 가능 네트워크 조회
            result = await check_all_exchanges(symbol)
            
            networks = set()
            if result:
                for exchange_info in result:
                    if hasattr(exchange_info, 'networks'):
                        for net in exchange_info.networks:
                            if net.deposit_enabled:
                                networks.add(net.network.lower())
            
            return list(networks)
            
        except Exception as e:
            logger.warning(f"국내 거래소 네트워크 조회 실패: {e}")
            # 실패 시 일반적인 네트워크 반환
            return ["eth", "sol", "trc20"]
    
    def _check_bridge_required(self, result: TransferAnalysis):
        """브릿지 필요 여부 판단"""
        
        # 해외 거래소에서 출금 가능한 모든 네트워크
        all_foreign_networks = set()
        for ex, networks in result.exchange_networks.items():
            all_foreign_networks.update([n.lower() for n in networks])
        
        # 국내 거래소 입금 가능 네트워크
        korean_networks = set([n.lower() for n in result.korean_deposit_networks])
        
        # 겹치는 네트워크 찾기
        common_networks = all_foreign_networks & korean_networks
        
        if not common_networks:
            # 겹치는 네트워크 없음 → 브릿지 필요
            result.bridge_required = True
            result.bridge_reason = f"해외({', '.join(all_foreign_networks)}) ↔ 국내({', '.join(korean_networks)}) 공통 체인 없음"
            
            # 추천 브릿지 찾기
            for bridge in BRIDGES:
                from_match = all_foreign_networks & set(bridge.from_chains)
                to_match = korean_networks & set(bridge.to_chains)
                if from_match and to_match:
                    result.recommended_bridge = bridge
                    break
            
            result.warnings.append("⚠️ 브릿지 필요 - 추가 시간/비용 발생")
        else:
            result.bridge_required = False
            logger.info(f"공통 네트워크: {common_networks}")
    
    def _calculate_best_route(self, result: TransferAnalysis):
        """최적 전송 경로 계산"""
        from collectors.network_speed import get_network_info
        
        routes = []
        
        for exchange, networks in result.exchange_networks.items():
            for network in networks:
                network_lower = network.lower()
                
                # 국내 입금 가능한지 확인
                is_direct = network_lower in [n.lower() for n in result.korean_deposit_networks]
                
                # 네트워크 속도 정보
                net_info = get_network_info(network_lower)
                estimated_time = net_info.estimated_time if net_info else "확인 필요"
                confirmations = net_info.confirmations if net_info else None
                
                route = TransferRoute(
                    from_exchange=exchange,
                    to_exchange="upbit/bithumb",
                    network=network,
                    estimated_time=estimated_time,
                    confirmations=confirmations,
                    withdraw_fee=None,  # API로 조회 필요
                    is_direct=is_direct,
                    bridge_info=result.recommended_bridge if not is_direct else None
                )
                routes.append(route)
        
        # 직접 전송 가능한 경로 우선, 시간 짧은 순
        time_order = {"~30초": 1, "~1분": 2, "~2분": 3, "~5분": 4, "~7분": 5, "~10분": 6, "~15분": 7, "~30분": 8}
        
        def route_score(r: TransferRoute) -> tuple:
            direct_score = 0 if r.is_direct else 1
            time_score = time_order.get(r.estimated_time, 10)
            return (direct_score, time_score)
        
        routes.sort(key=route_score)
        
        result.all_routes = routes
        result.best_route = routes[0] if routes else None
        
        if result.best_route:
            result.fastest_time = result.best_route.estimated_time


async def analyze_transfer(symbol: str) -> TransferAnalysis:
    """전송 분석 (단일 호출용)"""
    async with TransferAnalyzer() as analyzer:
        return await analyzer.analyze(symbol)


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    async def test():
        print("=== 전송 분석 테스트 ===\n")
        
        result = await analyze_transfer("ETH")
        
        print(f"심볼: {result.symbol}")
        print(f"브릿지 필요: {result.bridge_required}")
        if result.bridge_reason:
            print(f"사유: {result.bridge_reason}")
        if result.recommended_bridge:
            print(f"추천 브릿지: {result.recommended_bridge.name}")
        
        print(f"\n거래소별 네트워크:")
        for ex, nets in result.exchange_networks.items():
            print(f"  {ex}: {nets}")
        
        print(f"\n국내 입금 가능: {result.korean_deposit_networks}")
        
        if result.best_route:
            print(f"\n최적 경로:")
            print(f"  {result.best_route.from_exchange} → {result.best_route.to_exchange}")
            print(f"  네트워크: {result.best_route.network}")
            print(f"  예상 시간: {result.best_route.estimated_time}")
            print(f"  직접 전송: {result.best_route.is_direct}")
    
    asyncio.run(test())
