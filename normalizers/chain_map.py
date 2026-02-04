"""
Chain normalization helpers.
"""

from typing import Dict


CHAIN_ALIASES: Dict[str, str] = {
    "ETHEREUM": "ETH",
    "ERC20": "ETH",
    "BINANCE SMART CHAIN": "BSC",
    "BNB": "BSC",
    "SOLANA": "SOL",
    "ARBITRUM": "ARB",
    "OPTIMISM": "OP",
    "BASE": "BASE",
}


def normalize_chain(chain: str) -> str:
    if not chain:
        return ""
    s = chain.strip().upper()
    return CHAIN_ALIASES.get(s, s)
