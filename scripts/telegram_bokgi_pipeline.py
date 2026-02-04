#!/usr/bin/env python3
"""
Telegram HTML export -> raw messages + bokgi cases + merge into guide_listing_cases.csv

Steps:
1) Parse Telegram HTML exports into raw messages (JSONL/CSV)
2) Extract bokgi cases (복기) into JSON/CSV
3) Merge bokgi cases into docs/guide_listing_cases.csv
"""

import csv
import html as html_lib
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---- Input paths ----
EXPORT_DIRS = [
    r"C:\Users\user\Downloads\Telegram Desktop\ChatExport_2026-02-02 (3)",
    r"C:\Users\user\Downloads\Telegram Desktop\ChatExport_2026-02-02 (1)",
    r"C:\Users\user\Downloads\Telegram Desktop\ChatExport_2026-02-02",
]

PROJECT_ROOT = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot")
OUT_DIR = PROJECT_ROOT / "data" / "telegram_exports"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GUIDE_CSV = PROJECT_ROOT / "docs" / "guide_listing_cases.csv"


# ---- Models ----
@dataclass
class RawMessage:
    source_file: str
    channel: str
    message_id: Optional[int]
    ts_title: str
    date_ymd: str
    time_hm: str
    text: str


@dataclass
class BokgiCase:
    case_date: str  # YYYY-MM-DD or raw
    exchange: str
    symbol: str
    profit_pct: Optional[float]
    market_cap: Optional[str]
    deposit_amount: Optional[str]
    best_play: List[str]
    pika_play: List[str]
    good_points: List[str]
    bad_points: List[str]
    lessons: List[str]
    tags: List[str]
    raw_text: str
    source_file: str
    message_id: Optional[int]
    ts_title: str
    max_premium_pct: Optional[float]
    hedge_type: Optional[str]
    network_chain: Optional[str]
    withdrawal_open: Optional[bool]
    listing_type: Optional[str]


@dataclass
class GuideNote:
    date_ymd: str
    time_hm: str
    channel: str
    topic: str
    key_points: List[str]
    raw_text: str
    source_file: str
    message_id: Optional[int]


# ---- Helpers ----
def _strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<.*?>", "", s, flags=re.S)
    return html_lib.unescape(s).strip()


def _safe_parse_date(date_str: str) -> str:
    # Telegram bokgi uses "yy.mm.dd" (e.g., 25.12.03) or "dd.mm.yyyy"
    m = re.match(r"^(\d{2})\.(\d{1,2})\.(\d{1,2})$", date_str)
    if m:
        yy = int(m.group(1))
        mm = int(m.group(2))
        dd = int(m.group(3))
        # Interpret as year-month-day
        return f"{2000 + yy:04d}-{mm:02d}-{dd:02d}"
    # Try formats: "25.01.2025" or "25.1.2025"
    for fmt in ("%d.%m.%Y",):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return date_str


def _detect_channel(html_text: str) -> str:
    # Telegram export header: <div class="text bold">채널명</div>
    m = re.search(r'<div class="text bold">\s*(.*?)\s*</div>', html_text, re.S)
    if not m:
        return ""
    return _strip_tags(m.group(1))


def parse_html_messages(html_path: Path) -> List[RawMessage]:
    text = html_path.read_text(encoding="utf-8", errors="replace")
    channel = _detect_channel(text)

    # Split by message divs
    blocks = re.split(r'<div class="message ', text)
    messages: List[RawMessage] = []
    for b in blocks[1:]:
        # Only default message blocks
        mtype = re.match(r'([^"]+)', b)
        mtype = mtype.group(1) if mtype else ""
        if "default" not in mtype:
            continue

        # message id
        msg_id = None
        mid = re.search(r'id="message(\d+)"', b)
        if mid:
            try:
                msg_id = int(mid.group(1))
            except ValueError:
                msg_id = None

        # timestamp title
        ts_title = ""
        date_ymd = ""
        time_hm = ""
        mt = re.search(r'<div class="pull_right date details" title="([^"]+)">', b)
        if mt:
            ts_title = mt.group(1)
            # "25.01.2025 13:54:33 UTC+09:00"
            mdt = re.search(r'(\d{2}\.\d{1,2}\.\d{4})\s+(\d{2}:\d{2})', ts_title)
            if mdt:
                date_ymd = _safe_parse_date(mdt.group(1))
                time_hm = mdt.group(2)

        # message text
        mt2 = re.search(r'<div class="text">\s*(.*?)\s*</div>', b, re.S)
        if not mt2:
            continue
        body = _strip_tags(mt2.group(1))
        if not body:
            continue

        messages.append(
            RawMessage(
                source_file=str(html_path),
                channel=channel,
                message_id=msg_id,
                ts_title=ts_title,
                date_ymd=date_ymd,
                time_hm=time_hm,
                text=body,
            )
        )
    return messages


