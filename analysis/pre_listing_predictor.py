#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""상장 전 GO/NO-GO 예측 (가격 없이 판단).

따리 펀더멘탈 기반:
- 핵심: 거래량 > 입금액 → 흥따리
- 가격 없이도 토크노믹스, 현선갭, 거래량, 공급량으로 예측

데이터 소스:
1. 현선갭 + 펀딩비 → spot_futures_gap.py
2. 토크노믹스 (MC, FDV, 유통량) → CoinGecko
3. 글로벌 24H 거래량 → CoinGecko / CCXT
4. 선물 유무 → spot_futures_gap.py
5. 네트워크 속도 → networks.yaml
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any

import aiohttp
import yaml

from analysis.spot_futures_gap import (
    SpotFuturesGapAnalyzer,
    SpotFuturesGapResult,
    HedgeType,
)
from analysis.market_condition import (
    MarketConditionAnalyzer,
    MarketCondition,
    MarketConditionResult,
)
from analysis.hot_wallet_analyzer import (
    HotWalletAnalyzer,
    HotWalletAnalysisResult,
)

logger = logging.getLogger(__name__)


class PredictionSignal(Enum):
    """예측 시그널"""
    STRONG_GO = "strong_go"      # 강한 GO (흥따리 유력)
    GO = "go"                    # GO (괜찮음)
    NEUTRAL = "neutral"          # 보통
    NO_GO = "no_go"              # NO-GO
    STRONG_NO_GO = "strong_no_go"  # 강한 NO-GO (망따리 유력)


class ListingType(Enum):
    """상장 유형"""
    TGE = "tge"              # Token Genesis Event (첫 상장)
    DIRECT = "direct"        # 직상장 (기존 토큰)
    SIDE = "side"            # 옆상장 (BTC마켓 → KRW마켓)
    UNKNOWN = "unknown"


@dataclass
class TokenomicsData:
    """토크노믹스 데이터"""
    symbol: str
    name: Optional[str] = None
    
    # 시가총액
    market_cap_usd: Optional[float] = None
    fdv_usd: Optional[float] = None  # Fully Diluted Valuation
    
    # 유통량
    circulating_supply: Optional[float] = None
    total_supply: Optional[float] = None
    max_supply: Optional[float] = None
    
    # 유통 비율 (%)
    circulating_ratio: Optional[float] = None
    
    # 글로벌 거래량
    volume_24h_usd: Optional[float] = None
    
    # 현재 가격
    price_usd: Optional[float] = None
    
    # 데이터 소스
    data_source: str = "unknown"
    timestamp: float = 0


@dataclass
class SupplyPressureFactors:
    """공급(입금액) 압력 요인"""
    
    # 현선갭 (높으면 헷지 어려움 → 입금↓)
    spot_futures_gap_pct: Optional[float] = None
    gap_score: float = 0  # -10 ~ +10 (높을수록 흥따리)
    
    # 펀딩비 (음펀비면 숏 비용 → 입금↓)
    funding_rate_8h_pct: Optional[float] = None
    funding_score: float = 0
    
    # 헷지 가능성
    hedge_type: HedgeType = HedgeType.NO_HEDGE
    hedge_score: float = 0
    
    # 네트워크 속도 (느리면 입금↓)
    network: Optional[str] = None
    transfer_time_min: Optional[float] = None
    network_score: float = 0
    
    # 유통량 (적으면 입금↓)
    circulating_ratio: Optional[float] = None
    supply_score: float = 0
    
    # 핫월렛 물량 (Phase 2 추가)
    hot_wallet_holdings_usd: Optional[float] = None
    hot_wallet_tier: str = "unknown"  # very_low / low / medium / high / very_high
    hot_wallet_score: float = 0  # -10 ~ +10 (높을수록 물량 많음 = 망따리)
    
    # 총 공급 점수 (높을수록 흥따리 = 입금 적음)
    total_supply_score: float = 0


