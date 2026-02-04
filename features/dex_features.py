"""
DEX liquidity feature builders (placeholder).
"""

from typing import Dict, Any


def build_dex_features(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    feats = {}
    if "liquidity_usd" in snapshot:
        feats["liquidity_usd"] = snapshot.get("liquidity_usd")
    return feats
