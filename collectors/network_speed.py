"""네트워크 속도 정보 모듈.

체인별 입금 속도, 컨펌 수, 리스크 정보 제공.
GO/NO-GO 판단에 활용.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class NetworkInfo:
    """네트워크 정보."""
    chain: str
    speed: str  # "very_slow", "slow", "medium", "fast", "very_fast"
    estimated_time: str  # "~7분", "~30초" 등
    confirmations: Optional[int]  # 필요 컨펌 수
    risk_note: Optional[str]  # 리스크 메모
    go_signal: str  # "GO", "CAUTION", "NO_GO"
    
    @property
    def emoji(self) -> str:
        """속도 이모지."""
        return {
            "very_slow": "🐢",
            "slow": "🚶",
            "medium": "🚗",
            "fast": "⚡",
            "very_fast": "🚀",
        }.get(self.speed, "❓")
    
    @property
    def speed_korean(self) -> str:
        """속도 한글."""
        return {
            "very_slow": "매우 느림",
            "slow": "느림",
            "medium": "보통",
            "fast": "빠름",
            "very_fast": "매우 빠름",
        }.get(self.speed, "알 수 없음")


# 체인별 속도 데이터베이스
NETWORK_DATABASE: dict[str, NetworkInfo] = {
    # === EVM 메인넷 ===
    "ethereum": NetworkInfo(
        chain="Ethereum",
        speed="medium",
        estimated_time="~7분",
        confirmations=36,
        risk_note=None,
        go_signal="GO",
    ),
    "eth": NetworkInfo(
        chain="Ethereum",
        speed="medium",
        estimated_time="~7분",
        confirmations=36,
        risk_note=None,
        go_signal="GO",
    ),
    "erc20": NetworkInfo(
        chain="Ethereum (ERC-20)",
        speed="medium",
        estimated_time="~7분",
        confirmations=36,
        risk_note=None,
        go_signal="GO",
    ),
    
    # === L2 ===
    "arbitrum": NetworkInfo(
        chain="Arbitrum",
        speed="medium",
        estimated_time="~5분",
        confirmations=None,
        risk_note="L2 - 가스비 저렴",
        go_signal="CAUTION",
    ),
    "arb": NetworkInfo(
        chain="Arbitrum",
        speed="medium",
        estimated_time="~5분",
        confirmations=None,
        risk_note="L2 - 가스비 저렴",
        go_signal="CAUTION",
    ),
    "optimism": NetworkInfo(
        chain="Optimism",
        speed="slow",
        estimated_time="~10분",
        confirmations=None,
        risk_note="L2 - 출금 지연 가능",
        go_signal="GO",
    ),
    "op": NetworkInfo(
        chain="Optimism",
        speed="slow",
        estimated_time="~10분",
        confirmations=None,
        risk_note="L2 - 출금 지연 가능",
        go_signal="GO",
    ),
    "base": NetworkInfo(
        chain="Base",
        speed="slow",
        estimated_time="~15분",
        confirmations=None,
        risk_note="L2 - Coinbase 체인",
        go_signal="GO",
    ),
    "zksync": NetworkInfo(
        chain="zkSync Era",
        speed="slow",
        estimated_time="~10분",
        confirmations=None,
        risk_note="ZK Rollup",
        go_signal="GO",
    ),
    "polygon": NetworkInfo(
        chain="Polygon",
        speed="fast",
        estimated_time="~2분",
        confirmations=128,
        risk_note="가스비 저렴, 빠름",
        go_signal="CAUTION",
    ),
    "matic": NetworkInfo(
        chain="Polygon",
        speed="fast",
        estimated_time="~2분",
        confirmations=128,
        risk_note="가스비 저렴, 빠름",
        go_signal="CAUTION",
    ),
    
    # === 빠른 체인 (NO-GO 또는 CAUTION) ===
    "solana": NetworkInfo(
        chain="Solana",
        speed="very_fast",
        estimated_time="~30초",
        confirmations=32,
        risk_note="⚠️ 후따리 매우 쉬움",
        go_signal="NO_GO",
    ),
    "sol": NetworkInfo(
        chain="Solana",
        speed="very_fast",
        estimated_time="~30초",
        confirmations=32,
        risk_note="⚠️ 후따리 매우 쉬움",
        go_signal="NO_GO",
    ),
    "avalanche": NetworkInfo(
        chain="Avalanche",
        speed="fast",
        estimated_time="~1분",
        confirmations=1,
        risk_note="빠른 finality",
        go_signal="CAUTION",
    ),
    "avax": NetworkInfo(
        chain="Avalanche",
        speed="fast",
        estimated_time="~1분",
        confirmations=1,
        risk_note="빠른 finality",
        go_signal="CAUTION",
    ),
    "bsc": NetworkInfo(
        chain="BNB Smart Chain",
        speed="fast",
        estimated_time="~1분",
        confirmations=15,
        risk_note="빠름, 브릿지 필요할 수 있음",
        go_signal="CAUTION",
    ),
    "bnb": NetworkInfo(
        chain="BNB Smart Chain",
        speed="fast",
        estimated_time="~1분",
        confirmations=15,
        risk_note="빠름, 브릿지 필요할 수 있음",
        go_signal="CAUTION",
    ),
    "tron": NetworkInfo(
        chain="Tron",
        speed="fast",
        estimated_time="~1분",
        confirmations=19,
        risk_note="빠름",
        go_signal="CAUTION",
    ),
    "trx": NetworkInfo(
        chain="Tron",
        speed="fast",
        estimated_time="~1분",
        confirmations=19,
        risk_note="빠름",
        go_signal="CAUTION",
    ),
    "sui": NetworkInfo(
        chain="Sui",
        speed="very_fast",
        estimated_time="~10초",
        confirmations=None,
        risk_note="⚠️ 매우 빠름 - 후따리 주의",
        go_signal="NO_GO",
    ),
    "aptos": NetworkInfo(
        chain="Aptos",
        speed="very_fast",
        estimated_time="~5초",
        confirmations=None,
        risk_note="⚠️ 매우 빠름 - 후따리 주의",
        go_signal="NO_GO",
    ),
    "apt": NetworkInfo(
        chain="Aptos",
        speed="very_fast",
        estimated_time="~5초",
        confirmations=None,
        risk_note="⚠️ 매우 빠름 - 후따리 주의",
        go_signal="NO_GO",
    ),
    "ton": NetworkInfo(
        chain="TON",
        speed="fast",
        estimated_time="~30초",
        confirmations=None,
        risk_note="Telegram 체인",
        go_signal="CAUTION",
    ),
    
    # === 느린 체인 (GO) ===
    "bitcoin": NetworkInfo(
        chain="Bitcoin",
        speed="very_slow",
        estimated_time="~60분",
        confirmations=6,
        risk_note="매우 느림 - 선따리 유리",
        go_signal="GO",
    ),
    "btc": NetworkInfo(
        chain="Bitcoin",
        speed="very_slow",
        estimated_time="~60분",
        confirmations=6,
        risk_note="매우 느림 - 선따리 유리",
        go_signal="GO",
    ),
    
    # === 자체 메인넷 (보통 느림 - GO) ===
    "cosmos": NetworkInfo(
        chain="Cosmos",
        speed="fast",
        estimated_time="~1분",
        confirmations=None,
        risk_note="IBC 브릿지 필요할 수 있음",
        go_signal="CAUTION",
    ),
    "atom": NetworkInfo(
        chain="Cosmos",
        speed="fast",
        estimated_time="~1분",
        confirmations=None,
        risk_note="IBC 브릿지 필요할 수 있음",
        go_signal="CAUTION",
    ),
    "near": NetworkInfo(
        chain="NEAR",
        speed="fast",
        estimated_time="~2초",
        confirmations=None,
        risk_note="빠름",
        go_signal="CAUTION",
    ),
    "ckb": NetworkInfo(
        chain="Nervos CKB",
        speed="very_slow",
        estimated_time="~30분+",
        confirmations=None,
        risk_note="POW - 체인 혼잡 시 매우 느림",
        go_signal="GO",
    ),
    "mina": NetworkInfo(
        chain="Mina",
        speed="very_slow",
        estimated_time="~30분+",
        confirmations=None,
        risk_note="ZK 체인 - 느림",
        go_signal="GO",
    ),
    "kaspa": NetworkInfo(
        chain="Kaspa",
        speed="slow",
        estimated_time="~10분",
        confirmations=None,
        risk_note="POW - DAG 기반",
        go_signal="GO",
    ),
    "kas": NetworkInfo(
        chain="Kaspa",
        speed="slow",
        estimated_time="~10분",
        confirmations=None,
        risk_note="POW - DAG 기반",
        go_signal="GO",
    ),
    "sei": NetworkInfo(
        chain="Sei",
        speed="very_fast",
        estimated_time="~0.5초",
        confirmations=None,
        risk_note="⚠️ 초고속 - 후따리 매우 쉬움",
        go_signal="NO_GO",
    ),
    
    # === 기본값 ===
    "unknown": NetworkInfo(
        chain="Unknown",
        speed="medium",
        estimated_time="확인 필요",
        confirmations=None,
        risk_note="네트워크 정보 없음",
        go_signal="CAUTION",
    ),
}

# 심볼 → 네트워크 매핑 (자주 사용되는 토큰)
SYMBOL_NETWORK_MAP: dict[str, str] = {
    # 주요 코인
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "AVAX": "avalanche",
    "MATIC": "polygon",
    "BNB": "bsc",
    "TRX": "tron",
    "ATOM": "cosmos",
    "NEAR": "near",
    "APT": "aptos",
    "SUI": "sui",
    "TON": "ton",
    "SEI": "sei",
    "CKB": "ckb",
    "MINA": "mina",
    "KAS": "kaspa",
    
    # L2 토큰
    "ARB": "arbitrum",
    "OP": "optimism",
    
    # 기타 (네트워크 자동 추론 힌트)
}


def get_network_info(network: str) -> NetworkInfo:
    """네트워크 정보 조회.
    
    Args:
        network: 네트워크 이름 (ethereum, solana 등)
    
    Returns:
        NetworkInfo 객체
    """
    key = network.lower().strip()
    
    # 직접 매칭
    if key in NETWORK_DATABASE:
        return NETWORK_DATABASE[key]
    
    # 부분 매칭 시도
    for db_key, info in NETWORK_DATABASE.items():
        if db_key in key or key in db_key:
            return info
    
    # 기본값
    logger.warning(f"Unknown network: {network}, using default")
    return NETWORK_DATABASE["unknown"]


def get_network_by_symbol(symbol: str) -> Optional[NetworkInfo]:
    """심볼로 네트워크 정보 추론.
    
    Args:
        symbol: 토큰 심볼 (BTC, ETH 등)
    
    Returns:
        NetworkInfo 또는 None (추론 불가 시)
    """
    sym = symbol.upper().strip()
    
    if sym in SYMBOL_NETWORK_MAP:
        network = SYMBOL_NETWORK_MAP[sym]
        return get_network_info(network)
    
    return None


def get_network_go_signal(network: str) -> tuple[str, str]:
    """네트워크 기반 GO/NO-GO 신호.
    
    Returns:
        (signal, reason) 튜플
        signal: "GO", "CAUTION", "NO_GO"
    """
    info = get_network_info(network)
    
    reasons = {
        "GO": f"{info.emoji} {info.chain} ({info.estimated_time}) - 느림, 선따리 유리",
        "CAUTION": f"{info.emoji} {info.chain} ({info.estimated_time}) - 주의 필요",
        "NO_GO": f"{info.emoji} {info.chain} ({info.estimated_time}) - 후따리 쉬움",
    }
    
    return info.go_signal, reasons.get(info.go_signal, "")


def get_all_networks() -> list[str]:
    """사용 가능한 모든 네트워크 목록."""
    return list(set(info.chain for info in NETWORK_DATABASE.values()))
