"""
Phase 0 분석 스크립트 — 라벨링 데이터에서 임계값 도출

사용법:
    python scripts/phase0_analysis.py

입력: data/labeling/listing_data.csv (50건+ 수동 라벨링)
출력: 콘솔에 분석 결과 출력 → config/thresholds.yaml에 수동 반영
"""

import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path

CSV_PATH = Path(__file__).parent.parent / "data" / "labeling" / "listing_data.csv"


def load_data() -> list[dict]:
    """CSV 로드 및 숫자 필드 변환."""
    rows = []
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 빈 행 스킵
            if not row.get("symbol"):
                continue
            # 숫자 필드 변환
            for key in [
                "market_cap_usd", "deposit_krw", "volume_5m_krw",
                "volume_1m_krw", "turnover_ratio", "max_premium_pct",
                "premium_at_5m_pct", "dex_liquidity_usd", "hot_wallet_usd",
                "network_speed_min", "airdrop_claim_rate",
            ]:
                val = row.get(key, "").strip()
                row[key] = float(val) if val else None
            # bool 필드
            for key in ["withdrawal_open"]:
                val = row.get(key, "").strip().lower()
                row[key] = val in ("true", "yes", "1", "o", "open")
            # enum 필드 (v14: hedge_type)
            hedge_val = row.get("hedge_type", "").strip().lower()
            row["hedge_type"] = hedge_val if hedge_val in ("cex_futures", "dex_futures", "none") else "unknown"
            rows.append(row)
    return rows


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def analyze_basic_stats(data: list[dict]):
    """기본 통계: 건수, 거래소별, 판정별 분포."""
    print_section("1. 기본 통계")
    print(f"  총 건수: {len(data)}")

    exchange_counts = Counter(r["exchange"] for r in data)
    print(f"  거래소별: {dict(exchange_counts)}")

    result_counts = Counter(r["result_label"] for r in data)
    print(f"  판정 분포: {dict(result_counts)}")

    listing_type_counts = Counter(r["listing_type"] for r in data)
    print(f"  상장 유형: {dict(listing_type_counts)}")

    if len(data) < 50:
        print(f"\n  ⚠️  데이터 {len(data)}건 — 최소 50건 권장")


def analyze_turnover_ratio(data: list[dict]):
    """Turnover Ratio 사분위수 도출."""
    print_section("2. Turnover Ratio 사분위수")

    values = [r["turnover_ratio"] for r in data if r["turnover_ratio"] is not None]
    if not values:
        print("  ⚠️  turnover_ratio 데이터 없음")
        return

    values_sorted = sorted(values)
    n = len(values_sorted)

    def percentile(pct: float) -> float:
        idx = (pct / 100) * (n - 1)
        lower = int(idx)
        upper = min(lower + 1, n - 1)
        frac = idx - lower
        return values_sorted[lower] + frac * (values_sorted[upper] - values_sorted[lower])

    p25 = percentile(25)
    p50 = percentile(50)
    p75 = percentile(75)
    p90 = percentile(90)

    print(f"  전체 ({n}건):")
    print(f"    P25 (low):          {p25:.2f}")
    print(f"    P50 (normal):       {p50:.2f}")
    print(f"    P75 (high):         {p75:.2f}")
    print(f"    P90 (extreme_high): {p90:.2f}")
    print(f"    min: {min(values):.2f}, max: {max(values):.2f}")

    # 흥따리 건만 별도 분석
    heung_values = [
        r["turnover_ratio"] for r in data
        if r["turnover_ratio"] is not None
        and r.get("result_label") in ("heung", "대흥따리", "흥따리")
    ]
    if heung_values:
        heung_sorted = sorted(heung_values)
        print(f"\n  흥따리 건만 ({len(heung_values)}건):")
        print(f"    중앙값: {statistics.median(heung_sorted):.2f}")
        print(f"    평균:   {statistics.mean(heung_sorted):.2f}")
        print(f"    min: {min(heung_sorted):.2f}, max: {max(heung_sorted):.2f}")

    print(f"\n  → thresholds.yaml 반영:")
    print(f"    turnover_ratio:")
    print(f"      low: {p25:.1f}")
    print(f"      normal: {p50:.1f}")
    print(f"      high: {p75:.1f}")
    print(f"      extreme_high: {p90:.1f}")


