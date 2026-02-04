# -*- coding: utf-8 -*-
"""Hot Wallet Token Balance Checker.

거래소 핫월렛의 특정 토큰 잔액을 온체인에서 조회.
"""

from __future__ import annotations

import json
import logging
import requests
from typing import Optional, Dict, List
from decimal import Decimal

logger = logging.getLogger("wallet_balance")

# Public RPC endpoints
RPC_ENDPOINTS = {
    "ethereum": "https://eth.llamarpc.com",
    "bsc": "https://bsc-dataseed1.binance.org",
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "base": "https://mainnet.base.org",
    "optimism": "https://mainnet.optimism.io",
    "polygon": "https://polygon-rpc.com",
    "avalanche": "https://api.avax.network/ext/bc/C/rpc",
    "solana": "https://api.mainnet-beta.solana.com",
}

# ERC-20 balanceOf function signature
BALANCE_OF_SIG = "0x70a08231"  # balanceOf(address)


def get_evm_token_balance(
    wallet_address: str,
    token_contract: str,
    chain: str,
    decimals: int = 18
) -> Optional[float]:
    """EVM 체인에서 토큰 잔액 조회.
    
    Args:
        wallet_address: 지갑 주소
        token_contract: 토큰 컨트랙트 주소
        chain: 체인 이름 (ethereum, bsc, arbitrum, base, etc.)
        decimals: 토큰 소수점 자릿수
    
    Returns:
        토큰 잔액 (float) 또는 None (실패시)
    """
    rpc_url = RPC_ENDPOINTS.get(chain.lower())
    if not rpc_url:
        logger.warning(f"Unknown chain: {chain}")
        return None
    
    # Pad wallet address to 32 bytes
    padded_address = wallet_address.lower().replace("0x", "").zfill(64)
    data = BALANCE_OF_SIG + padded_address
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {
                "to": token_contract,
                "data": data
            },
            "latest"
        ]
    }
    
    try:
        resp = requests.post(rpc_url, json=payload, timeout=10)
        result = resp.json()
        
        if "result" in result and result["result"] != "0x":
            hex_balance = result["result"]
            raw_balance = int(hex_balance, 16)
            balance = raw_balance / (10 ** decimals)
            return balance
        return 0.0
    except Exception as e:
        logger.error(f"EVM balance query failed: {e}")
        return None


def get_solana_token_balance(
    wallet_address: str,
    token_mint: str,
    decimals: int = 9
) -> Optional[float]:
    """Solana에서 SPL 토큰 잔액 조회.
    
    Args:
        wallet_address: 지갑 주소
        token_mint: 토큰 민트 주소
        decimals: 토큰 소수점 자릿수
    
    Returns:
        토큰 잔액 (float) 또는 None (실패시)
    """
    rpc_url = RPC_ENDPOINTS["solana"]
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {"mint": token_mint},
            {"encoding": "jsonParsed"}
        ]
    }
    
    try:
        resp = requests.post(rpc_url, json=payload, timeout=10)
        result = resp.json()
        
        if "result" in result and result["result"]["value"]:
            accounts = result["result"]["value"]
            total_balance = 0.0
            for acc in accounts:
                token_amount = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]
                total_balance += float(token_amount["uiAmount"] or 0)
            return total_balance
        return 0.0
    except Exception as e:
        logger.error(f"Solana balance query failed: {e}")
        return None


def get_token_balance(
    wallet_address: str,
    token_address: str,
    chain: str,
    decimals: int = 18
) -> Optional[float]:
    """체인에 맞는 방법으로 토큰 잔액 조회.
    
    Args:
        wallet_address: 지갑 주소
        token_address: 토큰 주소 (EVM: contract, Solana: mint)
        chain: 체인 이름
        decimals: 토큰 소수점 자릿수
    
    Returns:
        토큰 잔액 또는 None
    """
    chain_lower = chain.lower()
    
    if chain_lower == "solana":
        return get_solana_token_balance(wallet_address, token_address, decimals)
    else:
        return get_evm_token_balance(wallet_address, token_address, chain_lower, decimals)


def get_exchange_token_balance(
    exchange: str,
    token_address: str,
    chain: str,
    decimals: int = 18
) -> Dict[str, float]:
    """거래소의 모든 핫월렛에서 특정 토큰 잔액 합계 조회.
    
    Args:
        exchange: 거래소 이름 (binance, bybit, gate, etc.)
        token_address: 토큰 주소
        chain: 체인 이름
        decimals: 토큰 소수점 자릿수
    
    Returns:
        {"total": 총잔액, "wallets": {주소: 잔액}}
    """
    from .hot_wallet_db import get_hot_wallets
    
    wallets = get_hot_wallets(exchange, chain)
    if not wallets:
        return {"total": 0.0, "wallets": {}, "count": 0}
    
    result = {"total": 0.0, "wallets": {}, "count": len(wallets)}
    
    for wallet in wallets[:5]:  # 최대 5개 지갑만 조회 (rate limit 방지)
        balance = get_token_balance(wallet, token_address, chain, decimals)
        if balance is not None:
            result["wallets"][wallet] = balance
            result["total"] += balance
    
    return result


def format_balance(balance: float, symbol: str = "") -> str:
    """잔액을 읽기 쉬운 형식으로 포맷.
    
    Args:
        balance: 토큰 잔액
        symbol: 토큰 심볼
    
    Returns:
        포맷된 문자열 (예: "1.23M", "456.7K")
    """
    if balance >= 1_000_000_000:
        return f"{balance/1e9:.2f}B {symbol}".strip()
    elif balance >= 1_000_000:
        return f"{balance/1e6:.2f}M {symbol}".strip()
    elif balance >= 1_000:
        return f"{balance/1e3:.2f}K {symbol}".strip()
    elif balance >= 1:
        return f"{balance:,.2f} {symbol}".strip()
    else:
        return f"{balance:.6f} {symbol}".strip()


# 테스트용
if __name__ == "__main__":
    # BIRB on Base (예시)
    # 실제 테스트하려면 token contract 주소 필요
    print("Wallet Balance Module Ready")
