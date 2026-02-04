#!/usr/bin/env python3
"""
Normalize docs/guide_listing_cases.csv by adding structured columns
and attempting to auto-fill values from descriptors/context.
"""

import re
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot")
CSV_PATH = ROOT / "docs" / "guide_listing_cases.csv"


NEW_COLUMNS = [
    "exchange",
    "listing_type",
    "network_chain",
    "hot_wallet_usd",
    "max_premium_pct",
    "premium_min_pct",
    "premium_max_pct",
    "funding_rate_pct",
    "result_label",
    "profit_pct",
    "market_cap_usd",
    "deposit_krw",
    "hedge_type",
    "dex_liquidity_usd",
    "withdrawal_open",
    "airdrop_claim_rate",
    "notes_norm",
]


EXCHANGES = {
    "Upbit": ["업비트", "UPBIT", "업빗"],
    "Bithumb": ["빗썸", "BITHUMB", "빗"],
    "Coinone": ["코인원", "COINONE"],
    "Binance": ["바이낸스", "BINANCE", "바낸"],
    "Bybit": ["바이빗", "BYBIT"],
    "OKX": ["OKX", "오케이엑스"],
    "Bitget": ["BITGET", "비트겟"],
    "Gate.io": ["GATE", "GATE.IO", "게이트"],
    "KuCoin": ["KUCOIN", "쿠코인"],
    "MEXC": ["MEXC", "엠이엑스씨"],
}

CHAINS = {
    "ETH": ["ETH", "이더", "이더리움", "ERC20"],
    "BSC": ["BSC", "BNB", "바이낸스체인"],
    "SOL": ["SOL", "솔라나"],
    "ARB": ["ARB", "아비트럼"],
    "OP": ["OP", "옵티미즘"],
    "BASE": ["BASE", "베이스"],
    "AVAX": ["AVAX", "아발란체"],
    "POLY": ["POLYGON", "POLY", "폴리곤"],
    "SUI": ["SUI", "수이"],
    "APT": ["APT", "앱토스"],
}


def _is_empty(v) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return s == "" or s.lower() == "nan"


def _parse_float(s):
    try:
        return float(s)
    except Exception:
        return None


def _parse_market_cap_usd(text: str):
    # mcap=25M / 시총 25M / 25M 시총
    m = re.search(r"(?:mcap|시총)\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)([MB])", text, re.I)
    if m:
        val = float(m.group(1))
        return val * (1_000_000 if m.group(2).upper() == "M" else 1_000_000_000)
    m2 = re.search(r"시총\s*[=:]?\s*([0-9]+)\s*억", text)
    if m2:
        return float(m2.group(1)) * 100_000_000
    return None


def _parse_deposit_krw(text: str):
    m = re.search(r"(?:deposit|입금액)\s*[=:]?\s*(약?\s*[0-9]+(?:\.[0-9]+)?)\s*억", text, re.I)
    if m:
        return float(m.group(1).replace("약", "").strip()) * 100_000_000
    m2 = re.search(r"(?:deposit|입금액)\s*[=:]?\s*(약?\s*[0-9]+(?:\.[0-9]+)?)\s*만", text, re.I)
    if m2:
        return float(m2.group(1).replace("약", "").strip()) * 10_000
    # loose pattern: "입금액 40억", "입금액 약 40억+a", "입금액 40억 언더"
    m3 = re.search(r"입금액[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)\s*억", text)
    if m3:
        return float(m3.group(1)) * 100_000_000
    return None


def _parse_profit_pct(text: str):
    m = re.search(r"profit_pct=([+-]?[0-9]+(?:\.[0-9]+)?)%", text)
    if m:
        return float(m.group(1))
    m2 = re.search(r"\(([+-]?[0-9]+(?:\.[0-9]+)?)%\)", text)
    if m2:
        return float(m2.group(1))
    m3 = re.search(r"수익률\s*([+-]?[0-9]+(?:\.[0-9]+)?)%", text)
    if m3:
        return float(m3.group(1))
    return None


def _parse_premium_pct(text: str):
    m = re.search(r"(?:현선|갭|김프|premium)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*%", text, re.I)
    if m:
        return float(m.group(1))
    m2 = re.search(r"(?:현선|갭|김프)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:퍼|프로|퍼센트)", text)
    if m2:
        return float(m2.group(1))
    m3 = re.search(r"(?:현선|갭|김프)\s*([0-9]+(?:\.[0-9]+)?)\s*%대", text)
    if m3:
        return float(m3.group(1))
    return None


