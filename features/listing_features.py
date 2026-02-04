"""
Listing-related feature builders (placeholder).
"""

from typing import Dict, Any


def build_listing_features(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    # Placeholder: compute spikes and simple flags
    feats = {}
    if "deposit_krw" in snapshot:
        feats["deposit_spike_krw"] = snapshot.get("deposit_krw")
    if "premium_max_5m" in snapshot:
        feats["premium_max_5m"] = snapshot.get("premium_max_5m")
    return feats
