#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""핫월렛 분석 모듈 (Phase 2).

상장 전 GO/NO-GO 판단용 핫월렛 물량 분석.

핵심 인사이트 (따리 펀더멘탈):
- 핫월렛 물량 적음 → 입금액 ↓ → 흥따리 확률 ↑
- 핫월렛 물량 많음 → 입금액 ↑ → 망따리 위험

사용법:
    analyzer = HotWalletAnalyzer()
    result = await analyzer.analyze_token("SENT", token_addresses={"ethereum": "0x..."})
    print(f"총 거래소 보유량: ${result.total_exchange_holdings_usd:,.0f}")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ExchangeHolding:
    """거래소별 토큰 보유량"""
    exchange: str
    exchange_label: str
    balance_raw: int = 0
    balance_human: float = 0.0
    balance_usd: float = 0.0
    chains_checked: List[str] = field(default_factory=list)


@dataclass
class HotWalletAnalysisResult:
    """핫월렛 분석 결과"""
    symbol: str
    
    # 총 거래소 보유량
    total_exchange_holdings_usd: float = 0.0
    total_exchange_holdings_human: float = 0.0
    
    # 거래소별 상세
    exchange_holdings: List[ExchangeHolding] = field(default_factory=list)
    
    # 공급 압력 점수 (높을수록 물량 많음 = 망따리 위험)
    supply_pressure_score: float = 0.0
    supply_pressure_tier: str = "unknown"  # very_low / low / medium / high / very_high
    
    # 분석 메타
    exchanges_checked: int = 0
    chains_checked: List[str] = field(default_factory=list)
    has_data: bool = False
    error: Optional[str] = None


# 공급 압력 기준 (USD)
SUPPLY_PRESSURE_THRESHOLDS = {
    "very_low": (0, 100_000),           # < $100K (매우 적음 - 흥따리)
    "low": (100_000, 500_000),           # $100K ~ $500K (적음)
    "medium": (500_000, 2_000_000),      # $500K ~ $2M (보통)
    "high": (2_000_000, 10_000_000),     # $2M ~ $10M (많음)
    "very_high": (10_000_000, float('inf')),  # > $10M (매우 많음 - 망따리 위험)
}


class HotWalletAnalyzer:
    """핫월렛 분석기 (Alchemy 기반)"""
    
    def __init__(self, config_dir: str = "config"):
        self._config_dir = Path(config_dir)
        self._hot_wallets = self._load_hot_wallets()
        self._tracker = None  # lazy init
        
    def _load_hot_wallets(self) -> dict:
        """hot_wallets.yaml 로드"""
        path = self._config_dir / "hot_wallets.yaml"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}
    
    async def _get_tracker(self):
        """HotWalletTracker lazy 초기화"""
        if self._tracker is None:
            try:
                from collectors.hot_wallet_tracker import HotWalletTracker
                self._tracker = HotWalletTracker(config_dir=str(self._config_dir))
            except ImportError as e:
                logger.warning(f"[HotWalletAnalyzer] HotWalletTracker import 실패: {e}")
                return None
        return self._tracker
    
    async def close(self):
        """리소스 정리"""
        if self._tracker:
            await self._tracker.close()
    
    async def analyze_token(
        self,
        symbol: str,
        token_addresses: Optional[Dict[str, str]] = None,
        token_price_usd: Optional[float] = None,
        exchanges: Optional[List[str]] = None,
    ) -> HotWalletAnalysisResult:
        """특정 토큰의 거래소 핫월렛 보유량 분석
        
        Args:
            symbol: 토큰 심볼 (e.g., "SENT")
            token_addresses: 체인별 토큰 주소 {"ethereum": "0x...", "arbitrum": "0x..."}
            token_price_usd: 토큰 USD 가격 (없으면 stablecoin만 계산)
            exchanges: 분석할 거래소 목록 (None이면 전체)
            
        Returns:
            HotWalletAnalysisResult
        """
        result = HotWalletAnalysisResult(symbol=symbol.upper())
        
        # 토큰 주소 확인
        if not token_addresses:
            # common_tokens에서 찾기
            token_addresses = self._hot_wallets.get("common_tokens", {}).get(symbol.upper(), {})
            
            # new_listing_tokens에서 찾기
            if not token_addresses:
                token_addresses = self._hot_wallets.get("new_listing_tokens", {}).get(symbol.upper(), {})
        
        if not token_addresses:
            result.error = f"토큰 주소 없음: {symbol}"
            logger.warning(f"[HotWalletAnalyzer] {result.error}")
            return result
        
        # HotWalletTracker 초기화
        tracker = await self._get_tracker()
        if not tracker:
            result.error = "HotWalletTracker 초기화 실패 (Alchemy API 키 필요)"
            return result
        
        # 분석할 거래소 목록
        if exchanges is None:
            exchanges = list(self._hot_wallets.get("exchanges", {}).keys())
        
        result.exchanges_checked = len(exchanges)
        result.chains_checked = list(token_addresses.keys())
        
        # 각 거래소별 잔액 조회
        total_holdings_raw = 0
        total_holdings_human = 0.0
        total_holdings_usd = 0.0
        
        for exchange in exchanges:
            try:
                holding_result = await tracker.get_token_balance_for_symbol(
                    symbol=symbol,
                    exchange=exchange,
                    token_addresses=token_addresses,
                )
                
                if holding_result and holding_result.total_balance_usd > 0:
                    exchange_holding = ExchangeHolding(
                        exchange=exchange,
                        exchange_label=self._hot_wallets.get("exchanges", {}).get(exchange, {}).get("label", exchange),
                        balance_usd=holding_result.total_balance_usd,
                        chains_checked=holding_result.chains_checked,
                    )
                    result.exchange_holdings.append(exchange_holding)
                    total_holdings_usd += holding_result.total_balance_usd
                    result.has_data = True
                    
            except Exception as e:
                logger.debug(f"[HotWalletAnalyzer] {exchange} 조회 실패: {e}")
        
        result.total_exchange_holdings_usd = total_holdings_usd
        
        # 공급 압력 점수 계산
        result.supply_pressure_tier, result.supply_pressure_score = self._calculate_supply_pressure(
            total_holdings_usd
        )
        
        logger.info(
            "[HotWalletAnalyzer] %s: $%.0f (%s, score: %.1f)",
            symbol, total_holdings_usd, result.supply_pressure_tier, result.supply_pressure_score
        )
        
        return result
    
    def _calculate_supply_pressure(self, holdings_usd: float) -> tuple[str, float]:
        """공급 압력 점수 계산
        
        Returns:
            (tier, score) - score는 -10 ~ +10 (높을수록 물량 많음 = 망따리 위험)
        """
        for tier, (low, high) in SUPPLY_PRESSURE_THRESHOLDS.items():
            if low <= holdings_usd < high:
                # 점수 계산 (tier 내 위치 기반)
                if tier == "very_low":
                    score = -8  # 매우 적음 = 흥따리
                elif tier == "low":
                    score = -4
                elif tier == "medium":
                    score = 0
                elif tier == "high":
                    score = 4
                else:  # very_high
                    score = 8  # 매우 많음 = 망따리 위험
                
                return tier, score
        
        return "unknown", 0.0
    
    def add_token_address(self, symbol: str, chain: str, address: str) -> bool:
        """신규 상장 토큰 주소 추가 (메모리 + 파일)
        
        Args:
            symbol: 토큰 심볼
            chain: 체인 이름 (ethereum, arbitrum, ...)
            address: 토큰 컨트랙트 주소
            
        Returns:
            성공 여부
        """
        try:
            symbol = symbol.upper()
            
            # 메모리 업데이트
            if "new_listing_tokens" not in self._hot_wallets:
                self._hot_wallets["new_listing_tokens"] = {}
            
            if symbol not in self._hot_wallets["new_listing_tokens"]:
                self._hot_wallets["new_listing_tokens"][symbol] = {}
            
            self._hot_wallets["new_listing_tokens"][symbol][chain] = address
            
            # 파일 저장
            path = self._config_dir / "hot_wallets.yaml"
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(self._hot_wallets, f, allow_unicode=True, default_flow_style=False)
            
            logger.info(f"[HotWalletAnalyzer] 토큰 주소 추가: {symbol} ({chain}: {address})")
            return True
            
        except Exception as e:
            logger.error(f"[HotWalletAnalyzer] 토큰 주소 추가 실패: {e}")
            return False


