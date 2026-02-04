"""Exchange Network Database - 거래소별 지원 네트워크 조회.

각 거래소의 일반적인 지원 네트워크 목록.
실제 토큰별 지원 여부는 다를 수 있음.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, List

# 데이터 파일 경로
DATA_FILE = Path(__file__).parent.parent / "data" / "exchange_networks.json"

# 캐시
_network_data: Optional[dict] = None


def _load_data() -> dict:
    """데이터 로드 (캐시 사용)."""
    global _network_data
    if _network_data is None:
        if DATA_FILE.exists():
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                _network_data = json.load(f)
        else:
            _network_data = {"exchanges": {}, "networkInfo": {}}
    return _network_data


def get_exchange_networks(exchange: str) -> List[str]:
    """거래소의 지원 네트워크 목록 반환.
    
    Args:
        exchange: 거래소 이름 (binance, bybit, okx, gate, bitget, htx, mexc, kucoin, upbit, bithumb)
    
    Returns:
        네트워크 리스트 (예: ["ETH", "BSC", "SOL"])
    """
    data = _load_data()
    exchange_info = data.get("exchanges", {}).get(exchange.lower(), {})
    return exchange_info.get("networks", [])


def get_exchange_main_networks(exchange: str) -> List[str]:
    """거래소의 주요 네트워크 목록 반환."""
    data = _load_data()
    exchange_info = data.get("exchanges", {}).get(exchange.lower(), {})
    return exchange_info.get("mainNets", [])


def get_exchange_fast_networks(exchange: str) -> List[str]:
    """거래소의 빠른 네트워크 목록 반환."""
    data = _load_data()
    exchange_info = data.get("exchanges", {}).get(exchange.lower(), {})
    return exchange_info.get("fastNets", [])


def get_network_info(network: str) -> Optional[dict]:
    """네트워크 정보 반환.
    
    Returns:
        {"name": "Ethereum", "speed": "slow", "avgTime": "5-15min", "fee": "high"}
    """
    data = _load_data()
    return data.get("networkInfo", {}).get(network.upper())


def get_common_networks(exchanges: List[str]) -> List[str]:
    """여러 거래소가 공통으로 지원하는 네트워크 반환."""
    if not exchanges:
        return []
    
    sets = [set(get_exchange_networks(ex)) for ex in exchanges]
    if not sets:
        return []
    
    common = sets[0]
    for s in sets[1:]:
        common = common.intersection(s)
    
    return list(common)


def get_fastest_common_network(exchanges: List[str]) -> Optional[str]:
    """여러 거래소가 공통으로 지원하는 가장 빠른 네트워크 반환."""
    common = get_common_networks(exchanges)
    if not common:
        return None
    
    # 속도 우선순위
    priority = ["SOL", "TRON", "BSC", "ARB", "OP", "BASE", "MATIC", "AVAX", "ETH"]
    
    for net in priority:
        if net in common:
            return net
    
    return common[0] if common else None


def format_networks_str(exchange: str, max_count: int = 3) -> str:
    """거래소 네트워크를 문자열로 포맷팅."""
    networks = get_exchange_networks(exchange)
    if not networks:
        return "-"
    
    if len(networks) <= max_count:
        return ", ".join(networks)
    else:
        return ", ".join(networks[:max_count]) + f" +{len(networks) - max_count}"
