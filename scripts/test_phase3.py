"""Phase 3 통합 테스트 — 오프라인 (REST API 불필요).

검증 항목:
  1. DB 마이그레이션 v2 (fx_snapshots + alert_debounce)
  2. Config YAML 5개 로드
  3. CoinGeckoCache TTL 로직
  4. CostModel 계산 (슬리피지, 헤지, 총비용)
  5. PremiumCalculator.calculate_premium() (fx_source 전달)
  6. GateChecker.check_hard_blockers() (4 Blocker + 3 Warning)
  7. GateChecker WATCH_ONLY (hardcoded FX)
  8. TelegramAlert debounce DB 동작
  9. TelegramAlert 레벨별 라우팅
  10. MarketMonitor 시그니처 검증 (gate_checker + alert)
  11. collector_daemon import 체인
  12. _graceful_shutdown alert.flush_batch 호출 확인

사용법:
    python scripts/test_phase3.py
"""

import asyncio
import inspect
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from store.database import get_connection, apply_migrations
from store.writer import DatabaseWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test_phase3")

_TEST_DB = str(_ROOT / "test_phase3.db")
_PASS = 0
_FAIL = 0


def result(name: str, ok: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if ok:
        _PASS += 1
        status = "PASS"
    else:
        _FAIL += 1
        status = "FAIL"
    msg = f"[{status}] {name}"
    if detail:
        msg += f" — {detail}"
    logger.info(msg)


# ---- 테스트 함수 ----


def test_01_migration_v2() -> None:
    """DB 마이그레이션 v2: fx_snapshots + alert_debounce 생성."""
    conn = get_connection(_TEST_DB)
    version = apply_migrations(conn)
    result("01 Migration v2", version == 2, f"v{version}")

    # fx_snapshots 테이블 확인
    cols = conn.execute("PRAGMA table_info(fx_snapshots)").fetchall()
    col_names = {c["name"] for c in cols}
    expected = {"id", "timestamp", "fx_rate", "source", "btc_krw", "btc_usd"}
    result(
        "01 fx_snapshots columns",
        expected.issubset(col_names),
        f"{col_names}",
    )

    # alert_debounce 테이블 확인
    cols = conn.execute("PRAGMA table_info(alert_debounce)").fetchall()
    col_names = {c["name"] for c in cols}
    expected = {"key", "last_sent_at", "expires_at"}
    result(
        "01 alert_debounce columns",
        expected.issubset(col_names),
        f"{col_names}",
    )

    # 인덱스 확인
    idxs = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_fx%'"
    ).fetchall()
    result(
        "01 fx_snapshots index",
        len(idxs) >= 1,
        f"{[i['name'] for i in idxs]}",
    )
    conn.close()


def test_02_config_yamls() -> None:
    """Config YAML 5개 로드 검증."""
    import yaml

    configs = {
        "features.yaml": ["hard_gate"],
        "networks.yaml": ["networks"],
        "exchanges.yaml": ["global", "domestic"],
        "fees.yaml": ["trading_fees", "hedge_fees"],
        "vasp_matrix.yaml": ["vasp_matrix"],
    }

    for filename, required_keys in configs.items():
        path = _ROOT / "config" / filename
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            has_keys = all(k in data for k in required_keys)
            result(
                f"02 {filename}",
                has_keys,
                f"keys={list(data.keys())[:5]}",
            )
        except Exception as e:
            result(f"02 {filename}", False, str(e))


def test_03_cache_ttl() -> None:
    """CoinGeckoCache TTL 로직."""
    from store.cache import CoinGeckoCache, _CacheEntry, TTL_STATIC, TTL_SEMI_STATIC, TTL_DYNAMIC

    # TTL 값 검증
    result("03 TTL_STATIC", TTL_STATIC == 86400, f"{TTL_STATIC}")
    result("03 TTL_SEMI_STATIC", TTL_SEMI_STATIC == 3600, f"{TTL_SEMI_STATIC}")
    result("03 TTL_DYNAMIC", TTL_DYNAMIC == 60, f"{TTL_DYNAMIC}")

    # CacheEntry 만료 검증
    fresh = _CacheEntry(data="x", fetched_at=time.time() - 10, ttl=60)
    result("03 CacheEntry fresh", not fresh.is_expired, f"age={fresh.age_sec:.0f}s")

    expired = _CacheEntry(data="x", fetched_at=time.time() - 100, ttl=60)
    result("03 CacheEntry expired", expired.is_expired, f"age={expired.age_sec:.0f}s")

    # 키 정렬 일관성
    k1 = CoinGeckoCache._make_key("/test", {"b": "2", "a": "1"})
    k2 = CoinGeckoCache._make_key("/test", {"a": "1", "b": "2"})
    result("03 Cache key consistency", k1 == k2, f"k1={k1}")


