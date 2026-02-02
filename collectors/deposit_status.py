"""거래소 입출금 상태 확인 모듈.

상장 전 GO/NO-GO 판단의 중요 요소:
- 입금 Suspended → 물량 공급 불가 → 망따리 위험
- 출금 Suspended → 물량 빼기 불가 (해외 거래소)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum

import aiohttp

logger = logging.getLogger(__name__)


class DepositStatus(Enum):
    """입금 상태."""
    ENABLED = "enabled"      # 입금 가능
    DISABLED = "disabled"    # 입금 불가
    UNKNOWN = "unknown"      # 상태 불명


class WithdrawStatus(Enum):
    """출금 상태."""
    ENABLED = "enabled"      # 출금 가능
    DISABLED = "disabled"    # 출금 불가
    UNKNOWN = "unknown"      # 상태 불명


@dataclass
class NetworkStatus:
    """네트워크별 입출금 상태."""
    network: str              # 네트워크 이름 (ETH, BSC, SOL 등)
    chain: str                # 체인 ID
    deposit_enabled: bool
    withdraw_enabled: bool
    min_confirm: int          # 최소 컨펌 수
    withdraw_fee: float       # 출금 수수료
    withdraw_min: float       # 최소 출금량
    

@dataclass
class CoinDepositInfo:
    """코인 입출금 정보."""
    exchange: str
    symbol: str
    name: str
    networks: list[NetworkStatus]
    timestamp: datetime
    
    @property
    def any_deposit_enabled(self) -> bool:
        """하나라도 입금 가능한 네트워크 있음."""
        return any(n.deposit_enabled for n in self.networks)
    
    @property
    def any_withdraw_enabled(self) -> bool:
        """하나라도 출금 가능한 네트워크 있음."""
        return any(n.withdraw_enabled for n in self.networks)
    
    @property
    def enabled_networks(self) -> list[NetworkStatus]:
        """입출금 모두 가능한 네트워크."""
        return [n for n in self.networks if n.deposit_enabled and n.withdraw_enabled]
    
    @property
    def go_signal(self) -> str:
        """GO/NO-GO 신호.
        
        - GO: 입출금 모두 가능한 네트워크 존재
        - CAUTION: 일부만 가능
        - NO_GO: 모두 불가
        """
        if not self.networks:
            return "UNKNOWN"
        if self.enabled_networks:
            return "GO"
        if self.any_deposit_enabled or self.any_withdraw_enabled:
            return "CAUTION"
        return "NO_GO"


async def get_bithumb_deposit_status(symbol: str) -> Optional[CoinDepositInfo]:
    """빗썸 입출금 상태 조회.
    
    Public API - 인증 불필요!
    https://api.bithumb.com/public/assetsstatus/{currency}
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.bithumb.com/public/assetsstatus/{symbol.upper()}"
            
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if data.get("status") != "0000":
                        return None
                    
                    coin_data = data.get("data", {})
                    
                    # 빗썸은 네트워크 구분 없이 단일 상태만 제공
                    deposit_enabled = coin_data.get("deposit_status") == 1
                    withdraw_enabled = coin_data.get("withdrawal_status") == 1
                    
                    networks = [NetworkStatus(
                        network="default",
                        chain="default",
                        deposit_enabled=deposit_enabled,
                        withdraw_enabled=withdraw_enabled,
                        min_confirm=0,
                        withdraw_fee=0,
                        withdraw_min=0,
                    )]
                    
                    return CoinDepositInfo(
                        exchange="bithumb",
                        symbol=symbol.upper(),
                        name=symbol.upper(),
                        networks=networks,
                        timestamp=datetime.now(),
                    )
                    
    except Exception as e:
        logger.warning(f"Bithumb API error: {e}")
    return None