@dataclass
class DemandFactors:
    """수요(거래량) 요인"""
    
    # 시가총액 수준 (저시총이면 거래량↑ 기대)
    market_cap_usd: Optional[float] = None
    mc_tier: str = "unknown"  # micro / low / mid / high / mega
    mc_score: float = 0
    
    # 글로벌 24H 거래량 (관심도)
    volume_24h_usd: Optional[float] = None
    volume_score: float = 0
    
    # 시황 (불장/망장) - 외부에서 주입
    market_condition: str = "neutral"  # bull / neutral / bear
    market_score: float = 0
    
    # 총 수요 점수 (높을수록 흥따리)
    total_demand_score: float = 0


@dataclass
class PreListingPrediction:
    """상장 전 예측 결과"""
    symbol: str
    exchange: str  # 상장 예정 거래소 (upbit/bithumb)
    
    # 예측 시그널
    signal: PredictionSignal = PredictionSignal.NEUTRAL
    
    # 흥따리 점수 (0~100)
    heung_score: float = 50
    
    # 상장 유형
    listing_type: ListingType = ListingType.UNKNOWN
    
    # 세부 요인
    supply_factors: Optional[SupplyPressureFactors] = None
    demand_factors: Optional[DemandFactors] = None
    
    # 현선갭 상세
    gap_result: Optional[SpotFuturesGapResult] = None
    
    # 토크노믹스 상세
    tokenomics: Optional[TokenomicsData] = None
    
    # 시황 상세 (Phase 1 추가)
    market_condition_result: Optional["MarketConditionResult"] = None
    
    # 핫월렛 상세 (Phase 2 추가)
    hot_wallet_result: Optional["HotWalletAnalysisResult"] = None
    
    # 경고/권장사항
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    # 메타
    timestamp: float = 0
    analysis_duration_ms: float = 0


# 시가총액 티어 기준 (USD)
MC_TIERS = {
    "micro": (0, 25_000_000),           # < 25M
    "low": (25_000_000, 60_000_000),    # 25M ~ 60M
    "mid": (60_000_000, 150_000_000),   # 60M ~ 150M
    "high": (150_000_000, 300_000_000), # 150M ~ 300M
    "mega": (300_000_000, float('inf')), # > 300M
}

# 네트워크 속도 기준 (분)
NETWORK_SPEEDS = {
    "fast": (0, 5),      # < 5분
    "normal": (5, 15),   # 5~15분
    "slow": (15, 30),    # 15~30분
    "very_slow": (30, float('inf')),  # > 30분
}


