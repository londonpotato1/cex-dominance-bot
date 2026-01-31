#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
상장 데이터 자동 기록 모듈

기능:
- 상장 감지 시 CSV에 기본 정보 자동 기록
- 중복 체크 (symbol + exchange + date)
- 파일 잠금으로 동시성 처리

CSV 경로: data/labeling/listing_data.csv
"""

import asyncio
import csv
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import time

logger = logging.getLogger(__name__)

# CSV 컬럼 정의
CSV_COLUMNS = [
    "symbol",
    "exchange",
    "date",
    "listing_type",
    "market_cap_usd",
    "top_exchange",
    "top_exchange_tier",
    "deposit_krw",
    "volume_5m_krw",
    "volume_1m_krw",
    "turnover_ratio",
    "max_premium_pct",
    "premium_at_5m_pct",
    "supply_label",
    "hedge_type",
    "dex_liquidity_usd",
    "hot_wallet_usd",
    "network_chain",
    "network_speed_min",
    "withdrawal_open",
    "airdrop_claim_rate",
    "prev_listing_result",
    "market_condition",
    "result_label",
    "result_notes",
]

# 기본 CSV 경로
DEFAULT_CSV_PATH = Path(__file__).parent.parent / "data" / "labeling" / "listing_data.csv"


@dataclass
class ListingDataRecord:
    """상장 데이터 레코드"""
    # 필수 필드
    symbol: str
    exchange: str
    date: str  # YYYY-MM-DD
    listing_type: str  # TGE, 직상장, 옆상장
    
    # 자동 수집 가능 필드
    market_cap_usd: Optional[float] = None
    top_exchange: Optional[str] = None
    top_exchange_tier: Optional[str] = None
    dex_liquidity_usd: Optional[float] = None
    hot_wallet_usd: Optional[float] = None
    network_chain: Optional[str] = None
    network_speed_min: Optional[float] = None
    withdrawal_open: Optional[bool] = None
    supply_label: Optional[str] = None  # constrained, smooth
    hedge_type: Optional[str] = None  # none, cex_futures, dex_futures
    
    # 수동 입력 필드 (빈칸으로 둠)
    deposit_krw: Optional[float] = None
    volume_5m_krw: Optional[float] = None
    volume_1m_krw: Optional[float] = None
    turnover_ratio: Optional[float] = None
    max_premium_pct: Optional[float] = None
    premium_at_5m_pct: Optional[float] = None
    airdrop_claim_rate: Optional[float] = None
    prev_listing_result: Optional[str] = None
    market_condition: Optional[str] = None  # bull, bear, neutral
    result_label: Optional[str] = None  # 대흥따리, 흥따리, 보통, 망따리
    result_notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """CSV 기록용 딕셔너리 변환"""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "date": self.date,
            "listing_type": self.listing_type,
            "market_cap_usd": self.market_cap_usd if self.market_cap_usd else "",
            "top_exchange": self.top_exchange or "",
            "top_exchange_tier": self.top_exchange_tier or "",
            "deposit_krw": self.deposit_krw if self.deposit_krw else "",
            "volume_5m_krw": self.volume_5m_krw if self.volume_5m_krw else "",
            "volume_1m_krw": self.volume_1m_krw if self.volume_1m_krw else "",
            "turnover_ratio": self.turnover_ratio if self.turnover_ratio else "",
            "max_premium_pct": self.max_premium_pct if self.max_premium_pct else "",
            "premium_at_5m_pct": self.premium_at_5m_pct if self.premium_at_5m_pct else "",
            "supply_label": self.supply_label or "",
            "hedge_type": self.hedge_type or "",
            "dex_liquidity_usd": int(self.dex_liquidity_usd) if self.dex_liquidity_usd else "",
            "hot_wallet_usd": int(self.hot_wallet_usd) if self.hot_wallet_usd else "",
            "network_chain": self.network_chain or "",
            "network_speed_min": self.network_speed_min if self.network_speed_min else "",
            "withdrawal_open": str(self.withdrawal_open).lower() if self.withdrawal_open is not None else "",
            "airdrop_claim_rate": self.airdrop_claim_rate if self.airdrop_claim_rate else "",
            "prev_listing_result": self.prev_listing_result or "",
            "market_condition": self.market_condition or "",
            "result_label": self.result_label or "",
            "result_notes": self.result_notes or "",
        }


class ListingDataLogger:
    """상장 데이터 로거
    
    CSV 파일에 상장 데이터를 기록하고 중복을 관리합니다.
    """
    
    def __init__(self, csv_path: Optional[Path] = None):
        """
        Args:
            csv_path: CSV 파일 경로 (기본값: data/labeling/listing_data.csv)
        """
        self.csv_path = csv_path or DEFAULT_CSV_PATH
        self._ensure_csv_exists()
        self._lock = asyncio.Lock()
    
    def _ensure_csv_exists(self) -> None:
        """CSV 파일이 없으면 헤더와 함께 생성"""
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        
        if not self.csv_path.exists():
            with open(self.csv_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
            logger.info(f"CSV 파일 생성됨: {self.csv_path}")
    
    def _read_existing_records(self) -> List[Dict[str, str]]:
        """기존 레코드 읽기"""
        records = []
        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(row)
        except Exception as e:
            logger.error(f"CSV 읽기 실패: {e}")
        return records
    
    def _is_duplicate(self, symbol: str, exchange: str, date: str) -> bool:
        """중복 체크 (symbol + exchange + date)"""
        records = self._read_existing_records()
        
        for record in records:
            if (record.get("symbol", "").upper() == symbol.upper() and
                record.get("exchange", "").lower() == exchange.lower() and
                record.get("date", "") == date):
                return True
        return False
    
    async def log_listing(
        self,
        symbol: str,
        exchange: str,
        listing_type: str,
        analysis_result: Optional[Dict[str, Any]] = None,
        date: Optional[str] = None,
    ) -> bool:
        """상장 데이터 기록
        
        Args:
            symbol: 심볼 (예: BTC)
            exchange: 거래소 (예: Upbit, Bithumb)
            listing_type: 상장 유형 (TGE, 직상장, 옆상장)
            analysis_result: 분석 결과 딕셔너리
            date: 상장 날짜 (기본값: 오늘)
            
        Returns:
            bool: 기록 성공 여부
        """
        async with self._lock:
            return await self._log_listing_internal(
                symbol, exchange, listing_type, analysis_result, date
            )
    
    async def _log_listing_internal(
        self,
        symbol: str,
        exchange: str,
        listing_type: str,
        analysis_result: Optional[Dict[str, Any]] = None,
        date: Optional[str] = None,
    ) -> bool:
        """내부 기록 로직 (락 획득 후 호출)"""
        # 날짜 기본값
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        # 중복 체크
        if self._is_duplicate(symbol, exchange, date):
            logger.info(f"[ListingDataLogger] 중복 스킵: {symbol}/{exchange}/{date}")
            return False
        
        # 분석 결과에서 데이터 추출
        analysis = analysis_result or {}
        
        record = ListingDataRecord(
            symbol=symbol.upper(),
            exchange=exchange.capitalize(),
            date=date,
            listing_type=listing_type,
            # 분석 결과에서 추출
            market_cap_usd=analysis.get("market_cap_usd"),
            top_exchange=analysis.get("top_exchange"),
            dex_liquidity_usd=analysis.get("dex_liquidity_usd"),
            hot_wallet_usd=analysis.get("hot_wallet_usd"),
            network_chain=analysis.get("network_chain"),
            network_speed_min=analysis.get("network_speed_min"),
            withdrawal_open=analysis.get("withdrawal_open"),
            supply_label=analysis.get("supply_label"),
            hedge_type=analysis.get("hedge_type"),
        )
        
        # CSV에 기록 (retry 로직)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with open(self.csv_path, 'a', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                    writer.writerow(record.to_dict())
                
                logger.info(f"[ListingDataLogger] 기록 완료: {symbol}/{exchange}/{date}")
                return True
                
            except PermissionError:
                if attempt < max_retries - 1:
                    logger.warning(f"파일 잠금, 재시도 {attempt + 1}/{max_retries}")
                    await asyncio.sleep(0.5)
                else:
                    logger.error(f"CSV 기록 실패 (권한 오류): {symbol}")
                    return False
            except Exception as e:
                logger.error(f"CSV 기록 실패: {e}")
                return False
        
        return False
    
    def update_result(
        self,
        symbol: str,
        exchange: str,
        date: str,
        result_label: str,
        result_notes: Optional[str] = None,
        **kwargs
    ) -> bool:
        """결과 라벨 업데이트
        
        Args:
            symbol: 심볼
            exchange: 거래소
            date: 날짜
            result_label: 결과 라벨 (대흥따리, 흥따리, 보통, 망따리)
            result_notes: 결과 노트
            **kwargs: 추가 필드 업데이트
            
        Returns:
            bool: 업데이트 성공 여부
        """
        records = self._read_existing_records()
        updated = False
        
        for record in records:
            if (record.get("symbol", "").upper() == symbol.upper() and
                record.get("exchange", "").lower() == exchange.lower() and
                record.get("date", "") == date):
                
                record["result_label"] = result_label
                if result_notes:
                    record["result_notes"] = result_notes
                
                # 추가 필드 업데이트
                for key, value in kwargs.items():
                    if key in CSV_COLUMNS:
                        record[key] = str(value) if value is not None else ""
                
                updated = True
                break
        
        if updated:
            # 전체 파일 다시 쓰기
            try:
                with open(self.csv_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                    writer.writeheader()
                    writer.writerows(records)
                
                logger.info(f"[ListingDataLogger] 결과 업데이트: {symbol}/{exchange}/{date} → {result_label}")
                return True
            except Exception as e:
                logger.error(f"결과 업데이트 실패: {e}")
                return False
        else:
            logger.warning(f"[ListingDataLogger] 레코드 없음: {symbol}/{exchange}/{date}")
            return False
    
    def get_unlabeled_records(self) -> List[Dict[str, str]]:
        """라벨링 안 된 레코드 조회"""
        records = self._read_existing_records()
        return [r for r in records if not r.get("result_label")]
    
    def get_record(self, symbol: str, exchange: str, date: str) -> Optional[Dict[str, str]]:
        """특정 레코드 조회"""
        records = self._read_existing_records()
        
        for record in records:
            if (record.get("symbol", "").upper() == symbol.upper() and
                record.get("exchange", "").lower() == exchange.lower() and
                record.get("date", "") == date):
                return record
        return None


# =============================================================================
# 편의 함수
# =============================================================================

# 싱글톤 인스턴스
_logger_instance: Optional[ListingDataLogger] = None


def get_listing_data_logger() -> ListingDataLogger:
    """싱글톤 로거 인스턴스 반환"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = ListingDataLogger()
    return _logger_instance