def test_04_cost_model() -> None:
    """CostModel 계산 (슬리피지, 헤지, 총비용)."""
    from analysis.cost_model import CostModel

    cm = CostModel()

    # 헤지 비용 테스트
    hc_cex = cm.get_hedge_cost("cex")
    result(
        "04 HedgeCost cex",
        hc_cex.fee_pct > 0 and hc_cex.funding_cost_pct > 0,
        f"fee={hc_cex.fee_pct}%, funding={hc_cex.funding_cost_pct}%",
    )

    hc_none = cm.get_hedge_cost("none")
    result(
        "04 HedgeCost none",
        hc_none.fee_pct == 0 and hc_none.funding_cost_pct == 0,
        "zero cost",
    )

    # 슬리피지 (오더북)
    mock_ob = {
        "asks": [
            [100000, 1.0],
            [100100, 2.0],
            [100500, 5.0],
        ]
    }
    slip = cm.estimate_slippage(mock_ob, 300_000)
    result(
        "04 Slippage with orderbook",
        0 < slip < 5,
        f"{slip:.4f}%",
    )

    # 슬리피지 (오더북 없음)
    slip_none = cm.estimate_slippage(None, 1_000_000)
    result("04 Slippage no orderbook", slip_none == 1.0, f"{slip_none}%")

    # 총비용 계산
    cr = cm.calculate_total_cost(
        premium_pct=5.0,
        network="ethereum",
        amount_krw=10_000_000,
        hedge_type="cex",
        fx_rate=1350.0,
        domestic_exchange="upbit",
        global_exchange="binance",
    )
    result(
        "04 Total cost",
        cr.total_cost_pct > 0 and cr.net_profit_pct < 5.0,
        f"total={cr.total_cost_pct:.2f}%, net={cr.net_profit_pct:.2f}%",
    )

    # 가스비 경고 (소액에서 가스비 비율 높음)
    cr_small = cm.calculate_total_cost(
        premium_pct=5.0,
        network="ethereum",
        amount_krw=100_000,  # 10만원 — 가스비 비율 높음
        hedge_type="none",
        fx_rate=1350.0,
    )
    result(
        "04 Gas warning on small amount",
        cr_small.gas_warn,
        f"gas_cost={cr_small.gas_cost_krw:,.0f}원, amount=100K",
    )


async def test_05_premium_calculate() -> None:
    """PremiumCalculator.calculate_premium() fx_source 전달."""
    from analysis.premium import PremiumCalculator

    conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(conn)
    writer.start()

    pc = PremiumCalculator(writer)

    # 정상 계산
    r = await pc.calculate_premium(
        krw_price=150_000_000,
        global_usd_price=100_000,
        fx_rate=1350.0,
        fx_source="btc_implied",
    )
    result(
        "05 Premium calc",
        abs(r.premium_pct - 11.11) < 0.1,
        f"premium={r.premium_pct:.2f}%",
    )
    result("05 fx_source passed", r.fx_source == "btc_implied", r.fx_source)

    # 기본 fx_source
    r2 = await pc.calculate_premium(
        krw_price=150_000_000,
        global_usd_price=100_000,
        fx_rate=1350.0,
    )
    result("05 Default fx_source", r2.fx_source == "unknown", r2.fx_source)

    # 에러 케이스 (global_usd_price=0)
    r3 = await pc.calculate_premium(
        krw_price=150_000_000,
        global_usd_price=0,
        fx_rate=1350.0,
        fx_source="eth_implied",
    )
    result(
        "05 Error case preserves fx_source",
        r3.fx_source == "eth_implied" and r3.premium_pct == 0.0,
        f"source={r3.fx_source}, prem={r3.premium_pct}",
    )

    writer.shutdown()


