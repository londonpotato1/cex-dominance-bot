"""AI 데이터 보완 모듈 (Claude API).

빈 데이터 자동 채우기 + 팩트 체크.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Claude API 설정
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-3-haiku-20240307"  # 빠르고 저렴한 모델


@dataclass
class TokenInfo:
    """토큰 정보."""
    symbol: str
    name: Optional[str] = None
    network_chain: Optional[str] = None
    network_speed: Optional[str] = None  # fast, medium, slow
    market_cap_usd: Optional[float] = None
    fdv_usd: Optional[float] = None
    circulating_supply_pct: Optional[float] = None
    description: Optional[str] = None
    category: Optional[str] = None  # DeFi, Gaming, L1, L2, Meme 등
    confidence: float = 0.0  # AI 신뢰도 (0-1)
    source: str = "claude"


@dataclass
class MarketCondition:
    """시장 상황."""
    status: str  # bull, neutral, bear
    description: str
    btc_trend: str
    volume_level: str  # high, medium, low
    confidence: float


class AIEnricher:
    """AI 기반 데이터 보완."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self._cache: dict[str, TokenInfo] = {}
    
    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)
    
    async def _call_claude(self, prompt: str, system: str = "") -> Optional[str]:
        """Claude API 호출."""
        if not self.is_configured:
            logger.warning("ANTHROPIC_API_KEY not configured")
            return None
        
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        
        if system:
            payload["system"] = system
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    ANTHROPIC_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=30,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["content"][0]["text"]
                    else:
                        error = await resp.text()
                        logger.error(f"Claude API error: {resp.status} - {error}")
                        return None
        except Exception as e:
            logger.error(f"Claude API call failed: {e}")
            return None
    
    async def enrich_token_info(self, symbol: str) -> Optional[TokenInfo]:
        """토큰 정보 보완."""
        # 캐시 확인
        cache_key = symbol.upper()
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        system = """You are a crypto data analyst. Provide accurate information about tokens.
Always respond in valid JSON format with these fields:
- name: token full name
- network_chain: primary blockchain (ethereum, solana, bsc, arbitrum, base, optimism, avalanche, polygon, sui, aptos, cosmos, mina, etc.)
- network_speed: "fast" (1-10s), "medium" (10-60s), "slow" (60s+)
- category: DeFi, Gaming, L1, L2, Meme, AI, NFT, etc.
- description: one sentence description
- confidence: 0.0-1.0 how confident you are"""

        prompt = f"""Give me information about the cryptocurrency token: {symbol}

Respond ONLY with valid JSON, no other text:
{{
  "name": "...",
  "network_chain": "...",
  "network_speed": "fast|medium|slow",
  "category": "...",
  "description": "...",
  "confidence": 0.0-1.0
}}"""

        response = await self._call_claude(prompt, system)
        
        if not response:
            return None
        
        try:
            # JSON 파싱
            data = json.loads(response.strip())
            
            info = TokenInfo(
                symbol=symbol.upper(),
                name=data.get("name"),
                network_chain=data.get("network_chain"),
                network_speed=data.get("network_speed"),
                category=data.get("category"),
                description=data.get("description"),
                confidence=float(data.get("confidence", 0.5)),
            )
            
            # 캐시 저장
            self._cache[cache_key] = info
            
            return info
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse Claude response: {e}")
            return None
    
    async def get_market_condition(self) -> Optional[MarketCondition]:
        """현재 시장 상황 분석."""
        system = """You are a crypto market analyst. Analyze current market conditions.
Respond in valid JSON format."""

        prompt = """Analyze the current cryptocurrency market condition (as of today).
Consider: BTC price trend, overall market sentiment, trading volumes.

Respond ONLY with valid JSON:
{
  "status": "bull|neutral|bear",
  "description": "brief description in Korean",
  "btc_trend": "up|sideways|down",
  "volume_level": "high|medium|low",
  "confidence": 0.0-1.0
}"""

        response = await self._call_claude(prompt, system)
        
        if not response:
            return None
        
        try:
            data = json.loads(response.strip())
            
            return MarketCondition(
                status=data.get("status", "neutral"),
                description=data.get("description", ""),
                btc_trend=data.get("btc_trend", "sideways"),
                volume_level=data.get("volume_level", "medium"),
                confidence=float(data.get("confidence", 0.5)),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse market condition: {e}")
            return None
    
    async def fact_check_listing(
        self,
        symbol: str,
        exchange: str,
        claimed_data: dict,
    ) -> dict:
        """상장 데이터 팩트 체크."""
        system = """You are a crypto fact checker. Verify listing information.
Be skeptical and verify claims. Respond in valid JSON."""

        prompt = f"""Fact check this listing information:

Symbol: {symbol}
Exchange: {exchange}
Claimed data: {json.dumps(claimed_data, ensure_ascii=False)}

Verify and respond ONLY with valid JSON:
{{
  "verified": true|false,
  "corrections": {{
    "field_name": "corrected_value or null if correct"
  }},
  "warnings": ["list of concerns"],
  "confidence": 0.0-1.0
}}"""

        response = await self._call_claude(prompt, system)
        
        if not response:
            return {"verified": False, "error": "API call failed"}
        
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            return {"verified": False, "error": "Parse error"}
    
    def clear_cache(self):
        """캐시 초기화."""
        self._cache.clear()


# 싱글톤 인스턴스
enricher = AIEnricher()


# 편의 함수
async def enrich_token(symbol: str) -> Optional[TokenInfo]:
    """토큰 정보 보완."""
    return await enricher.enrich_token_info(symbol)


async def get_market_status() -> Optional[MarketCondition]:
    """시장 상황 조회."""
    return await enricher.get_market_condition()


async def fact_check(symbol: str, exchange: str, data: dict) -> dict:
    """팩트 체크."""
    return await enricher.fact_check_listing(symbol, exchange, data)


# 테스트
if __name__ == "__main__":
    async def test():
        # 토큰 정보 테스트
        info = await enrich_token("SENT")
        if info:
            print(f"Token: {info.name}")
            print(f"Chain: {info.network_chain}")
            print(f"Speed: {info.network_speed}")
            print(f"Category: {info.category}")
            print(f"Confidence: {info.confidence}")
        else:
            print("Failed to get token info (API key needed)")
        
        # 시장 상황 테스트
        market = await get_market_status()
        if market:
            print(f"\nMarket: {market.status}")
            print(f"Description: {market.description}")
        
    asyncio.run(test())