async def get_bithumb_all_status() -> dict[str, dict]:
    """빗썸 전체 코인 입출금 상태 조회 (캐시용).
    
    Returns:
        {symbol: {"deposit": bool, "withdraw": bool}}
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.bithumb.com/public/assetsstatus/ALL"
            
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if data.get("status") != "0000":
                        return {}
                    
                    result = {}
                    for symbol, status in data.get("data", {}).items():
                        result[symbol.upper()] = {
                            "deposit": status.get("deposit_status") == 1,
                            "withdraw": status.get("withdrawal_status") == 1,
                        }
                    
                    return result
                    
    except Exception as e:
        logger.warning(f"Bithumb ALL API error: {e}")
    return {}


async def get_upbit_deposit_status(
    symbol: str,
    access_key: str = "",
    secret_key: str = "",
) -> Optional[CoinDepositInfo]:
    """업비트 입출금 상태 조회.
    
    Note: 인증 필요! (access_key, secret_key)
    API 키가 없으면 None 반환.
    """
    if not access_key or not secret_key:
        logger.debug("Upbit API requires authentication")
        return None
    
    try:
        import jwt
        import uuid
        import hashlib
        
        payload = {
            'access_key': access_key,
            'nonce': str(uuid.uuid4()),
        }
        jwt_token = jwt.encode(payload, secret_key)
        headers = {"Authorization": f"Bearer {jwt_token}"}
        
        async with aiohttp.ClientSession() as session:
            url = "https://api.upbit.com/v1/status/wallet"
            
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # symbol에 해당하는 코인 찾기
                    for coin in data:
                        if coin.get("currency", "").upper() == symbol.upper():
                            wallet_state = coin.get("wallet_state", "")
                            
                            # wallet_state: working, withdraw_only, deposit_only, paused
                            deposit_enabled = wallet_state in ("working", "deposit_only")
                            withdraw_enabled = wallet_state in ("working", "withdraw_only")
                            
                            # 네트워크별 상태
                            net_type = coin.get("net_type", "default")
                            
                            networks = [NetworkStatus(
                                network=net_type,
                                chain=net_type,
                                deposit_enabled=deposit_enabled,
                                withdraw_enabled=withdraw_enabled,
                                min_confirm=0,
                                withdraw_fee=0,
                                withdraw_min=0,
                            )]
                            
                            return CoinDepositInfo(
                                exchange="upbit",
                                symbol=symbol.upper(),
                                name=coin.get("currency", symbol),
                                networks=networks,
                                timestamp=datetime.now(),
                            )
                    
    except ImportError:
        logger.warning("PyJWT not installed for Upbit auth")
    except Exception as e:
        logger.warning(f"Upbit API error: {e}")
    return None


async def get_binance_deposit_status(symbol: str) -> Optional[CoinDepositInfo]:
    """바이낸스 입출금 상태 조회.
    
    Public API - 인증 불필요!
    https://www.binance.com/bapi/capital/v1/public/capital/getNetworkCoinAll
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://www.binance.com/bapi/capital/v1/public/capital/getNetworkCoinAll"
            
            async with session.get(url, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if data.get("code") != "000000":
                        return None
                    
                    # symbol에 해당하는 코인 찾기
                    for coin in data.get("data", []):
                        if coin.get("coin", "").upper() == symbol.upper():
                            network_list = coin.get("networkList", [])
                            
                            networks = []
                            for net in network_list:
                                networks.append(NetworkStatus(
                                    network=net.get("network", ""),
                                    chain=net.get("networkDisplay", net.get("network", "")),
                                    deposit_enabled=net.get("depositEnable", False),
                                    withdraw_enabled=net.get("withdrawEnable", False),
                                    min_confirm=int(net.get("minConfirm", 0) or 0),
                                    withdraw_fee=float(net.get("withdrawFee", 0) or 0),
                                    withdraw_min=float(net.get("withdrawMin", 0) or 0),
                                ))
                            
                            return CoinDepositInfo(
                                exchange="binance",
                                symbol=symbol.upper(),
                                name=coin.get("name", symbol),
                                networks=networks,
                                timestamp=datetime.now(),
                            )
                    
    except Exception as e:
        logger.warning(f"Binance API error: {e}")
    return None


# 바이낸스 전체 코인 캐시 (5분 TTL)
_binance_cache: dict = {}
_binance_cache_time: float = 0


async def get_binance_all_status() -> dict[str, dict]:
    """바이낸스 전체 코인 입출금 상태 조회 (캐시용).
    
    Returns:
        {symbol: {"deposit": bool, "withdraw": bool, "networks": [...]}}
    """
    global _binance_cache, _binance_cache_time
    import time
    
    now = time.time()
    if now - _binance_cache_time < 300 and _binance_cache:  # 5분 캐시
        return _binance_cache
    
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://www.binance.com/bapi/capital/v1/public/capital/getNetworkCoinAll"
            
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if data.get("code") != "000000":
                        return _binance_cache
                    
                    result = {}
                    for coin in data.get("data", []):
                        symbol = coin.get("coin", "").upper()
                        if not symbol:
                            continue
                        
                        networks = []
                        for net in coin.get("networkList", []):
                            networks.append({
                                "network": net.get("network"),
                                "deposit": net.get("depositEnable", False),
                                "withdraw": net.get("withdrawEnable", False),
                            })
                        
                        result[symbol] = {
                            "deposit": coin.get("depositAllEnable", False),
                            "withdraw": coin.get("withdrawAllEnable", False),
                            "networks": networks,
                        }
                    
                    _binance_cache = result
                    _binance_cache_time = now
                    return result
                    
    except Exception as e:
        logger.warning(f"Binance ALL API error: {e}")
    
    return _binance_cache


async def get_bybit_deposit_status(
    symbol: str,
    api_key: str = "",
    api_secret: str = "",
) -> Optional[CoinDepositInfo]:
    """바이비트 입출금 상태 조회.
    
    Note: API 키 필요! 키 없으면 None 반환.
    환경변수: BYBIT_API_KEY, BYBIT_API_SECRET
    """
    import os
    api_key = api_key or os.environ.get("BYBIT_API_KEY", "")
    
    if not api_key:
        logger.debug("Bybit API requires authentication")
        return None
    
    try:
        import time
        import hmac
        import hashlib
        
        api_secret = api_secret or os.environ.get("BYBIT_API_SECRET", "")
        timestamp = str(int(time.time() * 1000))
        params = {"coin": symbol.upper()}
        param_str = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        sign_str = f"{timestamp}{api_key}{param_str}"
        signature = hmac.new(api_secret.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
        
        headers = {
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
        }
        
        async with aiohttp.ClientSession() as session:
            url = "https://api.bybit.com/v5/asset/coin/query-info"
            
            async with session.get(url, params=params, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if data.get("retCode") != 0:
                        return None
                    
                    rows = data.get("result", {}).get("rows", [])
                    if not rows:
                        return None
                    
                    coin_info = rows[0]
                    chains = coin_info.get("chains", [])
                    
                    networks = []
                    for chain in chains:
                        networks.append(NetworkStatus(
                            network=chain.get("chainType", ""),
                            chain=chain.get("chain", ""),
                            deposit_enabled=chain.get("chainDeposit") == "1",
                            withdraw_enabled=chain.get("chainWithdraw") == "1",
                            min_confirm=int(chain.get("minAccuracy", 0) or 0),
                            withdraw_fee=float(chain.get("withdrawFee", 0) or 0),
                            withdraw_min=float(chain.get("withdrawMin", 0) or 0),
                        ))
                    
                    return CoinDepositInfo(
                        exchange="bybit",
                        symbol=symbol.upper(),
                        name=coin_info.get("name", symbol),
                        networks=networks,
                        timestamp=datetime.now(),
                    )
                    
    except Exception as e:
        logger.warning(f"Bybit API 오류: {e}")
    return None


async def get_okx_deposit_status(symbol: str) -> Optional[CoinDepositInfo]:
    """OKX 입출금 상태 조회.
    
    Public API로 조회 가능!
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://www.okx.com/api/v5/asset/currencies"
            params = {"ccy": symbol.upper()}
            
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if data.get("code") != "0":
                        return None
                    
                    currencies = data.get("data", [])
                    if not currencies:
                        return None
                    
                    networks = []
                    for curr in currencies:
                        networks.append(NetworkStatus(
                            network=curr.get("chain", ""),
                            chain=curr.get("chain", ""),
                            deposit_enabled=curr.get("canDep", False),
                            withdraw_enabled=curr.get("canWd", False),
                            min_confirm=int(curr.get("minDepArrivalConfirm", 0) or 0),
                            withdraw_fee=float(curr.get("minFee", 0) or 0),
                            withdraw_min=float(curr.get("minWd", 0) or 0),
                        ))
                    
                    name = currencies[0].get("name", symbol) if currencies else symbol
                    
                    return CoinDepositInfo(
                        exchange="okx",
                        symbol=symbol.upper(),
                        name=name,
                        networks=networks,
                        timestamp=datetime.now(),
                    )
                    
    except Exception as e:
        logger.warning(f"OKX API 오류: {e}")
    return None


async def get_bitget_deposit_status(symbol: str) -> Optional[CoinDepositInfo]:
    """Bitget 입출금 상태 조회.
    
    Public API로 조회 가능!
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.bitget.com/api/v2/spot/public/coins"
            params = {"coin": symbol.upper()}
            
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if data.get("code") != "00000":
                        return None
                    
                    coins = data.get("data", [])
                    if not coins:
                        return None
                    
                    coin_info = coins[0]
                    chains = coin_info.get("chains", [])
                    
                    networks = []
                    for chain in chains:
                        networks.append(NetworkStatus(
                            network=chain.get("chain", ""),
                            chain=chain.get("chain", ""),
                            deposit_enabled=chain.get("rechargeable") == "true",
                            withdraw_enabled=chain.get("withdrawable") == "true",
                            min_confirm=int(chain.get("depositConfirm", 0) or 0),
                            withdraw_fee=float(chain.get("withdrawFee", 0) or 0),
                            withdraw_min=float(chain.get("minWithdrawAmount", 0) or 0),
                        ))
                    
                    return CoinDepositInfo(
                        exchange="bitget",
                        symbol=symbol.upper(),
                        name=coin_info.get("coinName", symbol),
                        networks=networks,
                        timestamp=datetime.now(),
                    )
                    
    except Exception as e:
        logger.warning(f"Bitget API 오류: {e}")
    return None


async def get_gate_deposit_status(symbol: str) -> Optional[CoinDepositInfo]:
    """Gate.io 입출금 상태 조회.
    
    Public API로 조회 가능!
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.gateio.ws/api/v4/spot/currencies/{symbol.upper()}"
            
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Gate는 단일 체인 정보만 반환
                    networks = [NetworkStatus(
                        network=data.get("chain", ""),
                        chain=data.get("chain", ""),
                        deposit_enabled=not data.get("deposit_disabled", True),
                        withdraw_enabled=not data.get("withdraw_disabled", True),
                        min_confirm=int(data.get("deposit_tag", 0) or 0),
                        withdraw_fee=float(data.get("withdraw_fix_fee", 0) or 0),
                        withdraw_min=float(data.get("min_withdraw_amount", 0) or 0),
                    )]
                    
                    return CoinDepositInfo(
                        exchange="gate",
                        symbol=symbol.upper(),
                        name=data.get("currency", symbol),
                        networks=networks,
                        timestamp=datetime.now(),
                    )
                    
    except Exception as e:
        logger.warning(f"Gate API 오류: {e}")
    return None


async def check_all_exchanges(
    symbol: str,
    include_auth_required: bool = False
) -> dict[str, CoinDepositInfo]:
    """모든 거래소 입출금 상태 병렬 조회.
    
    Args:
        symbol: 토큰 심볼
        include_auth_required: 인증 필요 거래소 포함 여부
        
    Note:
        - Gate: Public API (인증 불필요)
        - Bybit, OKX: 인증 필요 (API 키 설정 시만 사용)
    
    Returns:
        {exchange: CoinDepositInfo}
    """
    # Public API 거래소 (인증 불필요)
    tasks = [
        # 국내
        ("bithumb", get_bithumb_deposit_status(symbol)),
        # 해외 - 주요 5개
        ("binance", get_binance_deposit_status(symbol)),
        ("bybit", get_bybit_deposit_status(symbol)),
        ("okx", get_okx_deposit_status(symbol)),
        ("gate", get_gate_deposit_status(symbol)),
        ("bitget", get_bitget_deposit_status(symbol)),
    ]
    
    # 인증 필요 거래소는 선택적 (현재 없음 - 모두 Public API 사용 가능)
    
    # 업비트는 환경변수에서 키 조회
    import os
    upbit_access = os.environ.get("UPBIT_ACCESS_KEY", "")
    upbit_secret = os.environ.get("UPBIT_SECRET_KEY", "")
    if upbit_access and upbit_secret:
        tasks.append(("upbit", get_upbit_deposit_status(symbol, upbit_access, upbit_secret)))
    
    results = {}
    for exchange, task in tasks:
        try:
            info = await task
            if info:
                results[exchange] = info
        except Exception as e:
            logger.warning(f"{exchange} 조회 실패: {e}")
    
    return results


async def get_deposit_status_quick(symbol: str) -> Optional[CoinDepositInfo]:
    """빠른 입출금 상태 확인 (Gate 단일 조회).
    
    GO/NO-GO 판단용 빠른 체크.
    인증 불필요.
    """
    return await get_gate_deposit_status(symbol)


def format_deposit_report(infos: dict[str, CoinDepositInfo], symbol: str) -> str:
    """입출금 상태 리포트 포맷."""
    if not infos:
        return f"입출금 상태 조회 실패: {symbol}"
    
    lines = [
        f"입출금 상태: {symbol}",
        "",
    ]
    
    for exchange, info in infos.items():
        signal_emoji = {"GO": "[GO]", "CAUTION": "[!]", "NO_GO": "[X]", "UNKNOWN": "[?]"}
        lines.append(f"{exchange.upper()}: {signal_emoji.get(info.go_signal, '?')} {info.go_signal}")
        
        for net in info.networks[:3]:  # 상위 3개 네트워크만
            dep = "O" if net.deposit_enabled else "X"
            wth = "O" if net.withdraw_enabled else "X"
            lines.append(f"  {net.network}: Dep={dep} / Wth={wth}")
        
        if len(info.networks) > 3:
            lines.append(f"  ... +{len(info.networks) - 3} more networks")
        lines.append("")
    
    return "\n".join(lines)


# 테스트
if __name__ == "__main__":
    async def test():
        symbols = ["BTC", "ETH", "AVAIL", "VIRTUAL"]
        for symbol in symbols:
            print(f"\n{'='*50}")
            infos = await check_all_exchanges(symbol)
            print(format_deposit_report(infos, symbol))
    
    asyncio.run(test())
