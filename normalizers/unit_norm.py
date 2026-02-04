"""
Unit normalization helpers.
"""

def krw_to_usd(krw: float, fx: float) -> float:
    if fx == 0:
        return 0.0
    return krw / fx


def usd_to_krw(usd: float, fx: float) -> float:
    return usd * fx