def analyze_premium(data: list[dict]):
    """김프 분포 분석."""
    print_section("3. 프리미엄(김프) 분포")

    max_prems = [r["max_premium_pct"] for r in data if r["max_premium_pct"] is not None]
    if not max_prems:
        print("  ⚠️  max_premium_pct 데이터 없음")
        return

    print(f"  전체 ({len(max_prems)}건):")
    print(f"    평균: {statistics.mean(max_prems):.1f}%")
    print(f"    중앙값: {statistics.median(max_prems):.1f}%")
    print(f"    min: {min(max_prems):.1f}%, max: {max(max_prems):.1f}%")

    # 판정별
    by_label = defaultdict(list)
    for r in data:
        if r["max_premium_pct"] is not None:
            by_label[r.get("result_label", "unknown")].append(r["max_premium_pct"])

    print(f"\n  판정별 최대 김프:")
    for label, vals in sorted(by_label.items()):
        avg = statistics.mean(vals)
        med = statistics.median(vals)
        print(f"    {label:10s}: 평균 {avg:6.1f}% | 중앙값 {med:6.1f}% | 건수 {len(vals)}")


def analyze_scenario_probabilities(data: list[dict]):
    """시나리오별 조건부 확률 계산."""
    print_section("4. 시나리오 조건부 확률")

    total = len(data)
    if total == 0:
        print("  ⚠️  데이터 없음")
        return

    heung_labels = ("heung", "대흥따리", "흥따리")

    def heung_rate(subset: list[dict]) -> str:
        if not subset:
            return "N/A (0건)"
        count = sum(1 for r in subset if r.get("result_label") in heung_labels)
        rate = count / len(subset)
        return f"{rate:.1%} ({count}/{len(subset)})"

    # 기본 확률
    print(f"  P(흥따리): {heung_rate(data)}")

    # supply_label별
    constrained = [r for r in data if r.get("supply_label") == "constrained"]
    smooth = [r for r in data if r.get("supply_label") == "smooth"]
    print(f"  P(흥따리 | constrained): {heung_rate(constrained)}")
    print(f"  P(흥따리 | smooth):      {heung_rate(smooth)}")

    # hedge_type별 (v14: 3단계 — cex_futures / dex_futures / none)
    for ht in ["cex_futures", "dex_futures", "none"]:
        subset = [r for r in data if r.get("hedge_type") == ht]
        print(f"  P(흥따리 | hedge={ht:12s}): {heung_rate(subset)}")

    # market_condition별
    for cond in ["bull", "bear", "neutral"]:
        subset = [r for r in data if r.get("market_condition") == cond]
        print(f"  P(흥따리 | market={cond:7s}): {heung_rate(subset)}")

    # prev_listing_result별
    prev_heung = [r for r in data if r.get("prev_listing_result") in heung_labels]
    print(f"  P(흥따리 | prev=heung):  {heung_rate(prev_heung)}")

    # 교차: constrained AND prev_heung
    cross = [r for r in data
             if r.get("supply_label") == "constrained"
             and r.get("prev_listing_result") in heung_labels]
    print(f"  P(흥따리 | constrained AND prev=heung): {heung_rate(cross)}")

    # listing_type별
    print(f"\n  상장 유형별:")
    for lt in ["TGE", "직상장", "옆상장"]:
        subset = [r for r in data if r.get("listing_type") == lt]
        print(f"    P(흥따리 | {lt:6s}): {heung_rate(subset)}")


