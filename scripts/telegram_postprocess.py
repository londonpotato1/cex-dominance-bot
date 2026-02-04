#!/usr/bin/env python3
"""
Post-process telegram exports:
1) Filter guide notes related to listing/arbitrage
2) Enrich bokgi cases and map to labeling schema
3) Merge enriched bokgi rows into listing_data.csv
"""

import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot")
EXPORT_DIR = ROOT / "data" / "telegram_exports"
LABEL_DIR = ROOT / "data" / "labeling"

GUIDE_NOTES_CSV = EXPORT_DIR / "guide_notes.csv"
BOKGI_CASES_CSV = EXPORT_DIR / "bokgi_cases.csv"

GUIDE_LISTING_CSV = EXPORT_DIR / "guide_notes_listing.csv"
GUIDE_LISTING_JSON = EXPORT_DIR / "guide_notes_listing.json"

ENRICHED_V2 = LABEL_DIR / "telegram_bokgi_enriched_v2.csv"
MERGED_V2 = LABEL_DIR / "listing_data_bokgi_merged_v2.csv"
LISTING_DATA = LABEL_DIR / "listing_data.csv"
LISTING_BACKUP = LABEL_DIR / "listing_data_before_bokgi_merge.csv"

GUIDE_SUMMARY_CSV = EXPORT_DIR / "guide_notes_listing_summary.csv"
BOKGI_MANUAL_CSV = LABEL_DIR / "bokgi_manual_enrichment.csv"
BOKGI_MANUAL_PREFILL = LABEL_DIR / "bokgi_manual_enrichment_prefill.csv"


def read_csv(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict], fieldnames: List[str]):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, rows: List[Dict]):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def parse_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_market_cap_usd(mcap: Optional[str]) -> Optional[float]:
    if not mcap:
        return None
    s = mcap.strip().upper().replace(",", "")
    try:
        if s.endswith("M"):
            return float(s[:-1]) * 1_000_000
        if s.endswith("B"):
            return float(s[:-1]) * 1_000_000_000
        if s.endswith("억"):
            return float(s[:-1]) * 100_000_000
        return float(s)
    except ValueError:
        return None


