"""Health 판정 + Streamlit 배너 + 텔레그램 테스트.

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
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
import asyncio

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
    logger.info(f"[Health] load_health() returned: {data is not None}, path: {_HEALTH_PATH}")

    if data is None:
        st_module.info(f"수집 데몬 미실행 (health.json 없음) - 경로: {_HEALTH_PATH}")
        return

    status, issues = evaluate_health(data)
    logger.info(f"[Health] status={status}, issues={issues}")

    if status == "RED":
        st_module.error(f"🔴 시스템 이상: {' | '.join(issues)}")
    elif status == "YELLOW":
        st_module.warning(f"🟡 주의: {' | '.join(issues)}")
    else:
        # GREEN → 정상 상태 표시
        st_module.success("🟢 수집 데몬 정상 작동 중")

    # 디버그: health.json 원본 데이터 표시
    with st_module.expander("🔧 Health 디버그 정보"):
        now = time.time()
        st_module.code(f"파일 경로: {_HEALTH_PATH}")
        st_module.code(f"현재 시각: {now:.0f}")

        if data:
            hb_ts = data.get("heartbeat_timestamp", 0)
            st_module.code(f"heartbeat: {hb_ts:.0f} (age: {now - hb_ts:.0f}초)")

            last_msg = data.get("last_msg_time", {})
            if isinstance(last_msg, dict):
                for ex, ts in last_msg.items():
                    age = now - ts if ts > 0 else "N/A"
                    st_module.code(f"{ex} last_msg: {ts:.0f} (age: {age}초)" if ts > 0 else f"{ex} last_msg: 0")

            st_module.json(data)

        # 텔레그램 알림 테스트
        st_module.markdown("---")
        st_module.markdown("**📱 텔레그램 알림 테스트**")
        
        col1, col2 = st_module.columns([1, 2])
        with col1:
            if st_module.button("🧪 테스트 알림 전송", key="test_telegram"):
                _send_test_telegram_alert(st_module)
        with col2:
            if st_module.button("🚀 GO 알림 테스트", key="test_go_alert"):
                _send_test_go_alert(st_module)
        
        # 로그 파일 표시
        st_module.markdown("---")
        st_module.markdown("**📋 데몬 로그 (최근 50줄)**")
        log_path = Path(os.environ.get("DATA_DIR", "/data")) / "daemon.log"
        try:
            if log_path.exists():
                with open(log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    recent_lines = lines[-50:] if len(lines) > 50 else lines
                    st_module.code("".join(recent_lines), language="log")
            else:
                st_module.info(f"로그 파일 없음: {log_path}")
        except Exception as e:
            st_module.error(f"로그 읽기 실패: {e}")


# ============================================================
# 텔레그램 알림 테스트 함수
# ============================================================

def _send_test_telegram_alert(st_module) -> None:
    """간단한 테스트 알림 전송."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        st_module.error("❌ 텔레그램 환경변수 미설정 (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")
        return
    
    async def _send():
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"""🧪 *CEX Dominance Bot 테스트 알림*

이 메시지가 보이면 텔레그램 알림이 정상 작동합니다!

⏱️ 테스트 시간: {now_str}"""
        
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }
        
        start = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    elapsed = time.time() - start
                    if resp.status == 200:
                        return True, f"✅ 전송 성공! (응답시간: {elapsed:.2f}초)"
                    else:
                        error = await resp.text()
                        return False, f"❌ 전송 실패: HTTP {resp.status}\n{error[:100]}"
        except asyncio.TimeoutError:
            return False, "❌ 타임아웃 (10초 초과)"
        except Exception as e:
            return False, f"❌ 에러: {e}"
    
    try:
        loop = asyncio.new_event_loop()
        success, msg = loop.run_until_complete(_send())
        loop.close()
        
        if success:
            st_module.success(msg)
        else:
            st_module.error(msg)
    except Exception as e:
        st_module.error(f"❌ 알림 전송 실패: {e}")


def _send_test_go_alert(st_module) -> None:
    """GO 알림 포맷 테스트."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        st_module.error("❌ 텔레그램 환경변수 미설정")
        return
    
    async def _send():
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        now_str = datetime.now().strftime("%H:%M:%S")
        
        # 실제 GO 알림 포맷 (바로가기 링크 포함)
        message = f"""🚀 *GO! 따리 기회 감지 (테스트)*

*TESTCOIN* @upbit → binance

📊 *분석 결과*
• 프리미엄: +8.5%
• 예상 비용: -1.2%
• *순수익: +7.3%*

⏱️ *전송 정보*
• 네트워크: Ethereum (ERC-20)
• 예상 시간: ~5분
• 가스비: $2.50

⚠️ *주의사항*
• 헤지: Binance 선물 가능
• VC: Tier 1 (a16z, Paradigm)
• TGE 언락: 5% (LOW 리스크)

👉 *바로가기*
• [업비트 입금](https://upbit.com/exchange?code=CRIX.UPBIT.KRW-BTC)
• [바이낸스 선물](https://www.binance.com/en/futures/BTCUSDT)
• [빗썸 입금](https://www.bithumb.com/trade/order/BTC_KRW)

🕐 감지 시간: {now_str}

_이것은 테스트 알림입니다_"""
        
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }
        
        start = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    elapsed = time.time() - start
                    if resp.status == 200:
                        return True, f"✅ GO 알림 전송 성공! (응답시간: {elapsed:.2f}초)"
                    else:
                        error = await resp.text()
                        return False, f"❌ 전송 실패: HTTP {resp.status}\n{error[:100]}"
        except asyncio.TimeoutError:
            return False, "❌ 타임아웃"
        except Exception as e:
            return False, f"❌ 에러: {e}"
    
    try:
        loop = asyncio.new_event_loop()
        success, msg = loop.run_until_complete(_send())
        loop.close()
        
        if success:
            st_module.success(msg)
        else:
            st_module.error(msg)
    except Exception as e:
        st_module.error(f"❌ GO 알림 전송 실패: {e}")