async def log_listing_to_csv(
    symbol: str,
    exchange: str,
    listing_type: str,
    analysis_result: Optional[Dict[str, Any]] = None,
    date: Optional[str] = None,
) -> bool:
    """상장 감지 시 CSV에 기본 정보 자동 기록
    
    자동 수집 가능한 필드:
    - symbol, exchange, date (현재 시간)
    - listing_type (TGE/직상장 등)
    - dex_liquidity_usd (API에서)
    - network_chain, network_speed_min (API에서)
    - hedge_type (분석 결과에서)
    - market_cap_usd (가능하면)
    
    수동 입력 필요 (빈칸으로 둠):
    - deposit_krw, volume_5m_krw, volume_1m_krw
    - max_premium_pct, premium_at_5m_pct
    - result_label, result_notes
    
    Args:
        symbol: 심볼
        exchange: 거래소
        listing_type: 상장 유형
        analysis_result: 분석 결과 (StrategyRecommendation에서 추출)
        date: 상장 날짜
        
    Returns:
        bool: 기록 성공 여부
        
    Example:
        # 분석 결과를 딕셔너리로 변환
        analysis = {
            "dex_liquidity_usd": rec.dex_liquidity_usd,
            "hot_wallet_usd": rec.hot_wallet_krw / 1300 if rec.hot_wallet_krw else None,
            "network_chain": rec.network_speed,
            "hedge_type": "cex_futures" if rec.loan_available else "none",
            "supply_label": "smooth" if rec.dex_liquidity_usd and rec.dex_liquidity_usd > 500000 else "constrained",
        }
        await log_listing_to_csv("NEWCOIN", "Upbit", "TGE", analysis)
    """
    logger_instance = get_listing_data_logger()
    return await logger_instance.log_listing(
        symbol=symbol,
        exchange=exchange,
        listing_type=listing_type,
        analysis_result=analysis_result,
        date=date,
    )