def _parse_premium_range(text: str):
    # keyword-first: "현선 0.4-0.5%" / "갭 5~7%"
    m = re.search(
        r"(?:현선|갭|김프|premium)[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)\s*%?\s*(?:~|-)\s*([0-9]+(?:\.[0-9]+)?)\s*%?",
        text,
        re.I,
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    # number-first: "0.4-0.5% 현선"
    m2 = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*%?\s*(?:~|-)\s*([0-9]+(?:\.[0-9]+)?)\s*%?.{0,10}(?:현선|갭|김프|premium)",
        text,
        re.I,
    )
    if m2:
        return float(m2.group(1)), float(m2.group(2))
    return None, None


def _parse_funding_rate_pct(text: str):
    # "펀비 -0.7%", "펀딩비 0.5%", "funding -0.25%"
    m = re.search(r"(?:펀비|펀딩|펀딩비|funding)[^0-9+-]{0,10}([+-]?[0-9]+(?:\.[0-9]+)?)\s*%?", text, re.I)
    if m:
        return float(m.group(1))
    m2 = re.search(r"([+-]?[0-9]+(?:\.[0-9]+)?)\s*%?.{0,10}(?:펀비|펀딩|펀딩비|funding)", text, re.I)
    if m2:
        return float(m2.group(1))
    return None


def _detect_exchange(text: str):
    up = text.upper()
    for ex, kws in EXCHANGES.items():
        if any(kw.upper() in up for kw in kws):
            return ex
    return ""


def _detect_chain(text: str):
    up = text.upper()
    for chain, kws in CHAINS.items():
        if any(kw.upper() in up for kw in kws):
            return chain
    return ""


def _detect_listing_type(text: str):
    if "TGE" in text.upper():
        return "TGE"
    if "OTC" in text.upper():
        return "OTC"
    if "런치패드" in text or "LAUNCHPAD" in text.upper():
        return "LAUNCHPAD"
    if "직상장" in text:
        return "직상장"
    if "원상" in text:
        return "원상"
    if "상장" in text:
        return "상장"
    return ""


def _detect_hedge_type(text: str):
    if "현선" in text:
        return "spot_futures"
    if "선선" in text:
        return "futures"
    if "롱" in text or "숏" in text:
        return "futures_only"
    if "헷징" in text:
        return "hedged"
    return ""


def _detect_result_label(text: str, profit_pct):
    for label in ["대흥따리", "흥따리", "보통", "망따리"]:
        if label in text:
            return label
    if profit_pct is None:
        return ""
    if profit_pct >= 30:
        return "대흥따리"
    if profit_pct >= 10:
        return "흥따리"
    if profit_pct > 0:
        return "보통"
    return "망따리"


def _detect_withdrawal_open(text: str):
    if "출금 열" in text or "출금 오픈" in text:
        return "true"
    if "출금 막" in text or "출금 중지" in text:
        return "false"
    return ""


