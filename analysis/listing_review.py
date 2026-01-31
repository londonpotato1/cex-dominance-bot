"""상장 복기 자동화 모듈 (Phase 8 Week 4).

상장 후 데이터를 자동 수집하고 흥/망 판정.

흥/망 판정 기준 (DDARI_FUNDAMENTALS.md 기준):
- 손바뀜 비율 = 거래량 / 입금액
- 5배 이상 → 대흥따리
- 3배 이상 → 흥따리 
- 1~3배 → 보통
- 1배 이하 → 망따리

수집 데이터:
- 5분 거래량 (volume_5m_krw)
- 1분 거래량 (volume_1m_krw)
- 최고 프리미엄 (max_premium_pct)
- 입금액 추정 (deposit_krw)
- 시총 상승분 (market_cap_change_pct)
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# CSV 파일 경로
LISTING_DATA_PATH = Path(__file__).parent.parent / "data" / "labeling" / "listing_data.csv"


class ResultLabel(Enum):
    """상장 결과 라벨."""
    MEGA_SUCCESS = "대흥따리"      # 손바뀜 5배+
    SUCCESS = "흥따리"             # 손바뀜 3~5배
    NORMAL = "보통"                # 손바뀜 1~3배
    FAIL = "망따리"                # 손바뀜 1배 이하


@dataclass
class ListingReviewData:
    """상장 복기 데이터."""
    # 기본 정보
    symbol: str
    exchange: str
    date: str  # YYYY-MM-DD
    listing_type: str  # TGE, 직상장, 옆상장
    
    # 시장 데이터
    market_cap_usd: Optional[float] = None
    top_exchange: Optional[str] = None
    top_exchange_tier: Optional[str] = None
    
    # 핵심 지표
    deposit_krw: Optional[float] = None           # 입금액 (원)
    volume_5m_krw: Optional[float] = None         # 5분 거래량 (원)
    volume_1m_krw: Optional[float] = None         # 1분 거래량 (원)
    turnover_ratio: Optional[float] = None        # 손바뀜 비율
    max_premium_pct: Optional[float] = None       # 최고 프리미엄 (%)
    premium_at_5m_pct: Optional[float] = None     # 5분 시점 프리미엄 (%)
    
    # 공급 분석
    supply_label: Optional[str] = None            # constrained, smooth
    hedge_type: Optional[str] = None              # cex_futures, dex_futures, none
    dex_liquidity_usd: Optional[float] = None
    hot_wallet_usd: Optional[float] = None
    network_chain: Optional[str] = None
    network_speed_min: Optional[float] = None
    withdrawal_open: Optional[bool] = None
    airdrop_claim_rate: Optional[float] = None
    
    # 시황
    prev_listing_result: Optional[str] = None
    market_condition: Optional[str] = None        # bull, bear, neutral
    
    # 결과
    result_label: Optional[str] = None
    result_notes: Optional[str] = None


class ListingResultClassifier:
    """흥/망 판정 분류기.
    
    손바뀜 비율 기반 자동 분류:
    - 손바뀜 비율 = 거래량 / 입금액
    - 5배 이상 → 대흥따리
    - 3배 이상 → 흥따리
    - 1~3배 → 보통
    - 1배 이하 → 망따리
    """
    
    # 손바뀜 비율 기준
    MEGA_SUCCESS_THRESHOLD = 5.0   # 5배 이상: 대흥따리
    SUCCESS_THRESHOLD = 3.0        # 3배 이상: 흥따리
    NORMAL_THRESHOLD = 1.0         # 1배 이상: 보통
    # 1배 미만: 망따리
    
    def classify(
        self,
        volume_krw: float,
        deposit_krw: float,
        max_premium_pct: Optional[float] = None,
    ) -> tuple[ResultLabel, float, str]:
        """흥/망 판정.
        
        Args:
            volume_krw: 5분 거래량 (원)
            deposit_krw: 입금액 추정 (원)
            max_premium_pct: 최고 프리미엄 (%) - 보조 지표
            
        Returns:
            (ResultLabel, turnover_ratio, reason)
        """
        if deposit_krw <= 0:
            logger.warning("입금액이 0 이하입니다. 분류 불가.")
            return ResultLabel.NORMAL, 0.0, "입금액 데이터 없음"
        
        # 손바뀜 비율 계산
        turnover_ratio = volume_krw / deposit_krw
        
        # 기본 분류
        if turnover_ratio >= self.MEGA_SUCCESS_THRESHOLD:
            label = ResultLabel.MEGA_SUCCESS
            reason = f"손바뀜 {turnover_ratio:.1f}배 (5배+)"
        elif turnover_ratio >= self.SUCCESS_THRESHOLD:
            label = ResultLabel.SUCCESS
            reason = f"손바뀜 {turnover_ratio:.1f}배 (3~5배)"
        elif turnover_ratio >= self.NORMAL_THRESHOLD:
            label = ResultLabel.NORMAL
            reason = f"손바뀜 {turnover_ratio:.1f}배 (1~3배)"
        else:
            label = ResultLabel.FAIL
            reason = f"손바뀜 {turnover_ratio:.1f}배 (1배 미만)"
        
        # 프리미엄 보조 지표 반영
        if max_premium_pct is not None:
            if max_premium_pct >= 100 and label != ResultLabel.MEGA_SUCCESS:
                # 김프 100%+ 인데 대흥따리 아닌 경우 → 업그레이드 고려
                reason += f", 최고김프 {max_premium_pct:.0f}%"
            elif max_premium_pct <= 0 and label not in (ResultLabel.FAIL, ResultLabel.NORMAL):
                # 역프인데 흥따리인 경우 → 다운그레이드 고려
                reason += f", ⚠️ 역프 발생"
        
        return label, turnover_ratio, reason
    
    def classify_from_data(self, data: ListingReviewData) -> tuple[ResultLabel, str]:
        """ListingReviewData로부터 분류.
        
        Returns:
            (ResultLabel, reason)
        """
        if data.volume_5m_krw is None or data.deposit_krw is None:
            return ResultLabel.NORMAL, "데이터 부족"
        
        label, turnover_ratio, reason = self.classify(
            volume_krw=data.volume_5m_krw,
            deposit_krw=data.deposit_krw,
            max_premium_pct=data.max_premium_pct,
        )
        
        # turnover_ratio 업데이트
        data.turnover_ratio = turnover_ratio
        
        return label, reason


class ListingDataStore:
    """listing_data.csv 관리."""
    
    # CSV 컬럼 순서 (기존 형식 유지)
    COLUMNS = [
        "symbol", "exchange", "date", "listing_type",
        "market_cap_usd", "top_exchange", "top_exchange_tier",
        "deposit_krw", "volume_5m_krw", "volume_1m_krw",
        "turnover_ratio", "max_premium_pct", "premium_at_5m_pct",
        "supply_label", "hedge_type", "dex_liquidity_usd", "hot_wallet_usd",
        "network_chain", "network_speed_min", "withdrawal_open",
        "airdrop_claim_rate", "prev_listing_result", "market_condition",
        "result_label", "result_notes",
    ]
    
    def __init__(self, csv_path: Path = LISTING_DATA_PATH) -> None:
        self.csv_path = csv_path
    
    def load_all(self) -> list[ListingReviewData]:
        """모든 데이터 로드."""
        if not self.csv_path.exists():
            logger.warning(f"CSV 파일 없음: {self.csv_path}")
            return []
        
        results = []
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                data = self._row_to_data(row)
                results.append(data)
        
        logger.info(f"로드 완료: {len(results)}건")
        return results
    
    def find(self, symbol: str, exchange: str, date: Optional[str] = None) -> Optional[ListingReviewData]:
        """특정 상장 데이터 찾기."""
        all_data = self.load_all()
        for data in all_data:
            if data.symbol == symbol and data.exchange == exchange:
                if date is None or data.date == date:
                    return data
        return None
    
    def save(self, data: ListingReviewData, update_existing: bool = True) -> bool:
        """데이터 저장 (추가 또는 업데이트).
        
        Args:
            data: 저장할 데이터
            update_existing: True면 기존 데이터 업데이트, False면 중복 무시
            
        Returns:
            저장 성공 여부
        """
        all_data = self.load_all()
        
        # 기존 데이터 찾기
        existing_idx = None
        for i, existing in enumerate(all_data):
            if (existing.symbol == data.symbol and 
                existing.exchange == data.exchange and
                (existing.date == data.date or not existing.date or not data.date)):
                existing_idx = i
                break
        
        if existing_idx is not None:
            if update_existing:
                all_data[existing_idx] = data
                logger.info(f"업데이트: {data.symbol}@{data.exchange}")
            else:
                logger.info(f"중복 스킵: {data.symbol}@{data.exchange}")
                return False
        else:
            all_data.append(data)
            logger.info(f"추가: {data.symbol}@{data.exchange}")
        
        # CSV 저장
        self._save_all(all_data)
        return True
    
    def _save_all(self, all_data: list[ListingReviewData]) -> None:
        """전체 데이터 CSV 저장."""
        # 부모 디렉토리 생성
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.COLUMNS)
            writer.writeheader()
            for data in all_data:
                row = self._data_to_row(data)
                writer.writerow(row)
        
        logger.info(f"저장 완료: {len(all_data)}건 → {self.csv_path}")
    
    def _row_to_data(self, row: dict) -> ListingReviewData:
        """CSV row → ListingReviewData."""
        return ListingReviewData(
            symbol=row.get("symbol", ""),
            exchange=row.get("exchange", ""),
            date=row.get("date", ""),
            listing_type=row.get("listing_type", ""),
            market_cap_usd=self._parse_float(row.get("market_cap_usd")),
            top_exchange=row.get("top_exchange") or None,
            top_exchange_tier=row.get("top_exchange_tier") or None,
            deposit_krw=self._parse_float(row.get("deposit_krw")),
            volume_5m_krw=self._parse_float(row.get("volume_5m_krw")),
            volume_1m_krw=self._parse_float(row.get("volume_1m_krw")),
            turnover_ratio=self._parse_float(row.get("turnover_ratio")),
            max_premium_pct=self._parse_float(row.get("max_premium_pct")),
            premium_at_5m_pct=self._parse_float(row.get("premium_at_5m_pct")),
            supply_label=row.get("supply_label") or None,
            hedge_type=row.get("hedge_type") or None,
            dex_liquidity_usd=self._parse_float(row.get("dex_liquidity_usd")),
            hot_wallet_usd=self._parse_float(row.get("hot_wallet_usd")),
            network_chain=row.get("network_chain") or None,
            network_speed_min=self._parse_float(row.get("network_speed_min")),
            withdrawal_open=self._parse_bool(row.get("withdrawal_open")),
            airdrop_claim_rate=self._parse_float(row.get("airdrop_claim_rate")),
            prev_listing_result=row.get("prev_listing_result") or None,
            market_condition=row.get("market_condition") or None,
            result_label=row.get("result_label") or None,
            result_notes=row.get("result_notes") or None,
        )
    
    def _data_to_row(self, data: ListingReviewData) -> dict:
        """ListingReviewData → CSV row."""
        return {
            "symbol": data.symbol,
            "exchange": data.exchange,
            "date": data.date or "",
            "listing_type": data.listing_type or "",
            "market_cap_usd": self._format_number(data.market_cap_usd),
            "top_exchange": data.top_exchange or "",
            "top_exchange_tier": data.top_exchange_tier or "",
            "deposit_krw": self._format_number(data.deposit_krw),
            "volume_5m_krw": self._format_number(data.volume_5m_krw),
            "volume_1m_krw": self._format_number(data.volume_1m_krw),
            "turnover_ratio": self._format_number(data.turnover_ratio, decimals=2),
            "max_premium_pct": self._format_number(data.max_premium_pct),
            "premium_at_5m_pct": self._format_number(data.premium_at_5m_pct),
            "supply_label": data.supply_label or "",
            "hedge_type": data.hedge_type or "",
            "dex_liquidity_usd": self._format_number(data.dex_liquidity_usd),
            "hot_wallet_usd": self._format_number(data.hot_wallet_usd),
            "network_chain": data.network_chain or "",
            "network_speed_min": self._format_number(data.network_speed_min),
            "withdrawal_open": str(data.withdrawal_open).lower() if data.withdrawal_open is not None else "",
            "airdrop_claim_rate": self._format_number(data.airdrop_claim_rate),
            "prev_listing_result": data.prev_listing_result or "",
            "market_condition": data.market_condition or "",
            "result_label": data.result_label or "",
            "result_notes": data.result_notes or "",
        }
    
    @staticmethod
    def _parse_float(value: Optional[str]) -> Optional[float]:
        """문자열 → float."""
        if value is None or value == "":
            return None
        try:
            return float(value)
        except ValueError:
            return None
    
    @staticmethod
    def _parse_bool(value: Optional[str]) -> Optional[bool]:
        """문자열 → bool."""
        if value is None or value == "":
            return None
        return value.lower() == "true"
    
    @staticmethod
    def _format_number(value: Optional[float], decimals: int = 0) -> str:
        """숫자 포맷팅."""
        if value is None:
            return ""
        if decimals == 0:
            return str(int(value))
        return f"{value:.{decimals}f}"


class ListingReviewCollector:
    """상장 후 데이터 자동 수집기.
    
    거래소 API를 통해 상장 후 데이터를 수집하고
    자동으로 흥/망 판정.
    """
    
    def __init__(self) -> None:
        self.classifier = ListingResultClassifier()
        self.store = ListingDataStore()
    
    def collect_and_classify(
        self,
        symbol: str,
        exchange: str,
        deposit_krw: float,
        volume_5m_krw: float,
        volume_1m_krw: Optional[float] = None,
        max_premium_pct: Optional[float] = None,
        premium_at_5m_pct: Optional[float] = None,
        market_cap_usd: Optional[float] = None,
        listing_type: str = "TGE",
        date: Optional[str] = None,
        notes: Optional[str] = None,
        **kwargs,
    ) -> ListingReviewData:
        """상장 데이터 수집 및 분류.
        
        Args:
            symbol: 토큰 심볼
            exchange: 거래소 (Upbit, Bithumb)
            deposit_krw: 입금액 추정 (원)
            volume_5m_krw: 5분 거래량 (원)
            volume_1m_krw: 1분 거래량 (원)
            max_premium_pct: 최고 프리미엄 (%)
            premium_at_5m_pct: 5분 시점 프리미엄 (%)
            market_cap_usd: 시가총액 (USD)
            listing_type: 상장 유형 (TGE, 직상장, 옆상장)
            date: 상장일 (YYYY-MM-DD)
            notes: 메모
            **kwargs: 추가 필드
            
        Returns:
            분류된 ListingReviewData
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        # 데이터 생성
        data = ListingReviewData(
            symbol=symbol.upper(),
            exchange=exchange,
            date=date,
            listing_type=listing_type,
            market_cap_usd=market_cap_usd,
            deposit_krw=deposit_krw,
            volume_5m_krw=volume_5m_krw,
            volume_1m_krw=volume_1m_krw,
            max_premium_pct=max_premium_pct,
            premium_at_5m_pct=premium_at_5m_pct,
        )
        
        # 추가 필드 설정
        for key, value in kwargs.items():
            if hasattr(data, key):
                setattr(data, key, value)
        
        # 흥/망 분류
        label, reason = self.classifier.classify_from_data(data)
        data.result_label = label.value
        
        # 노트 추가
        if notes:
            data.result_notes = notes
        else:
            data.result_notes = reason
        
        logger.info(f"분류 완료: {symbol}@{exchange} → {label.value} ({reason})")
        
        return data
    
    def collect_classify_save(
        self,
        symbol: str,
        exchange: str,
        deposit_krw: float,
        volume_5m_krw: float,
        **kwargs,
    ) -> ListingReviewData:
        """수집 + 분류 + 저장 일괄 처리."""
        data = self.collect_and_classify(
            symbol=symbol,
            exchange=exchange,
            deposit_krw=deposit_krw,
            volume_5m_krw=volume_5m_krw,
            **kwargs,
        )
        
        self.store.save(data)
        return data
    
    def reclassify_all(self) -> dict[str, int]:
        """모든 데이터 재분류.
        
        기존 CSV의 turnover_ratio가 없는 항목들을 
        다시 계산하고 result_label 업데이트.
        
        Returns:
            {"updated": N, "skipped": M, "total": T}
        """
        all_data = self.store.load_all()
        updated = 0
        skipped = 0
        
        for data in all_data:
            if data.volume_5m_krw and data.deposit_krw:
                old_label = data.result_label
                label, reason = self.classifier.classify_from_data(data)
                new_label = label.value
                
                if old_label != new_label:
                    logger.info(f"재분류: {data.symbol}@{data.exchange} {old_label} → {new_label}")
                    data.result_label = new_label
                    updated += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        
        # 저장
        self.store._save_all(all_data)
        
        result = {
            "updated": updated,
            "skipped": skipped,
            "total": len(all_data),
        }
        logger.info(f"재분류 완료: {result}")
        return result


