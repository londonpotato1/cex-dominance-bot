"""Health 판정 + Streamlit 배너.

판정 규칙:
  RED:    heartbeat > 60초 (수집기 중단)
  YELLOW: upbit WS > 30초 stale | bithumb WS > 120초 stale
          | queue > 10K | drops > 0
  GREEN:  정상

health.json IPC 파일을 읽어서 판정.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Railway Volume 지원: HEALTH_PATH 환경변수 우선
_DEFAULT_HEALTH = Path(__file__).resolve().parent.parent / "health.json"
_HEALTH_PATH = Path(os.environ.get("HEALTH_PATH", str(_DEFAULT_HEALTH)))

# 판정 임계값
_HEARTBEAT_RED_SEC = 60.0
_UPBIT_STALE_SEC = 30.0
_BITHUMB_STALE_SEC = 120.0
_QUEUE_YELLOW = 10_000


def load_health(path: Path | str | None = None) -> Optional[dict]:
    """health.json 로드.

    Args:
        path: health.json 경로 (None이면 기본 경로).

    Returns:
        파싱된 dict 또는 None (파일 없음/깨진 JSON).
    """
    p = Path(path) if path else _HEALTH_PATH
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("health.json 파싱 실패: %s", e)
        return None


def evaluate_health(data: dict) -> tuple[str, list[str]]:
    """Health 판정.

    Args:
        data: health.json 파싱 결과.

    Returns:
        (status, issues) where status is "RED"/"YELLOW"/"GREEN".
    """
    issues: list[str] = []
    now = time.time()

    # RED: heartbeat > 60초
    heartbeat_ts = data.get("heartbeat_timestamp", 0)
    heartbeat_age = now - heartbeat_ts
    if heartbeat_age > _HEARTBEAT_RED_SEC:
        issues.append(f"수집기 중단: heartbeat {heartbeat_age:.0f}초 전")
        return "RED", issues

    # YELLOW 조건들
    last_msg = data.get("last_msg_time", {})

    # Upbit WS stale
    upbit_last = last_msg.get("upbit", 0) if isinstance(last_msg, dict) else 0
    if upbit_last > 0:
        upbit_age = now - upbit_last
        if upbit_age > _UPBIT_STALE_SEC:
            issues.append(f"Upbit WS 지연: {upbit_age:.0f}초")

    # Bithumb WS stale
    bithumb_last = last_msg.get("bithumb", 0) if isinstance(last_msg, dict) else 0
    if bithumb_last > 0:
        bithumb_age = now - bithumb_last
        if bithumb_age > _BITHUMB_STALE_SEC:
            issues.append(f"Bithumb WS 지연: {bithumb_age:.0f}초")

    # Queue overflow
    queue_size = data.get("queue_size", 0)
    if queue_size > _QUEUE_YELLOW:
        issues.append(f"큐 과부하: {queue_size:,}건")

    # Drops
    drops = data.get("queue_drops", 0)
    if drops > 0:
        issues.append(f"데이터 드롭 발생: {drops:,}건")

    if issues:
        return "YELLOW", issues

    return "GREEN", []


def render_health_banner(st_module) -> None:
    """Streamlit health 배너 렌더링.

    Args:
        st_module: streamlit 모듈 (import st).
    """
    data = load_health()

    if data is None:
        st_module.info("수집 데몬 미실행 (health.json 없음)")
        return

    status, issues = evaluate_health(data)

    if status == "RED":
        st_module.error(f"시스템 이상: {' | '.join(issues)}")
    elif status == "YELLOW":
        st_module.warning(f"주의: {' | '.join(issues)}")
    # GREEN → 배너 없음