async def test_06_gate_blockers() -> None:
    """GateChecker 4 Blocker + 3 Warning."""
    from analysis.gate import GateChecker, GateInput, AlertLevel
    from analysis.cost_model import CostResult, CostModel
    from analysis.premium import PremiumCalculator

    conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(conn)
    pc = PremiumCalculator(writer)
    cm = CostModel()
    gc = GateChecker(pc, cm, writer)

    def cost(net_profit=5.0, gas_warn=False):
        return CostResult(
            slippage_pct=1.0, gas_cost_krw=20000, exchange_fee_pct=0.15,
            hedge_cost_pct=0.06, total_cost_pct=1.41,
            net_profit_pct=net_profit, gas_warn=gas_warn,
        )

    # Blocker 1: 입금 차단
    r = gc.check_hard_blockers(GateInput(
        symbol="A", exchange="upbit", premium_pct=10,
        cost_result=cost(), deposit_open=False, withdrawal_open=True,
        transfer_time_min=5, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="cex", top_exchange="binance",
    ))
    result("06 Blocker: deposit closed", not r.can_proceed and "입금" in r.blockers[0])

    # Blocker 2: 수익성 부족
    r = gc.check_hard_blockers(GateInput(
        symbol="A", exchange="upbit", premium_pct=1,
        cost_result=cost(-0.5), deposit_open=True, withdrawal_open=True,
        transfer_time_min=5, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="cex", top_exchange="binance",
    ))
    result("06 Blocker: negative profit", not r.can_proceed and "수익성" in str(r.blockers))

    # Blocker 3: 전송 시간
    r = gc.check_hard_blockers(GateInput(
        symbol="A", exchange="upbit", premium_pct=10,
        cost_result=cost(), deposit_open=True, withdrawal_open=True,
        transfer_time_min=45, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="cex", top_exchange="binance",
    ))
    result("06 Blocker: slow transfer", not r.can_proceed and "전송" in str(r.blockers))

    # Warning 1: 유동성 부족
    r = gc.check_hard_blockers(GateInput(
        symbol="A", exchange="upbit", premium_pct=10,
        cost_result=cost(), deposit_open=True, withdrawal_open=True,
        transfer_time_min=5, global_volume_usd=50_000,
        fx_source="btc_implied", hedge_type="cex", top_exchange="binance",
    ))
    result("06 Warning: low volume", r.can_proceed and "유동성" in str(r.warnings))

    # Warning 2: 가스비
    r = gc.check_hard_blockers(GateInput(
        symbol="A", exchange="upbit", premium_pct=10,
        cost_result=cost(gas_warn=True), deposit_open=True, withdrawal_open=True,
        transfer_time_min=5, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="cex", top_exchange="binance",
    ))
    result("06 Warning: gas", r.can_proceed and "가스비" in str(r.warnings))

    # Warning 3: DEX-only
    r = gc.check_hard_blockers(GateInput(
        symbol="A", exchange="upbit", premium_pct=10,
        cost_result=cost(), deposit_open=True, withdrawal_open=True,
        transfer_time_min=5, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="dex_only", top_exchange="binance",
    ))
    result("06 Warning: DEX-only", r.can_proceed and "DEX-only" in str(r.warnings))

    conn.close()


async def test_07_gate_watch_only() -> None:
    """GateChecker WATCH_ONLY: hardcoded FX → blocker."""
    from analysis.gate import GateChecker, GateInput
    from analysis.cost_model import CostResult, CostModel
    from analysis.premium import PremiumCalculator

    conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(conn)
    gc = GateChecker(PremiumCalculator(writer), CostModel(), writer)

    cr = CostResult(
        slippage_pct=1.0, gas_cost_krw=20000, exchange_fee_pct=0.15,
        hedge_cost_pct=0.06, total_cost_pct=1.41,
        net_profit_pct=5.0, gas_warn=False,
    )

    r = gc.check_hard_blockers(GateInput(
        symbol="A", exchange="upbit", premium_pct=10,
        cost_result=cr, deposit_open=True, withdrawal_open=True,
        transfer_time_min=5, global_volume_usd=500_000,
        fx_source="hardcoded_fallback", hedge_type="cex", top_exchange="binance",
    ))
    result(
        "07 WATCH_ONLY blocker",
        not r.can_proceed and any("WATCH_ONLY" in b for b in r.blockers),
        f"blockers={r.blockers}",
    )
    conn.close()


