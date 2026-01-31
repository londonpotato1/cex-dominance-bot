"""scripts 폴더 테스트용 pytest fixtures."""

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from store.database import get_connection, apply_migrations
from store.writer import DatabaseWriter


_TEST_DB_PHASE2 = str(_ROOT / "test_phase2.db")
_TEST_DB_PHASE4 = str(_ROOT / "test_phase4.db")


@pytest.fixture(scope="module")
def conn_phase2() -> sqlite3.Connection:
    """Phase2 테스트용 DB 연결."""
    conn = get_connection(_TEST_DB_PHASE2)
    apply_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def conn_phase4() -> sqlite3.Connection:
    """Phase4 테스트용 DB 연결."""
    conn = get_connection(_TEST_DB_PHASE4)
    apply_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def conn(request) -> sqlite3.Connection:
    """테스트 파일에 따라 적절한 conn 반환."""
    test_file = request.fspath.basename
    if "phase2" in test_file:
        db_path = _TEST_DB_PHASE2
    elif "phase4" in test_file:
        db_path = _TEST_DB_PHASE4
    else:
        db_path = str(_ROOT / "test_default.db")
    
    conn = get_connection(db_path)
    apply_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def writer(conn) -> DatabaseWriter:
    """DatabaseWriter fixture."""
    writer_conn = get_connection(conn.execute("PRAGMA database_list").fetchone()[2])
    w = DatabaseWriter(writer_conn)
    w.start()
    yield w
    w.shutdown()


@pytest.fixture
def symbol() -> str:
    """테스트용 심볼."""
    return "BTC"


@pytest.fixture
def exchange() -> str:
    """테스트용 거래소."""
    return "upbit"
