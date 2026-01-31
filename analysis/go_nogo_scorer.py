"""GO/NO-GO 스코어링 엔진.

상장 전 따리 참여 여부를 자동 판단.
가격 없이 공급/수요 요소만으로 예측.

스코어링 기준 (DDARI_FUNDAMENTALS.md 기반):
- 100점 만점, 70점 이상 = GO
- 각 요소별 가중치 적용
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Signal(Enum):
    """GO/NO-GO 신호."""
    STRONG_GO = "STRONG_GO"      # 🟢🟢 강력 GO (85점+)
    GO = "GO"                     # 🟢 GO (70-84점)
    CAUTION = "CAUTION"           # 🟡 주의 (50-69점)
    NO_GO = "NO_GO"               # 🔴 NO-GO (50점 미만)


@dataclass
class ScoreComponent:
    """개별 스코어 요소."""
    name: str
    score: float           # 0-100 정규화 점수
    weight: float          # 가중치 (0-1)
    weighted_score: float  # score * weight
    signal: str            # GO/CAUTION/NO_GO
    reason: str            # 판단 근거
    raw_value: Optional[str] = None  # 원본 값


@dataclass
class GoNoGoResult:
    """GO/NO-GO 판단 결과."""
    symbol: str
    exchange: str
    total_score: float
    signal: Signal
    components: list[ScoreComponent] = field(default_factory=list)
    summary: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def emoji(self) -> str:
        return {
            Signal.STRONG_GO: "🟢🟢",
            Signal.GO: "🟢",
            Signal.CAUTION: "🟡",
            Signal.NO_GO: "🔴",
        }.get(self.signal, "❓")
    
    @property
    def signal_text(self) -> str:
        return {
            Signal.STRONG_GO: "강력 GO",
            Signal.GO: "GO",
            Signal.CAUTION: "주의",
            Signal.NO_GO: "NO-GO",
        }.get(self.signal, "알 수 없음")


class GoNoGoScorer:
    """GO/NO-GO 스코어링 엔진."""
    
    # 가중치 설정 (합계 = 1.0)
    WEIGHTS = {
        "dex_liquidity": 0.25,      # DEX 유동성 (핵심!)
        "spot_futures_gap": 0.20,   # 현선갭
        "funding_rate": 0.10,       # 펀딩비
        "network_speed": 0.15,      # 네트워크 속도
        "hot_wallet": 0.20,         # 핫월렛 물량 (핵심!)
        "market_condition": 0.10,   # 시황
    }
    
    # 신호 임계값
    STRONG_GO_THRESHOLD = 85
    GO_THRESHOLD = 70
    CAUTION_THRESHOLD = 50
    
    def __init__(self):
        self._components: list[ScoreComponent] = []
    
    async def calculate_score(
        self,
        symbol: str,
        exchange: str = "bithumb",
        dex_liquidity_usd: Optional[float] = None,
        spot_futures_gap_pct: Optional[float] = None,
        funding_rate: Optional[float] = None,
        network_chain: Optional[str] = None,
        hot_wallet_usd: Optional[float] = None,
        market_volume_krw: Optional[float] = None,
        use_ai: bool = True,  # AI 보완 사용 여부
    ) -> GoNoGoResult:
        """GO/NO-GO 스코어 계산.
        
        Args:
            symbol: 토큰 심볼
            exchange: 상장 거래소
            dex_liquidity_usd: DEX 총 유동성 (USD)
            spot_futures_gap_pct: 현선갭 (%)
            funding_rate: 펀딩비 (소수점, 0.0001 = 0.01%)
            network_chain: 네트워크/체인 이름
            hot_wallet_usd: 핫월렛 물량 (USD)
            market_volume_krw: 시장 1분 거래량 (KRW)
            use_ai: AI 데이터 보완 사용 여부
        
        Returns:
            GoNoGoResult
        """
        self._components = []
        
        # AI 데이터 보완 (빈 데이터가 있고 use_ai=True일 때)
        if use_ai and network_chain is None:
            try:
                from analysis.ai_enricher import enrich_token
                token_info = await enrich_token(symbol)
                if token_info:
                    network_chain = token_info.network_chain
                    logger.info(f"AI 보완: {symbol} 체인={network_chain}")
            except Exception as e:
                logger.warning(f"AI 보완 실패: {e}")
        
        # 1. DEX 유동성 스코어
        self._score_dex_liquidity(dex_liquidity_usd)
        
        # 2. 현선갭 스코어
        self._score_spot_futures_gap(spot_futures_gap_pct)
        
        # 3. 펀딩비 스코어
        self._score_funding_rate(funding_rate)
        
        # 4. 네트워크 속도 스코어
        self._score_network_speed(network_chain)
        
        # 5. 핫월렛 물량 스코어
        self._score_hot_wallet(hot_wallet_usd)
        
        # 6. 시황 스코어
        self._score_market_condition(market_volume_krw)
        
        # 총점 계산
        total_score = sum(c.weighted_score for c in self._components)
        
        # 신호 판단
        if total_score >= self.STRONG_GO_THRESHOLD:
            signal = Signal.STRONG_GO
        elif total_score >= self.GO_THRESHOLD:
            signal = Signal.GO
        elif total_score >= self.CAUTION_THRESHOLD:
            signal = Signal.CAUTION
        else:
            signal = Signal.NO_GO
        
        # 요약 생성
        summary = self._generate_summary(total_score, signal)
        
        return GoNoGoResult(
            symbol=symbol,
            exchange=exchange,
            total_score=total_score,
            signal=signal,
            components=self._components.copy(),
            summary=summary,
        )
    
    def _add_component(
        self,
        name: str,
        score: float,
        weight_key: str,
        signal: str,
        reason: str,
        raw_value: Optional[str] = None,
    ):
        """스코어 컴포넌트 추가."""
        weight = self.WEIGHTS.get(weight_key, 0)
        self._components.append(ScoreComponent(
            name=name,
            score=score,
            weight=weight,
            weighted_score=score * weight,
            signal=signal,
            reason=reason,
            raw_value=raw_value,
        ))
    
    def _score_dex_liquidity(self, liquidity_usd: Optional[float]):
        """DEX 유동성 스코어링.
        
        기준:
        - 200k 이하: 100점 (STRONG_GO)
        - 500k 이하: 80점 (GO)
        - 1M 이하: 50점 (CAUTION)
        - 1M 초과: 20점 (NO_GO)
        """
        if liquidity_usd is None:
            self._add_component(
                name="DEX 유동성",
                score=50,  # 데이터 없으면 중립
                weight_key="dex_liquidity",
                signal="UNKNOWN",
                reason="데이터 없음",
            )
            return
        
        if liquidity_usd < 200_000:
            score, signal = 100, "STRONG_GO"
            reason = "유동성 매우 적음 → 후따리 어려움"
        elif liquidity_usd < 500_000:
            score, signal = 80, "GO"
            reason = "유동성 적음 → 흥따리 가능성"
        elif liquidity_usd < 1_000_000:
            score, signal = 50, "CAUTION"
            reason = "유동성 중간 → 주의 필요"
        else:
            score, signal = 20, "NO_GO"
            reason = "유동성 충분 → 후따리 쉬움"
        
        self._add_component(
            name="DEX 유동성",
            score=score,
            weight_key="dex_liquidity",
            signal=signal,
            reason=reason,
            raw_value=f"${liquidity_usd:,.0f}",
        )
    
    def _score_spot_futures_gap(self, gap_pct: Optional[float]):
        """현선갭 스코어링.
        
        기준 (갭이 낮을수록 헷징 쉬움 = NO-GO):
        - 10%+: 100점 (STRONG_GO) - 헷징 비용 과다
        - 5-10%: 80점 (GO)
        - 2-5%: 50점 (CAUTION)
        - 2% 미만: 30점 (NO_GO) - 헷징 쉬움
        """
        if gap_pct is None:
            self._add_component(
                name="현선갭",
                score=50,
                weight_key="spot_futures_gap",
                signal="UNKNOWN",
                reason="데이터 없음",
            )
            return
        
        abs_gap = abs(gap_pct)
        
        if abs_gap >= 10:
            score, signal = 100, "STRONG_GO"
            reason = "갭 매우 큼 → 헷징 어려움 → 공급 제약"
        elif abs_gap >= 5:
            score, signal = 80, "GO"
            reason = "갭 큼 → 헷징 비용 부담"
        elif abs_gap >= 2:
            score, signal = 50, "CAUTION"
            reason = "갭 중간"
        else:
            score, signal = 30, "NO_GO"
            reason = "갭 작음 → 헷징 쉬움 → 공급 증가 예상"
        
        self._add_component(
            name="현선갭",
            score=score,
            weight_key="spot_futures_gap",
            signal=signal,
            reason=reason,
            raw_value=f"{gap_pct:+.2f}%",
        )
    
    def _score_funding_rate(self, funding_rate: Optional[float]):
        """펀딩비 스코어링.
        
        기준:
        - 높은 양수 (0.1%+): 70점 - 롱 과다, 조정 가능성
        - 보통 양수: 50점 - 중립
        - 음수: 60점 - 숏 과다, 상승 여력
        """
        if funding_rate is None:
            self._add_component(
                name="펀딩비",
                score=50,
                weight_key="funding_rate",
                signal="UNKNOWN",
                reason="데이터 없음",
            )
            return
        
        rate_pct = funding_rate * 100  # 퍼센트로 변환
        
        if rate_pct >= 0.1:
            score, signal = 40, "CAUTION"
            reason = "펀딩비 높음 → 롱 과다"
        elif rate_pct >= 0.01:
            score, signal = 50, "NEUTRAL"
            reason = "펀딩비 정상"
        elif rate_pct >= -0.01:
            score, signal = 60, "GO"
            reason = "펀딩비 중립~음수"
        else:
            score, signal = 70, "GO"
            reason = "펀딩비 음수 → 숏 과다 → 상승 여력"
        
        self._add_component(
            name="펀딩비",
            score=score,
            weight_key="funding_rate",
            signal=signal,
            reason=reason,
            raw_value=f"{rate_pct:.4f}%",
        )
    
    def _score_network_speed(self, chain: Optional[str]):
        """네트워크 속도 스코어링.
        
        기준 (느릴수록 GO):
        - 자체메인넷/POW: 100점 (STRONG_GO)
        - 이더리움: 80점 (GO)
        - L2 (Base, OP 등): 60점 (CAUTION)
        - 솔라나/빠른 체인: 30점 (NO_GO)
        """
        if chain is None:
            self._add_component(
                name="네트워크 속도",
                score=50,
                weight_key="network_speed",
                signal="UNKNOWN",
                reason="데이터 없음",
            )
            return
        
        chain_lower = chain.lower()
        
        # 느린 체인 (GO)
        slow_chains = ["mina", "ckb", "kaspa", "aleph", "qubic", "pow"]
        # 중간 체인
        medium_chains = ["ethereum", "eth", "erc20", "erc-20"]
        # L2 체인 (약간 느림)
        l2_chains = ["base", "optimism", "op", "arbitrum", "arb", "zksync", "scroll", "linea"]
        # 빠른 체인 (NO-GO)
        fast_chains = ["solana", "sol", "bsc", "bnb", "avalanche", "avax", "polygon", "matic", "sui", "aptos"]
        
        if any(c in chain_lower for c in slow_chains):
            score, signal = 100, "STRONG_GO"
            reason = "느린 체인 → 입금 어려움"
        elif any(c in chain_lower for c in medium_chains):
            score, signal = 80, "GO"
            reason = "이더리움 → 입금 시간 적당"
        elif any(c in chain_lower for c in l2_chains):
            score, signal = 60, "CAUTION"
            reason = "L2 체인 → 입금 중간"
        elif any(c in chain_lower for c in fast_chains):
            score, signal = 30, "NO_GO"
            reason = "빠른 체인 → 후따리 쉬움"
        else:
            score, signal = 50, "UNKNOWN"
            reason = f"알 수 없는 체인: {chain}"
        
        self._add_component(
            name="네트워크 속도",
            score=score,
            weight_key="network_speed",
            signal=signal,
            reason=reason,
            raw_value=chain,
        )
    
    def _score_hot_wallet(self, hot_wallet_usd: Optional[float]):
        """핫월렛 물량 스코어링.
        
        기준 (적을수록 GO):
        - 1M 이하: 100점 (STRONG_GO)
        - 5M 이하: 80점 (GO)
        - 20M 이하: 50점 (CAUTION)
        - 20M 초과: 20점 (NO_GO)
        """
        if hot_wallet_usd is None:
            self._add_component(
                name="핫월렛 물량",
                score=50,
                weight_key="hot_wallet",
                signal="UNKNOWN",
                reason="데이터 없음 (Arkham API 필요)",
            )
            return
        
        if hot_wallet_usd < 1_000_000:
            score, signal = 100, "STRONG_GO"
            reason = "물량 매우 적음 → 공급 제약"
        elif hot_wallet_usd < 5_000_000:
            score, signal = 80, "GO"
            reason = "물량 적음"
        elif hot_wallet_usd < 20_000_000:
            score, signal = 50, "CAUTION"
            reason = "물량 중간"
        else:
            score, signal = 20, "NO_GO"
            reason = "물량 많음 → 입금 폭탄 예상"
        
        self._add_component(
            name="핫월렛 물량",
            score=score,
            weight_key="hot_wallet",
            signal=signal,
            reason=reason,
            raw_value=f"${hot_wallet_usd:,.0f}",
        )
    
    def _score_market_condition(self, volume_krw: Optional[float]):
        """시황 스코어링.
        
        기준 (업비트 1분 거래량):
        - 500억+: 100점 (STRONG_GO) - 초불장
        - 200억+: 80점 (GO) - 불장
        - 100억+: 60점 (CAUTION) - 보통
        - 100억 미만: 40점 (NO_GO) - 약세장
        """
        if volume_krw is None:
            self._add_component(
                name="시황",
                score=50,
                weight_key="market_condition",
                signal="UNKNOWN",
                reason="데이터 없음",
            )
            return
        
        volume_billion = volume_krw / 1_000_000_000  # 억 단위
        
        if volume_billion >= 500:
            score, signal = 100, "STRONG_GO"
            reason = f"초불장 ({volume_billion:.0f}억)"
        elif volume_billion >= 200:
            score, signal = 80, "GO"
            reason = f"불장 ({volume_billion:.0f}억)"
        elif volume_billion >= 100:
            score, signal = 60, "CAUTION"
            reason = f"보통 ({volume_billion:.0f}억)"
        else:
            score, signal = 40, "NO_GO"
            reason = f"약세장 ({volume_billion:.0f}억)"
        
        self._add_component(
            name="시황",
            score=score,
            weight_key="market_condition",
            signal=signal,
            reason=reason,
            raw_value=f"₩{volume_krw:,.0f}",
        )
    
    def _generate_summary(self, total_score: float, signal: Signal) -> str:
        """결과 요약 생성."""
        go_factors = [c for c in self._components if c.signal in ("STRONG_GO", "GO")]
        nogo_factors = [c for c in self._components if c.signal == "NO_GO"]
        
        summary_parts = []
        
        if signal in (Signal.STRONG_GO, Signal.GO):
            summary_parts.append(f"✅ {signal.value} 권장")
            if go_factors:
                reasons = [f"{c.name}" for c in go_factors[:3]]
                summary_parts.append(f"긍정: {', '.join(reasons)}")
        else:
            summary_parts.append(f"⚠️ {signal.value}")
            if nogo_factors:
                reasons = [f"{c.name}" for c in nogo_factors[:3]]
                summary_parts.append(f"주의: {', '.join(reasons)}")
        
        return " | ".join(summary_parts)


def format_go_nogo_report(result: GoNoGoResult) -> str:
    """GO/NO-GO 리포트 포맷."""
    lines = [
        f"{'='*50}",
        f"{result.emoji} GO/NO-GO 분석: {result.symbol} @ {result.exchange.upper()}",
        f"{'='*50}",
        f"",
        f"📊 총점: {result.total_score:.1f}/100 → {result.signal_text}",
        f"📝 요약: {result.summary}",
        f"",
        f"{'─'*50}",
        f"세부 스코어:",
    ]
    
    for c in result.components:
        signal_emoji = {"STRONG_GO": "🟢", "GO": "🟢", "CAUTION": "🟡", "NO_GO": "🔴"}.get(c.signal, "⚪")
        raw = f" [{c.raw_value}]" if c.raw_value else ""
        lines.append(f"  {signal_emoji} {c.name}: {c.score:.0f}점{raw}")
        lines.append(f"     └ {c.reason}")
    
    lines.append(f"{'─'*50}")
    lines.append(f"⏰ 분석 시간: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    
    return "\n".join(lines)


# 편의 함수
async def analyze_listing(
    symbol: str,
    exchange: str = "bithumb",
    **kwargs
) -> GoNoGoResult:
    """상장 분석 (통합 함수)."""
    scorer = GoNoGoScorer()
    return await scorer.calculate_score(symbol, exchange, **kwargs)


# 테스트
if __name__ == "__main__":
    async def test():
        # 가상 데이터로 테스트
        result = await analyze_listing(
            symbol="NEWCOIN",
            exchange="bithumb",
            dex_liquidity_usd=300_000,      # 30만 달러 - GO
            spot_futures_gap_pct=7.5,        # 7.5% 갭 - GO
            funding_rate=0.0001,             # 0.01% - 중립
            network_chain="ethereum",        # 이더리움 - GO
            hot_wallet_usd=None,             # 데이터 없음
            market_volume_krw=250_000_000_000,  # 2500억 - GO
        )
        
        print(format_go_nogo_report(result))
    
    asyncio.run(test())
