#!/usr/bin/env python3
"""신규 상장 시뮬레이션 테스트.

GateChecker.analyze_listing()을 직접 호출하여 Gate 파이프라인 테스트.
실제로 신규 상장이 감지된 것처럼 분석 결과를 생성.

사용법:
    python scripts/test_listing_now.py BTC upbit
    python scripts/test_listing_now.py ETH bithumb
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from store.database import get_connection, apply_migrations
from store.writer import DatabaseWriter
from analysis.premium import PremiumCalculator
from analysis.cost_model import CostModel
from analysis.gate import GateChecker


async def test_listing(symbol: str, exchange: str) -> None:
    """신규 상장 분석 테스트."""
    print(f"\n{'='*60}")
    print(f"신규 상장 시뮬레이션: {symbol} @ {exchange}")
    print(f"{'='*60}\n")

    # DB 연결
    conn = get_connection()
    apply_migrations(conn)

    # Writer 시작
    writer = DatabaseWriter(conn)

    # Gate 컴포넌트
    premium_calc = PremiumCalculator(writer)
    cost_model = CostModel()
    gate_checker = GateChecker(premium_calc, cost_model, writer)

    try:
        # Gate 분석 실행
        print("Gate 분석 실행 중...")
        result = await gate_checker.analyze_listing(symbol, exchange)

        # 결과 출력
        print(f"\n{'='*60}")
        print("분석 결과")
        print(f"{'='*60}")
        print(f"심볼: {symbol}")
        print(f"거래소: {exchange}")
        print(f"GO/NO-GO: {'✅ GO' if result.can_proceed else '❌ NO-GO'}")
        print(f"Alert Level: {result.alert_level.name if result.alert_level else 'N/A'}")

        # GateInput에서 프리미엄/비용 정보 추출
        if result.gate_input:
            inp = result.gate_input
            print(f"\n📊 김치 프리미엄: {inp.premium_pct:.2f}%")
            print(f"   FX 소스: {inp.fx_source}")

            if inp.cost_result:
                print(f"\n💰 비용 분석:")
                print(f"   총 비용: {inp.cost_result.total_cost_pct:.2f}%")
                print(f"   순수익: {inp.cost_result.net_profit_pct:.2f}%")
                print(f"   슬리피지: {inp.cost_result.slippage_pct:.2f}%")
                print(f"   거래수수료: {inp.cost_result.exchange_fee_pct:.2f}%")

        if result.blockers:
            print(f"\n🚫 차단 사유:")
            for b in result.blockers:
                print(f"   - {b}")

        if result.warnings:
            print(f"\n⚠️ 경고:")
            for w in result.warnings:
                print(f"   - {w}")

        # Phase 5a 확장 결과
        if result.supply_result:
            sr = result.supply_result
            print(f"\n📦 공급 분류: {sr.classification.value}")
            print(f"   스코어: {sr.total_score:.2f}")
            print(f"   신뢰도: {sr.confidence:.2f}")
            if sr.turnover_ratio:
                print(f"   Turnover Ratio: {sr.turnover_ratio:.2f}")
            if sr.factors:
                print(f"   팩터:")
                for f in sr.factors:
                    print(f"     - {f.name}: {f.score:.2f} (가중치 {f.weight:.2f})")

        if result.listing_type_result:
            lt = result.listing_type_result
            print(f"\n🏷️ 상장 유형: {lt.listing_type.value}")
            print(f"   신뢰도: {lt.confidence:.2f}")
            if lt.top_exchange:
                print(f"   Top 거래소: {lt.top_exchange}")
            if lt.reason:
                print(f"   사유: {lt.reason}")

        if result.recommended_strategy:
            print(f"\n🎯 추천 전략: {result.recommended_strategy.value}")

        print(f"\n{'='*60}\n")

    finally:
        writer.shutdown()
        conn.close()


def main():
    if len(sys.argv) < 3:
        print("사용법: python scripts/test_listing_now.py <SYMBOL> <EXCHANGE>")
        print("예시: python scripts/test_listing_now.py BTC upbit")
        print("      python scripts/test_listing_now.py ETH bithumb")
        sys.exit(1)

    symbol = sys.argv[1].upper()
    exchange = sys.argv[2].lower()

    if exchange not in ("upbit", "bithumb"):
        print(f"오류: 거래소는 'upbit' 또는 'bithumb'만 지원 (입력: {exchange})")
        sys.exit(1)

    asyncio.run(test_listing(symbol, exchange))


if __name__ == "__main__":
    main()