def analyze_supply_correlation(data: list[dict]):
    """SupplyClassifier 5-factor 상관 분석."""
    print_section("5. Supply Factor 상관 분석")

    heung_labels = ("heung", "대흥따리", "흥따리")

    # result를 0/1로 변환
    results = []
    for r in data:
        results.append(1 if r.get("result_label") in heung_labels else 0)

    factors = {
        "hot_wallet_usd": [r.get("hot_wallet_usd") for r in data],
        "dex_liquidity_usd": [r.get("dex_liquidity_usd") for r in data],
        "withdrawal_open": [1 if r.get("withdrawal_open") else 0 for r in data],
        "airdrop_claim_rate": [r.get("airdrop_claim_rate") for r in data],
        "network_speed_min": [r.get("network_speed_min") for r in data],
    }

    print(f"  Factor별 흥따리 비율 (있음 vs 없음/낮음):\n")

    for fname, fvalues in factors.items():
        # None이 아닌 건만
        valid_pairs = [
            (fv, rv) for fv, rv in zip(fvalues, results)
            if fv is not None
        ]
        if not valid_pairs:
            print(f"    {fname:25s}: 데이터 없음")
            continue

        fvals, rvals = zip(*valid_pairs)
        total_valid = len(fvals)
        heung_count = sum(rvals)

        # 간단 상관: 중앙값 기준으로 high/low 분류
        if isinstance(fvals[0], (int, float)):
            median_val = statistics.median(fvals)
            high_group = [rv for fv, rv in valid_pairs if fv >= median_val]
            low_group = [rv for fv, rv in valid_pairs if fv < median_val]

            high_rate = sum(high_group) / len(high_group) if high_group else 0
            low_rate = sum(low_group) / len(low_group) if low_group else 0

            direction = "↑ 높을수록 흥" if high_rate > low_rate else "↓ 낮을수록 흥"
            diff = abs(high_rate - low_rate)
            print(f"    {fname:25s}: high={high_rate:.1%} low={low_rate:.1%} "
                  f"(차이 {diff:.1%}) {direction} [{total_valid}건]")
        else:
            print(f"    {fname:25s}: {total_valid}건 (비수치)")

    print(f"\n  → 차이가 큰 factor에 더 높은 가중치 부여 권장")


def apply_shrinkage(raw_coeff: float, sample_count: int, min_sample: int = 10) -> float:
    """표본 부족 시 계수를 baseline(0.0)으로 축소 (v15).

    shrink_factor = min(1.0, sample_count / min_sample)
    effective_coeff = raw_coeff * shrink_factor

    예: raw=0.15, count=4 → 0.15 * 0.4 = 0.06
    예: raw=0.37, count=45 → 0.37 * 1.0 = 0.37 (충분)
    """
    shrink_factor = min(1.0, sample_count / min_sample)
    return raw_coeff * shrink_factor


