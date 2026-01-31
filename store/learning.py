"""학습 데이터 관리 모듈 (Phase 4.1+ 데이터 플라이휠).

고수 복기 글, 과거 케이스 수집 → 모델 학습 데이터로 활용.

결과 라벨:
  - heung_big: 대흥따리 (+5% 이상)
  - heung: 흥따리 (+2~5%)
  - neutral: 보통 (0~2%)
  - mang: 망따리 (마이너스)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from store.writer import DatabaseWriter

logger = logging.getLogger(__name__)

# 결과 라벨 정의
RESULT_LABELS = {
    "heung_big": {"name": "대흥따리", "emoji": "🔥🔥", "min_profit": 5.0},
    "heung": {"name": "흥따리", "emoji": "🔥", "min_profit": 2.0},
    "neutral": {"name": "보통", "emoji": "😐", "min_profit": 0.0},
    "mang": {"name": "망따리", "emoji": "💀", "min_profit": -999},
}


def classify_result(profit_pct: float) -> str:
    """수익률로 결과 라벨 자동 분류."""
    if profit_pct >= 5.0:
        return "heung_big"
    elif profit_pct >= 2.0:
        return "heung"
    elif profit_pct >= 0.0:
        return "neutral"
    else:
        return "mang"


def get_label_info(label: str) -> dict:
    """라벨 정보 조회."""
    return RESULT_LABELS.get(label, {"name": label, "emoji": "❓"})


@dataclass
class LearningCase:
    """학습 케이스 데이터."""
    symbol: str
    result_label: str
    
    # 선택 필드
    exchange: Optional[str] = None
    listing_date: Optional[str] = None
    
    # 시장 데이터
    market_cap_usd: Optional[float] = None
    fdv_usd: Optional[float] = None
    circulating_ratio: Optional[float] = None
    
    # 토크노믹스
    total_supply: Optional[float] = None
    circulating_supply: Optional[float] = None
    unlock_schedule: Optional[str] = None
    
    # VC/MM
    vc_tier: Optional[str] = None
    vc_names: Optional[list[str]] = None
    mm_name: Optional[str] = None
    
    # 상장 유형
    listing_type: Optional[str] = None
    
    # 결과
    max_profit_pct: Optional[float] = None
    actual_profit_pct: Optional[float] = None
    
    # 복기 내용
    source: Optional[str] = None
    source_url: Optional[str] = None
    analysis_text: Optional[str] = None
    key_factors: Optional[list[str]] = None
    lessons_learned: Optional[str] = None


class LearningDataManager:
    """학습 데이터 관리자."""
    
    def __init__(
        self,
        writer: "DatabaseWriter",
        read_conn: sqlite3.Connection,
    ) -> None:
        self._writer = writer
        self._read_conn = read_conn
        self._read_conn.row_factory = sqlite3.Row
    
    def add_case(self, case: LearningCase) -> bool:
        """학습 케이스 추가."""
        sql = """
        INSERT INTO learning_cases (
            symbol, exchange, listing_date,
            market_cap_usd, fdv_usd, circulating_ratio,
            total_supply, circulating_supply, unlock_schedule,
            vc_tier, vc_names, mm_name,
            listing_type,
            result_label, max_profit_pct, actual_profit_pct,
            source, source_url, analysis_text, key_factors, lessons_learned,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        params = (
            case.symbol,
            case.exchange,
            case.listing_date,
            case.market_cap_usd,
            case.fdv_usd,
            case.circulating_ratio,
            case.total_supply,
            case.circulating_supply,
            case.unlock_schedule,
            case.vc_tier,
            json.dumps(case.vc_names) if case.vc_names else None,
            case.mm_name,
            case.listing_type,
            case.result_label,
            case.max_profit_pct,
            case.actual_profit_pct,
            case.source,
            case.source_url,
            case.analysis_text,
            json.dumps(case.key_factors) if case.key_factors else None,
            case.lessons_learned,
            time.time(),
        )
        
        try:
            self._writer.enqueue_sync(sql, params)
            logger.info(
                "[Learning] 케이스 추가: %s (%s)",
                case.symbol, case.result_label,
            )
            return True
        except Exception as e:
            logger.error("[Learning] 케이스 추가 실패: %s", e)
            return False
    
    def add_simple_case(
        self,
        symbol: str,
        result_label: str,
        profit_pct: Optional[float] = None,
        exchange: Optional[str] = None,
        listing_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """간단한 케이스 추가 (최소 정보)."""
        # 수익률로 라벨 자동 분류 (라벨 미지정 시)
        if profit_pct is not None and result_label == "auto":
            result_label = classify_result(profit_pct)
        
        case = LearningCase(
            symbol=symbol.upper(),
            result_label=result_label,
            exchange=exchange,
            listing_date=listing_date,
            actual_profit_pct=profit_pct,
            analysis_text=notes,
            source="manual",
        )
        
        return self.add_case(case)
    
    def get_cases_by_label(self, label: str, limit: int = 20) -> list[dict]:
        """라벨별 케이스 조회."""
        try:
            rows = self._read_conn.execute("""
                SELECT * FROM learning_cases
                WHERE result_label = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (label, limit)).fetchall()
            
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []
    
    def get_statistics(self) -> dict:
        """라벨별 통계 조회."""
        try:
            rows = self._read_conn.execute("""
                SELECT 
                    result_label,
                    COUNT(*) as count,
                    AVG(actual_profit_pct) as avg_profit
                FROM learning_cases
                WHERE result_label IS NOT NULL
                GROUP BY result_label
            """).fetchall()
            
            stats = {}
            for r in rows:
                label = r["result_label"]
                info = get_label_info(label)
                stats[label] = {
                    "name": info["name"],
                    "emoji": info["emoji"],
                    "count": r["count"],
                    "avg_profit": round(r["avg_profit"] or 0, 2),
                }
            
            return stats
        except sqlite3.OperationalError:
            return {}
    
    def get_pattern_insights(self) -> list[dict]:
        """패턴 인사이트 추출 (라벨별 공통점)."""
        insights = []
        
        try:
            # 대흥따리 패턴
            heung_big = self._read_conn.execute("""
                SELECT 
                    AVG(market_cap_usd) as avg_mc,
                    AVG(fdv_usd) as avg_fdv,
                    AVG(circulating_ratio) as avg_circ
                FROM learning_cases
                WHERE result_label = 'heung_big'
            """).fetchone()
            
            if heung_big and heung_big["avg_mc"]:
                insights.append({
                    "label": "heung_big",
                    "pattern": f"평균 MC ${heung_big['avg_mc']/1e6:.1f}M, 유통비율 {heung_big['avg_circ'] or 0:.1f}%",
                })
            
            # 망따리 패턴
            mang = self._read_conn.execute("""
                SELECT 
                    AVG(market_cap_usd) as avg_mc,
                    AVG(fdv_usd) as avg_fdv,
                    AVG(circulating_ratio) as avg_circ
                FROM learning_cases
                WHERE result_label = 'mang'
            """).fetchone()
            
            if mang and mang["avg_mc"]:
                insights.append({
                    "label": "mang",
                    "pattern": f"평균 MC ${mang['avg_mc']/1e6:.1f}M, 유통비율 {mang['avg_circ'] or 0:.1f}%",
                })
                
        except sqlite3.OperationalError:
            pass
        
        return insights
    
    def search_similar(self, symbol: str) -> list[dict]:
        """유사 케이스 검색 (같은 심볼 또는 비슷한 조건)."""
        try:
            rows = self._read_conn.execute("""
                SELECT * FROM learning_cases
                WHERE symbol = ?
                ORDER BY created_at DESC
                LIMIT 5
            """, (symbol.upper(),)).fetchall()
            
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []
