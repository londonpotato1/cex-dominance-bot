"""SQLite WAL 연결 및 마이그레이션 관리."""

import hashlib
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# 프로젝트 루트 (cex_dominance_bot/)
_PROJECT_ROOT = Path(__file__).parent.parent

_DEFAULT_DB_PATH = str(_PROJECT_ROOT / "ddari.db")
_DEFAULT_MIGRATIONS_DIR = str(_PROJECT_ROOT / "migrations")


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """SQLite WAL 모드 연결 생성.

    Args:
        db_path: DB 파일 경로. None이면 환경변수 DATABASE_URL 또는 기본값 사용.

    Returns:
        설정 완료된 sqlite3.Connection.

    Raises:
        NotImplementedError: DATABASE_URL이 postgres로 시작하는 경우.
    """
    if db_path is None:
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url.startswith("postgres"):
            raise NotImplementedError(
                "PostgreSQL 미지원. Phase 1은 SQLite만 사용합니다."
            )
        db_path = db_url if db_url else _DEFAULT_DB_PATH

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA temp_store=MEMORY")

    logger.info("DB 연결 완료: %s (WAL 모드)", db_path)
    return conn


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    """schema_version 테이블이 없으면 생성."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version   INTEGER PRIMARY KEY,
            filename  TEXT NOT NULL,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            checksum  TEXT NOT NULL
        )
    """)
    conn.commit()


def _file_checksum(path: Path) -> str:
    """파일 MD5 체크섬 반환."""
    return hashlib.md5(path.read_bytes()).hexdigest()


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: str | None = None,
) -> int:
    """마이그레이션 파일들을 순서대로 적용.

    Args:
        conn: SQLite 연결.
        migrations_dir: 마이그레이션 디렉토리 경로.

    Returns:
        현재 스키마 버전 번호.

    Raises:
        FileNotFoundError: 마이그레이션 디렉토리가 없는 경우.
        RuntimeError: 마이그레이션 적용 실패 또는 체크섬 불일치.
    """
    if migrations_dir is None:
        migrations_dir = _DEFAULT_MIGRATIONS_DIR

    mig_path = Path(migrations_dir)
    if not mig_path.is_dir():
        raise FileNotFoundError(f"마이그레이션 디렉토리 없음: {mig_path}")

    _ensure_schema_version_table(conn)

    # 이미 적용된 버전 조회
    applied: dict[int, str] = {}
    for row in conn.execute("SELECT version, checksum FROM schema_version"):
        applied[row["version"]] = row["checksum"]

    # SQL 파일 정렬 순서로 처리
    sql_files = sorted(mig_path.glob("*.sql"))
    if not sql_files:
        logger.info("적용할 마이그레이션 없음")
        return 0

    current_version = 0

    for sql_file in sql_files:
        # 파일명에서 버전 번호 추출: 001_initial.sql → 1
        try:
            version = int(sql_file.stem.split("_")[0])
        except (ValueError, IndexError):
            logger.warning("파일명 형식 오류, 건너뜀: %s", sql_file.name)
            continue

        checksum = _file_checksum(sql_file)

        if version in applied:
            # 체크섬 검증
            if applied[version] != checksum:
                raise RuntimeError(
                    f"마이그레이션 변조 감지: {sql_file.name} "
                    f"(기존={applied[version]}, 현재={checksum})"
                )
            logger.debug("이미 적용됨, 건너뜀: %s", sql_file.name)
            current_version = max(current_version, version)
            continue

        # 마이그레이션 적용
        sql = sql_file.read_text(encoding="utf-8")
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version, filename, checksum) VALUES (?, ?, ?)",
                (version, sql_file.name, checksum),
            )
            conn.commit()
            current_version = max(current_version, version)
            logger.info("마이그레이션 적용 완료: %s (v%d)", sql_file.name, version)
        except Exception:
            logger.exception("마이그레이션 실패: %s", sql_file.name)
            raise RuntimeError(f"마이그레이션 실패: {sql_file.name}")

    logger.info("스키마 버전: %d", current_version)
    return current_version
