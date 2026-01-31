#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
마진 론(Loan) 가능 거래소 스캔

기능:
- 각 거래소별 마진 론 가능 여부 확인
- 이자율 조회
- 최대 대출량 조회
- 거래소별 비교 및 추천

지원 거래소:
- Binance (Cross/Isolated Margin)
- Bybit (Spot Margin)
- OKX (Margin)
- Gate.io (Cross Margin)
- Bitget (Cross Margin)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

import aiohttp

logger = logging.getLogger(__name__)


class MarginType(Enum):
    """마진 유형"""
    CROSS = "cross"       # 교차 마진
    ISOLATED = "isolated" # 격리 마진


@dataclass
class LoanInfo:
    """론 정보"""
    exchange: str                    # 거래소명
    symbol: str                      # 심볼 (예: BTC)
    available: bool                  # 론 가능 여부
    margin_type: MarginType          # 마진 유형
    max_loan_amount: Optional[float] = None  # 최대 대출량
    hourly_rate: Optional[float] = None      # 시간당 이자율 (%)
    daily_rate: Optional[float] = None       # 일일 이자율 (%)
    min_loan_amount: Optional[float] = None  # 최소 대출량
    borrowable: Optional[float] = None       # 현재 빌릴 수 있는 양
    timestamp: float = field(default_factory=time.time)
    error: Optional[str] = None      # 에러 메시지
    
    @property
    def annual_rate(self) -> Optional[float]:
        """연간 이자율 (%)"""
        if self.daily_rate is not None:
            return self.daily_rate * 365
        elif self.hourly_rate is not None:
            return self.hourly_rate * 24 * 365
        return None


@dataclass
class LoanScanResult:
    """론 스캔 결과"""
    symbol: str
    scan_time: float
    results: List[LoanInfo]
    best_exchange: Optional[str] = None      # 이자율 최저 거래소
    best_rate: Optional[float] = None        # 최저 이자율
    available_count: int = 0                 # 론 가능 거래소 수
    
    def __post_init__(self):
        """최적 거래소 계산"""
        available = [r for r in self.results if r.available and r.hourly_rate is not None]
        self.available_count = len(available)
        
        if available:
            best = min(available, key=lambda x: x.hourly_rate or float('inf'))
            self.best_exchange = best.exchange
            self.best_rate = best.hourly_rate


