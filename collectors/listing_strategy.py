#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
상장 공지 종합 전략 추천 시스템

기능:
- 상장 공지 시 자동 분석
- 현선갭 + 론 + DEX + 핫월렛 + 네트워크 통합
- 최적 전략 추천 (헷지 갭익절 / 현물 선따리 / 후따리 / 역따리)
- 실시간 갭 알림 트리거

Phase 1-3 통합 모듈
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """전략 유형"""
    HEDGE_GAP_EXIT = "hedge_gap_exit"    # 헷지 갭익절 전략
    SPOT_ONLY = "spot_only"              # 현물만 선따리
    POST_LISTING = "post_listing"        # 후따리 대기
    REVERSE_ARB = "reverse_arb"          # 역따리
    HIGH_RISK = "high_risk"              # 리스크 높음
    PASS = "pass"                        # 패스 권장


class RiskLevel(Enum):
    """리스크 레벨"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class GapInfo:
    """현선갭 정보"""
    exchange: str
    spot_price: float
    futures_price: float
    gap_percent: float
    is_reverse: bool = False  # 역프 여부


@dataclass
class LoanDetail:
    """거래소별 론 상세 정보"""
    exchange: str
    available: bool
    hourly_rate: Optional[float] = None
    max_amount: Optional[float] = None


@dataclass
class SimilarCase:
    """복기 데이터 - 유사 케이스"""
    symbol: str
    listing_date: str
    result_label: str  # heung_big, heung, neutral, mang
    max_premium_pct: Optional[float] = None
    similarity_reason: str = ""


@dataclass
class ExchangeMarket:
    """거래소별 마켓 정보"""
    exchange: str
    has_spot: bool = False
    has_futures: bool = False
    spot_pairs: List[str] = field(default_factory=list)
    futures_pairs: List[str] = field(default_factory=list)
    # 입출금 상태
    deposit_enabled: bool = False
    withdraw_enabled: bool = False
    networks: List[str] = field(default_factory=list)


@dataclass
class StrategyRecommendation:
    """전략 추천 결과"""
    symbol: str
    timestamp: float
    
    # 전략
    strategy_type: StrategyType
    strategy_name: str
    strategy_detail: str
    risk_level: RiskLevel
    go_score: int  # 0-100
    
    # 토크노믹스 (기본 정보)
    name: Optional[str] = None
    market_cap_usd: Optional[float] = None
    fdv_usd: Optional[float] = None
    current_price_usd: Optional[float] = None
    circulating_supply: Optional[float] = None
    total_supply: Optional[float] = None
    circulating_percent: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    price_change_24h_pct: Optional[float] = None  # 24시간 등락률
    platforms: List[str] = field(default_factory=list)  # 지원 체인
    
    # 거래소별 마켓 정보
    exchange_markets: List[ExchangeMarket] = field(default_factory=list)
    
    # 개별 분석 결과
    best_gap: Optional[GapInfo] = None
    all_gaps: List[GapInfo] = field(default_factory=list)  # 거래소별 전체 갭
    loan_available: bool = False
    loan_exchanges: List[str] = field(default_factory=list)
    loan_details: List[LoanDetail] = field(default_factory=list)  # 거래소별 론 상세
    best_loan_exchange: Optional[str] = None
    best_loan_rate: Optional[float] = None
    
    dex_liquidity_usd: Optional[float] = None
    hot_wallet_krw: Optional[float] = None
    network_speed: Optional[str] = None
    network_time: Optional[str] = None
    network_chain: Optional[str] = None  # 체인명 (ETH, SOL 등)
    
    # 전송 분석
    bridge_required: bool = False  # 브릿지 필요 여부
    bridge_info: Optional[str] = None  # 브릿지 정보
    bridge_name: Optional[str] = None  # 추천 브릿지 이름
    exchange_networks: Dict[str, List[str]] = field(default_factory=dict)  # 거래소별 출금 가능 네트워크
    best_transfer_route: Optional[str] = None  # 최적 전송 경로
    fastest_transfer_time: Optional[str] = None  # 가장 빠른 전송 시간
    
    # 흥/망 예측 (복기 데이터 기반)
    predicted_result: Optional[str] = None  # heung, mang, neutral
    similar_cases: List[SimilarCase] = field(default_factory=list)
    
    # 액션 아이템
    actions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class ListingStrategyAnalyzer:
    """상장 전략 분석기"""
    
    # 갭 임계값
    GAP_LOW = 2.0       # 갭 낮음 기준 (%)
    GAP_MEDIUM = 4.0    # 갭 보통 기준 (%)
    GAP_HIGH = 10.0     # 갭 높음 기준 (%)
    
    # DEX 유동성 기준 (USD)
    DEX_LOW = 200000    # 20만불 이하 = 적음
    DEX_HIGH = 1000000  # 100만불 이상 = 많음
    
    # 핫월렛 기준 (KRW)
    WALLET_HIGH = 50_000_000_000  # 500억 이상 = 많음
    
    def __init__(self):
        self._gap_monitors = {}  # 갭 모니터링 세션
    
    async def analyze(self, symbol: str) -> StrategyRecommendation:
        """종합 분석 및 전략 추천
        
        Args:
            symbol: 심볼 (예: NEWCOIN)
            
        Returns:
            StrategyRecommendation: 전략 추천 결과
        """
        symbol = symbol.upper()
        
        # 병렬로 모든 데이터 수집
        gap_task = self._get_gap_info(symbol)
        loan_task = self._get_loan_info(symbol)
        dex_task = self._get_dex_liquidity(symbol)
        wallet_task = self._get_hot_wallet(symbol)
        network_task = self._get_network_info(symbol)
        similar_task = self._get_similar_cases(symbol)
        transfer_task = self._get_transfer_analysis(symbol)
        intel_task = self._get_listing_intel(symbol)
        
        results = await asyncio.gather(
            gap_task, loan_task, dex_task, wallet_task, network_task, similar_task, transfer_task, intel_task,
            return_exceptions=True
        )
        
        gap_result = results[0] if not isinstance(results[0], Exception) else {"best": None, "all": []}
        loan_info = results[1] if not isinstance(results[1], Exception) else {}
        dex_liquidity = results[2] if not isinstance(results[2], Exception) else None
        hot_wallet = results[3] if not isinstance(results[3], Exception) else None
        network_info = results[4] if not isinstance(results[4], Exception) else {}
        similar_cases = results[5] if not isinstance(results[5], Exception) else []
        transfer_analysis = results[6] if not isinstance(results[6], Exception) else None
        listing_intel = results[7] if not isinstance(results[7], Exception) else None
        
        # 전략 결정
        return self._determine_strategy(
            symbol=symbol,
            gap_result=gap_result,
            loan_info=loan_info,
            dex_liquidity=dex_liquidity,
            hot_wallet=hot_wallet,
            network_info=network_info,
            similar_cases=similar_cases,
            transfer_analysis=transfer_analysis,
            listing_intel=listing_intel
        )
    
    async def _get_gap_info(self, symbol: str) -> Dict:
        """현선갭 조회 - 실제 API 연동 (거래소별 전체 갭 반환)"""
        try:
            from collectors.exchange_service import exchange_service
            from collectors.gap_calculator import GapCalculator
            
            # 현물/선물 거래소 목록
            spot_exchanges = ["binance", "bybit", "okx"]
            futures_exchanges = ["binance", "bybit", "okx"]
            
            # 병렬로 가격 조회
            prices = exchange_service.fetch_all_prices(
                symbol=symbol,
                spot_exchanges=spot_exchanges,
                futures_exchanges=futures_exchanges
            )
            
            spot_prices = prices.get('spot', {})
            futures_prices = prices.get('futures', {})
            
            if not spot_prices or not futures_prices:
                logger.warning(f"{symbol}: 가격 데이터 없음 (spot={len(spot_prices)}, futures={len(futures_prices)})")
                return {"best": None, "all": []}
            
            # 모든 조합의 갭 계산
            all_gaps = []
            best_gap = None
            best_gap_percent = float('inf')
            
            for futures_ex, futures_data in futures_prices.items():
                for spot_ex, spot_data in spot_prices.items():
                    if spot_data.price <= 0 or futures_data.price <= 0:
                        continue
                    
                    gap_percent = ((futures_data.price - spot_data.price) / spot_data.price) * 100
                    is_reverse = gap_percent < 0
                    
                    gap_info = GapInfo(
                        exchange=f"{spot_ex}/{futures_ex}",
                        spot_price=spot_data.price,
                        futures_price=futures_data.price,
                        gap_percent=gap_percent,
                        is_reverse=is_reverse
                    )
                    all_gaps.append(gap_info)
                    
                    # 갭이 낮을수록 좋음 - 절대값이 작은 것 선호
                    if abs(gap_percent) < abs(best_gap_percent):
                        best_gap_percent = gap_percent
                        best_gap = gap_info
            
            # 갭 낮은 순으로 정렬
            all_gaps.sort(key=lambda x: abs(x.gap_percent))
            
            if best_gap:
                logger.info(f"{symbol} 갭: {best_gap.gap_percent:.2f}% ({best_gap.exchange}), 총 {len(all_gaps)}개")
            
            return {"best": best_gap, "all": all_gaps}
            
        except Exception as e:
            logger.error(f"Gap info 조회 실패: {e}")
            return {"best": None, "all": []}
    
    async def _get_loan_info(self, symbol: str) -> Dict:
        """론 가능 거래소 조회"""
        try:
            from collectors.margin_loan import scan_loan_availability
            
            result = await scan_loan_availability(symbol)
            
            available = [r for r in result.results if r.available]
            
            return {
                "available": len(available) > 0,
                "exchanges": [r.exchange for r in available],
                "best_exchange": result.best_exchange,
                "best_rate": result.best_rate,
                "all_results": result.results
            }
            
        except Exception as e:
            logger.error(f"Loan info 조회 실패: {e}")
            return {"available": False, "exchanges": []}
    
    async def _get_dex_liquidity(self, symbol: str) -> Optional[float]:
        """DEX 유동성 조회"""
        try:
            from collectors.dex_liquidity import get_dex_liquidity
            
            result = await get_dex_liquidity(symbol)
            if result:
                # DexLiquidityResult 객체인 경우 - total_liquidity_usd 사용
                if hasattr(result, 'total_liquidity_usd'):
                    return result.total_liquidity_usd
                # 기존 호환성
                elif hasattr(result, 'liquidity_usd'):
                    return result.liquidity_usd
                elif isinstance(result, dict):
                    return result.get("total_liquidity_usd") or result.get("liquidity_usd")
            return None
            
        except Exception as e:
            logger.error(f"DEX liquidity 조회 실패: {e}")
            return None
    
    async def _get_hot_wallet(self, symbol: str) -> Optional[float]:
        """핫월렛 물량 조회"""
        try:
            # 다양한 함수명 시도
            try:
                from collectors.hot_wallet_tracker import get_hot_wallet_balance
                result = await get_hot_wallet_balance(symbol)
            except ImportError:
                try:
                    from collectors.hot_wallet_tracker import HotWalletTracker
                    tracker = HotWalletTracker()
                    result = await tracker.get_balance(symbol)
                except:
                    return None
            
            if result:
                if hasattr(result, 'total_krw'):
                    return result.total_krw
                elif isinstance(result, dict):
                    return result.get("total_krw")
            return None
            
        except Exception as e:
            logger.error(f"Hot wallet 조회 실패: {e}")
            return None
    
    async def _get_network_info(self, symbol: str) -> Dict:
        """네트워크 정보 조회"""
        try:
            from collectors.network_speed import get_network_info, get_network_by_symbol, NetworkInfo
            
            # 먼저 심볼로 네트워크 추론 시도
            result = get_network_by_symbol(symbol)
            
            # 추론 실패 시 심볼을 네트워크명으로 직접 시도
            if not result:
                result = get_network_info(symbol)
            
            if result:
                # NetworkInfo 객체인 경우 dict로 변환
                if isinstance(result, NetworkInfo):
                    return {
                        "speed": result.speed,
                        "time": result.estimated_time,  # estimated_time 사용
                        "go_signal": result.go_signal
                    }
                elif hasattr(result, 'speed'):
                    return {
                        "speed": result.speed,
                        "time": getattr(result, 'estimated_time', getattr(result, 'time', 'N/A')),
                        "go_signal": getattr(result, 'go_signal', 'N/A')
                    }
                elif isinstance(result, dict):
                    return result
            return {}
            
        except Exception as e:
            logger.error(f"Network info 조회 실패: {e}")
            return {}
    
    async def _get_similar_cases(self, symbol: str) -> List[SimilarCase]:
        """복기 데이터에서 유사 케이스 조회"""
        try:
            import sqlite3
            import os
            from pathlib import Path
            
            # DB 경로 (환경변수 또는 기본 경로)
            data_dir = os.environ.get("DATA_DIR", "/data")
            db_path = Path(data_dir) / "listing_history.db"
            
            if not db_path.exists():
                # 로컬 개발 환경
                db_path = Path("C:/Users/user/clawd/data/listing_history.db")
            
            if not db_path.exists():
                logger.debug("listing_history.db not found")
                return []
            
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # learning_cases 테이블에서 유사 케이스 검색
            # (향후: 시총, 거래소, 네트워크 등 조건으로 유사도 계산 가능)
            cursor.execute("""
                SELECT symbol, listing_date, result_label, max_premium_pct, 
                       top_exchange, network_chain, market_cap_usd
                FROM learning_cases
                WHERE result_label IS NOT NULL
                ORDER BY listing_date DESC
                LIMIT 5
            """)
            
            cases = []
            for row in cursor.fetchall():
                similarity_reason = f"{row['top_exchange'] or ''} 상장"
                if row['network_chain']:
                    similarity_reason += f", {row['network_chain']} 체인"
                
                cases.append(SimilarCase(
                    symbol=row['symbol'],
                    listing_date=row['listing_date'] or '',
                    result_label=row['result_label'],
                    max_premium_pct=row['max_premium_pct'],
                    similarity_reason=similarity_reason
                ))
            
            conn.close()
            
            if cases:
                logger.info(f"{symbol}: {len(cases)}개 유사 케이스 발견")
            
            return cases
            
        except Exception as e:
            logger.error(f"Similar cases 조회 실패: {e}")
            return []
    
    async def _get_transfer_analysis(self, symbol: str):
        """전송 분석 (브릿지, 출금 가능 네트워크)"""
        try:
            from collectors.transfer_analyzer import analyze_transfer
            return await analyze_transfer(symbol)
        except Exception as e:
            logger.error(f"Transfer analysis 실패: {e}")
            return None
    
    async def _get_listing_intel(self, symbol: str):
        """토크노믹스 + 거래소 마켓 정보 수집"""
        try:
            from collectors.listing_intel import ListingIntelCollector
            
            collector = ListingIntelCollector()
            try:
                intel = await collector.collect(symbol)
                return intel
            finally:
                await collector.close()
        except Exception as e:
            logger.error(f"Listing intel 조회 실패: {e}")
            return None
    
    def _predict_result(self, similar_cases: List[SimilarCase]) -> Optional[str]:
        """유사 케이스 기반 흥/망 예측"""
        if not similar_cases:
            return None
        
        heung_count = sum(1 for c in similar_cases if c.result_label in ('heung', 'heung_big', '흥따리', '대흥따리'))
        mang_count = sum(1 for c in similar_cases if c.result_label in ('mang', '망따리'))
        
        total = heung_count + mang_count
        if total == 0:
            return "neutral"
        
        heung_rate = heung_count / total
        if heung_rate >= 0.6:
            return "heung"
        elif heung_rate <= 0.4:
            return "mang"
        else:
            return "neutral"
    
    def _determine_strategy(
        self,
        symbol: str,
        gap_result: Dict,
        loan_info: Dict,
        dex_liquidity: Optional[float],
        hot_wallet: Optional[float],
        network_info: Dict,
        similar_cases: List[SimilarCase] = None,
        transfer_analysis = None,
        listing_intel = None
    ) -> StrategyRecommendation:
        """전략 결정 로직
        
        조건 조합:
        - 갭 낮음(1-2%) + 론 가능 + 유동성 적음 → 헷지 갭익절 전략
        - 갭 낮음 + 론 불가 + 유동성 적음 → 현물만 선따리
        - 갭 높음 + 유동성 많음 → 후따리 대기
        - 역프 → 역따리 전략
        - 핫월렛 많음 + 네트워크 빠름 → 경쟁 치열, 리스크 ↑
        """
        if similar_cases is None:
            similar_cases = []
        
        actions = []
        warnings = []
        go_score = 50  # 기본 점수
        
        # === 갭 정보 처리 ===
        gap_info = gap_result.get("best") if gap_result else None
        all_gaps = gap_result.get("all", []) if gap_result else []
        gap_percent = gap_info.gap_percent if gap_info else None
        is_reverse = gap_info.is_reverse if gap_info else False
        
        # 갭 정보 없으면 중간값으로 가정 (보수적 접근)
        if gap_percent is None:
            # 경고 추가
            warnings.append("⚠️ 현선갭 조회 실패 - 선물 미상장일 수 있음")
            gap_percent = 3.0  # 보수적 기본값 (중간 영역)
        
        # === 론 정보 처리 ===
        has_loan = loan_info.get("available", False)
        loan_exchanges = loan_info.get("exchanges", [])
        best_loan = loan_info.get("best_exchange")
        best_rate = loan_info.get("best_rate")
        
        # === DEX 유동성 처리 ===
        dex_low = dex_liquidity is None or dex_liquidity < self.DEX_LOW
        dex_high = dex_liquidity and dex_liquidity >= self.DEX_HIGH
        
        # === 핫월렛 처리 ===
        wallet_high = hot_wallet and hot_wallet >= self.WALLET_HIGH
        
        # === 네트워크 처리 ===
        network_fast = network_info.get("speed") in ["very_fast", "fast"]
        network_speed = network_info.get("speed", "unknown")
        network_time = network_info.get("time", "N/A")
        
        # =========================================================
        # 전략 결정
        # =========================================================
        
        # 1. 역프 상황
        if gap_percent < 0 or is_reverse:
            strategy_type = StrategyType.REVERSE_ARB
            strategy_name = "🔄 역따리 전략"
            strategy_detail = f"역프 {abs(gap_percent):.1f}% 발생! 국내 매수 + 해외 숏 전략"
            risk_level = RiskLevel.MEDIUM
            go_score = 70
            
            actions = [
                "✅ 국내(업비트/빗썸) 현물 매수",
                "✅ 해외 선물 숏 헷지",
                "✅ 해외로 코인 전송",
                "✅ 해외 현물 매도 + 숏 청산",
                f"💰 예상 수익: {abs(gap_percent):.1f}% - 수수료"
            ]
        
        # 2. 갭 매우 낮음 (1-2%)
        elif gap_percent < self.GAP_LOW:
            if has_loan:
                strategy_type = StrategyType.HEDGE_GAP_EXIT
                strategy_name = "🎯 헷지 갭익절 전략"
                strategy_detail = f"갭 {gap_percent:.1f}% 매우 낮음! 론 가능! 헷지 잡고 갭 벌어지면 익절"
                risk_level = RiskLevel.LOW
                go_score = 85
                
                actions = [
                    f"✅ {best_loan} 론 빌리기 ({best_rate:.4f}%/h)" if best_loan else "✅ 론 빌리기",
                    f"✅ 현물 매수 + 선물 숏 (갭 {gap_percent:.1f}%)",
                    "✅ 국내 입금 대기",
                    "✅ 갭 벌어지면 단계별 익절",
                    "   • 5% → 모니터링",
                    "   • 10% → 1/3 익절",
                    "   • 20% → 2/3 익절",
                    "   • 30%+ → 전량 익절"
                ]
            else:
                strategy_type = StrategyType.SPOT_ONLY
                strategy_name = "📦 현물 선따리"
                strategy_detail = f"갭 {gap_percent:.1f}% 낮음! 론 불가 → 현물만 진행"
                risk_level = RiskLevel.MEDIUM
                go_score = 65
                
                actions = [
                    "✅ 현물 매수 (헷지 없이)",
                    "✅ 국내 입금",
                    "⚠️ 가격 변동 리스크 있음"
                ]
        
        # 3. 갭 보통 (2-4%)
        elif gap_percent < self.GAP_MEDIUM:
            strategy_type = StrategyType.SPOT_ONLY
            strategy_name = "⚠️ 헷지 비용 고려"
            strategy_detail = f"갭 {gap_percent:.1f}% 보통, 헷지 비용이 수익 일부 차지"
            risk_level = RiskLevel.MEDIUM
            go_score = 55
            
            actions = [
                f"🟡 헷지 시 비용 {gap_percent:.1f}% 발생",
                "🟡 김프 예상치와 비교 필요",
                "🟡 물량 줄이거나 현물만 고려"
            ]
        
        # 4. 갭 높음 (4%+)
        else:
            if dex_high:
                strategy_type = StrategyType.POST_LISTING
                strategy_name = "⏳ 후따리 대기"
                strategy_detail = f"갭 {gap_percent:.1f}% 높음 + DEX 유동성 충분 → 상장 후 후따리"
                risk_level = RiskLevel.LOW
                go_score = 50
                
                actions = [
                    f"🔴 헷지 비용 {gap_percent:.1f}% 너무 높음",
                    "✅ 상장 후 김프 확인",
                    "✅ 김프 유지되면 후따리 진입"
                ]
            else:
                strategy_type = StrategyType.HIGH_RISK
                strategy_name = "🚫 리스크 높음"
                strategy_detail = f"갭 {gap_percent:.1f}% 높음 + DEX 유동성 부족"
                risk_level = RiskLevel.HIGH
                go_score = 30
                
                actions = [
                    f"🔴 헷지 비용 {gap_percent:.1f}% 높음",
                    "🔴 후따리 유동성도 부족",
                    "⚠️ 패스 고려 또는 소량만"
                ]
        
        # === 추가 경고 ===
        if wallet_high:
            warnings.append("⚠️ 핫월렛 물량 많음 - 입금 경쟁 치열 예상")
            go_score -= 10
        
        if network_fast:
            warnings.append("⚠️ 네트워크 빠름 - 후따리 쉬움, 프리미엄 빨리 사라질 수 있음")
            go_score -= 5
        
        go_score = max(0, min(100, go_score))
        
        # === 흥/망 예측 ===
        predicted_result = self._predict_result(similar_cases)
        if predicted_result == "heung":
            go_score = min(100, go_score + 10)
            actions.append("📈 복기 데이터: 흥따리 유력 (유사 케이스 기반)")
        elif predicted_result == "mang":
            go_score = max(0, go_score - 10)
            warnings.append("📉 복기 데이터: 망따리 주의 (유사 케이스 기반)")
        
        # === 론 상세 정보 ===
        loan_details = []
        all_results = loan_info.get("all_results", [])
        for r in all_results:
            if hasattr(r, 'exchange'):
                loan_details.append(LoanDetail(
                    exchange=r.exchange,
                    available=r.available,
                    hourly_rate=getattr(r, 'hourly_rate', None),
                    max_amount=getattr(r, 'max_loan_amount', None)
                ))
        
        # === 전송 분석 결과 ===
        bridge_required = False
        bridge_info = None
        bridge_name = None
        exchange_networks = {}
        best_transfer_route = None
        fastest_transfer_time = None
        
        if transfer_analysis:
            bridge_required = transfer_analysis.bridge_required
            if transfer_analysis.bridge_reason:
                bridge_info = transfer_analysis.bridge_reason
            if transfer_analysis.recommended_bridge:
                bridge_name = transfer_analysis.recommended_bridge.name
                warnings.append(f"🔗 브릿지 필요: {bridge_name} 이용 추천")
            exchange_networks = transfer_analysis.exchange_networks
            if transfer_analysis.best_route:
                best_transfer_route = f"{transfer_analysis.best_route.from_exchange} → {transfer_analysis.best_route.network}"
            fastest_transfer_time = transfer_analysis.fastest_time
        
        # === 토크노믹스 정보 (listing_intel) ===
        name = None
        market_cap_usd = None
        fdv_usd = None
        current_price_usd = None
        circulating_supply = None
        total_supply = None
        circulating_percent = None
        platforms = []
        exchange_markets = []
        
        volume_24h_usd = None
        price_change_24h_pct = None
        
        if listing_intel:
            name = listing_intel.name
            market_cap_usd = listing_intel.market_cap_usd
            fdv_usd = listing_intel.fdv_usd
            current_price_usd = listing_intel.current_price_usd or listing_intel.futures_price_usd
            circulating_supply = listing_intel.circulating_supply
            total_supply = listing_intel.total_supply
            circulating_percent = listing_intel.circulating_percent
            volume_24h_usd = listing_intel.volume_24h_usd
            price_change_24h_pct = listing_intel.price_change_24h_pct
            platforms = listing_intel.platforms or []
            
            # 거래소별 마켓 정보 (입출금 상태 포함)
            for ex_name, ex_status in (listing_intel.exchanges or {}).items():
                exchange_markets.append(ExchangeMarket(
                    exchange=ex_name,
                    has_spot=ex_status.has_spot,
                    has_futures=ex_status.has_futures,
                    spot_pairs=ex_status.spot_pairs,
                    futures_pairs=ex_status.futures_pairs,
                    deposit_enabled=ex_status.deposit_enabled,
                    withdraw_enabled=ex_status.withdraw_enabled,
                    networks=ex_status.networks or []
                ))
        
        return StrategyRecommendation(
            symbol=symbol,
            timestamp=time.time(),
            strategy_type=strategy_type,
            strategy_name=strategy_name,
            strategy_detail=strategy_detail,
            risk_level=risk_level,
            go_score=go_score,
            # 토크노믹스
            name=name,
            market_cap_usd=market_cap_usd,
            fdv_usd=fdv_usd,
            current_price_usd=current_price_usd,
            circulating_supply=circulating_supply,
            total_supply=total_supply,
            circulating_percent=circulating_percent,
            volume_24h_usd=volume_24h_usd,
            price_change_24h_pct=price_change_24h_pct,
            platforms=platforms,
            exchange_markets=exchange_markets,
            # 갭/론
            best_gap=gap_info,
            all_gaps=all_gaps,
            loan_available=has_loan,
            loan_exchanges=loan_exchanges,
            loan_details=loan_details,
            best_loan_exchange=best_loan,
            best_loan_rate=best_rate,
            dex_liquidity_usd=dex_liquidity,
            hot_wallet_krw=hot_wallet,
            network_speed=network_speed,
            network_time=network_time,
            bridge_required=bridge_required,
            bridge_info=bridge_info,
            bridge_name=bridge_name,
            exchange_networks=exchange_networks,
            best_transfer_route=best_transfer_route,
            fastest_transfer_time=fastest_transfer_time,
            predicted_result=predicted_result,
            similar_cases=similar_cases,
            actions=actions,
            warnings=warnings
        )


def format_strategy_recommendation(rec: StrategyRecommendation) -> str:
    """전략 추천 결과를 텔레그램 메시지 형식으로 포맷
    
    Args:
        rec: StrategyRecommendation
        
    Returns:
        포맷된 문자열
    """
    lines = [
        f"🚀 [신규 상장 분석] {rec.symbol}",
        "",
        "━" * 28,
        "📊 종합 분석",
        "━" * 28,
        f"GO Score: {rec.go_score}/100 {'🟢' if rec.go_score >= 70 else '🟡' if rec.go_score >= 50 else '🔴'}",
        ""
    ]
    
    # DEX 유동성
    if rec.dex_liquidity_usd:
        dex_str = f"${rec.dex_liquidity_usd/1000:.0f}K" if rec.dex_liquidity_usd >= 1000 else f"${rec.dex_liquidity_usd:.0f}"
        lines.append(f"💧 DEX 유동성: {dex_str}")
    
    # 핫월렛
    if rec.hot_wallet_krw:
        wallet_str = f"{rec.hot_wallet_krw/100000000:.0f}억" if rec.hot_wallet_krw >= 100000000 else f"{rec.hot_wallet_krw/10000:.0f}만"
        lines.append(f"🔥 핫월렛: {wallet_str}")
    
    # 네트워크
    if rec.network_speed:
        lines.append(f"⚡ 네트워크: {rec.network_speed} ({rec.network_time})")
    
    lines.append("")
    
    # 론 가능 거래소
    lines.extend([
        "━" * 28,
        "💰 론 가능 거래소",
        "━" * 28,
    ])
    
    if rec.loan_available:
        for i, ex in enumerate(rec.loan_exchanges[:3], 1):
            rec_mark = " ✅" if ex == rec.best_loan_exchange else ""
            rate_str = f" ({rec.best_loan_rate:.4f}%/h)" if ex == rec.best_loan_exchange and rec.best_loan_rate else ""
            lines.append(f"{i}. {ex}{rate_str}{rec_mark}")
    else:
        lines.append("❌ 론 가능한 거래소 없음")
    
    lines.append("")
    
    # 현선갭
    lines.extend([
        "━" * 28,
        "📈 현선갭 현황",
        "━" * 28,
    ])
    
    if rec.best_gap:
        gap = rec.best_gap.gap_percent
        status = "🟢" if gap < 2 else "🟡" if gap < 4 else "🔴"
        lines.append(f"{rec.best_gap.exchange}: {gap:.1f}% {status}")
    else:
        lines.append("(갭 정보 없음 - 실제 조회 필요)")
    
    lines.append("")
    
    # 전략 추천
    lines.extend([
        "━" * 28,
        f"🎯 전략 추천: {rec.strategy_name}",
        "━" * 28,
        rec.strategy_detail,
        ""
    ])
    
    # 액션 플랜
    if rec.actions:
        lines.append("📋 액션 플랜:")
        for action in rec.actions:
            lines.append(action)
    
    # 경고
    if rec.warnings:
        lines.append("")
        lines.append("⚠️ 주의사항:")
        for warning in rec.warnings:
            lines.append(warning)
    
    return "\n".join(lines)


# =============================================================================
# 편의 함수
# =============================================================================

async def analyze_listing(symbol: str) -> StrategyRecommendation:
    """상장 공지 분석 (단일 호출용)
    
    Args:
        symbol: 심볼
        
    Returns:
        StrategyRecommendation
        
    Example:
        rec = await analyze_listing("NEWCOIN")
        print(format_strategy_recommendation(rec))
    """
    analyzer = ListingStrategyAnalyzer()
    return await analyzer.analyze(symbol)


# =============================================================================
# 테스트
# =============================================================================

if __name__ == "__main__":
    async def test():
        print("=== 상장 전략 분석 테스트 ===\n")
        
        rec = await analyze_listing("TESTCOIN")
        print(format_strategy_recommendation(rec))
    
    asyncio.run(test())