def extract_section(pattern: str, text: str) -> List[str]:
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    section = m.group(1) if m.lastindex else m.group(0)
    items = re.findall(r"-\s*(.+?)(?=\n-|\n\*|\n$|$)", section)
    return [i.strip() for i in items if i.strip()]


def extract_bokgi_cases(messages: List[RawMessage]) -> List[BokgiCase]:
    cases: List[BokgiCase] = []
    for msg in messages:
        text = msg.text
        if "복기" not in text:
            continue

        # date in text: "25.12.03 따리 복기"
        date_raw = ""
        mdate = re.search(r"(\d{2}\.\d{1,2}\.\d{1,2})\s*(?:따리\s*)?복기", text)
        if mdate:
            date_raw = _safe_parse_date(mdate.group(1))
        elif msg.date_ymd:
            date_raw = msg.date_ymd
        else:
            date_raw = ""

        # exchange + symbol + profit
        exchange = ""
        symbol = ""
        profit_pct = None

        trade_pattern = r"#?(업비트|빗썸|코인원|업빗썸)\s+([A-Z0-9]{2,10})\s+따리\s*\(([+-]?\d+\.?\d*)%\)"
        tm = re.search(trade_pattern, text)
        if tm:
            exchange = tm.group(1)
            symbol = tm.group(2)
            profit_pct = float(tm.group(3))
        else:
            # fallback symbol + profit
            tm2 = re.search(r"#([A-Z0-9]{2,10})\s+따리", text)
            if tm2:
                symbol = tm2.group(1)
            pm = re.search(r"\(([+-]?\d+\.?\d*)%\)", text)
            if pm:
                try:
                    profit_pct = float(pm.group(1))
                except ValueError:
                    profit_pct = None
            # exchange guess
            for ex in ["업비트", "빗썸", "코인원", "업빗썸"]:
                if ex in text:
                    exchange = ex
                    break

        if not symbol:
            continue

        # market cap / deposit amount
        mcap = None
        mcap_match = re.search(r"시총\s*[:：]?\s*(\d+[MB]?|\d+억)", text, re.IGNORECASE)
        if mcap_match:
            mcap = mcap_match.group(1)

        deposit = None
        dep_match = re.search(r"입금액\s*[:：]?\s*(약?\s*\d+[억만]?)", text)
        if dep_match:
            deposit = dep_match.group(1)

        # max premium (현선/갭 근처 %)
        max_premium_pct = None
        prem_match = re.search(r"(현선|갭|김프)\s*([0-9]+(?:\.[0-9]+)?)\s*%", text)
        if prem_match:
            try:
                max_premium_pct = float(prem_match.group(2))
            except ValueError:
                max_premium_pct = None

        # hedge type
        hedge_type = None
        if "선선" in text or "선물" in text and "현물" in text:
            hedge_type = "futures"
        elif "현선" in text:
            hedge_type = "spot_futures"
        elif "롱" in text or "숏" in text:
            hedge_type = "futures_only"

        # network chain detection
        network_chain = None
        chain_map = {
            "ETH": ["ETH", "이더", "이더리움"],
            "BSC": ["BSC", "BNB", "바이낸스체인"],
            "SOL": ["SOL", "솔라나"],
            "ARB": ["ARB", "아비트럼"],
            "OP": ["OP", "옵티미즘"],
            "BASE": ["BASE", "베이스"],
            "MANTA": ["MANTA"],
            "AVAIL": ["AVAIL"],
            "ZK": ["ZK", "ZKSYNC", "ZKSYNC"],
        }
        tupper = text.upper()
        for chain, kws in chain_map.items():
            if any(kw.upper() in tupper for kw in kws):
                network_chain = chain
                break

        # withdrawal open flag
        withdrawal_open = None
        if "출금 열" in text or "출금 오픈" in text:
            withdrawal_open = True
        elif "출금 막" in text or "출금 중지" in text:
            withdrawal_open = False

        # listing type
        listing_type = None
        if "TGE" in text.upper():
            listing_type = "TGE"
        elif "상장" in text:
            listing_type = "상장"

        best_play = extract_section(r"\*베스트\s*플레이\*?\s*\n?(.*?)(?=\*Pika|\*잘한|\*못한|\*추가|$)", text)
        pika_play = extract_section(r"\*Pika.?s?\s*플레이\*?\s*\n?(.*?)(?=\*잘한|\*못한|\*추가|\*베스트|$)", text)

        good_points = []
        bad_points = []
        good_matches = re.findall(r"(?:GOOD|잘한\s*것|잘한\s*점)\s*[:：]?\s*(.+?)(?=BAD|못한|$|\n\*)", text, re.DOTALL)
        for g in good_matches:
            items = re.findall(r"-?\s*(.+?)(?=\n|$)", g)
            good_points.extend([i.strip() for i in items if i.strip() and len(i.strip()) > 3])

        bad_matches = re.findall(r"(?:BAD|못한\s*것|못한\s*점)\s*[:：]?\s*(.+?)(?=GOOD|잘한|$|\n\*)", text, re.DOTALL)
        for b in bad_matches:
            items = re.findall(r"-?\s*(.+?)(?=\n|$)", b)
            bad_points.extend([i.strip() for i in items if i.strip() and len(i.strip()) > 3])

        lessons = []
        lessons_match = re.search(r"\*(?:추가된\s*원칙|개선할\s*점|원칙)\s*[/]?\s*(?:개선할\s*점)?\*?\s*\n?(.*?)(?=\n\n|$)", text, re.DOTALL)
        if lessons_match:
            lesson_text = lessons_match.group(1)
            items = re.findall(r"-\s*(.+?)(?=\n|$)", lesson_text)
            lessons.extend([i.strip() for i in items if i.strip()])

        tags = re.findall(r"#([가-힣A-Za-z0-9]+)", text)

        cases.append(
            BokgiCase(
                case_date=date_raw,
                exchange=exchange,
                symbol=symbol,
                profit_pct=profit_pct,
                market_cap=mcap,
                deposit_amount=deposit,
                best_play=best_play,
                pika_play=pika_play,
                good_points=good_points,
                bad_points=bad_points,
                lessons=lessons,
                tags=tags,
                raw_text=text[:2000],
                source_file=msg.source_file,
                message_id=msg.message_id,
                ts_title=msg.ts_title,
                max_premium_pct=max_premium_pct,
                hedge_type=hedge_type,
                network_chain=network_chain,
                withdrawal_open=withdrawal_open,
                listing_type=listing_type,
            )
        )
    return cases