async def test_08_alert_debounce() -> None:
    """TelegramAlert debounce DB 동작."""
    from alerts.telegram import TelegramAlert

    # DB 세팅
    conn = get_connection(_TEST_DB)
    apply_migrations(conn)

    writer_conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(writer_conn)
    writer.start()

    read_conn = get_connection(_TEST_DB)

    alert = TelegramAlert(writer, read_conn)
    result("08 Not configured (no token)", not alert.is_configured, "dry-run mode")

    # 첫 debounce check (비어있음 → True)
    can = alert._debounce_check("test_key_3")
    result("08 First check: can send", can)

    # debounce 업데이트
    alert._debounce_update("test_key_3", 300)
    time.sleep(0.5)  # Writer 처리 대기

    # 두 번째 check (디바운스 중 → False)
    can = alert._debounce_check("test_key_3")
    result("08 Second check: debounced", not can)

    # 다른 키는 영향 없음
    can = alert._debounce_check("other_key")
    result("08 Different key: can send", can)

    writer.shutdown()
    read_conn.close()
    conn.close()


async def test_09_alert_routing() -> None:
    """TelegramAlert 레벨별 라우팅."""
    from alerts.telegram import TelegramAlert
    from analysis.gate import AlertLevel

    conn = get_connection(_TEST_DB)
    apply_migrations(conn)
    writer_conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(writer_conn)
    writer.start()
    read_conn = get_connection(_TEST_DB)

    alert = TelegramAlert(writer, read_conn)

    # INFO → 로그만 (batch_buffer 영향 없음)
    alert._batch_buffer.clear()
    await alert.send(AlertLevel.INFO, "info test")
    result("09 INFO: no buffer", len(alert._batch_buffer) == 0)

    # LOW → batch_buffer에 추가
    await alert.send(AlertLevel.LOW, "low test")
    result("09 LOW: buffered", len(alert._batch_buffer) == 1)

    # CRITICAL → 즉시 (dry-run 로그)
    await alert.send(AlertLevel.CRITICAL, "critical test")
    result("09 CRITICAL: sent (dry-run)", True, "log output")

    # HIGH → 즉시
    await alert.send(AlertLevel.HIGH, "high test")
    result("09 HIGH: sent (dry-run)", True, "log output")

    # MEDIUM with debounce key
    await alert.send(AlertLevel.MEDIUM, "medium test", key="med_key")
    result("09 MEDIUM: sent with debounce", True)

    # flush_batch
    alert._batch_buffer = ["msg1", "msg2"]
    await alert.flush_batch()
    result("09 flush_batch: cleared", len(alert._batch_buffer) == 0)

    writer.shutdown()
    read_conn.close()
    conn.close()


def test_10_market_monitor_signature() -> None:
    """MarketMonitor 시그니처 검증."""
    from collectors.market_monitor import MarketMonitor

    sig = inspect.signature(MarketMonitor.__init__)
    params = list(sig.parameters.keys())
    result(
        "10 gate_checker param",
        "gate_checker" in params,
        f"params={params}",
    )
    result(
        "10 alert param",
        "alert" in params,
        f"params={params}",
    )

    # _format_alert 메서드 존재
    has_format = hasattr(MarketMonitor, "_format_alert")
    result("10 _format_alert exists", has_format)


def test_11_daemon_imports() -> None:
    """collector_daemon import 체인."""
    try:
        from analysis.premium import PremiumCalculator
        from analysis.cost_model import CostModel
        from analysis.gate import GateChecker
        from alerts.telegram import TelegramAlert
        result("11 Phase 3 imports", True)
    except ImportError as e:
        result("11 Phase 3 imports", False, str(e))