def analyze_listing_stats(csv_path: Path = LISTING_DATA_PATH) -> dict:
    """상장 통계 분석.
    
    Returns:
        통계 딕셔너리
    """
    store = ListingDataStore(csv_path)
    all_data = store.load_all()
    
    if not all_data:
        return {"error": "데이터 없음"}
    
    # 라벨별 집계
    label_counts = {}
    for data in all_data:
        label = data.result_label or "미분류"
        label_counts[label] = label_counts.get(label, 0) + 1
    
    # 거래소별 집계
    exchange_counts = {}
    for data in all_data:
        ex = data.exchange or "Unknown"
        exchange_counts[ex] = exchange_counts.get(ex, 0) + 1
    
    # 상장 유형별 집계
    type_counts = {}
    for data in all_data:
        lt = data.listing_type or "미분류"
        type_counts[lt] = type_counts.get(lt, 0) + 1
    
    # 손바뀜 비율 통계
    turnover_ratios = [d.turnover_ratio for d in all_data if d.turnover_ratio]
    avg_turnover = sum(turnover_ratios) / len(turnover_ratios) if turnover_ratios else 0
    max_turnover = max(turnover_ratios) if turnover_ratios else 0
    min_turnover = min(turnover_ratios) if turnover_ratios else 0
    
    return {
        "total": len(all_data),
        "by_label": label_counts,
        "by_exchange": exchange_counts,
        "by_type": type_counts,
        "turnover_stats": {
            "avg": round(avg_turnover, 2),
            "max": round(max_turnover, 2),
            "min": round(min_turnover, 2),
            "count": len(turnover_ratios),
        },
    }