def extract_guide_notes(messages: List[RawMessage]) -> List[GuideNote]:
    notes: List[GuideNote] = []
    for msg in messages:
        text = msg.text
        if "복기" in text:
            continue
        if len(text) < 120:
            continue
        # guide/strategy cues
        if not re.search(r"(가이드|전략|방법|팁|원칙|주의|리스크|정리|어떻게|플레이)", text):
            continue
        # avoid pure link dumps
        if len(re.findall(r"https?://", text)) > 3 and len(text) < 300:
            continue

        # topic: first line or header-like
        first_line = text.splitlines()[0].strip()
        topic = first_line[:80] if first_line else "guide_note"

        # key points: lines starting with 숫자/하이픈
        key_points = []
        for line in text.splitlines():
            line = line.strip()
            if re.match(r"^[-•]\s+", line):
                key_points.append(re.sub(r"^[-•]\s+", "", line))
            elif re.match(r"^\d+\.\s+", line):
                key_points.append(re.sub(r"^\d+\.\s+", "", line))
        if not key_points:
            # fallback: split by sentence
            key_points = [s.strip() for s in re.split(r"[.!?]\s+", text) if len(s.strip()) > 20][:5]

        notes.append(
            GuideNote(
                date_ymd=msg.date_ymd,
                time_hm=msg.time_hm,
                channel=msg.channel,
                topic=topic,
                key_points=key_points[:10],
                raw_text=text[:2000],
                source_file=msg.source_file,
                message_id=msg.message_id,
            )
        )
    return notes