def extract_analysis_for_csv(recommendation) -> Dict[str, Any]:
    """StrategyRecommendation에서 CSV 기록용 데이터 추출
    
    Args:
        recommendation: StrategyRecommendation 객체
        
    Returns:
        CSV 기록용 딕셔너리
    """
    # 헷지 유형 결정
    hedge_type = "none"
    if recommendation.loan_available:
        hedge_type = "cex_futures"
    elif recommendation.dex_liquidity_usd and recommendation.dex_liquidity_usd > 100000:
        hedge_type = "dex_futures"
    
    # 공급 라벨 결정
    supply_label = "smooth"
    if recommendation.dex_liquidity_usd:
        if recommendation.dex_liquidity_usd < 200000:
            supply_label = "constrained"
    else:
        supply_label = "constrained"  # 유동성 정보 없으면 constrained로 가정
    
    return {
        "market_cap_usd": None,  # 추가 API 필요
        "top_exchange": recommendation.best_loan_exchange,
        "dex_liquidity_usd": recommendation.dex_liquidity_usd,
        "hot_wallet_usd": recommendation.hot_wallet_krw / 1300 if recommendation.hot_wallet_krw else None,
        "network_chain": recommendation.network_speed,  # 실제로는 체인명이 필요
        "network_speed_min": None,  # 추가 파싱 필요
        "withdrawal_open": recommendation.loan_available,  # 론 가능하면 출금도 가능할 것으로 가정
        "supply_label": supply_label,
        "hedge_type": hedge_type,
    }


