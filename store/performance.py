"""실전 수익 기록 모듈 (Phase 4.1).

GO 신호 발생 → 실제 수익 추적 → 봇 신뢰도 검증.

사용법:
    from store.performance import PerformanceTracker
    
    tracker = PerformanceTracker(writer, read_conn)
    
    # 거래 결과 기록
    await tracker.record_trade(
        symbol="PYTH",
        exchange="bithumb",
        signal_timestamp=1706688000,
        predicted_profit_pct=2.8,
        actual_profit_pct=3.1,
        result_label="WIN",
    )
    
    # 성과 통계 조회
    stats = tracker.get_stats(days=30)
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from store.writer import DatabaseWriter

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """거래 결과 레코드."""
    symbol: str
    exchange: str
    signal_timestamp: float
    
    # 예측
    predicted_profit_pct: Optional[float] = None
    predicted_premium_pct: Optional[float] = None
    
    # 실제 결과
    actual_profit_pct: Optional[float] = None
    entry_price_krw: Optional[float] = None
    exit_price_krw: Optional[float] = None
    entry_price_usd: Optional[float] = None
    exit_price_usd: Optional[float] = None
    
    # 거래 정보
    trade_amount_krw: Optional[float] = None
    actual_cost_pct: Optional[float] = None
    holding_minutes: Optional[int] = None
    
    # 메타
    signal_id: Optional[str] = None
    result_label: Optional[str] = None  # WIN, LOSS, BREAKEVEN, SKIP
    user_note: Optional[str] = None


@dataclass
class PerformanceStats:
    """성과 통계."""
    total_trades: int
    wins: int
    losses: int
    skips: int
    
    win_rate: float  # 승률 (%)
    avg_profit_pct: float  # 평균 수익률
    total_profit_pct: float  # 총 수익률
    
    avg_predicted_pct: float  # 평균 예측 수익률
    prediction_accuracy: float  # 예측 정확도 (%)
    
    best_trade_pct: float
    worst_trade_pct: float
    
    period_days: int


class PerformanceTracker:
    """실전 수익 추적기."""
    
    def __init__(
        self,
        writer: "DatabaseWriter",
        read_conn: sqlite3.Connection,
    ) -> None:
        self._writer = writer
        self._read_conn = read_conn
        self._read_conn.row_factory = sqlite3.Row
    
    async def record_trade(self, record: TradeRecord) -> bool:
        """거래 결과 기록.
        
        Args:
            record: TradeRecord 객체.
            
        Returns:
            성공 여부.
        """
        sql = """
        INSERT INTO trade_results (
            signal_id, symbol, exchange, signal_timestamp,
            predicted_profit_pct, predicted_premium_pct,
            actual_profit_pct, entry_price_krw, exit_price_krw,
            entry_price_usd, exit_price_usd,
            trade_amount_krw, actual_cost_pct, holding_minutes,
            result_label, user_note, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        params = (
            record.signal_id,
            record.symbol,
            record.exchange,
            record.signal_timestamp,
            record.predicted_profit_pct,
            record.predicted_premium_pct,
            record.actual_profit_pct,
            record.entry_price_krw,
            record.exit_price_krw,
            record.entry_price_usd,
            record.exit_price_usd,
            record.trade_amount_krw,
            record.actual_cost_pct,
            record.holding_minutes,
            record.result_label,
            record.user_note,
            time.time(),
        )
        
        try:
            self._writer.enqueue_sync(sql, params)
            logger.info(
                "[Performance] 거래 기록: %s@%s, %s, %.2f%%",
                record.symbol, record.exchange,
                record.result_label, record.actual_profit_pct or 0,
            )
            return True
        except Exception as e:
            logger.error("[Performance] 기록 실패: %s", e)
            return False
    
    def record_trade_sync(
        self,
        symbol: str,
        exchange: str,
        signal_timestamp: float,
        actual_profit_pct: float,
        result_label: str,
        predicted_profit_pct: Optional[float] = None,
        user_note: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """거래 결과 기록 (동기 버전, 간편 인터페이스)."""
        record = TradeRecord(
            symbol=symbol,
            exchange=exchange,
            signal_timestamp=signal_timestamp,
            predicted_profit_pct=predicted_profit_pct,
            actual_profit_pct=actual_profit_pct,
            result_label=result_label,
            user_note=user_note,
            **kwargs,
        )
        
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(self.record_trade(record))
    
    def get_stats(self, days: int = 30) -> PerformanceStats:
        """성과 통계 조회.
        
        Args:
            days: 조회 기간 (일).
            
        Returns:
            PerformanceStats 객체.
        """
        cutoff = time.time() - (days * 86400)
        
        try:
            row = self._read_conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN result_label = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN result_label = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    SUM(CASE WHEN result_label = 'SKIP' THEN 1 ELSE 0 END) as skips,
                    AVG(actual_profit_pct) as avg_profit,
                    SUM(actual_profit_pct) as total_profit,
                    AVG(predicted_profit_pct) as avg_predicted,
                    MAX(actual_profit_pct) as best,
                    MIN(actual_profit_pct) as worst
                FROM trade_results
                WHERE signal_timestamp > ?
                AND result_label IS NOT NULL
            """, (cutoff,)).fetchone()
            
            total = row["total"] or 0
            wins = row["wins"] or 0
            losses = row["losses"] or 0
            skips = row["skips"] or 0
            
            # 승률 계산 (SKIP 제외)
            actual_trades = wins + losses
            win_rate = (wins / actual_trades * 100) if actual_trades > 0 else 0
            
            # 예측 정확도 계산
            accuracy_row = self._read_conn.execute("""
                SELECT AVG(
                    CASE 
                        WHEN predicted_profit_pct IS NOT NULL 
                        AND actual_profit_pct IS NOT NULL 
                        THEN 100 - ABS(predicted_profit_pct - actual_profit_pct) * 10
                        ELSE NULL 
                    END
                ) as accuracy
                FROM trade_results
                WHERE signal_timestamp > ?
                AND result_label IN ('WIN', 'LOSS')
            """, (cutoff,)).fetchone()
            
            accuracy = max(0, min(100, accuracy_row["accuracy"] or 0))
            
            return PerformanceStats(
                total_trades=total,
                wins=wins,
                losses=losses,
                skips=skips,
                win_rate=round(win_rate, 1),
                avg_profit_pct=round(row["avg_profit"] or 0, 2),
                total_profit_pct=round(row["total_profit"] or 0, 2),
                avg_predicted_pct=round(row["avg_predicted"] or 0, 2),
                prediction_accuracy=round(accuracy, 1),
                best_trade_pct=round(row["best"] or 0, 2),
                worst_trade_pct=round(row["worst"] or 0, 2),
                period_days=days,
            )
            
        except sqlite3.OperationalError as e:
            logger.warning("[Performance] 통계 조회 실패: %s", e)
            return PerformanceStats(
                total_trades=0, wins=0, losses=0, skips=0,
                win_rate=0, avg_profit_pct=0, total_profit_pct=0,
                avg_predicted_pct=0, prediction_accuracy=0,
                best_trade_pct=0, worst_trade_pct=0,
                period_days=days,
            )
    
    def get_recent_trades(self, limit: int = 10) -> list[dict]:
        """최근 거래 목록 조회."""
        try:
            rows = self._read_conn.execute("""
                SELECT 
                    symbol, exchange, signal_timestamp,
                    predicted_profit_pct, actual_profit_pct,
                    result_label, user_note, recorded_at
                FROM trade_results
                ORDER BY recorded_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            
            return [dict(r) for r in rows]
            
        except sqlite3.OperationalError:
            return []
    
    def get_symbol_stats(self, symbol: str) -> dict:
        """특정 심볼의 통계."""
        try:
            row = self._read_conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN result_label = 'WIN' THEN 1 ELSE 0 END) as wins,
                    AVG(actual_profit_pct) as avg_profit,
                    SUM(actual_profit_pct) as total_profit
                FROM trade_results
                WHERE symbol = ?
                AND result_label IS NOT NULL
            """, (symbol,)).fetchone()
            
            return {
                "symbol": symbol,
                "total": row["total"] or 0,
                "wins": row["wins"] or 0,
                "win_rate": round((row["wins"] or 0) / max(1, row["total"] or 1) * 100, 1),
                "avg_profit": round(row["avg_profit"] or 0, 2),
                "total_profit": round(row["total_profit"] or 0, 2),
            }
            
        except sqlite3.OperationalError:
            return {"symbol": symbol, "total": 0}