def format_review_report(data: ListingReviewData) -> str:
    """상장 복기 리포트 포맷."""
    lines = [
        f"📊 **상장 복기: {data.symbol}@{data.exchange}**",
        "━━━━━━━━━━━━━━━",
        f"📅 일자: {data.date or 'N/A'}",
        f"📌 유형: {data.listing_type or 'N/A'}",
        "",
        "**📈 핵심 지표**",
    ]
    
    if data.deposit_krw:
        lines.append(f"💰 입금액: ₩{data.deposit_krw/1e8:.1f}억")
    if data.volume_5m_krw:
        lines.append(f"📊 5분 거래량: ₩{data.volume_5m_krw/1e8:.1f}억")
    if data.volume_1m_krw:
        lines.append(f"⚡ 1분 거래량: ₩{data.volume_1m_krw/1e8:.1f}억")
    if data.turnover_ratio:
        lines.append(f"🔄 손바뀜 비율: {data.turnover_ratio:.2f}배")
    if data.max_premium_pct:
        lines.append(f"🥬 최고 김프: {data.max_premium_pct:.1f}%")
    
    lines.extend([
        "",
        "**🎯 판정**",
    ])
    
    # 라벨 이모지
    label_emoji = {
        "대흥따리": "🚀",
        "흥따리": "📈",
        "보통": "➖",
        "망따리": "📉",
    }
    emoji = label_emoji.get(data.result_label or "", "❓")
    lines.append(f"{emoji} **{data.result_label or '미분류'}**")
    
    if data.result_notes:
        lines.append(f"📝 {data.result_notes}")
    
    return "\n".join(lines)


