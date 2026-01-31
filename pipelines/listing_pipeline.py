"""상장 자동 분석 파이프라인.

상장 공지 감지 → GO/NO-GO 분석 → 텔레그램 알림 → 모니터링 시작
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class ListingEvent:
    """상장 이벤트."""
    symbol: str
    exchange: str
    listing_type: str  # TGE, 직상장, 옆상장
    listing_time: Optional[datetime] = None
    notice_url: Optional[str] = None
    detected_at: datetime = None
    
    def __post_init__(self):
        if self.detected_at is None:
            self.detected_at = datetime.now()


@dataclass
class PipelineResult:
    """파이프라인 실행 결과."""
    event: ListingEvent
    go_signal: str
    score: float
    dex_liquidity: Optional[float]
    spot_futures_gap: Optional[float]
    alert_sent: bool
    summary: str
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class ListingPipeline:
    """상장 자동 분석 파이프라인."""
    
    def __init__(
        self,
        on_result: Optional[Callable[[PipelineResult], Awaitable[None]]] = None,
    ):
        self.on_result = on_result
        self._processed_symbols: set[str] = set()
    
    async def process_listing(self, event: ListingEvent) -> PipelineResult:
        """상장 이벤트 처리.
        
        1. DEX 유동성 조회
        2. 현선갭 조회
        3. GO/NO-GO 분석
        4. 텔레그램 알림
        5. 결과 반환
        """
        logger.info(f"🚀 상장 파이프라인 시작: {event.symbol} @ {event.exchange}")
        
        # 중복 체크
        key = f"{event.symbol}_{event.exchange}"
        if key in self._processed_symbols:
            logger.info(f"이미 처리됨: {key}")
            return None
        self._processed_symbols.add(key)
        
        # 1. DEX 유동성 조회
        dex_liquidity = await self._fetch_dex_liquidity(event.symbol)
        
        # 2. 현선갭 조회
        spot_futures_gap, funding_rate = await self._fetch_gap(event.symbol)
        
        # 3. GO/NO-GO 분석
        go_result = await self._analyze_go_nogo(
            symbol=event.symbol,
            exchange=event.exchange,
            dex_liquidity=dex_liquidity,
            spot_futures_gap=spot_futures_gap,
            funding_rate=funding_rate,
        )
        
        # 4. 텔레그램 알림 (GO 신호일 때만)
        alert_sent = False
        if go_result["signal"] in ("STRONG_GO", "GO"):
            alert_sent = await self._send_alert(event, go_result, dex_liquidity, spot_futures_gap)
        
        # 5. 결과 생성
        result = PipelineResult(
            event=event,
            go_signal=go_result["signal"],
            score=go_result["score"],
            dex_liquidity=dex_liquidity,
            spot_futures_gap=spot_futures_gap,
            alert_sent=alert_sent,
            summary=go_result["summary"],
        )
        
        # 콜백 호출
        if self.on_result:
            await self.on_result(result)
        
        logger.info(f"✅ 파이프라인 완료: {event.symbol} → {go_result['signal']} ({go_result['score']:.0f}점)")
        
        return result
    
    async def _fetch_dex_liquidity(self, symbol: str) -> Optional[float]:
        """DEX 유동성 조회."""
        try:
            from collectors.dex_liquidity import get_dex_liquidity
            result = await get_dex_liquidity(symbol)
            if result:
                return result.total_liquidity_usd
        except Exception as e:
            logger.warning(f"DEX 유동성 조회 실패: {e}")
        return None
    
    async def _fetch_gap(self, symbol: str) -> tuple[Optional[float], Optional[float]]:
        """현선갭 조회."""
        try:
            from collectors.exchange_service import ExchangeService
            from collectors.gap_calculator import GapCalculator
            
            service = ExchangeService()
            prices = service.fetch_all_prices(
                symbol,
                ['binance', 'bybit', 'okx'],
                ['binance', 'bybit', 'okx']
            )
            gaps = GapCalculator.calculate_all_gaps(prices, symbol)
            
            if gaps:
                return gaps[0].gap_percent, gaps[0].funding_rate
        except Exception as e:
            logger.warning(f"현선갭 조회 실패: {e}")
        return None, None
    
    async def _analyze_go_nogo(
        self,
        symbol: str,
        exchange: str,
        dex_liquidity: Optional[float],
        spot_futures_gap: Optional[float],
        funding_rate: Optional[float],
    ) -> dict:
        """GO/NO-GO 분석."""
        try:
            from analysis.go_nogo_scorer import GoNoGoScorer
            
            scorer = GoNoGoScorer()
            result = await scorer.calculate_score(
                symbol=symbol,
                exchange=exchange,
                dex_liquidity_usd=dex_liquidity,
                spot_futures_gap_pct=spot_futures_gap,
                funding_rate=funding_rate,
            )
            
            return {
                "signal": result.signal.value,
                "score": result.total_score,
                "summary": result.summary,
            }
        except Exception as e:
            logger.error(f"GO/NO-GO 분석 실패: {e}")
            return {"signal": "UNKNOWN", "score": 0, "summary": f"분석 실패: {e}"}
    
    async def _send_alert(
        self,
        event: ListingEvent,
        go_result: dict,
        dex_liquidity: Optional[float],
        spot_futures_gap: Optional[float],
    ) -> bool:
        """텔레그램 알림 발송."""
        try:
            from alerts.telegram_notifier import send_go_alert
            
            return await send_go_alert(
                symbol=event.symbol,
                exchange=event.exchange,
                score=go_result["score"],
                signal=go_result["signal"],
                summary=go_result["summary"],
                dex_liquidity=dex_liquidity,
                spot_futures_gap=spot_futures_gap,
            )
        except Exception as e:
            logger.error(f"텔레그램 알림 실패: {e}")
            return False
    
    def clear_processed(self):
        """처리된 심볼 목록 초기화."""
        self._processed_symbols.clear()


# 싱글톤 인스턴스
pipeline = ListingPipeline()


# 편의 함수
async def process_new_listing(
    symbol: str,
    exchange: str,
    listing_type: str = "직상장",
    listing_time: Optional[datetime] = None,
) -> Optional[PipelineResult]:
    """새 상장 처리."""
    event = ListingEvent(
        symbol=symbol,
        exchange=exchange,
        listing_type=listing_type,
        listing_time=listing_time,
    )
    return await pipeline.process_listing(event)


# 테스트
if __name__ == "__main__":
    async def test():
        result = await process_new_listing(
            symbol="TESTCOIN",
            exchange="bithumb",
            listing_type="TGE",
        )
        
        if result:
            print(f"Signal: {result.go_signal}")
            print(f"Score: {result.score:.0f}")
            print(f"Alert sent: {result.alert_sent}")
            print(f"Summary: {result.summary}")
    
    asyncio.run(test())
