"""AI 기반 공시 분석 모듈 (Phase 3).

Claude API를 사용해서 공시 텍스트를 분석하고,
룰 기반 분석 결과와 크로스체크합니다.

비용 절감:
  - 기본: claude-3-haiku (빠르고 저렴)
  - 복잡한 분석: claude-3-sonnet (정확도 높음)
  
환경변수:
  - ANTHROPIC_API_KEY: Claude API 키
  - AI_ANALYZER_ENABLED: true/false (기본 true)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# API 키 확인
_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
_ENABLED = os.environ.get("AI_ANALYZER_ENABLED", "true").lower() == "true"

# 모델 설정
MODEL_FAST = "claude-3-haiku-20240307"  # 빠르고 저렴
MODEL_SMART = "claude-3-5-sonnet-20241022"  # 정확도 높음


class ListingRisk(Enum):
    """상장 리스크 레벨."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SupplyPressure(Enum):
    """공급 압력."""
    SMOOTH = "smooth"      # 원활 (흥따리 유력)
    MODERATE = "moderate"  # 보통
    TIGHT = "tight"        # 공급 압박 (망따리 주의)
    UNKNOWN = "unknown"


@dataclass
class AIAnalysisResult:
    """AI 분석 결과."""
    
    # 상장 유형
    listing_type: str  # TGE, DIRECT, SIDE
    listing_type_confidence: float  # 0.0 ~ 1.0
    
    # 리스크 평가
    risk_level: ListingRisk
    risk_factors: list[str]
    
    # 공급 압력
    supply_pressure: SupplyPressure
    supply_reasoning: str
    
    # AI 인사이트
    summary: str  # 한 줄 요약
    warnings: list[str]  # 주의사항
    
    # 메타
    model_used: str
    tokens_used: int
    analysis_time_ms: float
    
    # 원본 응답
    raw_response: Optional[dict] = None


class AIAnalyzer:
    """Claude 기반 공시 분석기."""
    
    def __init__(self, api_key: str | None = None):
        """
        Args:
            api_key: Anthropic API 키. None이면 환경변수 사용.
        """
        self._api_key = api_key or _API_KEY
        self._client = None
        
        if not self._api_key:
            logger.warning("[AIAnalyzer] API 키 없음 - AI 분석 비활성화")
        elif not _ENABLED:
            logger.info("[AIAnalyzer] AI 분석 비활성화됨 (AI_ANALYZER_ENABLED=false)")
    
    @property
    def is_available(self) -> bool:
        """AI 분석 가능 여부."""
        return bool(self._api_key and _ENABLED)
    
    def _get_client(self):
        """Anthropic 클라이언트 lazy 초기화."""
        if self._client is None:
            try:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self._api_key)
            except ImportError:
                logger.error("[AIAnalyzer] anthropic 패키지 미설치")
                return None
            except Exception as e:
                logger.error("[AIAnalyzer] 클라이언트 초기화 실패: %s", e)
                return None
        return self._client
    
    async def analyze_announcement(
        self,
        text: str,
        exchange: str,
        symbol: str | None = None,
        use_smart_model: bool = False,
    ) -> AIAnalysisResult | None:
        """공시 텍스트 분석.
        
        Args:
            text: 공시 텍스트 (HTML 또는 plain text).
            exchange: 거래소 (upbit, bithumb).
            symbol: 토큰 심볼 (알면).
            use_smart_model: True면 Sonnet 사용 (더 정확).
            
        Returns:
            AIAnalysisResult 또는 None (실패 시).
        """
        if not self.is_available:
            return None
        
        import time
        t0 = time.monotonic()
        
        client = self._get_client()
        if not client:
            return None
        
        model = MODEL_SMART if use_smart_model else MODEL_FAST
        
        prompt = self._build_prompt(text, exchange, symbol)
        
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                system=self._system_prompt(),
            )
            
            duration_ms = (time.monotonic() - t0) * 1000
            
            # 응답 파싱
            content = response.content[0].text
            result = self._parse_response(content, model, response.usage.input_tokens + response.usage.output_tokens, duration_ms)
            
            logger.info(
                "[AIAnalyzer] 분석 완료: %s@%s, risk=%s, supply=%s, %.0fms",
                symbol or "?", exchange, result.risk_level.value, 
                result.supply_pressure.value, duration_ms
            )
            
            return result
            
        except Exception as e:
            logger.error("[AIAnalyzer] 분석 실패: %s", e)
            return None
    
    def analyze_announcement_sync(
        self,
        text: str,
        exchange: str,
        symbol: str | None = None,
        use_smart_model: bool = False,
    ) -> AIAnalysisResult | None:
        """공시 텍스트 분석 (동기 버전)."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(
            self.analyze_announcement(text, exchange, symbol, use_smart_model)
        )
    
    async def cross_check(
        self,
        rule_result: dict,
        ai_result: AIAnalysisResult,
    ) -> dict:
        """룰 기반 결과와 AI 결과 크로스체크.
        
        Args:
            rule_result: 룰 기반 Gate 분석 결과.
            ai_result: AI 분석 결과.
            
        Returns:
            dict: {
                "agreement": bool,  # 일치 여부
                "confidence": float,  # 최종 신뢰도
                "warnings": list[str],  # 불일치 경고
                "recommendation": str,  # 최종 추천
            }
        """
        warnings = []
        
        # 1. GO/NO-GO 일치 확인
        rule_go = rule_result.get("can_proceed", False)
        ai_risk = ai_result.risk_level
        
        # AI가 HIGH/CRITICAL 리스크인데 룰이 GO면 경고
        if rule_go and ai_risk in (ListingRisk.HIGH, ListingRisk.CRITICAL):
            warnings.append(f"⚠️ AI 경고: {ai_risk.value} 리스크 감지")
        
        # 2. 공급 압력 비교
        rule_supply = rule_result.get("supply_classification", "unknown")
        ai_supply = ai_result.supply_pressure
        
        # 불일치 시 경고
        if "smooth" in str(rule_supply).lower() and ai_supply == SupplyPressure.TIGHT:
            warnings.append("⚠️ AI: 공급 압박 예상 (룰과 불일치)")
        elif "tight" in str(rule_supply).lower() and ai_supply == SupplyPressure.SMOOTH:
            warnings.append("💡 AI: 공급 원활 예상 (룰과 불일치)")
        
        # 3. AI 경고사항 추가
        for w in ai_result.warnings[:2]:
            warnings.append(f"🤖 {w}")
        
        # 4. 최종 신뢰도 계산
        rule_confidence = rule_result.get("confidence", 0.7)
        ai_confidence = ai_result.listing_type_confidence
        
        # 가중 평균 (룰 60%, AI 40%)
        final_confidence = rule_confidence * 0.6 + ai_confidence * 0.4
        
        # 불일치가 많으면 신뢰도 감소
        if len(warnings) > 2:
            final_confidence *= 0.8
        
        # 5. 최종 추천
        if rule_go and not warnings:
            recommendation = "GO - 룰/AI 일치"
        elif rule_go and warnings:
            recommendation = "GO - 주의 필요 (AI 경고)"
        else:
            recommendation = "NO-GO"
        
        return {
            "agreement": len(warnings) == 0,
            "confidence": round(final_confidence, 2),
            "warnings": warnings,
            "recommendation": recommendation,
            "ai_summary": ai_result.summary,
        }
    
    def _system_prompt(self) -> str:
        """시스템 프롬프트."""
        return """당신은 암호화폐 거래소 상장 공시를 분석하는 전문가입니다.