class PreListingPredictor:
    """상장 전 예측기"""
    
    def __init__(self, config_dir: str = "config"):
        self._config_dir = Path(config_dir)
        self._gap_analyzer = SpotFuturesGapAnalyzer()
        self._networks = self._load_networks_config()
        self._session: Optional[aiohttp.ClientSession] = None
    
    def _load_networks_config(self) -> dict:
        """networks.yaml 로드"""
        path = self._config_dir / "networks.yaml"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
        await self._gap_analyzer.close()
    
    async def predict(
        self,
        symbol: str,
        exchange: str = "upbit",
        listing_type: ListingType = ListingType.UNKNOWN,
        market_condition: str = "auto",
    ) -> PreListingPrediction:
        """상장 전 예측 실행 (메인 함수)
        
        Args:
            symbol: 토큰 심볼
            exchange: 상장 예정 거래소 (upbit/bithumb)
            listing_type: 상장 유형 (TGE/직상장/옆상장)
            market_condition: 시황 ("auto"면 자동 판단, 또는 bull/neutral/bear)
            
        Returns:
            PreListingPrediction
        """
        start_time = time.monotonic()
        symbol = symbol.upper()
        
        result = PreListingPrediction(
            symbol=symbol,
            exchange=exchange,
            listing_type=listing_type,
            timestamp=time.time(),
        )
        
        # 0. 시황 자동 판단 (market_condition="auto"인 경우)
        market_condition_result: Optional[MarketConditionResult] = None
        if market_condition == "auto":
            try:
                mc_analyzer = MarketConditionAnalyzer()
                market_condition_result = await mc_analyzer.analyze()
                await mc_analyzer.close()
                
                # MarketCondition enum → string 변환
                market_condition = market_condition_result.condition.value
                
                logger.info(
                    "[PreListingPredictor] 시황 자동 판단: %s (score: %d)",
                    market_condition, market_condition_result.market_score
                )
            except Exception as e:
                logger.warning(f"[PreListingPredictor] 시황 자동 판단 실패: {e}")
                market_condition = "neutral"
        
        # 1. 병렬 데이터 조회
        tasks = [
            self._gap_analyzer.analyze(symbol),
            self._fetch_tokenomics(symbol),
        ]
        
        try:
            gap_result, tokenomics = await asyncio.gather(
                *tasks, return_exceptions=True
            )
        except Exception as e:
            logger.error(f"[PreListingPredictor] 데이터 조회 실패: {e}")
            result.warnings.append(f"데이터 조회 실패: {e}")
            return result
        
        # 현선갭 결과 처리
        if isinstance(gap_result, SpotFuturesGapResult):
            result.gap_result = gap_result
        else:
            logger.warning(f"[PreListingPredictor] 현선갭 조회 실패: {gap_result}")
            result.warnings.append("현선갭 조회 실패")
            gap_result = SpotFuturesGapResult(symbol=symbol)
        
        # 토크노믹스 결과 처리
        if isinstance(tokenomics, TokenomicsData):
            result.tokenomics = tokenomics
        else:
            logger.warning(f"[PreListingPredictor] 토크노믹스 조회 실패: {tokenomics}")
            result.warnings.append("토크노믹스 조회 실패")
            tokenomics = TokenomicsData(symbol=symbol)
        
        # 시황 결과 저장 (Phase 1)
        if market_condition_result:
            result.market_condition_result = market_condition_result
        
        # 1.5 핫월렛 분석 (Phase 2) - 선택적 (API 키 필요)
        hot_wallet_result: Optional[HotWalletAnalysisResult] = None
        try:
            hw_analyzer = HotWalletAnalyzer(config_dir=str(self._config_dir))
            hot_wallet_result = await hw_analyzer.analyze_token(symbol)
            await hw_analyzer.close()
            
            if hot_wallet_result.has_data:
                result.hot_wallet_result = hot_wallet_result
                logger.info(
                    "[PreListingPredictor] 핫월렛 분석: $%.0f (%s)",
                    hot_wallet_result.total_exchange_holdings_usd,
                    hot_wallet_result.supply_pressure_tier
                )
        except Exception as e:
            logger.debug(f"[PreListingPredictor] 핫월렛 분석 스킵: {e}")
        
        # 2. 공급 요인 분석 (입금액 예측)
        supply_factors = self._analyze_supply_factors(
            gap_result, tokenomics, symbol, hot_wallet_result
        )
        result.supply_factors = supply_factors
        
        # 3. 수요 요인 분석 (거래량 예측)
        demand_factors = self._analyze_demand_factors(
            tokenomics, market_condition
        )
        result.demand_factors = demand_factors
        
        # 4. 상장 유형 판단 (미지정 시)
        if listing_type == ListingType.UNKNOWN:
            result.listing_type = self._determine_listing_type(
                gap_result, tokenomics
            )
        
        # 5. 흥따리 점수 계산
        heung_score = self._calculate_heung_score(
            supply_factors, demand_factors, result.listing_type
        )
        result.heung_score = heung_score
        
        # 6. 시그널 결정
        result.signal = self._determine_signal(heung_score, supply_factors)
        
        # 7. 권장사항 생성
        result.recommendations = self._generate_recommendations(
            result, supply_factors, demand_factors
        )
        
        # 분석 시간 기록
        result.analysis_duration_ms = (time.monotonic() - start_time) * 1000
        
        return result
    
    async def _fetch_tokenomics(self, symbol: str) -> TokenomicsData:
        """CoinGecko에서 토크노믹스 조회"""
        session = await self._get_session()
        
        result = TokenomicsData(symbol=symbol, timestamp=time.time())
        
        try:
            # CoinGecko 검색
            search_url = "https://api.coingecko.com/api/v3/search"
            async with session.get(search_url, params={"query": symbol}) as resp:
                if resp.status != 200:
                    return result
                data = await resp.json()
            
            coins = data.get("coins", [])
            if not coins:
                return result
            
            # 심볼 일치하는 첫 번째 코인
            coin_id = None
            for coin in coins:
                if coin.get("symbol", "").upper() == symbol:
                    coin_id = coin.get("id")
                    result.name = coin.get("name")
                    break
            
            if not coin_id:
                return result
            
            # 코인 상세 정보 조회
            detail_url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
            async with session.get(detail_url, params={
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
            }) as resp:
                if resp.status != 200:
                    return result
                detail = await resp.json()
            
            market_data = detail.get("market_data", {})
            
            result.market_cap_usd = market_data.get("market_cap", {}).get("usd")
            result.fdv_usd = market_data.get("fully_diluted_valuation", {}).get("usd")
            result.circulating_supply = market_data.get("circulating_supply")
            result.total_supply = market_data.get("total_supply")
            result.max_supply = market_data.get("max_supply")
            result.volume_24h_usd = market_data.get("total_volume", {}).get("usd")
            result.price_usd = market_data.get("current_price", {}).get("usd")
            
            # 유통 비율 계산
            if result.circulating_supply and result.total_supply:
                result.circulating_ratio = (
                    result.circulating_supply / result.total_supply * 100
                )
            
            result.data_source = "coingecko"
            
        except Exception as e:
            logger.warning(f"[PreListingPredictor] CoinGecko 조회 실패 ({symbol}): {e}")
        
        return result
    
    def _analyze_supply_factors(
        self,
        gap_result: SpotFuturesGapResult,
        tokenomics: TokenomicsData,
        symbol: str,
        hot_wallet_result: Optional[HotWalletAnalysisResult] = None,
    ) -> SupplyPressureFactors:
        """공급(입금액) 압력 요인 분석
        
        높은 점수 = 입금 어려움 = 흥따리 유리
        """
        factors = SupplyPressureFactors()
        
        # 1. 현선갭 점수 (갭이 클수록 헷지 어려움 → 입금↓ → 흥따리↑)
        if gap_result.spot_futures_gap_pct is not None:
            factors.spot_futures_gap_pct = gap_result.spot_futures_gap_pct
            gap = abs(gap_result.spot_futures_gap_pct)
            
            if gap >= 5:
                factors.gap_score = 10  # 매우 큰 갭 = 헷지 매우 어려움
            elif gap >= 3:
                factors.gap_score = 7
            elif gap >= 2:
                factors.gap_score = 5
            elif gap >= 1:
                factors.gap_score = 3
            elif gap >= 0.5:
                factors.gap_score = 1
            else:
                factors.gap_score = -2  # 작은 갭 = 헷지 쉬움 = 입금 많아질 수 있음
        
        # 2. 펀딩비 점수 (음펀비면 숏 비용 → 입금↓ → 흥따리↑)
        if gap_result.funding_rate_8h_pct is not None:
            factors.funding_rate_8h_pct = gap_result.funding_rate_8h_pct
            funding = gap_result.funding_rate_8h_pct
            
            if funding <= -0.5:
                factors.funding_score = 8  # 강한 음펀비
            elif funding <= -0.2:
                factors.funding_score = 5
            elif funding <= -0.05:
                factors.funding_score = 2
            elif funding <= 0.1:
                factors.funding_score = 0  # 중립
            else:
                factors.funding_score = -3  # 양펀비 = 숏 유리 = 입금 늘 수 있음
        
        # 3. 헷지 가능성 점수
        factors.hedge_type = gap_result.hedge_type
        if gap_result.hedge_type == HedgeType.NO_HEDGE:
            factors.hedge_score = 10  # 헷지 불가 = 생따리만 가능 = 입금↓
        elif gap_result.hedge_type == HedgeType.DEX_FUTURES:
            factors.hedge_score = 5  # DEX만 = 헷지 어려움
        else:
            factors.hedge_score = 0  # CEX 헷지 가능
        
        # 4. 네트워크 속도 점수
        networks = self._networks.get("networks", {})
        # symbol로 네트워크 추정 (간단 버전)
        if tokenomics.name:
            name_lower = tokenomics.name.lower()
            if "solana" in name_lower or symbol in ["SOL"]:
                factors.network = "solana"
            elif "ethereum" in name_lower or symbol in ["ETH"]:
                factors.network = "ethereum"
            # 더 많은 매핑 추가 가능
        
        if factors.network and factors.network in networks:
            transfer_time = networks[factors.network].get("avg_transfer_min", 5)
            factors.transfer_time_min = transfer_time
            
            if transfer_time >= 30:
                factors.network_score = 10  # 매우 느림 = 후따리 어려움
            elif transfer_time >= 15:
                factors.network_score = 6
            elif transfer_time >= 5:
                factors.network_score = 2
            else:
                factors.network_score = -2  # 빠름 = 입금 쉬움
        
        # 5. 유통량 점수 (낮은 유통률 = 초기 물량 적음 = 입금↓)
        if tokenomics.circulating_ratio is not None:
            factors.circulating_ratio = tokenomics.circulating_ratio
            ratio = tokenomics.circulating_ratio
            
            if ratio <= 10:
                factors.supply_score = 8  # 10% 이하 = 극소 유통
            elif ratio <= 20:
                factors.supply_score = 5
            elif ratio <= 40:
                factors.supply_score = 2
            elif ratio <= 60:
                factors.supply_score = 0
            else:
                factors.supply_score = -3  # 60%+ = 물량 많음
        
        # 6. 핫월렛 물량 점수 (Phase 2) - 물량 적으면 흥따리
        if hot_wallet_result and hot_wallet_result.has_data:
            factors.hot_wallet_holdings_usd = hot_wallet_result.total_exchange_holdings_usd
            factors.hot_wallet_tier = hot_wallet_result.supply_pressure_tier
            # 핫월렛 점수는 반대로 적용 (물량 많으면 망따리 → 점수 낮춤)
            factors.hot_wallet_score = -hot_wallet_result.supply_pressure_score
        
        # 총 공급 점수 (높을수록 흥따리 유리)
        factors.total_supply_score = (
            factors.gap_score +
            factors.funding_score +
            factors.hedge_score +
            factors.network_score +
            factors.supply_score +
            factors.hot_wallet_score  # Phase 2 추가
        )
        
        return factors
    
    def _analyze_demand_factors(
        self,
        tokenomics: TokenomicsData,
        market_condition: str,
    ) -> DemandFactors:
        """수요(거래량) 요인 분석
        
        높은 점수 = 거래량 기대 높음 = 흥따리 유리
        """
        factors = DemandFactors(market_condition=market_condition)
        
        # 1. 시가총액 티어 점수 (저시총이면 펌핑 기대 → 거래량↑)
        if tokenomics.market_cap_usd:
            factors.market_cap_usd = tokenomics.market_cap_usd
            mc = tokenomics.market_cap_usd
            
            for tier, (low, high) in MC_TIERS.items():
                if low <= mc < high:
                    factors.mc_tier = tier
                    break
            
            if factors.mc_tier == "micro":
                factors.mc_score = 8  # 초저시총 = 운전 가능
            elif factors.mc_tier == "low":
                factors.mc_score = 5
            elif factors.mc_tier == "mid":
                factors.mc_score = 2
            elif factors.mc_tier == "high":
                factors.mc_score = -2
            else:  # mega
                factors.mc_score = -5  # 초고시총 = 펌핑 어려움
        
        # 2. 24H 거래량 점수 (높으면 관심도 높음)
        if tokenomics.volume_24h_usd:
            factors.volume_24h_usd = tokenomics.volume_24h_usd
            vol = tokenomics.volume_24h_usd
            
            if vol >= 100_000_000:  # $100M+
                factors.volume_score = 5
            elif vol >= 10_000_000:  # $10M+
                factors.volume_score = 3
            elif vol >= 1_000_000:  # $1M+
                factors.volume_score = 1
            elif vol >= 100_000:  # $100K+
                factors.volume_score = 0
            else:
                factors.volume_score = -3  # 거래량 적음 = 관심 낮음
        
        # 3. 시황 점수
        if market_condition == "bull":
            factors.market_score = 10  # 불장 = 거래량 폭발
        elif market_condition == "neutral":
            factors.market_score = 0
        else:  # bear
            factors.market_score = -5  # 망장 = 거래량↓
        
        # 총 수요 점수
        factors.total_demand_score = (
            factors.mc_score +
            factors.volume_score +
            factors.market_score
        )
        
        return factors
    
    def _determine_listing_type(
        self,
        gap_result: SpotFuturesGapResult,
        tokenomics: TokenomicsData,
    ) -> ListingType:
        """상장 유형 추정"""
        # 선물 없음 + 거래량 없음 → TGE 가능성
        if not gap_result.has_cex_futures and not gap_result.has_dex_futures:
            if tokenomics.volume_24h_usd is None or tokenomics.volume_24h_usd < 100_000:
                return ListingType.TGE
        
        # 선물 존재 → 직상장
        if gap_result.has_cex_futures or gap_result.has_dex_futures:
            return ListingType.DIRECT
        
        return ListingType.UNKNOWN
    
    def _calculate_heung_score(
        self,
        supply: SupplyPressureFactors,
        demand: DemandFactors,
        listing_type: ListingType,
    ) -> float:
        """흥따리 점수 계산 (0~100)
        
        핵심: 거래량 > 입금액 → 흥따리
        점수 = 50 + (수요점수 - 공급점수) * 가중치 + 상장유형 보너스
        """
        base_score = 50
        
        # 공급 낮음(=입금 적음) → 흥따리에 유리 → 점수 상승
        # 수요 높음(=거래량 많음) → 흥따리에 유리 → 점수 상승
        supply_contribution = supply.total_supply_score * 1.5  # 공급 가중치
        demand_contribution = demand.total_demand_score * 1.5  # 수요 가중치
        
        # 상장 유형 보너스
        type_bonus = 0
        if listing_type == ListingType.TGE:
            type_bonus = 10  # TGE는 보통 흥따리 확률 높음
        elif listing_type == ListingType.SIDE:
            type_bonus = -5  # 옆상장은 거래량 적음
        
        score = base_score + supply_contribution + demand_contribution + type_bonus
        
        # 0~100 범위로 제한
        return max(0, min(100, score))
    
    def _determine_signal(
        self,
        heung_score: float,
        supply: SupplyPressureFactors,
    ) -> PredictionSignal:
        """시그널 결정"""
        # 헷지 불가 + 고점수 → STRONG_GO (단, 리스크 있음)
        if supply.hedge_type == HedgeType.NO_HEDGE:
            if heung_score >= 70:
                return PredictionSignal.STRONG_GO
            elif heung_score >= 50:
                return PredictionSignal.GO
        
        # 일반 판단
        if heung_score >= 75:
            return PredictionSignal.STRONG_GO
        elif heung_score >= 60:
            return PredictionSignal.GO
        elif heung_score >= 40:
            return PredictionSignal.NEUTRAL
        elif heung_score >= 25:
            return PredictionSignal.NO_GO
        else:
            return PredictionSignal.STRONG_NO_GO
    
    def _generate_recommendations(
        self,
        result: PreListingPrediction,
        supply: SupplyPressureFactors,
        demand: DemandFactors,
    ) -> List[str]:
        """권장사항 생성"""
        recs = []
        
        # 헷지 관련
        if supply.hedge_type == HedgeType.NO_HEDGE:
            recs.append("⚠️ 선물 없음 - 생따리만 가능 (손절 기준 설정 필수)")
        elif supply.hedge_type == HedgeType.DEX_FUTURES:
            recs.append("⚠️ DEX 선물만 가능 - 슬리피지/청산 주의")
        elif supply.spot_futures_gap_pct and abs(supply.spot_futures_gap_pct) >= 2:
            recs.append(f"📊 현선갭 {supply.spot_futures_gap_pct:+.2f}% - 갭 축소 가능성 고려")
        
        # 펀딩비
        if supply.funding_rate_8h_pct and supply.funding_rate_8h_pct <= -0.2:
            recs.append(f"💰 음펀비 {supply.funding_rate_8h_pct:.4f}% - 빌려서 먹기 전략 검토")
        
        # 시총
        if demand.mc_tier == "micro":
            recs.append("🚀 초저시총 - 운전 가능성, 변동성 주의")
        elif demand.mc_tier == "mega":
            recs.append("📉 고시총 - 알파 제한적, 보수적 접근")
        
        # 유통량
        if supply.circulating_ratio and supply.circulating_ratio <= 15:
            recs.append(f"📦 유통률 {supply.circulating_ratio:.1f}% - 초기 물량 제한적")
        
        # 시황
        if demand.market_condition == "bull":
            recs.append("🔥 불장 - 적극적 참여 고려")
        elif demand.market_condition == "bear":
            recs.append("❄️ 망장 - 보수적 접근 권장")
        
        # 시그널 기반
        if result.signal == PredictionSignal.STRONG_GO:
            recs.append("✅ 흥따리 조건 양호 - 참여 권장")
        elif result.signal == PredictionSignal.STRONG_NO_GO:
            recs.append("❌ 망따리 위험 - 패스 권장")
        
        return recs
    
    def format_prediction(self, result: PreListingPrediction) -> str:
        """예측 결과 포맷팅 (텔레그램 알림용)"""
        lines = []
        
        # 헤더
        signal_emoji = {
            PredictionSignal.STRONG_GO: "🚀🚀",
            PredictionSignal.GO: "🚀",
            PredictionSignal.NEUTRAL: "😐",
            PredictionSignal.NO_GO: "⚠️",
            PredictionSignal.STRONG_NO_GO: "🔴",
        }
        emoji = signal_emoji.get(result.signal, "❓")
        lines.append(f"{emoji} *상장 전 예측: {result.symbol}* @{result.exchange.upper()}")
        lines.append("")
        
        # 흥따리 점수
        score = result.heung_score
        bar_filled = int(score / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines.append(f"📊 흥따리 점수: *{score:.0f}/100* [{bar}]")
        lines.append("")
        
        # 현선갭 정보
        if result.gap_result:
            gap = result.gap_result
            if gap.has_cex_futures:
                lines.append(f"📈 현선갭: *{gap.spot_futures_gap_pct:+.2f}%* ({gap.top_futures_exchange})")
                if gap.funding_rate_8h_pct:
                    lines.append(f"💵 펀딩비(8h): *{gap.funding_rate_8h_pct:+.4f}%*")
                lines.append(f"🛡️ 헷지: {gap.hedge_type.value} ({gap.hedge_difficulty})")
            else:
                lines.append("❌ CEX 선물 없음 - 생따리만 가능")
        lines.append("")
        
        # 토크노믹스
        if result.tokenomics:
            tok = result.tokenomics
            if tok.market_cap_usd:
                mc_str = f"${tok.market_cap_usd/1e6:.1f}M"
                lines.append(f"💰 시총: {mc_str} ({result.demand_factors.mc_tier})")
            if tok.circulating_ratio:
                lines.append(f"📦 유통률: {tok.circulating_ratio:.1f}%")
            if tok.volume_24h_usd:
                vol_str = f"${tok.volume_24h_usd/1e6:.1f}M"
                lines.append(f"📊 24H 거래량: {vol_str}")
        lines.append("")
        
        # 시황 정보 (Phase 1)
        if result.market_condition_result:
            mc = result.market_condition_result
            mc_emoji = {"bull": "🔥", "neutral": "😐", "bear": "❄️"}
            mc_label = {"bull": "불장", "neutral": "보통", "bear": "망장"}
            emoji = mc_emoji.get(mc.condition.value, "❓")
            label = mc_label.get(mc.condition.value, "알수없음")
            lines.append(f"{emoji} 시황: *{label}* (점수: {mc.market_score:+.0f})")
            if mc.upbit_volume_24h_krw:
                lines.append(f"  📊 업비트 24H: {mc.upbit_volume_24h_krw/1e12:.1f}조원")
            if mc.btc_change_24h_pct is not None:
                lines.append(f"  ₿ BTC 24H: {mc.btc_change_24h_pct:+.1f}%")
        lines.append("")
        
        # 핫월렛 정보 (Phase 2)
        if result.hot_wallet_result and result.hot_wallet_result.has_data:
            hw = result.hot_wallet_result
            hw_emoji = {
                "very_low": "🟢", "low": "🟡", "medium": "🟠",
                "high": "🔴", "very_high": "🚨"
            }
            hw_label = {
                "very_low": "매우 적음", "low": "적음", "medium": "보통",
                "high": "많음", "very_high": "매우 많음"
            }
            emoji = hw_emoji.get(hw.supply_pressure_tier, "❓")
            label = hw_label.get(hw.supply_pressure_tier, "알수없음")
            lines.append(f"{emoji} 거래소 보유량: *${hw.total_exchange_holdings_usd:,.0f}* ({label})")
        lines.append("")
        
        # 권장사항
        if result.recommendations:
            lines.append("*💡 권장사항:*")
            for rec in result.recommendations[:3]:  # 최대 3개
                lines.append(f"  {rec}")
        
        return "\n".join(lines)


# 편의 함수
async def predict_listing(
    symbol: str,
    exchange: str = "upbit",
    market_condition: str = "auto",
) -> PreListingPrediction:
    """상장 전 예측 (편의 함수)
    
    Args:
        symbol: 토큰 심볼
        exchange: 상장 예정 거래소
        market_condition: "auto"면 자동 판단, 또는 bull/neutral/bear
    """
    predictor = PreListingPredictor()
    try:
        return await predictor.predict(
            symbol, exchange, market_condition=market_condition
        )
    finally:
        await predictor.close()


# 테스트용
if __name__ == "__main__":
    import sys
    
    async def main():
        symbol = sys.argv[1] if len(sys.argv) > 1 else "SENT"
        exchange = sys.argv[2] if len(sys.argv) > 2 else "bithumb"
        
        predictor = PreListingPredictor()
        try:
            result = await predictor.predict(symbol, exchange, market_condition="auto")
            
            # 콘솔용 출력 (이모지 제외)
            print(f"\n=== {symbol} Pre-Listing Prediction @{exchange} ===")
            print(f"Signal: {result.signal.value}")
            print(f"Heung Score: {result.heung_score:.0f}/100")
            print(f"Listing Type: {result.listing_type.value}")
            print(f"Analysis Time: {result.analysis_duration_ms:.0f}ms")
            
            if result.gap_result:
                gap = result.gap_result
                print(f"\n--- Spot-Futures Gap ---")
                print(f"CEX Futures: {'YES' if gap.has_cex_futures else 'NO'}")
                print(f"Gap: {gap.spot_futures_gap_pct:+.2f}%" if gap.spot_futures_gap_pct else "Gap: N/A")
                print(f"Funding(8h): {gap.funding_rate_8h_pct:+.4f}%" if gap.funding_rate_8h_pct else "Funding: N/A")
                print(f"Hedge: {gap.hedge_type.value} ({gap.hedge_difficulty})")
            
            if result.tokenomics:
                tok = result.tokenomics
                print(f"\n--- Tokenomics ---")
                if tok.market_cap_usd:
                    print(f"Market Cap: ${tok.market_cap_usd/1e6:.1f}M")
                if tok.circulating_ratio:
                    print(f"Circulating: {tok.circulating_ratio:.1f}%")
                if tok.volume_24h_usd:
                    print(f"24H Volume: ${tok.volume_24h_usd/1e6:.1f}M")
            
            if result.supply_factors:
                sf = result.supply_factors
                print(f"\n--- Supply Factors (higher = less supply = bullish) ---")
                print(f"Gap Score: {sf.gap_score}")
                print(f"Funding Score: {sf.funding_score}")
                print(f"Hedge Score: {sf.hedge_score}")
                print(f"Supply Score: {sf.supply_score}")
                print(f"Total: {sf.total_supply_score}")
            
            if result.demand_factors:
                df = result.demand_factors
                print(f"\n--- Demand Factors (higher = more demand = bullish) ---")
                print(f"MC Tier: {df.mc_tier} (score: {df.mc_score})")
                print(f"Volume Score: {df.volume_score}")
                print(f"Market Score: {df.market_score}")
                print(f"Total: {df.total_demand_score}")
            
            if result.warnings:
                print(f"\n--- Warnings ---")
                for w in result.warnings:
                    print(f"  - {w}")
            
            if result.recommendations:
                print(f"\n--- Recommendations ---")
                for r in result.recommendations:
                    # 이모지 제거
                    r_clean = r.encode('ascii', 'ignore').decode('ascii').strip()
                    if r_clean:
                        print(f"  - {r_clean}")
        
        finally:
            await predictor.close()
    
    asyncio.run(main())
