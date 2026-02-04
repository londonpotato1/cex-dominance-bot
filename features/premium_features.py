"""
Premium (spot-futures gap) feature builders (placeholder).
"""

from typing import Dict, Any


def build_premium_features(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    feats = {}
    if "premium_pct" in snapshot:
        feats["premium_pct"] = snapshot.get("premium_pct")
    return feats