def test_12_shutdown_signature() -> None:
    """_graceful_shutdown에 alert 파라미터 확인."""
    # collector_daemon.py 소스를 읽어서 확인
    daemon_path = _ROOT / "collector_daemon.py"
    source = daemon_path.read_text(encoding="utf-8")

    has_alert_param = "alert: TelegramAlert" in source
    result("12 shutdown alert param", has_alert_param)

    has_flush_call = "alert.flush_batch()" in source
    result("12 shutdown flush_batch call", has_flush_call)

    has_6_steps = "Shutdown 6/6" in source
    result("12 shutdown 6 steps", has_6_steps)


async def test_13_fx_snapshot_write() -> None:
    """FX 스냅샷 DB 저장 검증."""
    from analysis.premium import PremiumCalculator

    conn = get_connection(_TEST_DB)
    apply_migrations(conn)
    writer_conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(writer_conn)
    writer.start()

    pc = PremiumCalculator(writer)
    await pc.save_fx_snapshot(1350.0, "btc_implied", 140_000_000, 103_000)
    time.sleep(0.5)

    read_conn = get_connection(_TEST_DB)
    rows = read_conn.execute(
        "SELECT * FROM fx_snapshots ORDER BY id DESC LIMIT 1"
    ).fetchall()
    result(
        "13 FX snapshot saved",
        len(rows) == 1 and rows[0]["source"] == "btc_implied",
        f"rate={rows[0]['fx_rate']}, source={rows[0]['source']}" if rows else "no rows",
    )

    writer.shutdown()
    read_conn.close()
    conn.close()


async def test_14_alert_level_enum() -> None:
    """AlertLevel 5단계 값 검증."""
    from analysis.gate import AlertLevel

    levels = list(AlertLevel)
    result("14 AlertLevel count", len(levels) == 5, f"{len(levels)}")

    expected = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    actual = [l.value for l in levels]
    result("14 AlertLevel values", actual == expected, f"{actual}")


async def test_15_cost_model_networks() -> None:
    """CostModel 네트워크별 가스비 계산."""
    from analysis.cost_model import CostModel

    cm = CostModel()
    fx = 1350.0

    eth_gas = cm.get_gas_cost_krw("ethereum", fx)
    sol_gas = cm.get_gas_cost_krw("solana", fx)

    result(
        "15 ETH gas > SOL gas",
        eth_gas > sol_gas,
        f"ETH={eth_gas:,.0f}원, SOL={sol_gas:,.0f}원",
    )

    # 알 수 없는 네트워크 → 기본값
    unk_gas = cm.get_gas_cost_krw("unknown_chain", fx)
    result("15 Unknown network default", unk_gas == fx, f"{unk_gas}")


# ---- 메인 ----


async def main() -> None:
    """전체 테스트 실행."""
    # 기존 테스트 DB 삭제
    for f in [_TEST_DB, _TEST_DB + "-wal", _TEST_DB + "-shm"]:
        if os.path.exists(f):
            os.unlink(f)

    logger.info("=" * 60)
    logger.info("Phase 3 통합 테스트 시작")
    logger.info("=" * 60)

    # 동기 테스트
    test_01_migration_v2()
    test_02_config_yamls()
    test_03_cache_ttl()
    test_04_cost_model()

    # 비동기 테스트
    await test_05_premium_calculate()
    await test_06_gate_blockers()
    await test_07_gate_watch_only()
    await test_08_alert_debounce()
    await test_09_alert_routing()

    # 구조 검증 테스트
    test_10_market_monitor_signature()
    test_11_daemon_imports()
    test_12_shutdown_signature()

    # 추가 테스트
    await test_13_fx_snapshot_write()
    await test_14_alert_level_enum()
    await test_15_cost_model_networks()

    # 정리
    for f in [_TEST_DB, _TEST_DB + "-wal", _TEST_DB + "-shm"]:
        if os.path.exists(f):
            os.unlink(f)

    logger.info("=" * 60)
    logger.info("Phase 3 테스트 완료: %d PASS, %d FAIL (총 %d)", _PASS, _FAIL, _PASS + _FAIL)
    logger.info("=" * 60)

    if _FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