# CLI용 간편 함수들
def review(
    symbol: str,
    exchange: str,
    deposit: float,
    volume_5m: float,
    **kwargs,
) -> str:
    """상장 복기 간편 함수.
    
    사용법:
        from analysis.listing_review import review
        print(review("ERA", "Upbit", 205e8, 910e8, max_premium_pct=50))
    """
    collector = ListingReviewCollector()
    data = collector.collect_classify_save(
        symbol=symbol,
        exchange=exchange,
        deposit_krw=deposit,
        volume_5m_krw=volume_5m,
        **kwargs,
    )
    return format_review_report(data)


def stats() -> dict:
    """통계 간편 함수."""
    return analyze_listing_stats()


if __name__ == "__main__":
    # 테스트 실행
    logging.basicConfig(level=logging.INFO)
    
    # 통계 출력
    print("\n=== 상장 통계 ===")
    stats_result = analyze_listing_stats()
    for key, value in stats_result.items():
        print(f"{key}: {value}")
    
    # 예시: ERA 복기
    print("\n=== ERA 복기 예시 ===")
    result = review(
        symbol="TEST",
        exchange="Upbit",
        deposit=20.5e9,  # 205억
        volume_5m=91e9,   # 910억
        max_premium_pct=50,
        listing_type="TGE",
        notes="테스트용 데이터",
    )
    print(result)
