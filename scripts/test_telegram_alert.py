"""텔레그램 알림 테스트 스크립트.

사용법:
    python scripts/test_telegram_alert.py

환경변수 필요:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiohttp


async def test_telegram_direct():
    """텔레그램 직접 API 테스트."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    print("=" * 50)
    print("[TEST] Telegram Alert Test")
    print("=" * 50)
    
    # 1. 환경변수 확인
    print("\n[1] Check environment variables")
    if not bot_token:
        print("   [X] TELEGRAM_BOT_TOKEN not found")
        return False
    else:
        print(f"   [O] TELEGRAM_BOT_TOKEN: {bot_token[:10]}...{bot_token[-5:]}")
    
    if not chat_id:
        print("   [X] TELEGRAM_CHAT_ID not found")
        return False
    else:
        print(f"   [O] TELEGRAM_CHAT_ID: {chat_id}")
    
    # 2. 테스트 메시지 전송
    print("\n[2] Send test message")
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    test_message = """🧪 *CEX Dominance Bot 테스트 알림*

이 메시지가 보이면 텔레그램 알림이 정상 작동합니다!

테스트 시간: """ + time.strftime("%Y-%m-%d %H:%M:%S")
    
    payload = {
        "chat_id": chat_id,
        "text": test_message,
        "parse_mode": "Markdown",
    }
    
    start_time = time.time()
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                elapsed = time.time() - start_time
                
                if resp.status == 200:
                    print(f"   [O] Success! (took: {elapsed:.2f}s)")
                    data = await resp.json()
                    msg_id = data.get("result", {}).get("message_id")
                    print(f"   Message ID: {msg_id}")
                    return True
                else:
                    print(f"   [X] Failed: HTTP {resp.status}")
                    error = await resp.text()
                    print(f"   Error: {error[:200]}")
                    return False
                    
    except asyncio.TimeoutError:
        print("   [X] Timeout (>10s)")
        return False
    except Exception as e:
        print(f"   [X] Error: {e}")
        return False


async def test_go_alert_format():
    """GO 알림 포맷 테스트."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("\n[3] GO alert format test - SKIP (no env vars)")
        return
    
    print("\n[3] GO alert format test")
    
    # 실제 GO 알림처럼 생긴 테스트 메시지
    go_message = """🚀 *GO! 따리 기회 감지*

*NEWCOIN* @upbit → binance

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

🕐 감지 시간: """ + time.strftime("%H:%M:%S")
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": go_message,
        "parse_mode": "Markdown",
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    print("   [O] GO alert format sent!")
                else:
                    print(f"   [X] Failed: HTTP {resp.status}")
    except Exception as e:
        print(f"   [X] Error: {e}")


async def test_speed():
    """알림 속도 측정."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("\n[4] Speed test - SKIP (no env vars)")
        return
    
    print("\n[4] Speed test (5 rounds)")
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    times = []
    
    for i in range(5):
        payload = {
            "chat_id": chat_id,
            "text": f"Speed test {i+1}/5",
        }
        
        start = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    elapsed = time.time() - start
                    if resp.status == 200:
                        times.append(elapsed)
                        print(f"   [{i+1}] {elapsed:.3f}s")
                    else:
                        print(f"   [{i+1}] Failed")
        except Exception as e:
            print(f"   [{i+1}] Error: {e}")
        
        await asyncio.sleep(0.5)  # rate limit 방지
    
    if times:
        avg = sum(times) / len(times)
        print(f"\n   Avg response: {avg:.3f}s")
        print(f"   Min: {min(times):.3f}s / Max: {max(times):.3f}s")


async def main():
    """메인 테스트 실행."""
    print("\n" + "=" * 50)
    print("CEX Dominance Bot - Telegram Alert Test")
    print("=" * 50)
    
    # 1. 기본 연결 테스트
    success = await test_telegram_direct()
    
    if success:
        # 2. GO 알림 포맷 테스트
        await test_go_alert_format()
        
        # 3. 속도 측정
        await test_speed()
    
    print("\n" + "=" * 50)
    print("Test completed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