def _parse_hot_wallet_usd(text: str):
    m = re.search(r"(hot[_-]?wallet|핫월렛)\s*[=:]?\s*\$?\s*([0-9]+(?:\.[0-9]+)?)([KMB])?", text, re.I)
    if m:
        val = float(m.group(2))
        suf = (m.group(3) or "").upper()
        if suf == "K":
            val *= 1_000
        elif suf == "M":
            val *= 1_000_000
        elif suf == "B":
            val *= 1_000_000_000
        return val
    # pattern like "hot_wallet_usd=123.4"
    m2 = re.search(r"hot[_-]?wallet[_-]?usd\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
    if m2:
        return float(m2.group(1))
    return None


def main():
    if not CSV_PATH.exists():
        print(f"Missing: {CSV_PATH}")
        return
    df = pd.read_csv(CSV_PATH)
    base_cols = list(df.columns)
    for col in NEW_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    # ensure notes_norm is string/object to avoid dtype warnings
    df["notes_norm"] = df["notes_norm"].astype(str)

    for idx, row in df.iterrows():
        text = " ".join(
            str(x)
            for x in [
                row.get("listing_date_raw", ""),
                row.get("descriptors_raw", ""),
                row.get("context_raw", ""),
                row.get("source_file", ""),
            ]
        )

        if _is_empty(row.get("exchange", "")):
            df.at[idx, "exchange"] = _detect_exchange(text)

        if _is_empty(row.get("listing_type", "")):
            df.at[idx, "listing_type"] = _detect_listing_type(text)

        if _is_empty(row.get("network_chain", "")):
            df.at[idx, "network_chain"] = _detect_chain(text)

        if _is_empty(row.get("hot_wallet_usd", "")):
            hw = _parse_hot_wallet_usd(text)
            if hw is not None:
                df.at[idx, "hot_wallet_usd"] = hw

        if _is_empty(row.get("max_premium_pct", "")):
            prem = _parse_premium_pct(text)
            if prem is not None:
                df.at[idx, "max_premium_pct"] = prem

        # premium range
        if _is_empty(row.get("premium_min_pct", "")) or _is_empty(row.get("premium_max_pct", "")):
            pmin, pmax = _parse_premium_range(text)
            if pmin is not None and _is_empty(row.get("premium_min_pct", "")):
                df.at[idx, "premium_min_pct"] = pmin
            if pmax is not None and _is_empty(row.get("premium_max_pct", "")):
                df.at[idx, "premium_max_pct"] = pmax
            # fill max_premium_pct if empty from range
            if _is_empty(row.get("max_premium_pct", "")) and pmax is not None:
                df.at[idx, "max_premium_pct"] = pmax

        if _is_empty(row.get("profit_pct", "")):
            pct = _parse_profit_pct(text)
            if pct is not None:
                df.at[idx, "profit_pct"] = pct
        else:
            pct = _parse_float(row.get("profit_pct"))

        if _is_empty(row.get("market_cap_usd", "")):
            mc = _parse_market_cap_usd(text)
            if mc is not None:
                df.at[idx, "market_cap_usd"] = mc

        if _is_empty(row.get("deposit_krw", "")):
            dep = _parse_deposit_krw(text)
            if dep is not None:
                df.at[idx, "deposit_krw"] = dep

        if _is_empty(row.get("hedge_type", "")):
            df.at[idx, "hedge_type"] = _detect_hedge_type(text)

        if _is_empty(row.get("withdrawal_open", "")):
            df.at[idx, "withdrawal_open"] = _detect_withdrawal_open(text)

        if _is_empty(row.get("result_label", "")):
            df.at[idx, "result_label"] = _detect_result_label(text, pct)

        if _is_empty(row.get("funding_rate_pct", "")):
            fr = _parse_funding_rate_pct(text)
            if fr is not None:
                df.at[idx, "funding_rate_pct"] = fr

        # notes_norm: compact summary when empty
        if _is_empty(row.get("notes_norm", "")):
            parts = []
            ex = df.at[idx, "exchange"]
            if ex:
                parts.append(f"ex={ex}")
            lt = df.at[idx, "listing_type"]
            if lt:
                parts.append(f"type={lt}")
            chain = df.at[idx, "network_chain"]
            if chain:
                parts.append(f"chain={chain}")
            prem = df.at[idx, "max_premium_pct"]
            if prem != "" and prem is not None:
                parts.append(f"premium={prem}%")
            pmin = df.at[idx, "premium_min_pct"]
            pmax = df.at[idx, "premium_max_pct"]
            if pmin != "" and pmax != "":
                parts.append(f"premium_range={pmin}-{pmax}%")
            fr = df.at[idx, "funding_rate_pct"]
            if fr != "" and fr is not None:
                parts.append(f"funding={fr}%")
            dep = df.at[idx, "deposit_krw"]
            if dep != "" and dep is not None:
                parts.append(f"deposit_krw={dep}")
            profit = df.at[idx, "profit_pct"]
            if profit != "" and profit is not None:
                parts.append(f"profit={profit}%")
            if parts:
                df.at[idx, "notes_norm"] = "; ".join(parts)

    # reorder columns: base + new (in order)
    df = df[base_cols + [c for c in NEW_COLUMNS if c not in base_cols]]
    df.to_csv(CSV_PATH, index=False, encoding="utf-8")
    print(f"Normalized: {CSV_PATH}")


if __name__ == "__main__":
    main()