def analyze_hedge_type_detail(data: list[dict]):
    """헤징 유형 3단계 분석 + shrinkage 적용 (v14/v15)."""
    print_section("7. 헤징 유형 3단계 분석 (v14/v15)")

    heung_labels = ("heung", "대흥따리", "흥따리")
    total = len(data)
    total_heung = sum(1 for r in data if r.get("result_label") in heung_labels)
    base_rate = total_heung / total if total > 0 else 0

    print(f"  기저 흥따리율: {base_rate:.1%} ({total_heung}/{total})")
    print()

    # hedge_type별 분석
    hedge_types = ["cex_futures", "dex_futures", "none"]
    raw_coefficients = {}

    for ht in hedge_types:
        subset = [r for r in data if r.get("hedge_type") == ht]
        count = len(subset)
        heung_count = sum(1 for r in subset if r.get("result_label") in heung_labels)
        rate = heung_count / count if count > 0 else 0
        raw_coeff = rate - base_rate
        raw_coefficients[ht] = (raw_coeff, count)

        print(f"  [{ht}] {count}건")
        print(f"    흥따리율: {rate:.1%} ({heung_count}/{count})")
        print(f"    원본 계수: {raw_coeff:+.3f}")

    # shrinkage 적용 (v15)
    min_sample = 10
    print(f"\n  --- Shrinkage 적용 (min_sample={min_sample}) ---")
    print(f"  {'유형':14s} {'원본계수':>8s} {'표본수':>6s} {'shrink':>8s} {'유효계수':>8s}")
    print(f"  {'-'*48}")

    for ht in hedge_types:
        raw_coeff, count = raw_coefficients[ht]
        effective = apply_shrinkage(raw_coeff, count, min_sample)
        shrink_factor = min(1.0, count / min_sample)
        print(f"  {ht:14s} {raw_coeff:+8.3f} {count:6d} {shrink_factor:8.2f} {effective:+8.3f}")

    # 전체 시나리오 계수 shrinkage (참고)
    print(f"\n  --- 전체 시나리오 계수 shrinkage 참고 ---")
    scenario_factors = {
        "supply_constrained": ("supply_label", "constrained"),
        "supply_smooth": ("supply_label", "smooth"),
        "market_bull": ("market_condition", "bull"),
        "market_neutral": ("market_condition", "neutral"),
        "market_bear": ("market_condition", "bear"),
    }

    print(f"  {'계수명':22s} {'표본수':>6s} {'shrink':>8s} {'비고':>10s}")
    print(f"  {'-'*50}")

    for name, (field, value) in scenario_factors.items():
        subset = [r for r in data if r.get(field) == value]
        count = len(subset)
        shrink_factor = min(1.0, count / min_sample)
        status = "충분" if count >= min_sample else f"축소({shrink_factor:.1f}x)"
        print(f"  {name:22s} {count:6d} {shrink_factor:8.2f} {status:>10s}")

    # prev_heung
    prev_heung = [r for r in data if r.get("prev_listing_result") in heung_labels]
    count = len(prev_heung)
    shrink_factor = min(1.0, count / min_sample)
    status = "충분" if count >= min_sample else f"축소({shrink_factor:.1f}x)"
    print(f"  {'prev_heung':22s} {count:6d} {shrink_factor:8.2f} {status:>10s}")


def analyze_exchange_comparison(data: list[dict]):
    """거래소별 비교 분석."""
    print_section("6. 거래소별 비교")

    heung_labels = ("heung", "대흥따리", "흥따리")

    for exchange in ["Upbit", "Bithumb"]:
        subset = [r for r in data if r.get("exchange", "").lower() == exchange.lower()]
        if not subset:
            continue

        heung_count = sum(1 for r in subset if r.get("result_label") in heung_labels)
        rate = heung_count / len(subset) if subset else 0
        prems = [r["max_premium_pct"] for r in subset if r.get("max_premium_pct") is not None]
        avg_prem = statistics.mean(prems) if prems else 0

        print(f"  {exchange.capitalize()}:")
        print(f"    건수: {len(subset)}, 흥따리율: {rate:.1%} ({heung_count}/{len(subset)})")
        print(f"    평균 최대김프: {avg_prem:.1f}%")


def main():
    print("=" * 60)
    print("  Phase 0 분석 — 라벨링 데이터 → 임계값 도출")
    print("=" * 60)

    if not CSV_PATH.exists():
        print(f"\n  ❌ CSV 파일 없음: {CSV_PATH}")
        return

    data = load_data()
    if not data:
        print(f"\n  ❌ 데이터가 비어있습니다. listing_data.csv에 데이터를 입력하세요.")
        print(f"     파일 위치: {CSV_PATH}")
        return

    analyze_basic_stats(data)
    analyze_turnover_ratio(data)
    analyze_premium(data)
    analyze_scenario_probabilities(data)
    analyze_supply_correlation(data)
    analyze_exchange_comparison(data)
    analyze_hedge_type_detail(data)

    print_section("요약")
    print("  위 분석 결과를 config/thresholds.yaml에 반영하세요.")
    print("  특히 다음 값을 실측치로 교체:")
    print("    - turnover_ratio P25/P50/P75/P90")
    print("    - scenario_coefficients (조건부 확률 기반)")
    print("    - supply_classifier_weights (상관분석 기반)")
    print("    - hedge_type 3단계 계수 (v14)")
    print("    - coefficient_governance shrinkage 결과 확인 (v15)")


if __name__ == "__main__":
    main()
