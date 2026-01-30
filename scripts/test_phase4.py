#!/usr/bin/env python3
"""Phase 4 통합 테스트 — 오프라인 (REST API 불필요).

검증 항목 (30건+):
  1. DB 마이그레이션 v3 (gate_analysis_log)
  2. gate_analysis_log 컬럼/인덱스 확인
  3. Health 판정 (RED/YELLOW/GREEN)
  4. Health load 실패 (파일 없음, 깨진 JSON)
  5. Gate 분석 로그 DB 기록 + 조회
  6. Gate 열화 배지 (FX, 헤지, 네트워크)
  7. VASP alt_note 배지
  8. 빈 테이블 조회 (no crash)
  9. Feature flag 읽기
  10. Procfile 내용 검증
  11. UI 모듈 import 검증
  12. 캐싱 TTL 소스 코드 검증
  13. 동시 상장 처리 (2건)
  14. DB WAL 동시성
  15. Replay 67건 무크래시
  16. Phase 3 회귀 테스트
  17. 엣지 케이스 (8건)

사용법:
    python scripts/test_phase4.py
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from store.database import get_connection, apply_migrations
from store.writer import DatabaseWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test_phase4")

_TEST_DB = str(_ROOT / "test_phase4.db")
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


# ===========================================================
# Step 1: Migration v3
# ===========================================================

def test_01_migration_v3() -> sqlite3.Connection:
    """DB 마이그레이션 v3: gate_analysis_log 생성."""
    conn = get_connection(_TEST_DB)
    version = apply_migrations(conn)
    result("01 Migration v3", version == 3, f"v{version}")

    # gate_analysis_log 테이블 확인
    cols = conn.execute("PRAGMA table_info(gate_analysis_log)").fetchall()
    col_names = {c["name"] for c in cols}
    expected = {
        "id", "timestamp", "symbol", "exchange", "can_proceed", "alert_level",
        "premium_pct", "net_profit_pct", "total_cost_pct", "fx_rate", "fx_source",
        "blockers_json", "warnings_json", "hedge_type", "network",
        "global_volume_usd", "gate_duration_ms",
    }
    result(
        "02 gate_analysis_log columns",
        expected.issubset(col_names),
        f"missing: {expected - col_names}" if not expected.issubset(col_names) else "all 17 columns",
    )

    # 인덱스 확인
    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='gate_analysis_log'"
    ).fetchall()
    idx_names = {r["name"] for r in indexes}
    result(
        "03 gate_analysis_log indexes",
        "idx_gate_log_ts" in idx_names and "idx_gate_log_symbol" in idx_names,
        f"{idx_names}",
    )

    return conn


# ===========================================================
# Step 2: Observability
# ===========================================================

def test_04_log_gate_analysis(conn: sqlite3.Connection) -> None:
    """Gate 분석 로그 DB 기록 + 조회."""
    from analysis.gate import GateResult, GateInput, AlertLevel
    from analysis.cost_model import CostResult

    writer_conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(writer_conn)
    writer.start()

    cost = CostResult(
        slippage_pct=0.3, gas_cost_krw=5000, exchange_fee_pct=0.25,
        hedge_cost_pct=0.0, total_cost_pct=0.55, net_profit_pct=4.45,
        gas_warn=False,
    )
    gate_input = GateInput(
        symbol="TEST", exchange="upbit", premium_pct=5.0,
        cost_result=cost, deposit_open=True, withdrawal_open=True,
        transfer_time_min=3.0, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="cex",
        network="ethereum", top_exchange="binance",
    )
    gate_result = GateResult(
        can_proceed=True, blockers=[], warnings=["유동성 OK"],
        alert_level=AlertLevel.CRITICAL, gate_input=gate_input,
    )

    async def _test():
        from metrics.observability import log_gate_analysis
        await log_gate_analysis(writer, gate_result, 123.45)
        # Writer flush
        await asyncio.sleep(0.5)

    asyncio.run(_test())

    # 조회 확인
    row = conn.execute(
        "SELECT * FROM gate_analysis_log WHERE symbol='TEST'"
    ).fetchone()

    result(
        "04 log_gate_analysis DB insert",
        row is not None,
        f"symbol={row['symbol']}" if row else "row not found",
    )

    if row:
        result(
            "04b can_proceed value",
            row["can_proceed"] == 1,
            f"can_proceed={row['can_proceed']}",
        )
        result(
            "04c alert_level value",
            row["alert_level"] == "CRITICAL",
            f"alert_level={row['alert_level']}",
        )
        result(
            "04d premium_pct value",
            abs(row["premium_pct"] - 5.0) < 0.01,
            f"premium_pct={row['premium_pct']}",
        )
        result(
            "04e gate_duration_ms",
            abs(row["gate_duration_ms"] - 123.45) < 0.01,
            f"duration={row['gate_duration_ms']}",
        )
        result(
            "04f blockers_json",
            json.loads(row["blockers_json"]) == [],
            f"blockers={row['blockers_json']}",
        )
        result(
            "04g warnings_json",
            "유동성" in row["warnings_json"],
            f"warnings={row['warnings_json']}",
        )

    writer.shutdown()
    writer_conn.close()


def test_05_log_gate_no_input(conn: sqlite3.Connection) -> None:
    """gate_input=None인 GateResult 기록."""
    from analysis.gate import GateResult, AlertLevel

    writer_conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(writer_conn)
    writer.start()

    gate_result = GateResult(
        can_proceed=False,
        blockers=["국내 가격 조회 실패"],
        warnings=[],
        alert_level=AlertLevel.LOW,
        gate_input=None,
    )

    async def _test():
        from metrics.observability import log_gate_analysis
        await log_gate_analysis(writer, gate_result, 50.0)
        await asyncio.sleep(0.5)

    asyncio.run(_test())

    row = conn.execute(
        "SELECT * FROM gate_analysis_log WHERE symbol='unknown' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    result(
        "05 log_gate_no_input",
        row is not None and row["can_proceed"] == 0,
        f"symbol={row['symbol'] if row else '?'}, can_proceed={row['can_proceed'] if row else '?'}",
    )

    writer.shutdown()
    writer_conn.close()


# ===========================================================
# Step 3: Health 판정
# ===========================================================

def test_06_health_green() -> None:
    """Health GREEN 판정."""
    from ui.health_display import evaluate_health

    data = {
        "heartbeat_timestamp": time.time(),
        "last_msg_time": {
            "upbit": time.time(),
            "bithumb": time.time(),
        },
        "queue_size": 50,
        "queue_drops": 0,
    }
    status, issues = evaluate_health(data)
    result("06 Health GREEN", status == "GREEN" and len(issues) == 0, f"{status}")


def test_07_health_red() -> None:
    """Health RED: heartbeat > 60초."""
    from ui.health_display import evaluate_health

    data = {
        "heartbeat_timestamp": time.time() - 120,  # 2분 전
        "last_msg_time": {"upbit": time.time(), "bithumb": time.time()},
        "queue_size": 0,
        "queue_drops": 0,
    }
    status, issues = evaluate_health(data)
    result(
        "07 Health RED (heartbeat)",
        status == "RED" and len(issues) > 0,
        f"{status}: {issues}",
    )


def test_08_health_yellow_stale() -> None:
    """Health YELLOW: Upbit WS > 30초 stale."""
    from ui.health_display import evaluate_health

    data = {
        "heartbeat_timestamp": time.time(),
        "last_msg_time": {
            "upbit": time.time() - 60,   # 60초 전
            "bithumb": time.time(),
        },
        "queue_size": 0,
        "queue_drops": 0,
    }
    status, issues = evaluate_health(data)
    result(
        "08 Health YELLOW (Upbit stale)",
        status == "YELLOW",
        f"{status}: {issues}",
    )


def test_09_health_yellow_queue() -> None:
    """Health YELLOW: queue > 10K."""
    from ui.health_display import evaluate_health

    data = {
        "heartbeat_timestamp": time.time(),
        "last_msg_time": {"upbit": time.time(), "bithumb": time.time()},
        "queue_size": 15_000,
        "queue_drops": 0,
    }
    status, issues = evaluate_health(data)
    result(
        "09 Health YELLOW (queue)",
        status == "YELLOW",
        f"{status}: {issues}",
    )


def test_10_health_yellow_drops() -> None:
    """Health YELLOW: drops > 0."""
    from ui.health_display import evaluate_health

    data = {
        "heartbeat_timestamp": time.time(),
        "last_msg_time": {"upbit": time.time(), "bithumb": time.time()},
        "queue_size": 0,
        "queue_drops": 5,
    }
    status, issues = evaluate_health(data)
    result(
        "10 Health YELLOW (drops)",
        status == "YELLOW",
        f"{status}: {issues}",
    )


def test_11_health_load_missing() -> None:
    """Health load: 파일 없음 → None."""
    from ui.health_display import load_health

    data = load_health("/nonexistent/path/health.json")
    result("11 Health load missing", data is None)


def test_12_health_load_broken() -> None:
    """Health load: 깨진 JSON → None."""
    from ui.health_display import load_health

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{broken json!!!")
        tmp_path = f.name

    try:
        data = load_health(tmp_path)
        result("12 Health load broken JSON", data is None)
    finally:
        os.unlink(tmp_path)


# ===========================================================
# Step 4: Gate 열화 배지
# ===========================================================

def test_13_degradation_badges() -> None:
    """Gate 열화 배지 로직."""
    from ui.ddari_common import render_degradation_badges as _render_degradation_badges

    # hardcoded FX → 빨간 배지
    row1 = {"fx_source": "hardcoded_fallback", "hedge_type": "cex", "network": "solana"}
    html1 = _render_degradation_badges(row1)
    result(
        "13 FX hardcoded badge",
        "FX 기본값 사용" in html1 and "dc2626" in html1,
        f"len={len(html1)}",
    )

    # 2차 소스 FX → 노란 배지
    row2 = {"fx_source": "usdt_krw_direct", "hedge_type": "cex", "network": "solana"}
    html2 = _render_degradation_badges(row2)
    result(
        "13b FX secondary badge",
        "FX 2차 소스" in html2 and "d97706" in html2,
    )

    # 헤지 불가
    row3 = {"fx_source": "btc_implied", "hedge_type": "none", "network": "solana"}
    html3 = _render_degradation_badges(row3)
    result(
        "13c Hedge none badge",
        "헤지 불가" in html3,
    )

    # 네트워크 기본값
    row4 = {"fx_source": "btc_implied", "hedge_type": "cex", "network": "ethereum"}
    html4 = _render_degradation_badges(row4)
    result(
        "13d Network default badge",
        "네트워크 기본값" in html4,
    )

    # 모든 배지 — 신뢰할 수 있는 상태
    row5 = {"fx_source": "btc_implied", "hedge_type": "cex", "network": "solana"}
    html5 = _render_degradation_badges(row5)
    result(
        "13e No degradation",
        html5.strip() == "",
        f"html='{html5}'",
    )


# ===========================================================
# Step 4b: VASP alt_note 배지
# ===========================================================

def test_14_vasp_badges() -> None:
    """VASP alt_note 배지 로직."""
    from ui.ddari_common import render_vasp_badge as _render_vasp_badge

    vasp = {
        "vasp_matrix": {
            "upbit": {
                "binance": {"status": "ok", "alt_note": "주요 코인 전송 가능"},
                "okx": {"status": "ok", "alt_note": ""},
                "bad_exchange": {"status": "blocked", "alt_note": ""},
                "partial_ex": {"status": "partial", "alt_note": "일부 제한"},
            }
        }
    }

    # ok with alt_note
    html1 = _render_vasp_badge("upbit", vasp)
    result(
        "14 VASP ok + alt_note",
        "주요 코인 전송 가능" in html1,
    )

    # blocked
    result(
        "14b VASP blocked",
        "blocked" in html1,
    )

    # partial
    result(
        "14c VASP partial",
        "일부제한" in html1 and "일부 제한" in html1,
    )


# ===========================================================
# Step 5: 빈 테이블 조회
# ===========================================================

def test_15_empty_table(conn: sqlite3.Connection) -> None:
    """빈 테이블에서 조회 (no crash)."""
    # 기존 데이터 삭제 후 테스트
    conn.execute("DELETE FROM gate_analysis_log")
    conn.commit()

    rows = conn.execute(
        "SELECT * FROM gate_analysis_log ORDER BY timestamp DESC LIMIT 20"
    ).fetchall()
    result("15 Empty table query", len(rows) == 0)


# ===========================================================
# Step 6: Feature flag 읽기
# ===========================================================

def test_16_feature_flags() -> None:
    """Feature flag 파일 읽기."""
    import yaml

    features_path = _ROOT / "config" / "features.yaml"
    result("16 features.yaml exists", features_path.exists())

    if features_path.exists():
        with open(features_path, encoding="utf-8") as f:
            features = yaml.safe_load(f) or {}

        result(
            "16b hard_gate enabled",
            features.get("hard_gate") is True,
        )
        result(
            "16c telegram_interactive defined",
            "telegram_interactive" in features,
            f"value={features.get('telegram_interactive')}",
        )


# ===========================================================
# Step 7: Procfile 내용
# ===========================================================

def test_17_procfile() -> None:
    """Procfile에 web 프로세스 + app.py에 데몬 통합."""
    procfile = _ROOT / "Procfile"
    result("17 Procfile exists", procfile.exists())

    if procfile.exists():
        content = procfile.read_text(encoding="utf-8")
        result(
            "17b web process",
            "web:" in content and "streamlit" in content,
        )

    # Railway 단일 서비스: 데몬이 app.py에 통합됨
    app_py = _ROOT / "app.py"
    if app_py.exists():
        app_content = app_py.read_text(encoding="utf-8")
        result(
            "17c daemon integrated in app",
            "start_background_daemon" in app_content and "collector_daemon" in app_content,
        )


# ===========================================================
# Step 8: UI 모듈 import 검증
# ===========================================================

def test_18_ui_imports() -> None:
    """UI 모듈 import."""
    try:
        from ui.health_display import load_health, evaluate_health, render_health_banner
        result("18 ui.health_display import", True)
    except ImportError as e:
        result("18 ui.health_display import", False, str(e))

    try:
        from ui.ddari_tab import render_ddari_tab
        from ui.ddari_common import render_degradation_badges, render_vasp_badge
        result("18b ui.ddari_tab import", True)
    except ImportError as e:
        result("18b ui.ddari_tab import", False, str(e))

    try:
        from metrics.observability import log_gate_analysis
        result("18c metrics.observability import", True)
    except ImportError as e:
        result("18c metrics.observability import", False, str(e))

    try:
        from alerts.telegram_bot import TelegramBot
        result("18d alerts.telegram_bot import", True)
    except ImportError as e:
        result("18d alerts.telegram_bot import", False, str(e))


# ===========================================================
# Step 9: 캐싱 TTL 소스 코드 검증
# ===========================================================

def test_19_caching_ttl() -> None:
    """캐싱 TTL 값 소스 코드 확인."""
    import inspect
    from ui.ddari_common import (
        fetch_recent_analyses_cached as _fetch_recent_analyses_cached,
        fetch_stats_cached as _fetch_stats_cached,
        load_vasp_matrix_cached as _load_vasp_matrix_cached,
    )

    # _fetch_recent_analyses_cached — cache_data(ttl=60) inside
    src_recent = inspect.getsource(_fetch_recent_analyses_cached)
    result(
        "19 _fetch_recent_analyses TTL=60",
        "ttl=60" in src_recent,
    )

    # _fetch_stats_cached — cache_data(ttl=3600) inside
    src_stats = inspect.getsource(_fetch_stats_cached)
    result(
        "19b _fetch_stats TTL=3600",
        "ttl=3600" in src_stats,
    )

    # _load_vasp_matrix_cached — cache_data(ttl=300) inside
    src_vasp = inspect.getsource(_load_vasp_matrix_cached)
    result(
        "19c _load_vasp_matrix TTL=300",
        "ttl=300" in src_vasp,
    )


# ===========================================================
# Step 10: 동시 상장 처리
# ===========================================================

def test_20_concurrent_listings(conn: sqlite3.Connection) -> None:
    """동시 상장 2건 Gate 분석 + 로그."""
    from analysis.gate import GateInput, GateResult, AlertLevel, GateChecker
    from analysis.cost_model import CostResult

    writer_conn = get_connection(_TEST_DB)
    writer = DatabaseWriter(writer_conn)
    writer.start()

    gate = GateChecker(
        premium=MagicMock(),
        cost_model=MagicMock(),
        writer=writer,
    )

    cost = CostResult(
        slippage_pct=0.3, gas_cost_krw=3000, exchange_fee_pct=0.25,
        hedge_cost_pct=0.0, total_cost_pct=0.55, net_profit_pct=2.45,
        gas_warn=False,
    )

    symbols = ["ALPHA", "BETA"]
    results_list = []

    for sym in symbols:
        gi = GateInput(
            symbol=sym, exchange="upbit", premium_pct=3.0,
            cost_result=cost, deposit_open=True, withdrawal_open=True,
            transfer_time_min=5.0, global_volume_usd=200_000,
            fx_source="btc_implied", hedge_type="cex",
            network="solana", top_exchange="binance",
        )
        r = gate.check_hard_blockers(gi)
        results_list.append(r)

    # 두 건 모두 GO
    result(
        "20 Concurrent ALPHA GO",
        results_list[0].can_proceed is True,
    )
    result(
        "20b Concurrent BETA GO",
        results_list[1].can_proceed is True,
    )

    # DB 기록
    async def _log():
        from metrics.observability import log_gate_analysis
        for r in results_list:
            await log_gate_analysis(writer, r, 100.0)
        await asyncio.sleep(0.5)

    asyncio.run(_log())

    # 두 건 모두 DB에 기록됨
    count = conn.execute(
        "SELECT COUNT(*) as c FROM gate_analysis_log WHERE symbol IN ('ALPHA', 'BETA')"
    ).fetchone()["c"]
    result(
        "20c Both logged in DB",
        count == 2,
        f"count={count}",
    )

    writer.shutdown()
    writer_conn.close()


# ===========================================================
# Step 11: DB WAL 동시성
# ===========================================================

def test_21_wal_concurrency() -> None:
    """SQLite WAL 동시 읽기/쓰기."""
    write_conn = get_connection(_TEST_DB)
    read_conn = get_connection(_TEST_DB)

    writer = DatabaseWriter(write_conn)
    writer.start()

    # 쓰기
    writer.enqueue_sync(
        "INSERT INTO gate_analysis_log (timestamp, symbol, exchange, can_proceed, alert_level) "
        "VALUES (?, ?, ?, ?, ?)",
        (time.time(), "WAL_TEST", "bithumb", 1, "HIGH"),
    )
    time.sleep(0.5)

    # 동시 읽기
    row = read_conn.execute(
        "SELECT * FROM gate_analysis_log WHERE symbol='WAL_TEST'"
    ).fetchone()

    result(
        "21 WAL concurrent read/write",
        row is not None and row["symbol"] == "WAL_TEST",
    )

    writer.shutdown()
    read_conn.close()


# ===========================================================
# Step 12: Feature flag OFF → bot 미시작
# ===========================================================

def test_22_feature_flag_off() -> None:
    """Feature flag OFF → TelegramBot 미생성."""
    import yaml
    features_path = _ROOT / "config" / "features.yaml"
    with open(features_path, encoding="utf-8") as f:
        features = yaml.safe_load(f) or {}

    # telegram_interactive should be false by default
    result(
        "22 telegram_interactive default off",
        features.get("telegram_interactive") is False,
        f"value={features.get('telegram_interactive')}",
    )


# ===========================================================
# Step 13: GateInput 전체 기본값
# ===========================================================

def test_23_gate_default_values() -> None:
    """GateInput 전체 기본값 → gate 완료."""
    from analysis.gate import GateInput, GateChecker
    from analysis.cost_model import CostResult

    gate = GateChecker(
        premium=MagicMock(),
        cost_model=MagicMock(),
        writer=MagicMock(),
    )

    cost = CostResult(
        slippage_pct=0.0, gas_cost_krw=0, exchange_fee_pct=0.0,
        hedge_cost_pct=0.0, total_cost_pct=0.0, net_profit_pct=0.0,
        gas_warn=False,
    )

    gi = GateInput(
        symbol="DEFAULT", exchange="upbit", premium_pct=0.0,
        cost_result=cost, deposit_open=True, withdrawal_open=True,
        transfer_time_min=0.0, global_volume_usd=0.0,
        fx_source="btc_implied", hedge_type="none",
    )

    r = gate.check_hard_blockers(gi)
    result(
        "23 GateInput defaults",
        r is not None,
        f"can_proceed={r.can_proceed}, blockers={len(r.blockers)}, warnings={len(r.warnings)}",
    )
    # net_profit == 0 → blocker (수익성 부족)
    result(
        "23b Zero profit → blocker",
        not r.can_proceed and any("수익성" in b for b in r.blockers),
    )


# ===========================================================
# Step 14: Replay 67건 무크래시
# ===========================================================

def test_24_replay_no_crash() -> None:
    """67건 과거 상장 전부 크래시 없이 처리."""
    import csv
    from analysis.gate import GateInput, GateChecker
    from analysis.cost_model import CostResult

    csv_path = _ROOT / "data" / "labeling" / "listing_data.csv"
    result("24 listing_data.csv exists", csv_path.exists())

    if not csv_path.exists():
        return

    gate = GateChecker(
        premium=MagicMock(),
        cost_model=MagicMock(),
        writer=MagicMock(),
    )

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    result("24b CSV row count", len(rows) == 67, f"rows={len(rows)}")

    errors = 0
    for row in rows:
        try:
            symbol = row.get("symbol", "UNKNOWN")
            exchange = row.get("exchange", "bithumb").lower()
            premium = float(row.get("max_premium_pct", "") or "0")
            hedge = row.get("hedge_type", "none") or "none"
            withdrawal = row.get("withdrawal_open", "true").lower() in ("true", "1", "yes")
            transfer = float(row.get("network_speed_min", "") or "5")

            cost = CostResult(
                slippage_pct=0.3, gas_cost_krw=5000, exchange_fee_pct=0.25,
                hedge_cost_pct=0.0, total_cost_pct=0.55,
                net_profit_pct=premium - 0.55,
                gas_warn=False,
            )
            gi = GateInput(
                symbol=symbol, exchange=exchange, premium_pct=premium,
                cost_result=cost, deposit_open=True, withdrawal_open=withdrawal,
                transfer_time_min=transfer, global_volume_usd=100_000,
                fx_source="btc_implied", hedge_type=hedge,
            )
            gate.check_hard_blockers(gi)
        except Exception as e:
            errors += 1
            logger.error("Replay error: %s — %s", row.get("symbol"), e)

    result(
        "24c Replay 67 no crash",
        errors == 0,
        f"errors={errors}",
    )


# ===========================================================
# Step 15: Phase 3 회귀
# ===========================================================

def test_25_phase3_regression() -> None:
    """Phase 3 핵심 기능 회귀 테스트."""
    from analysis.gate import GateInput, GateChecker, AlertLevel
    from analysis.cost_model import CostResult

    gate = GateChecker(
        premium=MagicMock(),
        cost_model=MagicMock(),
        writer=MagicMock(),
    )

    # GO 케이스: 높은 프리미엄, 모든 조건 충족
    cost_go = CostResult(
        slippage_pct=0.3, gas_cost_krw=3000, exchange_fee_pct=0.25,
        hedge_cost_pct=0.15, total_cost_pct=0.7, net_profit_pct=4.3,
        gas_warn=False,
    )
    gi_go = GateInput(
        symbol="GOOD", exchange="upbit", premium_pct=5.0,
        cost_result=cost_go, deposit_open=True, withdrawal_open=True,
        transfer_time_min=3.0, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="cex",
        network="solana", top_exchange="binance",
    )
    r_go = gate.check_hard_blockers(gi_go)
    result("25 Phase3 GO", r_go.can_proceed and len(r_go.blockers) == 0)

    # NO-GO: 입금 차단
    gi_nogo = GateInput(
        symbol="BAD", exchange="upbit", premium_pct=5.0,
        cost_result=cost_go, deposit_open=False, withdrawal_open=True,
        transfer_time_min=3.0, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="cex",
    )
    r_nogo = gate.check_hard_blockers(gi_nogo)
    result("25b Phase3 deposit blocked", not r_nogo.can_proceed)

    # NO-GO: 출금 차단
    gi_wd = GateInput(
        symbol="BAD2", exchange="upbit", premium_pct=5.0,
        cost_result=cost_go, deposit_open=True, withdrawal_open=False,
        transfer_time_min=3.0, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="cex",
    )
    r_wd = gate.check_hard_blockers(gi_wd)
    result("25c Phase3 withdrawal blocked", not r_wd.can_proceed)

    # NO-GO: 수익성 부족
    cost_neg = CostResult(
        slippage_pct=0.3, gas_cost_krw=3000, exchange_fee_pct=0.25,
        hedge_cost_pct=0.15, total_cost_pct=3.0, net_profit_pct=-1.0,
        gas_warn=False,
    )
    gi_neg = GateInput(
        symbol="NEG", exchange="upbit", premium_pct=2.0,
        cost_result=cost_neg, deposit_open=True, withdrawal_open=True,
        transfer_time_min=3.0, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="cex",
    )
    r_neg = gate.check_hard_blockers(gi_neg)
    result("25d Phase3 negative profit", not r_neg.can_proceed)

    # NO-GO: 전송 시간 초과
    gi_slow = GateInput(
        symbol="SLOW", exchange="upbit", premium_pct=5.0,
        cost_result=cost_go, deposit_open=True, withdrawal_open=True,
        transfer_time_min=60.0, global_volume_usd=500_000,
        fx_source="btc_implied", hedge_type="cex",
    )
    r_slow = gate.check_hard_blockers(gi_slow)
    result("25e Phase3 transfer timeout", not r_slow.can_proceed)

    # WATCH_ONLY: hardcoded FX
    gi_fx = GateInput(
        symbol="FXTEST", exchange="upbit", premium_pct=5.0,
        cost_result=cost_go, deposit_open=True, withdrawal_open=True,
        transfer_time_min=3.0, global_volume_usd=500_000,
        fx_source="hardcoded_fallback", hedge_type="cex",
    )
    r_fx = gate.check_hard_blockers(gi_fx)
    result("25f Phase3 WATCH_ONLY", not r_fx.can_proceed)

    # Warning: 유동성 부족
    gi_low_vol = GateInput(
        symbol="LOWVOL", exchange="upbit", premium_pct=5.0,
        cost_result=cost_go, deposit_open=True, withdrawal_open=True,
        transfer_time_min=3.0, global_volume_usd=50_000,
        fx_source="btc_implied", hedge_type="cex",
    )
    r_low = gate.check_hard_blockers(gi_low_vol)
    result(
        "25g Phase3 low volume warning",
        r_low.can_proceed and any("유동성" in w for w in r_low.warnings),
    )

    # Alert level: CRITICAL (GO + trusted FX + actionable + no warnings)
    result(
        "25h Phase3 alert CRITICAL",
        r_go.alert_level == AlertLevel.CRITICAL,
        f"level={r_go.alert_level.value}",
    )


# ===========================================================
# Step 16: Telegram Bot 모듈 검증
# ===========================================================

def test_26_telegram_bot_module() -> None:
    """TelegramBot 명령어 핸들러 검증."""
    from alerts.telegram_bot import TelegramBot

    bot = TelegramBot(
        bot_token="test_token",
        chat_id="12345",
        read_conn=MagicMock(),
        gate_checker=MagicMock(),
        writer=MagicMock(),
    )

    # /help 명령
    help_text = bot._cmd_help()
    result(
        "26 Bot /help",
        "/status" in help_text and "/recent" in help_text and "/gate" in help_text,
    )

    # /status — health.json 없으면 미실행 메시지
    status_text = bot._cmd_status()
    result(
        "26b Bot /status (no health)",
        "미실행" in status_text or "상태" in status_text,
    )


# ===========================================================
# Main
# ===========================================================

def main() -> None:
    """모든 테스트 실행."""
    # 테스트 DB 초기화
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)

    # WAL 관련 파일도 정리
    for ext in ("-wal", "-shm"):
        p = _TEST_DB + ext
        if os.path.exists(p):
            os.remove(p)

    print(f"=== Phase 4 통합 테스트 ===\n")

    # Migration + 테이블 검증
    conn = test_01_migration_v3()

    # Observability
    test_04_log_gate_analysis(conn)
    test_05_log_gate_no_input(conn)

    # Health 판정
    test_06_health_green()
    test_07_health_red()
    test_08_health_yellow_stale()
    test_09_health_yellow_queue()
    test_10_health_yellow_drops()
    test_11_health_load_missing()
    test_12_health_load_broken()

    # Gate 열화 + VASP
    test_13_degradation_badges()
    test_14_vasp_badges()

    # 빈 테이블
    test_15_empty_table(conn)

    # Feature flags
    test_16_feature_flags()

    # Procfile
    test_17_procfile()

    # UI imports
    test_18_ui_imports()

    # 캐싱 TTL
    test_19_caching_ttl()

    # 동시 상장
    test_20_concurrent_listings(conn)

    # WAL 동시성
    test_21_wal_concurrency()

    # Feature flag off
    test_22_feature_flag_off()

    # GateInput defaults
    test_23_gate_default_values()

    # Replay 67건
    test_24_replay_no_crash()

    # Phase 3 회귀
    test_25_phase3_regression()

    # Telegram bot
    test_26_telegram_bot_module()

    # 정리
    conn.close()

    # 결과 요약
    total = _PASS + _FAIL
    print(f"\n{'=' * 50}")
    print(f"Phase 4 통합 테스트 결과: {_PASS}/{total} PASS")
    if _FAIL > 0:
        print(f"FAIL: {_FAIL}건")
        sys.exit(1)
    else:
        print("ALL PASS")


if __name__ == "__main__":
    main()