def write_jsonl(path: Path, rows: List[Dict]):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: List[Dict], fieldnames: List[str]):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _parse_market_cap_usd(mcap: Optional[str]) -> Optional[float]:
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


def _parse_krw_amount(text: Optional[str]) -> Optional[float]:
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


def _result_label_from_profit(pct: Optional[float]) -> str:
    if pct is None:
        return ""
    if pct >= 30:
        return "대흥따리"
    if pct >= 10:
        return "흥따리"
    if pct > 0:
        return "보통"
    return "망따리"


def export_bokgi_to_labeling(bokgi_cases: List[BokgiCase]) -> Path:
    out_path = PROJECT_ROOT / "data" / "labeling" / "telegram_bokgi_enriched.csv"
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

    rows: List[Dict] = []
    for c in bokgi_cases:
        ex_map = {"업비트": "Upbit", "빗썸": "Bithumb", "코인원": "Coinone", "업빗썸": "Upbit+Bithumb"}
        exchange = ex_map.get(c.exchange, c.exchange)

        notes_parts = []
        if c.best_play:
            notes_parts.append("best_play: " + " | ".join(c.best_play))
        if c.pika_play:
            notes_parts.append("pika_play: " + " | ".join(c.pika_play))
        if c.good_points:
            notes_parts.append("good: " + " | ".join(c.good_points))
        if c.bad_points:
            notes_parts.append("bad: " + " | ".join(c.bad_points))
        if c.lessons:
            notes_parts.append("lessons: " + " | ".join(c.lessons))
        if not notes_parts:
            notes_parts.append(c.raw_text[:400])

        rows.append({
            "symbol": c.symbol,
            "exchange": exchange,
            "date": c.case_date,
            "listing_type": c.listing_type or "",
            "market_cap_usd": _parse_market_cap_usd(c.market_cap),
            "top_exchange": "",
            "top_exchange_tier": "",
            "deposit_krw": _parse_krw_amount(c.deposit_amount),
            "volume_5m_krw": "",
            "volume_1m_krw": "",
            "turnover_ratio": "",
            "max_premium_pct": c.max_premium_pct if c.max_premium_pct is not None else "",
            "premium_at_5m_pct": "",
            "supply_label": "",
            "hedge_type": c.hedge_type or "",
            "dex_liquidity_usd": "",
            "hot_wallet_usd": "",
            "network_chain": c.network_chain or "",
            "network_speed_min": "",
            "withdrawal_open": "" if c.withdrawal_open is None else str(c.withdrawal_open),
            "airdrop_claim_rate": "",
            "prev_listing_result": "",
            "market_condition": "",
            "result_label": _result_label_from_profit(c.profit_pct),
            "result_notes": " || ".join(notes_parts),
        })

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def step1_parse_exports() -> List[RawMessage]:
    messages: List[RawMessage] = []
    for d in EXPORT_DIRS:
        dpath = Path(d)
        if not dpath.exists():
            continue
        for html_path in sorted(dpath.glob("messages*.html")):
            messages.extend(parse_html_messages(html_path))
    return messages


def step2_extract_bokgi(messages: List[RawMessage]) -> List[BokgiCase]:
    return extract_bokgi_cases(messages)


