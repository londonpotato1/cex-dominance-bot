"""상장 공급 체크 통합 모듈.

원상 공지 시 바로 확인해야 할 것들:
1. 입출금 상태 (국내/해외)
2. 핫월렛 잔액
3. GO/NO-GO 판단

사용법:
    checker = ListingSupplyChecker()
    result = await checker.check_supply("PEPE")
    print(result.summary())
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# .env 로드
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from collectors.deposit_status import (
    get_bithumb_deposit_status,
    get_bithumb_all_status,
    get_upbit_deposit_status,
    get_binance_deposit_status,
    get_bybit_deposit_status,
    get_okx_deposit_status,
    get_gate_deposit_status,
    get_bitget_deposit_status,
    CoinDepositInfo,
)
from collectors.hot_wallet_tracker import HotWalletTracker, HotWalletResult

logger = logging.getLogger(__name__)


@dataclass
class SupplyCheckResult:
    """공급 체크 결과."""
    symbol: str
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 입출금 상태
    deposit_status: dict[str, CoinDepositInfo] = field(default_factory=dict)
    
    # 핫월렛 잔액
    hot_wallet: Optional[HotWalletResult] = None
    
    # 에러
    errors: list[str] = field(default_factory=list)
    
    @property
    def bithumb_ok(self) -> bool:
        """빗썸 입금 가능 여부."""
        info = self.deposit_status.get("bithumb")
        return info.any_deposit_enabled if info else False
    
    @property
    def upbit_ok(self) -> bool:
        """업비트 입금 가능 여부."""
        info = self.deposit_status.get("upbit")
        return info.any_deposit_enabled if info else False
    
    @property
    def foreign_withdraw_ok(self) -> bool:
        """해외 거래소 출금 가능 여부 (하나라도)."""
        for ex in ["binance", "bybit", "okx", "gate", "bitget"]:
            info = self.deposit_status.get(ex)
            if info and info.any_withdraw_enabled:
                return True
        return False
    
    @property
    def hot_wallet_usd(self) -> float:
        """핫월렛 총 잔액 (USD)."""
        return self.hot_wallet.total_balance_usd if self.hot_wallet else 0.0
    
    @property
    def go_signal(self) -> str:
        """GO/NO-GO 신호.
        
        - GO: 입출금 OK + 핫월렛 충분
        - CAUTION: 일부 조건 미충족
        - NO_GO: 주요 조건 실패
        """
        # 국내 입금 불가 → NO_GO
        if not (self.bithumb_ok or self.upbit_ok):
            return "NO_GO"
        
        # 해외 출금 불가 → NO_GO  
        if not self.foreign_withdraw_ok:
            return "NO_GO"
        
        # 핫월렛 잔액 부족 ($100k 미만) → CAUTION
        if self.hot_wallet_usd < 100_000:
            return "CAUTION"
        
        return "GO"
    
    def summary(self) -> str:
        """결과 요약 문자열."""
        lines = [
            f"=== {self.symbol} Supply Check ===",
            f"Time: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Signal: {self.go_signal}",
            "",
            "[Deposit Status]",
        ]
        
        # 국내 거래소
        for ex in ["bithumb", "upbit"]:
            info = self.deposit_status.get(ex)
            if info:
                dep = "O" if info.any_deposit_enabled else "X"
                lines.append(f"  {ex.upper()}: Deposit={dep}")
            else:
                lines.append(f"  {ex.upper()}: (no data)")
        
        # 해외 거래소
        for ex in ["binance", "bybit", "okx", "gate", "bitget"]:
            info = self.deposit_status.get(ex)
            if info:
                dep = "O" if info.any_deposit_enabled else "X"
                wth = "O" if info.any_withdraw_enabled else "X"
                lines.append(f"  {ex.upper()}: Dep={dep} / Wth={wth}")
        
        lines.append("")
        lines.append("[Hot Wallet]")
        if self.hot_wallet:
            lines.append(f"  Total USD: ${self.hot_wallet_usd:,.0f}")
            lines.append(f"  Chains: {', '.join(self.hot_wallet.chains_checked)}")
            for bal in self.hot_wallet.balances[:3]:
                lines.append(f"    {bal.label}: ${bal.balance_usd:,.0f}")
            if len(self.hot_wallet.balances) > 3:
                lines.append(f"    ... +{len(self.hot_wallet.balances) - 3} more")
        else:
            lines.append("  (no data)")
        
        if self.errors:
            lines.append("")
            lines.append("[Errors]")
            for err in self.errors:
                lines.append(f"  - {err}")
        
        return "\n".join(lines)
    
    def to_telegram(self) -> str:
        """텔레그램 알림용 포맷."""
        signal_emoji = {"GO": "🟢", "CAUTION": "🟡", "NO_GO": "🔴"}.get(self.go_signal, "⚪")
        
        lines = [
            f"{signal_emoji} **{self.symbol}** Supply Check",
            "",
        ]
        
        # 국내 입금
        bithumb_emoji = "✅" if self.bithumb_ok else "❌"
        upbit_emoji = "✅" if self.upbit_ok else "❌"
        lines.append(f"국내 입금: 빗썸{bithumb_emoji} 업비트{upbit_emoji}")
        
        # 해외 출금
        foreign_emoji = "✅" if self.foreign_withdraw_ok else "❌"
        lines.append(f"해외 출금: {foreign_emoji}")
        
        # 핫월렛
        if self.hot_wallet_usd > 0:
            lines.append(f"핫월렛: ${self.hot_wallet_usd:,.0f}")
        else:
            lines.append("핫월렛: (조회 실패)")
        
        return "\n".join(lines)


class ListingSupplyChecker:
    """상장 공급 체크 통합 클래스."""
    
    def __init__(
        self,
        upbit_access_key: str = "",
        upbit_secret_key: str = "",
        hot_wallet_tracker: Optional[HotWalletTracker] = None,
    ) -> None:
        import os
        self._upbit_access = upbit_access_key or os.environ.get("UPBIT_ACCESS_KEY", "")
        self._upbit_secret = upbit_secret_key or os.environ.get("UPBIT_SECRET_KEY", "")
        self._hot_wallet_tracker = hot_wallet_tracker
    
    async def check_supply(
        self,
        symbol: str,
        check_hot_wallet: bool = True,
        hot_wallet_exchange: str = "binance",
    ) -> SupplyCheckResult:
        """공급 상태 종합 체크.
        
        Args:
            symbol: 토큰 심볼 (e.g., "PEPE")
            check_hot_wallet: 핫월렛 조회 여부
            hot_wallet_exchange: 핫월렛 조회할 거래소
        
        Returns:
            SupplyCheckResult
        """
        result = SupplyCheckResult(symbol=symbol.upper())
        
        # 입출금 상태 병렬 조회
        tasks = {
            # 국내
            "bithumb": get_bithumb_deposit_status(symbol),
            # 해외 주요 5개
            "binance": get_binance_deposit_status(symbol),
            "bybit": get_bybit_deposit_status(symbol),
            "okx": get_okx_deposit_status(symbol),
            "gate": get_gate_deposit_status(symbol),
            "bitget": get_bitget_deposit_status(symbol),
        }
        
        # 업비트 (인증 있을 때만)
        if self._upbit_access and self._upbit_secret:
            tasks["upbit"] = get_upbit_deposit_status(
                symbol, self._upbit_access, self._upbit_secret
            )
        
        # 병렬 실행
        for exchange, task in tasks.items():
            try:
                info = await task
                if info:
                    result.deposit_status[exchange] = info
            except Exception as e:
                result.errors.append(f"{exchange}: {e}")
        
        # 핫월렛 조회
        if check_hot_wallet and self._hot_wallet_tracker:
            try:
                hw_result = await self._hot_wallet_tracker.get_exchange_balance(
                    hot_wallet_exchange
                )
                result.hot_wallet = hw_result
            except Exception as e:
                result.errors.append(f"hot_wallet: {e}")
        
        return result
    
    async def quick_check(self, symbol: str) -> str:
        """빠른 체크 (텔레그램용)."""
        result = await self.check_supply(symbol, check_hot_wallet=False)
        return result.to_telegram()


# 캐시된 빗썸 전체 상태 (60초 TTL)
_bithumb_cache: dict = {}
_bithumb_cache_time: float = 0


async def get_bithumb_cached_status(symbol: str) -> Optional[dict]:
    """빗썸 입출금 상태 (캐시 사용)."""
    global _bithumb_cache, _bithumb_cache_time
    import time
    
    now = time.time()
    if now - _bithumb_cache_time > 60:  # 60초 캐시
        _bithumb_cache = await get_bithumb_all_status()
        _bithumb_cache_time = now
    
    return _bithumb_cache.get(symbol.upper())


# CLI 테스트
if __name__ == "__main__":
    async def test():
        checker = ListingSupplyChecker()
        
        symbols = ["BTC", "ETH", "PEPE", "VIRTUAL"]
        for symbol in symbols:
            print(f"\n{'='*50}")
            result = await checker.check_supply(symbol, check_hot_wallet=False)
            print(result.summary())
            print()
            print("Telegram format:")
            print(result.to_telegram())
    
    asyncio.run(test())
