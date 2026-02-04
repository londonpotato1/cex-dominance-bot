"""
Symbol normalization helpers.
"""

from typing import Dict


SYMBOL_ALIASES: Dict[str, str] = {
    "WBTC": "BTC",
    "WETH": "ETH",
}


def normalize_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    s = symbol.strip().upper()
    return SYMBOL_ALIASES.get(s, s)
