"""텔레그램 알림 서비스.

GO 신호, 상장 공지, 중요 이벤트 알림.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class TelegramConfig:
    """텔레그램 설정."""
    bot_token: str
    chat_id: str
    
    @classmethod
    def from_env(cls) -> Optional["TelegramConfig"]:
        """환경변수에서 설정 로드."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        
        if token and chat_id:
            return cls(bot_token=token, chat_id=chat_id)
        return None


class TelegramNotifier:
    """텔레그램 알림 발송기."""
    
    def __init__(self, config: Optional[TelegramConfig] = None):
        self.config = config or TelegramConfig.from_env()
        self._api_base = "https://api.telegram.org/bot"
    
    @property
    def is_configured(self) -> bool:
        """설정 완료 여부."""
        return self.config is not None
    
    async def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """메시지 발송.
        
        Args:
            text: 메시지 텍스트 (HTML 지원)
            parse_mode: 파싱 모드 (HTML, Markdown)
            disable_notification: 알림 음소거
        
        Returns:
            성공 여부
        """
        if not self.is_configured:
            logger.warning("텔레그램 설정 없음 (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")
            return False
        
        url = f"{self._api_base}{self.config.bot_token}/sendMessage"
        
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        logger.info(f"텔레그램 알림 전송 성공")
                        return True
                    else:
                        error = await resp.text()
                        logger.error(f"텔레그램 알림 실패: {error}")
                        return False
        except Exception as e:
            logger.error(f"텔레그램 알림 오류: {e}")
            return False
    
    async def send_go_alert(
        self,
        symbol: str,
        exchange: str,
        score: float,
        signal: str,
        summary: str,
        dex_liquidity: Optional[float] = None,
        spot_futures_gap: Optional[float] = None,
    ) -> bool:
        """GO 신호 알림."""
        emoji = "🟢🟢" if signal == "STRONG_GO" else "🟢"
        
        text = f"""
{emoji} <b>GO 신호 감지!</b>

<b>심볼:</b> {symbol}
<b>거래소:</b> {exchange.upper()}
<b>점수:</b> {score:.0f}/100
<b>신호:</b> {signal}

<b>요약:</b> {summary}
"""
        
        if dex_liquidity is not None:
            text += f"\n<b>DEX 유동성:</b> ${dex_liquidity:,.0f}"
        
        if spot_futures_gap is not None:
            text += f"\n<b>현선갭:</b> {spot_futures_gap:+.2f}%"
        
        text += f"\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return await self.send_message(text)
    
    async def send_listing_alert(
        self,
        symbol: str,
        exchange: str,
        listing_type: str,
        listing_time: Optional[str] = None,
    ) -> bool:
        """상장 공지 알림."""
        text = f"""
🚀 <b>신규 상장 감지!</b>

<b>심볼:</b> {symbol}
<b>거래소:</b> {exchange.upper()}
<b>유형:</b> {listing_type}
"""
        
        if listing_time:
            text += f"<b>상장 시간:</b> {listing_time}\n"
        
        text += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return await self.send_message(text)
    
    async def send_custom_alert(
        self,
        title: str,
        message: str,
        emoji: str = "📢",
    ) -> bool:
        """커스텀 알림."""
        text = f"""
{emoji} <b>{title}</b>

{message}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return await self.send_message(text)


# 싱글톤 인스턴스
notifier = TelegramNotifier()


# 편의 함수
async def send_go_alert(**kwargs) -> bool:
    """GO 알림 발송."""
    return await notifier.send_go_alert(**kwargs)


async def send_listing_alert(**kwargs) -> bool:
    """상장 알림 발송."""
    return await notifier.send_listing_alert(**kwargs)


async def send_alert(title: str, message: str, emoji: str = "📢") -> bool:
    """커스텀 알림 발송."""
    return await notifier.send_custom_alert(title, message, emoji)


# 테스트
if __name__ == "__main__":
    async def test():
        # 환경변수 설정 필요: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        success = await send_go_alert(
            symbol="TESTCOIN",
            exchange="bithumb",
            score=85,
            signal="STRONG_GO",
            summary="DEX 유동성 매우 적음, 느린 체인",
            dex_liquidity=150000,
            spot_futures_gap=8.5,
        )
        print(f"알림 전송: {'성공' if success else '실패'}")
    
    asyncio.run(test())
