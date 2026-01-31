#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
상장 공지 알림 핸들러

기능:
- 상장 공지 감지 시 자동으로 종합 분석 실행
- 텔레그램으로 전략 추천 알림 발송
- 실시간 갭 모니터링 시작

listing_monitor.py의 on_listing 콜백으로 사용
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Callable, Awaitable
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class GapMonitorSession:
    """갭 모니터링 세션"""
    symbol: str
    entry_gap: float
    entry_time: datetime
    exchange: str
    alert_levels: list = field(default_factory=lambda: [5, 10, 15, 20, 25, 30])
    alerted_levels: set = field(default_factory=set)
    is_active: bool = True


class ListingAlertHandler:
    """상장 알림 핸들러
    
    상장 공지 감지 → 분석 → 알림 → 갭 모니터링
    """
    
    def __init__(
        self,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        on_alert: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        """
        Args:
            telegram_bot_token: 텔레그램 봇 토큰
            telegram_chat_id: 알림 받을 채팅 ID
            on_alert: 알림 메시지 커스텀 핸들러
        """
        self._bot_token = telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self._chat_id = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self._on_alert = on_alert
        
        # 갭 모니터링 세션
        self._gap_monitors: Dict[str, GapMonitorSession] = {}
        self._monitor_task: Optional[asyncio.Task] = None
    
    async def handle_listing(self, notice) -> None:
        """상장 공지 감지 시 호출되는 핸들러
        
        Args:
            notice: ListingNotice 객체
        """
        from collectors.listing_monitor import ListingNotice
        
        if not isinstance(notice, ListingNotice):
            logger.warning(f"Invalid notice type: {type(notice)}")
            return
        
        logger.info(f"[ListingAlertHandler] 상장 감지: {notice.symbols} on {notice.exchange}")
        
        # 각 심볼에 대해 분석 실행
        for symbol in notice.symbols:
            await self._analyze_and_alert(symbol, notice)
    
    async def _analyze_and_alert(self, symbol: str, notice) -> None:
        """심볼 분석 및 알림 발송"""
        try:
            from collectors.listing_strategy import analyze_listing, format_strategy_recommendation
            from collectors.listing_data_logger import log_listing_to_csv, extract_analysis_for_csv
            
            # 종합 분석 실행
            recommendation = await analyze_listing(symbol)
            
            # 메시지 포맷
            message = self._format_alert_message(recommendation, notice)
            
            # 알림 발송
            await self._send_alert(message)
            
            # 헷지 전략인 경우 갭 모니터링 시작
            if recommendation.strategy_type.value == "hedge_gap_exit":
                await self._start_gap_monitoring(symbol, recommendation)
            
            # ============================================
            # CSV 자동 기록 (라벨링 데이터 수집)
            # ============================================
            try:
                # 상장 유형 결정 (notice에서 추론)
                listing_type = self._detect_listing_type(notice, symbol)
                
                # 분석 결과에서 CSV용 데이터 추출
                analysis_data = extract_analysis_for_csv(recommendation)
                
                # CSV에 기록 (중복 시 스킵됨)
                logged = await log_listing_to_csv(
                    symbol=symbol,
                    exchange=notice.exchange.capitalize(),
                    listing_type=listing_type,
                    analysis_result=analysis_data,
                )
                
                if logged:
                    logger.info(f"[ListingAlertHandler] CSV 기록 완료: {symbol}/{notice.exchange}")
                else:
                    logger.debug(f"[ListingAlertHandler] CSV 기록 스킵 (중복): {symbol}/{notice.exchange}")
                    
            except Exception as csv_err:
                logger.warning(f"[ListingAlertHandler] CSV 기록 실패 ({symbol}): {csv_err}")
                # CSV 기록 실패해도 알림은 이미 발송됨
            
        except Exception as e:
            logger.error(f"[ListingAlertHandler] 분석 실패 ({symbol}): {e}")
            # 에러 발생해도 기본 알림은 보냄
            await self._send_alert(f"🚀 신규 상장 감지: {symbol}\n분석 중 오류 발생: {e}")
    
    def _detect_listing_type(self, notice, symbol: str) -> str:
        """상장 유형 추론
        
        TGE: Token Generation Event - 최초 상장
        직상장: 기존 코인 신규 마켓 추가
        옆상장: 다른 거래소에 이미 상장된 코인
        """
        title_lower = notice.title.lower()
        
        # TGE 키워드 체크
        tge_keywords = ['tge', 'token generation', '신규 발행', '최초 상장', 'launchpad', 'launch']
        for kw in tge_keywords:
            if kw in title_lower:
                return "TGE"
        
        # 옆상장 키워드 (원화 마켓 추가 등)
        side_keywords = ['원화 마켓', 'krw 마켓', '마켓 추가', '페어 추가', '원화마켓']
        for kw in side_keywords:
            if kw in title_lower:
                return "옆상장"
        
        # 직상장 키워드
        direct_keywords = ['신규 상장', '거래 지원', '상장 안내']
        for kw in direct_keywords:
            if kw in title_lower:
                return "직상장"
        
        # 기본값
        return "직상장"
    
    def _format_alert_message(self, rec, notice) -> str:
        """알림 메시지 포맷"""
        from collectors.listing_strategy import format_strategy_recommendation
        
        # 기본 전략 추천 메시지
        base_message = format_strategy_recommendation(rec)
        
        # 상장 정보 추가
        listing_info = [
            "",
            "━" * 28,
            "📢 상장 정보",
            "━" * 28,
            f"거래소: {notice.exchange.upper()}",
            f"공지: {notice.title[:50]}...",
        ]
        
        if notice.listing_time:
            listing_info.append(f"상장 시간: {notice.listing_time}")
        
        listing_info.append(f"🔗 {notice.url}")
        
        return base_message + "\n".join(listing_info)
    
    async def _send_alert(self, message: str) -> None:
        """알림 발송"""
        # 커스텀 핸들러가 있으면 사용
        if self._on_alert:
            await self._on_alert(message)
            return
        
        # 텔레그램 발송
        if self._bot_token and self._chat_id:
            await self._send_telegram(message)
        else:
            # 콘솔 출력 (개발용)
            logger.info(f"[ALERT]\n{message}")
    
    async def _send_telegram(self, message: str) -> None:
        """텔레그램 메시지 발송"""
        import aiohttp
        
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status != 200:
                        logger.error(f"Telegram 발송 실패: {await resp.text()}")
        except Exception as e:
            logger.error(f"Telegram 발송 에러: {e}")
    
    # =========================================================================
    # 갭 모니터링
    # =========================================================================
    
    async def _start_gap_monitoring(self, symbol: str, rec) -> None:
        """갭 모니터링 시작"""
        entry_gap = rec.best_gap.gap_percent if rec.best_gap else 1.5
        exchange = rec.best_gap.exchange if rec.best_gap else "unknown"
        
        session = GapMonitorSession(
            symbol=symbol,
            entry_gap=entry_gap,
            entry_time=datetime.now(),
            exchange=exchange,
        )
        
        self._gap_monitors[symbol] = session
        
        logger.info(f"[GapMonitor] 모니터링 시작: {symbol} (진입 갭: {entry_gap:.1f}%)")
        
        await self._send_alert(
            f"📊 [{symbol}] 갭 모니터링 시작\n"
            f"진입 갭: {entry_gap:.1f}%\n"
            f"거래소: {exchange}\n"
            f"알림 레벨: 5%, 10%, 15%, 20%, 25%, 30%"
        )
        
        # 모니터링 태스크 시작 (이미 실행 중이 아니면)
        if not self._monitor_task or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._gap_monitor_loop())
    
    async def _gap_monitor_loop(self) -> None:
        """갭 모니터링 루프"""
        while self._gap_monitors:
            for symbol, session in list(self._gap_monitors.items()):
                if not session.is_active:
                    continue
                
                try:
                    await self._check_gap_alert(symbol, session)
                except Exception as e:
                    logger.error(f"[GapMonitor] 체크 에러 ({symbol}): {e}")
            
            await asyncio.sleep(30)  # 30초마다 체크
    
    async def _check_gap_alert(self, symbol: str, session: GapMonitorSession) -> None:
        """갭 알림 체크"""
        # 현재 갭 조회 (실제 구현 필요)
        current_gap = await self._get_current_gap(symbol)
        
        if current_gap is None:
            return
        
        for level in session.alert_levels:
            if level in session.alerted_levels:
                continue
            
            if current_gap >= level:
                profit = current_gap - session.entry_gap
                
                await self._send_gap_alert(symbol, level, current_gap, profit, session)
                session.alerted_levels.add(level)
    
    async def _get_current_gap(self, symbol: str) -> Optional[float]:
        """현재 갭 조회"""
        try:
            from collectors.exchange_service import ExchangeService, MarketType
            from collectors.gap_calculator import GapCalculator
            
            # 거래소 서비스로 가격 조회
            service = ExchangeService()
            
            # Binance 현물/선물 가격 조회 시도
            exchanges = ["binance", "bybit"]
            
            for exchange in exchanges:
                try:
                    spot_price = await service.get_price_async(
                        exchange, f"{symbol}USDT", MarketType.SPOT
                    )
                    futures_price = await service.get_price_async(
                        exchange, f"{symbol}USDT", MarketType.FUTURES
                    )
                    
                    if spot_price and futures_price:
                        gap_result = GapCalculator.calculate(
                            spot_price=spot_price.price,
                            futures_price=futures_price.price,
                            spot_exchange=exchange,
                            futures_exchange=exchange,
                            symbol=symbol
                        )
                        
                        if gap_result:
                            return gap_result.gap_percent
                except Exception as e:
                    logger.debug(f"Gap check failed for {exchange}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Gap 조회 실패: {e}")
            return None
    
    async def _send_gap_alert(
        self, 
        symbol: str, 
        level: int, 
        current_gap: float, 
        profit: float,
        session: GapMonitorSession
    ) -> None:
        """갭 알림 발송"""
        
        action_map = {
            5: "모니터링 계속",
            10: "1/3 익절 고려",
            15: "절반 익절 고려",
            20: "2/3 익절 강력 추천",
            25: "대부분 익절 추천",
            30: "전량 익절 강력 추천!",
        }
        
        emoji_map = {
            5: "📊",
            10: "📈",
            15: "🔥",
            20: "💰",
            25: "🚀",
            30: "🎯",
        }
        
        message = f"""
{emoji_map.get(level, '📊')} [{symbol}] 현선갭 {level}% 돌파!

진입: {session.entry_gap:.1f}% → 현재: {current_gap:.1f}%
예상 수익: +{profit:.1f}%

💡 {action_map.get(level, '')}
   - 현물 매도
   - 선물 숏 청산
"""
        
        await self._send_alert(message.strip())
    
    def stop_gap_monitor(self, symbol: str) -> None:
        """갭 모니터링 중지"""
        if symbol in self._gap_monitors:
            self._gap_monitors[symbol].is_active = False
            del self._gap_monitors[symbol]
            logger.info(f"[GapMonitor] 모니터링 중지: {symbol}")
    
    def get_active_monitors(self) -> Dict[str, GapMonitorSession]:
        """활성 모니터링 세션 조회"""
        return {k: v for k, v in self._gap_monitors.items() if v.is_active}


# =============================================================================
# 편의 함수
# =============================================================================

def create_listing_handler(
    telegram_bot_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
) -> ListingAlertHandler:
    """상장 알림 핸들러 생성
    
    Example:
        handler = create_listing_handler()
        monitor = ListingMonitor(on_listing=handler.handle_listing)
    """
    return ListingAlertHandler(
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )


# =============================================================================
# 테스트
# =============================================================================

if __name__ == "__main__":
    async def test():
        from collectors.listing_monitor import ListingNotice
        
        # 테스트용 공지 생성
        notice = ListingNotice(
            notice_id="test123",
            title="[마켓 추가] TESTCOIN(TST) 원화 마켓 추가",
            url="https://example.com/notice",
            exchange="upbit",
            symbols=["TST"],
            listing_time="2026-02-01 14:00:00",
        )
        
        # 핸들러 생성 (콘솔 출력 모드)
        handler = ListingAlertHandler()
        
        # 핸들러 테스트
        await handler.handle_listing(notice)
    
    asyncio.run(test())