# =============================================================================
# CLI 라벨링 스크립트
# =============================================================================

def cli_label_listing():
    """CLI에서 결과 라벨링
    
    사용법: python -m collectors.listing_data_logger
    """
    import sys
    
    logger_instance = get_listing_data_logger()
    unlabeled = logger_instance.get_unlabeled_records()
    
    if not unlabeled:
        print("✅ 모든 레코드가 라벨링되었습니다.")
        return
    
    print(f"\n📋 라벨링 필요한 레코드: {len(unlabeled)}개\n")
    
    labels = ["대흥따리", "흥따리", "보통", "망따리"]
    
    for i, record in enumerate(unlabeled, 1):
        print(f"━" * 40)
        print(f"[{i}/{len(unlabeled)}] {record['symbol']} / {record['exchange']} / {record['date']}")
        print(f"상장 유형: {record['listing_type']}")
        print(f"DEX 유동성: {record.get('dex_liquidity_usd', 'N/A')}")
        print(f"헷지 유형: {record.get('hedge_type', 'N/A')}")
        print()
        
        print("결과 선택:")
        for j, label in enumerate(labels, 1):
            print(f"  {j}. {label}")
        print("  0. 스킵")
        print("  q. 종료")
        
        choice = input("\n선택: ").strip()
        
        if choice.lower() == 'q':
            print("종료합니다.")
            break
        
        if choice == '0':
            print("스킵합니다.\n")
            continue
        
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(labels):
                result_label = labels[idx]
                notes = input("노트 (엔터로 스킵): ").strip()
                
                # 추가 필드 업데이트 (선택적)
                deposit_krw = input("입금액(억, 엔터로 스킵): ").strip()
                volume_5m = input("5분 거래량(억, 엔터로 스킵): ").strip()
                max_premium = input("최대 김프%(엔터로 스킵): ").strip()
                
                kwargs = {}
                if deposit_krw:
                    kwargs['deposit_krw'] = float(deposit_krw) * 100000000
                if volume_5m:
                    kwargs['volume_5m_krw'] = float(volume_5m) * 100000000
                if max_premium:
                    kwargs['max_premium_pct'] = float(max_premium)
                
                success = logger_instance.update_result(
                    symbol=record['symbol'],
                    exchange=record['exchange'],
                    date=record['date'],
                    result_label=result_label,
                    result_notes=notes if notes else None,
                    **kwargs
                )
                
                if success:
                    print(f"✅ 저장됨: {result_label}\n")
                else:
                    print(f"❌ 저장 실패\n")
            else:
                print("잘못된 선택\n")
        except ValueError:
            print("잘못된 입력\n")


# =============================================================================
# 테스트
# =============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "label":
        # CLI 라벨링 모드
        cli_label_listing()
    else:
        # 테스트 모드
        async def test():
            print("=== ListingDataLogger 테스트 ===\n")
            
            # 테스트용 분석 결과
            analysis = {
                "dex_liquidity_usd": 150000,
                "hot_wallet_usd": 50000000,
                "network_chain": "Ethereum",
                "hedge_type": "cex_futures",
                "supply_label": "constrained",
            }
            
            # 기록 테스트
            success = await log_listing_to_csv(
                symbol="TESTCOIN",
                exchange="Upbit",
                listing_type="TGE",
                analysis_result=analysis,
            )
            
            print(f"기록 결과: {'성공' if success else '실패 (중복일 수 있음)'}")
            
            # 결과 업데이트 테스트
            logger_instance = get_listing_data_logger()
            logger_instance.update_result(
                symbol="TESTCOIN",
                exchange="Upbit",
                date=datetime.now().strftime("%Y-%m-%d"),
                result_label="테스트",
                result_notes="자동 테스트 데이터"
            )
            
            # 라벨 안 된 레코드 조회
            unlabeled = logger_instance.get_unlabeled_records()
            print(f"\n라벨링 필요 레코드: {len(unlabeled)}개")
        
        asyncio.run(test())
