"""
Wallet flow feature builders (placeholder).
"""

from typing import Dict, Any


def build_wallet_features(flow: Dict[str, Any]) -> Dict[str, Any]:
    feats = {}
    if "usd_value" in flow:
        feats["flow_usd"] = flow.get("usd_value")
    return feats