def step3_merge_guide(bokgi_cases: List[BokgiCase]) -> Tuple[int, int]:
    if not GUIDE_CSV.exists():
        return (0, 0)

    with open(GUIDE_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        existing = list(reader)

    if not fieldnames:
        return (0, 0)

    # Remove previous telegram rows to avoid duplicates after rerun
    existing = [r for r in existing if not str(r.get("source_file", "")).startswith("telegram:")]

    existing_keys = set()
    for row in existing:
        key = (row.get("ticker", ""), row.get("listing_date_raw", ""), row.get("source_file", ""))
        existing_keys.add(key)

    added = 0
    for case in bokgi_cases:
        listing_date_raw = f"복기: {case.case_date}" if case.case_date else "복기: (date not specified)"
        descriptors = []
        if case.exchange:
            descriptors.append(f"exchange={case.exchange}")
        if case.profit_pct is not None:
            descriptors.append(f"profit_pct={case.profit_pct:+.2f}%")
        if case.market_cap:
            descriptors.append(f"mcap={case.market_cap}")
        if case.deposit_amount:
            descriptors.append(f"deposit={case.deposit_amount}")
        if case.tags:
            descriptors.append("tags=" + ",".join(case.tags[:10]))

        context_parts = []
        if case.best_play:
            context_parts.append("best_play: " + " | ".join(case.best_play))
        if case.pika_play:
            context_parts.append("pika_play: " + " | ".join(case.pika_play))
        if case.good_points:
            context_parts.append("good: " + " | ".join(case.good_points))
        if case.bad_points:
            context_parts.append("bad: " + " | ".join(case.bad_points))
        if case.lessons:
            context_parts.append("lessons: " + " | ".join(case.lessons))

        source = f"telegram:{Path(case.source_file).name}"
        if case.message_id:
            source += f"#message{case.message_id}"

        new_row = {
            "ticker": case.symbol,
            "name": "",
            "listing_date_raw": listing_date_raw,
            "descriptors_raw": "; ".join(descriptors),
            "context_raw": " || ".join(context_parts) if context_parts else case.raw_text[:500],
            "source_file": source,
        }

        key = (new_row["ticker"], new_row["listing_date_raw"], new_row["source_file"])
        if key in existing_keys:
            continue
        existing.append(new_row)
        existing_keys.add(key)
        added += 1

    with open(GUIDE_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing)

    return (len(existing), added)


def main():
    # Step 1
    raw_messages = step1_parse_exports()
    raw_rows = [asdict(m) for m in raw_messages]
    raw_jsonl = OUT_DIR / "raw_messages.jsonl"
    raw_csv = OUT_DIR / "raw_messages.csv"
    if raw_rows:
        write_jsonl(raw_jsonl, raw_rows)
        write_csv(raw_csv, raw_rows, list(raw_rows[0].keys()))

    # Step 2
    bokgi_cases = step2_extract_bokgi(raw_messages)
    bokgi_rows = [asdict(c) for c in bokgi_cases]
    bokgi_json = OUT_DIR / "bokgi_cases.json"
    bokgi_csv = OUT_DIR / "bokgi_cases.csv"
    with open(bokgi_json, "w", encoding="utf-8") as f:
        json.dump(bokgi_rows, f, ensure_ascii=False, indent=2)
    if bokgi_rows:
        write_csv(bokgi_csv, bokgi_rows, list(bokgi_rows[0].keys()))

    # Step 2b: Guide notes
    guide_notes = extract_guide_notes(raw_messages)
    guide_rows = [asdict(g) for g in guide_notes]
    guide_json = OUT_DIR / "guide_notes.json"
    guide_csv = OUT_DIR / "guide_notes.csv"
    with open(guide_json, "w", encoding="utf-8") as f:
        json.dump(guide_rows, f, ensure_ascii=False, indent=2)
    if guide_rows:
        write_csv(guide_csv, guide_rows, list(guide_rows[0].keys()))

    # Step 3
    total, added = step3_merge_guide(bokgi_cases)

    # Step 4: Export to labeling format
    labeling_path = export_bokgi_to_labeling(bokgi_cases)

    print("=== Telegram Bokgi Pipeline ===")
    print(f"Raw messages: {len(raw_messages)}")
    print(f"Bokgi cases: {len(bokgi_cases)}")
    print(f"Guide notes: {len(guide_notes)}")
    print(f"Output dir: {OUT_DIR}")
    print(f"Labeling export: {labeling_path}")
    if GUIDE_CSV.exists():
        print(f"Guide CSV total: {total}, added: {added}")
    else:
        print("Guide CSV not found; merge skipped.")


if __name__ == "__main__":
    main()
