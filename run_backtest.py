"""백테스트 실행 스크립트.

실행:
    python3 run_backtest.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

from analysis.backtest import BacktestEngine


async def main():
    """메인 함수."""
    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    print("\n" + "=" * 70)
    print(" Phase 7 시나리오 백테스팅")
    print("=" * 70)
    print()

    # 백테스팅 엔진 초기화
    engine = BacktestEngine()

    # 백테스트 실행
    print("📊 백테스트 실행 중...")
    print()
    summary = await engine.run_backtest()

    # 리포트 출력
    engine.print_report(summary)

    # 목표 달성 여부
    target_accuracy = 0.70
    if summary.accuracy >= target_accuracy:
        print(f"\n✅ 목표 달성! (정확도 {summary.accuracy:.1%} >= {target_accuracy:.0%})")
        return 0
    else:
        print(f"\n⚠️ 목표 미달 (정확도 {summary.accuracy:.1%} < {target_accuracy:.0%})")
        print("   → 시나리오 로직 개선 필요")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