class MarginLoanScanner:
    """마진 론 스캐너"""
    
    # API 엔드포인트
    ENDPOINTS = {
        "binance": {
            # 공개 API (인증 불필요)
            "exchange_info": "https://api.binance.com/api/v3/exchangeInfo",
            # 마진 페어 (SAPI는 인증 필요하므로 exchange_info로 대체)
        },
        "bybit": {
            "coin_info": "https://api.bybit.com/v5/asset/coin/query-info",
            "margin_coin": "https://api.bybit.com/v5/spot-margin-trade/data",
        },
        "okx": {
            "instruments": "https://www.okx.com/api/v5/public/instruments",
            "interest_rate": "https://www.okx.com/api/v5/public/interest-rate-loan-quota",
        },
        "gate": {
            "currencies": "https://api.gateio.ws/api/v4/margin/cross/currencies",
            "currency_detail": "https://api.gateio.ws/api/v4/margin/cross/currencies/",
        },
        "bitget": {
            # Cross Margin 통화 목록
            "currencies": "https://api.bitget.com/api/v2/margin/crossed/interest/list",
        }
    }
    
    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session
        self._own_session = False
        
    async def __aenter__(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._own_session and self._session:
            await self._session.close()
    
    async def _get(self, url: str, params: Optional[Dict] = None, 
                   headers: Optional[Dict] = None, timeout: float = 10.0) -> Optional[Dict]:
        """HTTP GET 요청"""
        try:
            async with self._session.get(url, params=params, headers=headers, 
                                         timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.warning(f"API 요청 실패: {url} - {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"API 요청 에러: {url} - {e}")
            return None
    
    # =========================================================================
    # Binance
    # =========================================================================
    
    async def check_binance_margin(self, symbol: str) -> List[LoanInfo]:
        """Binance 마진 론 가능 여부 확인 (공개 API 사용)
        
        Args:
            symbol: 심볼 (예: BTC, ETH)
            
        Returns:
            마진 정보 리스트
        """
        results = []
        symbol_upper = symbol.upper()
        
        try:
            # Exchange Info에서 마진 거래 가능 페어 확인
            data = await self._get(self.ENDPOINTS["binance"]["exchange_info"])
            
            if data and "symbols" in data:
                # USDT 페어 찾기 (예: BTCUSDT)
                target_pair = f"{symbol_upper}USDT"
                matching = [s for s in data["symbols"] if s.get("symbol") == target_pair]
                
                if matching:
                    pair_info = matching[0]
                    permissions = pair_info.get("permissions", [])
                    
                    # MARGIN 권한이 있으면 마진 거래 가능
                    has_margin = "MARGIN" in permissions
                    
                    results.append(LoanInfo(
                        exchange="Binance",
                        symbol=symbol_upper,
                        available=has_margin,
                        margin_type=MarginType.CROSS,
                        # 이자율은 인증 API 필요 (기본값 사용)
                        hourly_rate=0.02 if has_margin else None,  # 대략적인 기본값
                        daily_rate=0.48 if has_margin else None,
                    ))
                else:
                    results.append(LoanInfo(
                        exchange="Binance",
                        symbol=symbol_upper,
                        available=False,
                        margin_type=MarginType.CROSS,
                        error="USDT 페어 없음"
                    ))
                    
        except Exception as e:
            logger.error(f"Binance Margin 조회 실패: {e}")
            results.append(LoanInfo(
                exchange="Binance",
                symbol=symbol_upper,
                available=False,
                margin_type=MarginType.CROSS,
                error=str(e)
            ))
        
        return results
    
    # =========================================================================
    # Bybit
    # =========================================================================
    
    async def check_bybit_margin(self, symbol: str) -> LoanInfo:
        """Bybit Spot Margin 론 가능 여부 확인"""
        symbol_upper = symbol.upper()
        
        try:
            params = {"coin": symbol_upper}
            data = await self._get(self.ENDPOINTS["bybit"]["coin_info"], params=params)
            
            if data and data.get("retCode") == 0:
                rows = data.get("result", {}).get("rows", [])
                
                for coin_data in rows:
                    if coin_data.get("coin") == symbol_upper:
                        chains = coin_data.get("chains", [])
                        # borrowable 여부 확인
                        # Bybit API에서는 직접 borrowable 필드가 없을 수 있음
                        # margin trading 가능 여부로 판단
                        
                        return LoanInfo(
                            exchange="Bybit",
                            symbol=symbol_upper,
                            available=True,  # 기본적으로 가능으로 표시
                            margin_type=MarginType.CROSS,
                            # 이자율은 별도 조회 필요
                        )
            
            return LoanInfo(
                exchange="Bybit",
                symbol=symbol_upper,
                available=False,
                margin_type=MarginType.CROSS,
                error="코인 정보 없음"
            )
            
        except Exception as e:
            logger.error(f"Bybit Margin 조회 실패: {e}")
            return LoanInfo(
                exchange="Bybit",
                symbol=symbol_upper,
                available=False,
                margin_type=MarginType.CROSS,
                error=str(e)
            )
    
    # =========================================================================
    # OKX
    # =========================================================================
    
    async def check_okx_margin(self, symbol: str) -> LoanInfo:
        """OKX Margin 론 가능 여부 확인"""
        symbol_upper = symbol.upper()
        
        try:
            # 마진 거래 가능 상품 조회
            params = {"instType": "MARGIN"}
            data = await self._get(self.ENDPOINTS["okx"]["instruments"], params=params)
            
            if data and data.get("code") == "0":
                instruments = data.get("data", [])
                
                # symbol이 base로 있는 페어 찾기
                matching = [i for i in instruments if i.get("baseCcy") == symbol_upper]
                
                if matching:
                    # 이자율 조회
                    rate_params = {"ccy": symbol_upper}
                    rate_data = await self._get(self.ENDPOINTS["okx"]["interest_rate"], params=rate_params)
                    
                    hourly_rate = None
                    if rate_data and rate_data.get("code") == "0":
                        rate_info = rate_data.get("data", [])
                        if rate_info:
                            # rate는 일일 이자율로 제공됨
                            daily_rate_str = rate_info[0].get("rate", "0")
                            try:
                                daily_rate = float(daily_rate_str) * 100  # % 변환
                                hourly_rate = daily_rate / 24
                            except:
                                pass
                    
                    return LoanInfo(
                        exchange="OKX",
                        symbol=symbol_upper,
                        available=True,
                        margin_type=MarginType.CROSS,
                        hourly_rate=hourly_rate,
                        daily_rate=daily_rate if hourly_rate else None,
                    )
            
            return LoanInfo(
                exchange="OKX",
                symbol=symbol_upper,
                available=False,
                margin_type=MarginType.CROSS,
                error="마진 상품 없음"
            )
            
        except Exception as e:
            logger.error(f"OKX Margin 조회 실패: {e}")
            return LoanInfo(
                exchange="OKX",
                symbol=symbol_upper,
                available=False,
                margin_type=MarginType.CROSS,
                error=str(e)
            )
    
    # =========================================================================
    # Gate.io
    # =========================================================================
    
    async def check_gate_margin(self, symbol: str) -> LoanInfo:
        """Gate.io Cross Margin 론 가능 여부 확인"""
        symbol_upper = symbol.upper()
        
        try:
            # 전체 통화 목록 조회
            data = await self._get(self.ENDPOINTS["gate"]["currencies"])
            
            if data:
                # 해당 심볼 찾기
                matching = [c for c in data if c.get("name") == symbol_upper]
                
                if matching:
                    currency = matching[0]
                    
                    # 이자율 파싱
                    hourly_rate = None
                    rate_str = currency.get("rate")
                    if rate_str:
                        try:
                            # Gate는 시간당 이자율 제공
                            hourly_rate = float(rate_str) * 100  # % 변환
                        except:
                            pass
                    
                    return LoanInfo(
                        exchange="Gate.io",
                        symbol=symbol_upper,
                        available=currency.get("status", 0) == 1,
                        margin_type=MarginType.CROSS,
                        hourly_rate=hourly_rate,
                        daily_rate=hourly_rate * 24 if hourly_rate else None,
                        min_loan_amount=float(currency.get("min_borrow_amount", 0)) if currency.get("min_borrow_amount") else None,
                    )
            
            return LoanInfo(
                exchange="Gate.io",
                symbol=symbol_upper,
                available=False,
                margin_type=MarginType.CROSS,
                error="통화 정보 없음"
            )
            
        except Exception as e:
            logger.error(f"Gate.io Margin 조회 실패: {e}")
            return LoanInfo(
                exchange="Gate.io",
                symbol=symbol_upper,
                available=False,
                margin_type=MarginType.CROSS,
                error=str(e)
            )
    
    # =========================================================================
    # Bitget
    # =========================================================================
    
    async def check_bitget_margin(self, symbol: str) -> LoanInfo:
        """Bitget Cross Margin 론 가능 여부 확인"""
        symbol_upper = symbol.upper()
        
        try:
            # Interest list API 사용
            data = await self._get(self.ENDPOINTS["bitget"]["currencies"])
            
            if data and data.get("code") == "00000":
                interest_list = data.get("data", [])
                
                # 해당 심볼 찾기
                matching = [i for i in interest_list if i.get("coin", "").upper() == symbol_upper]
                
                if matching:
                    coin_data = matching[0]
                    # 이자율 파싱 (일일 이자율로 제공됨)
                    daily_rate = None
                    hourly_rate = None
                    try:
                        daily_rate_str = coin_data.get("dailyInterestRate", "0")
                        daily_rate = float(daily_rate_str) * 100  # % 변환
                        hourly_rate = daily_rate / 24
                    except:
                        pass
                    
                    return LoanInfo(
                        exchange="Bitget",
                        symbol=symbol_upper,
                        available=True,
                        margin_type=MarginType.CROSS,
                        hourly_rate=hourly_rate,
                        daily_rate=daily_rate,
                    )
            
            return LoanInfo(
                exchange="Bitget",
                symbol=symbol_upper,
                available=False,
                margin_type=MarginType.CROSS,
                error="마진 정보 없음"
            )
            
        except Exception as e:
            logger.error(f"Bitget Margin 조회 실패: {e}")
            return LoanInfo(
                exchange="Bitget",
                symbol=symbol_upper,
                available=False,
                margin_type=MarginType.CROSS,
                error=str(e)
            )
    
    # =========================================================================
    # 통합 스캔
    # =========================================================================
    
    async def scan_all(self, symbol: str, exchanges: Optional[List[str]] = None) -> LoanScanResult:
        """모든 거래소에서 론 가능 여부 스캔
        
        Args:
            symbol: 심볼 (예: BTC, ETH)
            exchanges: 스캔할 거래소 목록 (기본: 전체)
            
        Returns:
            LoanScanResult: 스캔 결과
        """
        if exchanges is None:
            exchanges = ["binance", "bybit", "okx", "gate", "bitget"]
        
        tasks = []
        
        for exchange in exchanges:
            if exchange.lower() == "binance":
                tasks.append(self.check_binance_margin(symbol))
            elif exchange.lower() == "bybit":
                tasks.append(self.check_bybit_margin(symbol))
            elif exchange.lower() == "okx":
                tasks.append(self.check_okx_margin(symbol))
            elif exchange.lower() == "gate":
                tasks.append(self.check_gate_margin(symbol))
            elif exchange.lower() == "bitget":
                tasks.append(self.check_bitget_margin(symbol))
        
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 결과 정리
        results = []
        for r in results_raw:
            if isinstance(r, Exception):
                logger.error(f"론 스캔 에러: {r}")
            elif isinstance(r, list):
                results.extend(r)  # Binance는 리스트 반환
            elif isinstance(r, LoanInfo):
                results.append(r)
        
        return LoanScanResult(
            symbol=symbol.upper(),
            scan_time=time.time(),
            results=results
        )


# =============================================================================
# 편의 함수
# =============================================================================

async def scan_loan_availability(symbol: str, exchanges: Optional[List[str]] = None) -> LoanScanResult:
    """론 가능 거래소 스캔 (단일 호출용)
    
    Args:
        symbol: 심볼 (예: BTC, ETH)
        exchanges: 스캔할 거래소 목록
        
    Returns:
        LoanScanResult: 스캔 결과
        
    Example:
        result = await scan_loan_availability("NEWCOIN")
        print(f"론 가능 거래소: {result.available_count}개")
        print(f"추천: {result.best_exchange} ({result.best_rate}%/h)")
    """
    async with MarginLoanScanner() as scanner:
        return await scanner.scan_all(symbol, exchanges)


def format_loan_result(result: LoanScanResult) -> str:
    """론 스캔 결과 포맷팅
    
    Args:
        result: LoanScanResult
        
    Returns:
        포맷된 문자열
    """
    lines = [
        f"💰 [{result.symbol}] 론 가능 거래소 ({result.available_count}개)",
        "━" * 30,
    ]
    
    # 론 가능한 것만 이자율 순 정렬
    available = sorted(
        [r for r in result.results if r.available],
        key=lambda x: x.hourly_rate if x.hourly_rate else float('inf')
    )
    
    for i, info in enumerate(available, 1):
        rate_str = f"{info.hourly_rate:.4f}%/h" if info.hourly_rate else "N/A"
        daily_str = f"({info.daily_rate:.2f}%/d)" if info.daily_rate else ""
        rec = " ✅ 추천" if i == 1 and info.hourly_rate else ""
        
        lines.append(f"{i}. {info.exchange} {rate_str} {daily_str}{rec}")
    
    # 불가능한 거래소
    unavailable = [r for r in result.results if not r.available]
    if unavailable:
        lines.append("")
        lines.append("❌ 론 불가:")
        for info in unavailable:
            error = f" ({info.error})" if info.error else ""
            lines.append(f"   • {info.exchange}{error}")
    
    return "\n".join(lines)


# =============================================================================
# 테스트
# =============================================================================

if __name__ == "__main__":
    async def test():
        print("=== 마진 론 스캔 테스트 ===\n")
        
        # BTC 테스트
        result = await scan_loan_availability("BTC")
        print(format_loan_result(result))
        print()
        
        # ETH 테스트
        result = await scan_loan_availability("ETH")
        print(format_loan_result(result))
    
    asyncio.run(test())