# 편의 함수
async def analyze_exchange_holdings(
    symbol: str,
    token_addresses: Optional[Dict[str, str]] = None,
) -> HotWalletAnalysisResult:
    """거래소 핫월렛 보유량 분석 (편의 함수)"""
    analyzer = HotWalletAnalyzer()
    try:
        return await analyzer.analyze_token(symbol, token_addresses)
    finally:
        await analyzer.close()


def format_hot_wallet_result(result: HotWalletAnalysisResult) -> str:
    """핫월렛 분석 결과 포맷팅 (텔레그램용)"""
    if not result.has_data:
        if result.error:
            return f"⚠️ 핫월렛 분석 실패: {result.error}"
        return "⚠️ 핫월렛 데이터 없음"
    
    # 공급 압력 이모지
    pressure_emoji = {
        "very_low": "🟢",
        "low": "🟡",
        "medium": "🟠",
        "high": "🔴",
        "very_high": "🚨",
    }
    emoji = pressure_emoji.get(result.supply_pressure_tier, "❓")
    
    pressure_label = {
        "very_low": "매우 적음 (흥따리 유리)",
        "low": "적음",
        "medium": "보통",
        "high": "많음",
        "very_high": "매우 많음 (망따리 위험)",
    }
    label = pressure_label.get(result.supply_pressure_tier, "알수없음")
    
    lines = [
        f"{emoji} **핫월렛 분석: {result.symbol}**",
        f"💰 거래소 보유량: ${result.total_exchange_holdings_usd:,.0f}",
        f"📊 공급 압력: {label}",
        "",
    ]
    
    # 상위 3개 거래소
    if result.exchange_holdings:
        sorted_holdings = sorted(
            result.exchange_holdings, 
            key=lambda x: x.balance_usd, 
            reverse=True
        )[:3]
        
        lines.append("*거래소별:*")
        for h in sorted_holdings:
            lines.append(f"  • {h.exchange_label}: ${h.balance_usd:,.0f}")
    
    return "\n".join(lines)


# 테스트
if __name__ == "__main__":
    async def main():
        print("=== 핫월렛 분석 테스트 ===\n")
        
        # USDT 테스트 (common_tokens에 있음)
        result = await analyze_exchange_holdings("USDT")
        
        print(f"Symbol: {result.symbol}")
        print(f"Total Holdings: ${result.total_exchange_holdings_usd:,.0f}")
        print(f"Supply Pressure: {result.supply_pressure_tier} (score: {result.supply_pressure_score})")
        print(f"Exchanges Checked: {result.exchanges_checked}")
        print(f"Has Data: {result.has_data}")
        
        if result.exchange_holdings:
            print("\n--- 거래소별 ---")
            for h in sorted(result.exchange_holdings, key=lambda x: x.balance_usd, reverse=True)[:5]:
                print(f"  {h.exchange_label}: ${h.balance_usd:,.0f}")
        
        if result.error:
            print(f"\nError: {result.error}")
    
    asyncio.run(main())