주어진 공시를 분석하고 다음 정보를 JSON 형식으로 반환하세요:

1. listing_type: 상장 유형
   - "TGE": 신규 토큰 발행 (Token Generation Event)
   - "DIRECT": 해외 먼저 상장된 토큰의 국내 직상장
   - "SIDE": 다른 국내 거래소에서 이미 상장된 토큰

2. listing_type_confidence: 유형 판단 신뢰도 (0.0 ~ 1.0)

3. risk_level: 리스크 레벨
   - "low": 리스크 낮음
   - "medium": 보통
   - "high": 주의 필요
   - "critical": 매우 위험

4. risk_factors: 리스크 요소 리스트 (최대 3개)

5. supply_pressure: 공급 압력
   - "smooth": 원활 (매도 압력 낮음, 흥따리 유력)
   - "moderate": 보통
   - "tight": 공급 압박 (에어드랍/언락 물량, 망따리 주의)
   - "unknown": 판단 불가

6. supply_reasoning: 공급 압력 판단 근거 (1문장)

7. summary: 핵심 요약 (1문장, 한국어)

8. warnings: 주의사항 리스트 (최대 2개, 한국어)

JSON만 반환하세요. 다른 텍스트 없이."""
    
    def _build_prompt(self, text: str, exchange: str, symbol: str | None) -> str:
        """분석 프롬프트 생성."""
        symbol_info = f"토큰: {symbol}" if symbol else ""
        
        return f"""다음 {exchange.upper()} 거래소 공시를 분석해주세요.

{symbol_info}

공시 내용:
---
{text[:3000]}
---

위 공시를 분석하고 JSON 형식으로 결과를 반환하세요."""
    
    def _parse_response(
        self, 
        content: str, 
        model: str, 
        tokens: int, 
        duration_ms: float
    ) -> AIAnalysisResult:
        """AI 응답 파싱."""
        try:
            # JSON 추출 (```json ... ``` 형태 처리)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            data = json.loads(content.strip())
            
            return AIAnalysisResult(
                listing_type=data.get("listing_type", "UNKNOWN"),
                listing_type_confidence=float(data.get("listing_type_confidence", 0.5)),
                risk_level=ListingRisk(data.get("risk_level", "medium")),
                risk_factors=data.get("risk_factors", [])[:3],
                supply_pressure=SupplyPressure(data.get("supply_pressure", "unknown")),
                supply_reasoning=data.get("supply_reasoning", ""),
                summary=data.get("summary", ""),
                warnings=data.get("warnings", [])[:2],
                model_used=model,
                tokens_used=tokens,
                analysis_time_ms=duration_ms,
                raw_response=data,
            )
            
        except Exception as e:
            logger.warning("[AIAnalyzer] 응답 파싱 실패: %s", e)
            
            # 기본값 반환
            return AIAnalysisResult(
                listing_type="UNKNOWN",
                listing_type_confidence=0.3,
                risk_level=ListingRisk.MEDIUM,
                risk_factors=["파싱 실패"],
                supply_pressure=SupplyPressure.UNKNOWN,
                supply_reasoning="AI 응답 파싱 실패",
                summary="분석 결과를 파싱할 수 없습니다",
                warnings=["AI 응답 형식 오류"],
                model_used=model,
                tokens_used=tokens,
                analysis_time_ms=duration_ms,
            )


# 싱글톤 인스턴스
_analyzer: AIAnalyzer | None = None


def get_ai_analyzer() -> AIAnalyzer:
    """AI Analyzer 싱글톤 인스턴스."""
    global _analyzer
    if _analyzer is None:
        _analyzer = AIAnalyzer()
    return _analyzer
