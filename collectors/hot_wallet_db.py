"""Hot Wallet Database - 거래소 핫월렛 주소 조회.

한국 거래소(업비트, 빗썸) hot wallet 주소 DB.
Arkham Intelligence & On-chain 분석 기반.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# 데이터 파일 경로
DATA_FILE = Path(__file__).parent.parent / "data" / "hot_wallets.json"

# 캐시
_wallet_data: Optional[dict] = None


def _load_data() -> dict:
    """데이터 로드 (캐시 사용)."""
    global _wallet_data
    if _wallet_data is None:
        if DATA_FILE.exists():
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                _wallet_data = json.load(f)
        else:
            _wallet_data = {"exchanges": {}, "summary": {}, "arkhamLinks": {}}
    return _wallet_data


def get_hot_wallets(exchange: str, chain: Optional[str] = None) -> list[str]:
    """특정 거래소의 hot wallet 주소 목록 반환.
    
    Args:
        exchange: 거래소 이름 (upbit, bithumb)
        chain: 체인 이름 (solana, ethereum, tron, base, arbitrum, optimism, flare)
               None이면 모든 체인의 주소 반환
    
    Returns:
        주소 리스트
    """
    data = _load_data()
    exchange_data = data.get("exchanges", {}).get(exchange.lower(), {})
    
    if chain:
        return exchange_data.get(chain.lower(), [])
    
    # 모든 체인 합치기
    all_addresses = []
    for addresses in exchange_data.values():
        all_addresses.extend(addresses)
    return all_addresses


def get_all_hot_wallets(chain: Optional[str] = None) -> dict[str, list[str]]:
    """모든 거래소의 hot wallet 반환.
    
    Args:
        chain: 체인 이름 (None이면 모든 체인)
    
    Returns:
        {거래소: [주소 리스트]} 딕셔너리
    """
    data = _load_data()
    result = {}
    
    for exchange, chains in data.get("exchanges", {}).items():
        if chain:
            addresses = chains.get(chain.lower(), [])
            if addresses:
                result[exchange] = addresses
        else:
            all_addresses = []
            for addresses in chains.values():
                all_addresses.extend(addresses)
            result[exchange] = all_addresses
    
    return result


def is_hot_wallet(address: str) -> Optional[str]:
    """주소가 hot wallet인지 확인.
    
    Args:
        address: 확인할 주소
    
    Returns:
        거래소 이름 (hot wallet이면), None (아니면)
    """
    data = _load_data()
    address_lower = address.lower()
    
    for exchange, chains in data.get("exchanges", {}).items():
        for chain_addresses in chains.values():
            for wallet in chain_addresses:
                if wallet.lower() == address_lower:
                    return exchange
    return None


def get_arkham_link(exchange: str) -> Optional[str]:
    """거래소의 Arkham Intelligence 링크 반환."""
    data = _load_data()
    return data.get("arkhamLinks", {}).get(exchange.lower())


def get_explorer_link(address: str, chain: str) -> str:
    """주소의 블록 익스플로러 링크 생성."""
    chain_lower = chain.lower()
    
    explorers = {
        "solana": f"https://solscan.io/account/{address}",
        "ethereum": f"https://etherscan.io/address/{address}",
        "base": f"https://basescan.org/address/{address}",
        "arbitrum": f"https://arbiscan.io/address/{address}",
        "optimism": f"https://optimistic.etherscan.io/address/{address}",
        "tron": f"https://tronscan.org/#/address/{address}",
        "flare": f"https://flarescan.com/address/{address}",
    }
    
    return explorers.get(chain_lower, f"https://blockscan.com/address/{address}")


def get_summary() -> dict:
    """전체 요약 정보 반환."""
    data = _load_data()
    return {
        "lastUpdated": data.get("lastUpdated"),
        "source": data.get("source"),
        "summary": data.get("summary", {}),
    }


# 편의 함수
def upbit_wallets(chain: Optional[str] = None) -> list[str]:
    """업비트 hot wallet 조회."""
    return get_hot_wallets("upbit", chain)


def bithumb_wallets(chain: Optional[str] = None) -> list[str]:
    """빗썸 hot wallet 조회."""
    return get_hot_wallets("bithumb", chain)
