#!/usr/bin/env python3
"""67건 과거 상장 Replay 테스트 (Phase 4).

data/labeling/listing_data.csv 67건을 GateChecker.check_hard_blockers()로 재현.

목적:
  1. 67건 전부 크래시 없이 처리
  2. Phase 3 Hard Gate만으로의 baseline 정확도 측정
  3. Phase 5+ 추가 분석 모듈의 효과 비교 기준선

result_label 분류:
  - 대흥따리/흥따리 → GO 기대 (profitable listing)
  - 망따리         → NO-GO 기대 (failed listing)
"""

import csv
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from analysis.gate import GateInput, GateChecker, GateResult
from analysis.cost_model import CostResult

# GO 기대 result_label 값들
_GO_LABELS = {"대흥따리", "흥따리"}
_NOGO_LABELS = {"망따리"}

_CSV_PATH = _ROOT / "data" / "labeling" / "listing_data.csv"


def _parse_float(val: str, default: float = 0.0) -> float:
    """CSV 문자열 → float (빈 문자열 → default)."""
    if not val or val.strip() == "":
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _parse_bool(val: str, default: bool = True) -> bool:
    """CSV 문자열 → bool."""
    if not val or val.strip() == "":
        return default
    return val.strip().lower() in ("true", "1", "yes")


def csv_to_gate_input(row: dict) -> GateInput:
    """CSV 레코드 → GateInput 변환.

    Phase 3 Hard Gate에 필요한 최소 필드만 매핑.
    """
    symbol = row.get("symbol", "UNKNOWN")
    exchange = row.get("exchange", "bithumb").lower()
    premium_pct = _parse_float(row.get("max_premium_pct", ""), 0.0)
    hedge_type = row.get("hedge_type", "none") or "none"
    network = row.get("network_chain", "unknown") or "unknown"
    withdrawal_open = _parse_bool(row.get("withdrawal_open", ""), True)
    transfer_time = _parse_float(row.get("network_speed_min", ""), 5.0)
    top_exchange = row.get("top_exchange", "") or ""

    # CostResult 조립 (Phase 3 기본값 기반)
    # 실제 비용 계산은 불가 (과거 데이터에 오더북 없음)
    # → 간이 추정: 거래수수료 0.5% + 슬리피지 0.3% + 가스 0.1% = ~0.9%
    total_cost_pct = 0.9
    net_profit_pct = premium_pct - total_cost_pct

    cost_result = CostResult(
        slippage_pct=0.3,
        gas_cost_krw=5000,
        exchange_fee_pct=0.5,
        hedge_cost_pct=0.0 if hedge_type == "none" else 0.15,
        total_cost_pct=total_cost_pct,
        net_profit_pct=net_profit_pct,
        gas_warn=False,
    )

    return GateInput(
        symbol=symbol,
        exchange=exchange,
        premium_pct=premium_pct,
        cost_result=cost_result,
        deposit_open=True,  # 과거 데이터에 deposit_open 미기록 → 기본 open
        withdrawal_open=withdrawal_open,
        transfer_time_min=transfer_time,
        global_volume_usd=100_000,  # 기본값 (과거 데이터에 글로벌 USD volume 미기록)
        fx_source="btc_implied",     # 과거 재현용 기본값
        hedge_type=hedge_type,
        network=network,
        top_exchange=top_exchange,
    )


def main() -> None:
    """67건 Replay 실행."""
    if not _CSV_PATH.exists():
        print(f"FAIL: CSV 파일 없음: {_CSV_PATH}")
        sys.exit(1)

    # GateChecker 생성 (check_hard_blockers만 사용하므로 minimal 초기화)
    # premium/cost_model/writer는 check_hard_blockers에서 사용하지 않음
    from unittest.mock import MagicMock
    gate = GateChecker(
        premium=MagicMock(),
        cost_model=MagicMock(),
        writer=MagicMock(),
    )

    with open(_CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)
    print(f"=== 과거 상장 Replay 테스트: {total}건 ===\n")

    passed = 0
    errors = 0
    correct_predictions = 0
    incorrect_predictions = 0
    skipped_labels = 0

    results = []

    for i, row in enumerate(rows, 1):
        symbol = row.get("symbol", "?")
        result_label = row.get("result_label", "").strip()

        try:
            gate_input = csv_to_gate_input(row)
            result = gate.check_hard_blockers(gate_input)
            passed += 1

            # 정확도 판정
            expected_go = result_label in _GO_LABELS
            expected_nogo = result_label in _NOGO_LABELS

            if expected_go or expected_nogo:
                if expected_go and result.can_proceed:
                    correct_predictions += 1
                    prediction_status = "CORRECT"
                elif expected_nogo and not result.can_proceed:
                    correct_predictions += 1
                    prediction_status = "CORRECT"
                else:
                    incorrect_predictions += 1
                    prediction_status = "WRONG"
            else:
                skipped_labels += 1
                prediction_status = "SKIP"

            go_str = "GO" if result.can_proceed else "NO-GO"
            results.append({
                "num": i,
                "symbol": symbol,
                "label": result_label,
                "gate": go_str,
                "prediction": prediction_status,
                "blockers": len(result.blockers),
                "warnings": len(result.warnings),
            })

        except Exception as e:
            errors += 1
            print(f"  ERROR [{i}] {symbol}: {e}")

    # 결과 출력
    print(f"{'#':>3} {'Symbol':<12} {'Label':<10} {'Gate':<8} {'Pred':<8} {'B':>2} {'W':>2}")
    print("-" * 55)
    for r in results:
        marker = "" if r["prediction"] == "CORRECT" else (
            " <<" if r["prediction"] == "WRONG" else ""
        )
        print(
            f"{r['num']:>3} {r['symbol']:<12} {r['label']:<10} {r['gate']:<8} "
            f"{r['prediction']:<8} {r['blockers']:>2} {r['warnings']:>2}{marker}"
        )

    print(f"\n=== Replay 결과 요약 ===")
    print(f"전체: {total}건")
    print(f"처리 성공: {passed}건, 에러: {errors}건")

    predictable = correct_predictions + incorrect_predictions
    if predictable > 0:
        accuracy = correct_predictions / predictable * 100
        print(f"\n정확도 (Phase 3 Hard Gate only):")
        print(f"  판정 가능: {predictable}건 (label 없음 제외: {skipped_labels}건)")
        print(f"  정확: {correct_predictions}건 ({accuracy:.1f}%)")
        print(f"  오답: {incorrect_predictions}건 ({100 - accuracy:.1f}%)")
    else:
        print("\n정확도 판정 불가 (유효 label 없음)")

    # 종료 코드
    if errors > 0:
        print(f"\nFAIL: {errors}건 에러 발생")
        sys.exit(1)
    else:
        print(f"\nPASS: {total}건 전부 크래시 없이 처리 완료")


if __name__ == "__main__":
    main()