def parse_krw_amount(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    s = text.replace("약", "").replace(",", "").strip()
    try:
        if "억" in s:
            num = float(s.replace("억", ""))
            return num * 100_000_000
        if "만" in s:
            num = float(s.replace("만", ""))
            return num * 10_000
        return float(s)
    except ValueError:
        return None


def detect_premium(text: str) -> Optional[float]:
    # Look for "현선 0.5%" / "갭 5%" / "김프 3%"
    m = re.search(r"(현선|갭|김프)\s*([0-9]+(?:\.[0-9]+)?)\s*%", text)
    if m:
        return parse_float(m.group(2))
    return None


def detect_listing_type(text: str) -> str:
    if "TGE" in text.upper():
        return "TGE"
    if "상장" in text:
        return "상장"
    return ""


def detect_exchange(text: str, exchange: str) -> str:
    if exchange:
        return exchange
    for ex in ["업비트", "빗썸", "코인원", "업빗썸"]:
        if ex in text:
            return ex
    return ""


def result_label_from_profit(pct: Optional[float]) -> str:
    if pct is None:
        return ""
    if pct >= 30:
        return "대흥따리"
    if pct >= 10:
        return "흥따리"
    if pct > 0:
        return "보통"
    return "망따리"


def step1_filter_guide_notes():
    rows = read_csv(GUIDE_NOTES_CSV)
    if not rows:
        return 0
    keywords = [
        "상장", "따리", "현선", "선선", "김프", "펀비", "입금", "출금",
        "TGE", "거래소", "업비트", "빗썸", "바이낸스", "바낸", "코인원",
        "아비트리지", "갭", "프리미엄",
    ]
    filtered = []
    for r in rows:
        text = (r.get("raw_text") or "") + " " + (r.get("topic") or "")
        if any(k in text for k in keywords):
            filtered.append(r)

    if filtered:
        write_csv(GUIDE_LISTING_CSV, filtered, list(filtered[0].keys()))
        write_json(GUIDE_LISTING_JSON, filtered)
    return len(filtered)


def step2_enrich_bokgi() -> List[Dict]:
    rows = read_csv(BOKGI_CASES_CSV)
    if not rows:
        return []

    fieldnames = [
        "symbol", "exchange", "date", "listing_type",
        "market_cap_usd", "top_exchange", "top_exchange_tier",
        "deposit_krw", "volume_5m_krw", "volume_1m_krw",
        "turnover_ratio", "max_premium_pct", "premium_at_5m_pct",
        "supply_label", "hedge_type", "dex_liquidity_usd",
        "hot_wallet_usd", "network_chain", "network_speed_min",
        "withdrawal_open", "airdrop_claim_rate", "prev_listing_result",
        "market_condition", "result_label", "result_notes"
    ]

    enriched = []
    ex_map = {"업비트": "Upbit", "빗썸": "Bithumb", "코인원": "Coinone", "업빗썸": "Upbit+Bithumb"}

    for r in rows:
        raw_text = r.get("raw_text", "")
        exchange_raw = detect_exchange(raw_text, r.get("exchange", ""))
        exchange = ex_map.get(exchange_raw, exchange_raw)

        profit_pct = parse_float(r.get("profit_pct"))
        max_premium = parse_float(r.get("max_premium_pct")) or detect_premium(raw_text)

        notes_parts = []
        for key in ["best_play", "pika_play", "good_points", "bad_points", "lessons"]:
            val = r.get(key, "")
            if isinstance(val, str) and val.strip():
                notes_parts.append(f"{key}: {val}")
        if not notes_parts:
            notes_parts.append(raw_text[:400])

        enriched.append({
            "symbol": r.get("symbol", ""),
            "exchange": exchange,
            "date": r.get("case_date", ""),
            "listing_type": r.get("listing_type", "") or detect_listing_type(raw_text),
            "market_cap_usd": parse_market_cap_usd(r.get("market_cap")),
            "top_exchange": "",
            "top_exchange_tier": "",
            "deposit_krw": parse_krw_amount(r.get("deposit_amount")),
            "volume_5m_krw": "",
            "volume_1m_krw": "",
            "turnover_ratio": "",
            "max_premium_pct": max_premium if max_premium is not None else "",
            "premium_at_5m_pct": "",
            "supply_label": "",
            "hedge_type": r.get("hedge_type", ""),
            "dex_liquidity_usd": "",
            "hot_wallet_usd": "",
            "network_chain": r.get("network_chain", ""),
            "network_speed_min": "",
            "withdrawal_open": r.get("withdrawal_open", ""),
            "airdrop_claim_rate": "",
            "prev_listing_result": "",
            "market_condition": "",
            "result_label": result_label_from_profit(profit_pct),
            "result_notes": " || ".join(notes_parts),
        })

    write_csv(ENRICHED_V2, enriched, fieldnames)
    return enriched


def step3_merge_listing(enriched_rows: List[Dict]) -> int:
    listing_rows = read_csv(LISTING_DATA)
    if not listing_rows:
        return 0

    fieldnames = list(listing_rows[0].keys())
    existing_keys = set()
    for r in listing_rows:
        existing_keys.add((r.get("symbol", ""), r.get("exchange", ""), r.get("date", "")))

    added = 0
    for r in enriched_rows:
        key = (r.get("symbol", ""), r.get("exchange", ""), r.get("date", ""))
        if key in existing_keys:
            continue
        new_row = {f: r.get(f, "") for f in fieldnames}
        listing_rows.append(new_row)
        existing_keys.add(key)
        added += 1

    write_csv(MERGED_V2, listing_rows, fieldnames)
    return added


def step4_replace_listing_data():
    # Backup current listing_data.csv
    if LISTING_DATA.exists():
        if not LISTING_BACKUP.exists():
            LISTING_BACKUP.write_text(LISTING_DATA.read_text(encoding="utf-8"), encoding="utf-8")
        # Replace with merged v2
        if MERGED_V2.exists():
            LISTING_DATA.write_text(MERGED_V2.read_text(encoding="utf-8"), encoding="utf-8")


def _extract_symbols(text: str) -> List[str]:
    symbols = set()
    # $AAA pattern
    for m in re.findall(r"\$([A-Z]{2,10})\b", text.upper()):
        symbols.add(m)
    # plain uppercase tokens (2-6)
    for m in re.findall(r"(?<![a-zA-Z])([A-Z]{2,6})(?=[^a-zA-Z]|$)", text.upper()):
        symbols.add(m)
    excluded = {
        "THE","AND","FOR","BUT","NOT","YOU","ALL","CAN","HER","WAS","ONE","OUR","OUT","DAY",
        "GET","HAS","HIM","HIS","HOW","MAN","NEW","NOW","OLD","SEE","WAY","WHO","BOY","DID",
        "ITS","LET","PUT","SAY","SHE","TOO","USE","FAQ","UTC","EXP","CEX","DEX","PRE","OTC",
        "TVL","APY","APR","SBF","FTX","WEN","EVM"
    }
    return [s for s in symbols if s not in excluded]


def _detect_exchanges(text: str) -> List[str]:
    ex_map = {
        "Upbit": ["업비트", "UPBIT", "업빗"],
        "Bithumb": ["빗썸", "BITHUMB", "빗"],
        "Binance": ["바이낸스", "BINANCE", "바낸"],
        "Bybit": ["바이빗", "BYBIT"],
        "OKX": ["OKX", "오케이엑스"],
        "Bitget": ["BITGET", "비트겟"],
        "Gate.io": ["GATE", "GATE.IO", "게이트"],
        "KuCoin": ["KUCOIN", "쿠코인"],
        "MEXC": ["MEXC", "엠이엑스씨"],
        "Hyperliquid": ["HYPERLIQUID", "하이퍼리퀴드", "하리"],
    }
    found = []
    up = text.upper()
    for ex, kws in ex_map.items():
        if any(kw.upper() in up for kw in kws):
            found.append(ex)
    return found


def _detect_action_type(text: str) -> str:
    if re.search(r"(상장|listing)", text, re.I):
        return "listing"
    if re.search(r"(따리|원상|현선|선선|갭|김프|아비트리지)", text):
        return "arbitrage"
    if re.search(r"(펀비|펀딩|funding)", text, re.I):
        return "funding"
    if re.search(r"(입금|출금|지연|오픈)", text):
        return "deposit_withdrawal"
    if re.search(r"(브릿지|bridge|체인)", text, re.I):
        return "bridge"
    if re.search(r"(에어드랍|airdrop|TGE)", text, re.I):
        return "airdrop"
    return "general"


def step5_guide_summary():
    rows = read_csv(GUIDE_LISTING_CSV)
    if not rows:
        return 0
    summary = []
    for r in rows:
        raw = r.get("raw_text", "")
        topic = r.get("topic", "")
        key_points = r.get("key_points", "")
        text = " ".join([topic, key_points, raw])
        symbols = _extract_symbols(text)
        exchanges = _detect_exchanges(text)
        action = _detect_action_type(text)
        # shorten key points
        kp_short = ""
        if key_points:
            kp_short = key_points[:200]
        summary.append({
            "date_ymd": r.get("date_ymd", ""),
            "time_hm": r.get("time_hm", ""),
            "channel": r.get("channel", ""),
            "topic": topic[:120],
            "action_type": action,
            "exchanges": ",".join(exchanges),
            "symbols": ",".join(symbols[:6]),
            "key_points_short": kp_short,
            "source_file": r.get("source_file", ""),
            "message_id": r.get("message_id", ""),
        })

    write_csv(GUIDE_SUMMARY_CSV, summary, list(summary[0].keys()))
    return len(summary)


def step6_manual_enrichment_template():
    rows = read_csv(BOKGI_CASES_CSV)
    if not rows:
        return 0
    template = []
    for r in rows:
        template.append({
            "case_date": r.get("case_date", ""),
            "exchange": r.get("exchange", ""),
            "symbol": r.get("symbol", ""),
            "profit_pct": r.get("profit_pct", ""),
            "market_cap": r.get("market_cap", ""),
            "deposit_amount": r.get("deposit_amount", ""),
            "max_premium_pct": r.get("max_premium_pct", ""),
            "hedge_type": r.get("hedge_type", ""),
            "network_chain": r.get("network_chain", ""),
            "withdrawal_open": r.get("withdrawal_open", ""),
            "listing_type": r.get("listing_type", ""),
            "entry_method": "",
            "exit_method": "",
            "funding_rate": "",
            "premium_range": "",
            "dex_used": "",
            "chain_used": "",
            "deposit_krw_exact": "",
            "notes_manual": "",
            "status": "TODO",
        })
    write_csv(BOKGI_MANUAL_CSV, template, list(template[0].keys()))
    return len(template)


def step7_prefill_manual_enrichment():
    rows = read_csv(BOKGI_MANUAL_CSV)
    if not rows:
        return 0

    # map from telegram bokgi cases for notes
    bokgi_path = EXPORT_DIR / "bokgi_cases.csv"
    bokgi_rows = read_csv(bokgi_path)
    bokgi_map = {}
    for r in bokgi_rows:
        key = (r.get("case_date", ""), r.get("symbol", ""), r.get("exchange", ""))
        bokgi_map[key] = r

    for r in rows:
        key = (r.get("case_date", ""), r.get("symbol", ""), r.get("exchange", ""))
        src = bokgi_map.get(key)
        if not src:
            continue
        text = src.get("raw_text", "")
        # entry/exit heuristics
        if not r.get("entry_method"):
            if "DEX" in text or "덱스" in text:
                r["entry_method"] = "DEX"
            elif "현선" in text:
                r["entry_method"] = "현선"
            elif "쌩매수" in text:
                r["entry_method"] = "쌩매수"
        if not r.get("exit_method"):
            if "매도" in text:
                r["exit_method"] = "매도"
            if "업비트" in text or "빗썸" in text:
                r["exit_method"] = (r.get("exit_method", "") + "/CEX").strip("/")
        if not r.get("funding_rate") and src.get("hedge_type"):
            # placeholder if hedge_type suggests funding involvement
            r["funding_rate"] = r.get("funding_rate", "")
        if not r.get("premium_range") and src.get("max_premium_pct"):
            r["premium_range"] = f"0-{src.get('max_premium_pct')}%"
        if not r.get("dex_used") and ("DEX" in text or "덱스" in text):
            r["dex_used"] = "unknown"
        if not r.get("chain_used") and src.get("network_chain"):
            r["chain_used"] = src.get("network_chain")
        if not r.get("deposit_krw_exact") and src.get("deposit_amount"):
            r["deposit_krw_exact"] = src.get("deposit_amount")
        if not r.get("notes_manual"):
            r["notes_manual"] = text[:400]

        if r.get("entry_method") or r.get("exit_method") or r.get("premium_range"):
            r["status"] = "PARTIAL"

    write_csv(BOKGI_MANUAL_PREFILL, rows, list(rows[0].keys()))
    return len(rows)


def main():
    cnt_filtered = step1_filter_guide_notes()
    enriched_rows = step2_enrich_bokgi()
    added = step3_merge_listing(enriched_rows)
    step4_replace_listing_data()
    summary_cnt = step5_guide_summary()
    manual_cnt = step6_manual_enrichment_template()
    prefill_cnt = step7_prefill_manual_enrichment()

    print("=== Telegram Postprocess ===")
    print(f"Guide notes filtered: {cnt_filtered}")
    print(f"Enriched bokgi rows: {len(enriched_rows)}")
    print(f"Listing merged added: {added}")
    print(f"Guide summary rows: {summary_cnt}")
    print(f"Manual enrichment rows: {manual_cnt}")
    print(f"Manual prefill rows: {prefill_cnt}")
    print(f"Guide listing CSV: {GUIDE_LISTING_CSV}")
    print(f"Guide summary CSV: {GUIDE_SUMMARY_CSV}")
    print(f"Enriched v2 CSV: {ENRICHED_V2}")
    print(f"Merged listing CSV: {MERGED_V2}")
    print(f"Listing data replaced: {LISTING_DATA}")
    print(f"Listing backup: {LISTING_BACKUP}")
    print(f"Manual enrichment CSV: {BOKGI_MANUAL_CSV}")
    print(f"Manual prefill CSV: {BOKGI_MANUAL_PREFILL}")


if __name__ == "__main__":
    main()
