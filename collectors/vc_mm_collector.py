"""VC/MM 정보 자동 수집기 (Phase 7 Week 3).

데이터 소스:
  - CoinGecko: 프로젝트 기본 정보, 개발자 정보
  - Rootdata: VC 포트폴리오, 펀딩 라운드 (API 키 필요)
  - Messari: 프로젝트 펀딩 정보 (API 키 필요)
  - 수동 YAML: vc_tiers.yaml (Tier 1/2/3 분류)

열화 규칙:
  - API 실패 → 수동 DB fallback
  - 모든 소스 실패 → unknown 반환 (GO 유지)

사용법:
    collector = VCMMCollector()
    info = await collector.collect("XYZ", "xyz-protocol")
    await collector.close()
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from collectors.api_client import (
    ResilientHTTPClient,
    ResilientHTTPConfig,
    RateLimiterConfig,
    CircuitBreakerConfig,
)

logger = logging.getLogger(__name__)

# 기본 설정
_CONFIG_DIR = Path(__file__).parent.parent / "data" / "vc_mm_info"
_VC_TIERS_FILE = _CONFIG_DIR / "vc_tiers.yaml"
_MANUAL_DB_FILE = _CONFIG_DIR / "manual_vc_db.yaml"


# =============================================================================
# 데이터 클래스
# =============================================================================


@dataclass
class VCFundingRound:
    """펀딩 라운드 정보."""
    round_type: str                   # "Seed", "Series A", "Private", ...
    amount_usd: float                 # 투자 금액
    date: str                         # 투자 일자 (YYYY-MM-DD)
    investors: list[str] = field(default_factory=list)
    lead_investor: Optional[str] = None


@dataclass
class VCInfo:
    """VC 정보."""
    name: str
    tier: int                         # 1, 2, 3
    avg_listing_roi: float = 0.0      # 평균 상장 ROI (%)
    portfolio_size: int = 0           # 포트폴리오 크기
    notable_projects: list[str] = field(default_factory=list)


@dataclass
class MMInfo:
    """마켓 메이커 정보."""
    name: str
    tier: int                         # 1, 2, 3
    risk_score: float = 0.0           # 조작 위험도 (0-10)
    known_projects: list[str] = field(default_factory=list)
    manipulation_flags: list[str] = field(default_factory=list)


@dataclass
class ProjectVCInfo:
    """프로젝트 VC/MM 정보."""
    symbol: str
    project_name: str

    # 펀딩 정보
    total_funding_usd: float = 0.0
    funding_rounds: list[VCFundingRound] = field(default_factory=list)

    # 투자자 정보
    all_investors: list[str] = field(default_factory=list)
    tier1_investors: list[str] = field(default_factory=list)
    tier2_investors: list[str] = field(default_factory=list)
    tier3_investors: list[str] = field(default_factory=list)

    # MM 정보
    mm_confirmed: bool = False
    mm_name: Optional[str] = None
    mm_risk_score: float = 0.0

    # 메타
    data_source: str = "unknown"      # "coingecko", "rootdata", "manual", "unknown"
    confidence: float = 0.5           # 신뢰도 (0.0 ~ 1.0)
    fetched_at: Optional[datetime] = None

    # Gate 통합용
    has_tier1_vc: bool = False
    vc_risk_level: str = "unknown"    # "low", "medium", "high", "unknown"


# =============================================================================
# VC 티어 분류
# =============================================================================


class VCTierClassifier:
    """VC 티어 분류기.

    Tier 1: 평균 상장 ROI 50%+, 포트폴리오 100개+
    Tier 2: 평균 상장 ROI 20-50%, 포트폴리오 30개+
    Tier 3: 그 외
    """

    # 하드코딩된 Tier 1 VC 리스트 (YAML 로드 실패 시 fallback)
    TIER1_VCS = {
        "Binance Labs", "Polychain Capital", "a16z", "Paradigm",
        "Sequoia Capital", "Founders Fund", "Coinbase Ventures",
        "Pantera Capital", "Digital Currency Group", "Multicoin Capital",
        "Dragonfly Capital", "Framework Ventures", "Electric Capital",
        "Jump Crypto", "Animoca Brands", "Spartan Group",
        "Lightspeed Venture Partners", "Tiger Global", "Coatue Management",
        "Protocol Labs", "Fenbushi Capital", "ConsenSys Ventures",
        "Wintermute Ventures",
    }

    TIER2_VCS = {
        "Hashed", "Galaxy Digital", "Blockchain Capital", "HashKey Capital",
        "OKX Ventures", "Mechanism Capital", "1confirmation", "Variant",
        "Placeholder VC", "Robot Ventures", "Nascent", "IOSG Ventures",
        "Sino Global Capital", "DeFiance Capital", "Amber Group",
        "Hack VC", "CoinFund", "Shima Capital", "Maven 11",
        "Bain Capital Crypto", "LongHash Ventures", "SevenX Ventures",
        "NGC Ventures", "Kenetic Capital", "Foresight Ventures",
        "Republic Capital", "KR1", "gumi Cryptos Capital", "Tribe Capital",
        "CMS Holdings", "Scalar Capital", "White Star Capital", "Ribbit Capital",
    }

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._config_path = config_path or _VC_TIERS_FILE
        self._tier1_vcs: set[str] = set()
        self._tier2_vcs: set[str] = set()
        self._tier3_vcs: set[str] = set()
        self._vc_details: dict[str, VCInfo] = {}
        self._load_config()

    def _load_config(self) -> None:
        """YAML 설정 로드."""
        if not self._config_path.exists():
            logger.warning(
                "[VCTier] 설정 파일 없음, 기본값 사용: %s", self._config_path
            )
            self._tier1_vcs = self.TIER1_VCS.copy()
            self._tier2_vcs = self.TIER2_VCS.copy()
            return

        try:
            with open(self._config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Tier 1 로드
            for vc_data in data.get("tier1", []):
                name = vc_data.get("name", "")
                if name:
                    self._tier1_vcs.add(name)
                    self._vc_details[name] = VCInfo(
                        name=name,
                        tier=1,
                        avg_listing_roi=vc_data.get("avg_listing_roi", 0),
                        portfolio_size=vc_data.get("portfolio_size", 0),
                        notable_projects=vc_data.get("notable", []),
                    )

            # Tier 2 로드
            for vc_data in data.get("tier2", []):
                name = vc_data.get("name", "")
                if name:
                    self._tier2_vcs.add(name)
                    self._vc_details[name] = VCInfo(
                        name=name,
                        tier=2,
                        avg_listing_roi=vc_data.get("avg_listing_roi", 0),
                        portfolio_size=vc_data.get("portfolio_size", 0),
                        notable_projects=vc_data.get("notable", []),
                    )

            # Tier 3 로드
            for vc_data in data.get("tier3", []):
                name = vc_data.get("name", "")
                if name:
                    self._tier3_vcs.add(name)
                    self._vc_details[name] = VCInfo(
                        name=name,
                        tier=3,
                        avg_listing_roi=vc_data.get("avg_listing_roi", 0),
                        portfolio_size=vc_data.get("portfolio_size", 0),
                        notable_projects=vc_data.get("notable", []),
                    )

            logger.info(
                "[VCTier] 설정 로드 완료: Tier1=%d, Tier2=%d, Tier3=%d (총 %d)",
                len(self._tier1_vcs), len(self._tier2_vcs), len(self._tier3_vcs),
                len(self._vc_details),
            )
        except Exception as e:
            logger.warning("[VCTier] 설정 로드 실패, 기본값 사용: %s", e)
            self._tier1_vcs = self.TIER1_VCS.copy()
            self._tier2_vcs = self.TIER2_VCS.copy()

    def classify(self, vc_name: str) -> int:
        """VC 이름으로 티어 분류.

        Returns:
            1, 2, 3 (티어) 또는 0 (알 수 없음)
        """
        # 빈 문자열/공백만 있는 경우 Tier 3
        if not vc_name or not vc_name.strip():
            return 3

        # 정확한 매칭
        if vc_name in self._tier1_vcs or vc_name in self.TIER1_VCS:
            return 1
        if vc_name in self._tier2_vcs or vc_name in self.TIER2_VCS:
            return 2

        # 부분 매칭 (예: "a16z Crypto" → "a16z")
        vc_lower = vc_name.lower()
        for tier1 in self._tier1_vcs | self.TIER1_VCS:
            if tier1.lower() in vc_lower or vc_lower in tier1.lower():
                return 1
        for tier2 in self._tier2_vcs | self.TIER2_VCS:
            if tier2.lower() in vc_lower or vc_lower in tier2.lower():
                return 2

        return 3  # 기본: Tier 3

    def classify_all(self, investors: list[str]) -> tuple[list[str], list[str], list[str]]:
        """투자자 리스트를 티어별로 분류.

        Returns:
            (tier1_list, tier2_list, tier3_list)
        """
        tier1, tier2, tier3 = [], [], []
        for inv in investors:
            tier = self.classify(inv)
            if tier == 1:
                tier1.append(inv)
            elif tier == 2:
                tier2.append(inv)
            else:
                tier3.append(inv)
        return tier1, tier2, tier3

    def get_vc_info(self, vc_name: str) -> Optional[VCInfo]:
        """VC 상세 정보 조회."""
        return self._vc_details.get(vc_name)

    def get_all_vcs(self, tier: Optional[int] = None) -> list[VCInfo]:
        """모든 VC 정보 조회.

        Args:
            tier: 특정 티어만 조회 (1, 2, 3). None이면 전체 조회.

        Returns:
            VCInfo 리스트
        """
        if tier is None:
            return list(self._vc_details.values())
        return [vc for vc in self._vc_details.values() if vc.tier == tier]

    def get_stats(self) -> dict:
        """VC 통계 정보."""
        return {
            "tier1_count": len(self._tier1_vcs),
            "tier2_count": len(self._tier2_vcs),
            "tier3_count": len(self._tier3_vcs),
            "total_count": len(self._vc_details),
        }


# =============================================================================
# MM 분류기
# =============================================================================


class MMClassifier:
    """마켓 메이커 분류기.

    Tier 1: 대형, 신뢰도 높음 (risk_score < 4)
    Tier 2: 중형, 논란/문제 있음 (4 <= risk_score < 7)
    Tier 3: 소형/의심스러움 (risk_score >= 7)
    """

    # 하드코딩된 Tier 1 MM (YAML 로드 실패 시 fallback)
    TIER1_MMS = {
        "Wintermute", "GSR", "Jump Trading", "Cumberland", "B2C2",
        "Jane Street", "Citadel Securities", "Virtu Financial",
        "Flow Traders", "Susquehanna (SIG)", "Two Sigma",
    }

    TIER2_MMS = {
        "Amber Group", "QCP Capital", "Kronos Research", "Auros",
        "DWF Labs", "Kairon Labs", "FBG Capital",
    }

    TIER3_MMS = {
        "Alameda Research", "Gotbit", "MyX", "CLS Global",
    }

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._config_path = config_path or _VC_TIERS_FILE
        self._tier1_mms: set[str] = set()
        self._tier2_mms: set[str] = set()
        self._tier3_mms: set[str] = set()
        self._mm_details: dict[str, MMInfo] = {}
        self._load_config()

    def _load_config(self) -> None:
        """YAML 설정에서 MM 정보 로드."""
        if not self._config_path.exists():
            logger.warning(
                "[MMClassifier] 설정 파일 없음, 기본값 사용: %s", self._config_path
            )
            self._tier1_mms = self.TIER1_MMS.copy()
            self._tier2_mms = self.TIER2_MMS.copy()
            self._tier3_mms = self.TIER3_MMS.copy()
            return

        try:
            with open(self._config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            mm_data = data.get("market_makers", {})

            # Tier 1 MM 로드
            for mm in mm_data.get("tier1", []):
                name = mm.get("name", "")
                if name:
                    self._tier1_mms.add(name)
                    self._mm_details[name] = MMInfo(
                        name=name,
                        tier=1,
                        risk_score=mm.get("risk_score", 2.0),
                        known_projects=mm.get("projects", []),
                        manipulation_flags=mm.get("manipulation_flags", []),
                    )

            # Tier 2 MM 로드
            for mm in mm_data.get("tier2", []):
                name = mm.get("name", "")
                if name:
                    self._tier2_mms.add(name)
                    self._mm_details[name] = MMInfo(
                        name=name,
                        tier=2,
                        risk_score=mm.get("risk_score", 5.0),
                        known_projects=mm.get("projects", []),
                        manipulation_flags=mm.get("manipulation_flags", []),
                    )

            # Tier 3 MM 로드
            for mm in mm_data.get("tier3", []):
                name = mm.get("name", "")
                if name:
                    self._tier3_mms.add(name)
                    self._mm_details[name] = MMInfo(
                        name=name,
                        tier=3,
                        risk_score=mm.get("risk_score", 8.0),
                        known_projects=mm.get("projects", []),
                        manipulation_flags=mm.get("manipulation_flags", []),
                    )

            logger.info(
                "[MMClassifier] 설정 로드 완료: Tier1=%d, Tier2=%d, Tier3=%d (총 %d)",
                len(self._tier1_mms), len(self._tier2_mms), len(self._tier3_mms),
                len(self._mm_details),
            )
        except Exception as e:
            logger.warning("[MMClassifier] 설정 로드 실패, 기본값 사용: %s", e)
            self._tier1_mms = self.TIER1_MMS.copy()
            self._tier2_mms = self.TIER2_MMS.copy()
            self._tier3_mms = self.TIER3_MMS.copy()

    def classify(self, mm_name: str) -> int:
        """MM 이름으로 티어 분류.

        Returns:
            1, 2, 3 (티어) 또는 0 (알 수 없음)
        """
        # 정확한 매칭
        if mm_name in self._tier1_mms or mm_name in self.TIER1_MMS:
            return 1
        if mm_name in self._tier2_mms or mm_name in self.TIER2_MMS:
            return 2
        if mm_name in self._tier3_mms or mm_name in self.TIER3_MMS:
            return 3

        # 부분 매칭
        mm_lower = mm_name.lower()
        for tier1 in self._tier1_mms | self.TIER1_MMS:
            if tier1.lower() in mm_lower or mm_lower in tier1.lower():
                return 1
        for tier2 in self._tier2_mms | self.TIER2_MMS:
            if tier2.lower() in mm_lower or mm_lower in tier2.lower():
                return 2
        for tier3 in self._tier3_mms | self.TIER3_MMS:
            if tier3.lower() in mm_lower or mm_lower in tier3.lower():
                return 3

        return 0  # 알 수 없음

    def get_mm_info(self, mm_name: str) -> Optional[MMInfo]:
        """MM 상세 정보 조회."""
        return self._mm_details.get(mm_name)

    def get_risk_score(self, mm_name: str) -> float:
        """MM 리스크 스코어 조회."""
        info = self.get_mm_info(mm_name)
        if info:
            return info.risk_score

        # 알려지지 않은 MM은 중간 리스크
        tier = self.classify(mm_name)
        if tier == 1:
            return 2.5
        elif tier == 2:
            return 5.0
        elif tier == 3:
            return 7.5
        return 5.0  # 기본값

    def has_manipulation_flags(self, mm_name: str) -> bool:
        """조작 플래그 존재 여부."""
        info = self.get_mm_info(mm_name)
        return bool(info and info.manipulation_flags)

    def get_manipulation_flags(self, mm_name: str) -> list[str]:
        """조작 플래그 조회."""
        info = self.get_mm_info(mm_name)
        return info.manipulation_flags if info else []

    def get_all_mms(self, tier: Optional[int] = None) -> list[MMInfo]:
        """모든 MM 정보 조회."""
        if tier is None:
            return list(self._mm_details.values())
        return [mm for mm in self._mm_details.values() if mm.tier == tier]

    def get_stats(self) -> dict:
        """MM 통계 정보."""
        return {
            "tier1_count": len(self._tier1_mms),
            "tier2_count": len(self._tier2_mms),
            "tier3_count": len(self._tier3_mms),
            "total_count": len(self._mm_details),
        }


# =============================================================================
# VC/MM 수집기
# =============================================================================


class VCMMCollector:
    """VC/MM 정보 수집기.

    다중 소스에서 프로젝트의 VC/MM 정보 수집:
      1. CoinGecko (무료, rate limit 주의)
      2. 수동 DB (manual_vc_db.yaml)
      3. Rootdata API (API 키 필요)

    사용법:
        collector = VCMMCollector()
        info = await collector.collect("XYZ", "xyz-protocol")
        await collector.close()
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        rootdata_api_key: Optional[str] = None,
        client: Optional[ResilientHTTPClient] = None,
    ) -> None:
        self._config_dir = config_dir or _CONFIG_DIR
        self._rootdata_key = rootdata_api_key or os.environ.get("ROOTDATA_API_KEY")

        # VC 티어 분류기
        self._tier_classifier = VCTierClassifier(
            config_path=self._config_dir / "vc_tiers.yaml"
        )

        # MM 분류기
        self._mm_classifier = MMClassifier(
            config_path=self._config_dir / "vc_tiers.yaml"
        )

        # HTTP 클라이언트
        if client:
            self._client = client
            self._owns_client = False
        else:
            self._client = ResilientHTTPClient(
                config=ResilientHTTPConfig(
                    rate_limiter=RateLimiterConfig(
                        tokens_per_second=2.0,  # CoinGecko 무료 한도
                        max_tokens=5.0,         # 버스트 허용
                        name="vc_mm_collector",
                    ),
                    circuit_breaker=CircuitBreakerConfig(
                        failure_threshold=3,
                        recovery_timeout=60.0,
                        name="vc_mm_collector",
                    ),
                    total_timeout=15.0,
                ),
            )
            self._owns_client = True

        # 수동 DB 캐시
        self._manual_db: dict[str, dict] = {}
        self._load_manual_db()

    def _load_manual_db(self) -> None:
        """수동 VC DB 로드."""
        manual_path = self._config_dir / "manual_vc_db.yaml"
        if not manual_path.exists():
            logger.debug("[VCCollector] 수동 DB 없음: %s", manual_path)
            return

        try:
            with open(manual_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._manual_db = data.get("projects", {})
            logger.info(
                "[VCCollector] 수동 DB 로드: %d개 프로젝트",
                len(self._manual_db),
            )
        except Exception as e:
            logger.warning("[VCCollector] 수동 DB 로드 실패: %s", e)

    async def close(self) -> None:
        """리소스 정리."""
        if self._owns_client:
            await self._client.close()

    # =========================================================================
    # MM 관련 메서드
    # =========================================================================

    def get_mm_info(self, mm_name: str) -> Optional[MMInfo]:
        """MM 정보 조회."""
        return self._mm_classifier.get_mm_info(mm_name)

    def get_mm_risk_score(self, mm_name: str) -> float:
        """MM 리스크 스코어 조회."""
        return self._mm_classifier.get_risk_score(mm_name)

    def has_mm_manipulation_flags(self, mm_name: str) -> bool:
        """MM 조작 플래그 존재 여부."""
        return self._mm_classifier.has_manipulation_flags(mm_name)

    def get_mm_manipulation_flags(self, mm_name: str) -> list[str]:
        """MM 조작 플래그 조회."""
        return self._mm_classifier.get_manipulation_flags(mm_name)

    def classify_mm(self, mm_name: str) -> int:
        """MM 티어 분류."""
        return self._mm_classifier.classify(mm_name)

    def get_all_mms(self, tier: Optional[int] = None) -> list[MMInfo]:
        """모든 MM 정보 조회."""
        return self._mm_classifier.get_all_mms(tier)

    def get_mm_stats(self) -> dict:
        """MM 통계 정보."""
        return self._mm_classifier.get_stats()

    # =========================================================================
    # VC 관련 메서드
    # =========================================================================

    def get_vc_info(self, vc_name: str) -> Optional[VCInfo]:
        """VC 정보 조회."""
        return self._tier_classifier.get_vc_info(vc_name)

    def classify_vc(self, vc_name: str) -> int:
        """VC 티어 분류."""
        return self._tier_classifier.classify(vc_name)

    def get_all_vcs(self, tier: Optional[int] = None) -> list[VCInfo]:
        """모든 VC 정보 조회."""
        return self._tier_classifier.get_all_vcs(tier)

    def get_vc_stats(self) -> dict:
        """VC 통계 정보."""
        return self._tier_classifier.get_stats()

    # =========================================================================
    # 프로젝트 정보 수집
    # =========================================================================

    async def collect(
        self,
        symbol: str,
        coingecko_id: Optional[str] = None,
    ) -> ProjectVCInfo:
        """프로젝트 VC/MM 정보 수집.

        수집 순서:
          1. 수동 DB 확인
          2. CoinGecko API 조회
          3. (선택) Rootdata API 조회

        Args:
            symbol: 토큰 심볼 (예: "XYZ")
            coingecko_id: CoinGecko ID (예: "xyz-protocol")

        Returns:
            ProjectVCInfo
        """
        symbol_upper = symbol.upper()

        # 1. 수동 DB 확인
        if symbol_upper in self._manual_db:
            logger.info("[VCCollector] 수동 DB에서 로드: %s", symbol_upper)
            return self._parse_manual_entry(symbol_upper)

        # 2. CoinGecko API 조회
        cg_id = coingecko_id or symbol.lower()
        cg_info = await self._fetch_coingecko(cg_id)

        if cg_info:
            logger.info("[VCCollector] CoinGecko에서 로드: %s", symbol_upper)
            return cg_info

        # 3. Rootdata API 조회 (API 키 있으면)
        if self._rootdata_key:
            rd_info = await self._fetch_rootdata(symbol_upper)
            if rd_info:
                logger.info("[VCCollector] Rootdata에서 로드: %s", symbol_upper)
                return rd_info

        # 모든 소스 실패 → unknown 반환
        logger.warning("[VCCollector] 모든 소스 실패: %s", symbol_upper)
        return ProjectVCInfo(
            symbol=symbol_upper,
            project_name=symbol_upper,
            data_source="unknown",
            confidence=0.0,
            fetched_at=datetime.now(),
        )

    def _parse_manual_entry(self, symbol: str) -> ProjectVCInfo:
        """수동 DB 엔트리 파싱."""
        entry = self._manual_db.get(symbol, {})

        investors = entry.get("investors", [])
        tier1, tier2, tier3 = self._tier_classifier.classify_all(investors)

        funding_rounds = []
        for round_data in entry.get("funding_rounds", []):
            funding_rounds.append(VCFundingRound(
                round_type=round_data.get("type", "Unknown"),
                amount_usd=round_data.get("amount_usd", 0),
                date=round_data.get("date", ""),
                investors=round_data.get("investors", []),
                lead_investor=round_data.get("lead"),
            ))

        total_funding = sum(r.amount_usd for r in funding_rounds)

        return ProjectVCInfo(
            symbol=symbol,
            project_name=entry.get("name", symbol),
            total_funding_usd=total_funding,
            funding_rounds=funding_rounds,
            all_investors=investors,
            tier1_investors=tier1,
            tier2_investors=tier2,
            tier3_investors=tier3,
            mm_confirmed=entry.get("mm_confirmed", False),
            mm_name=entry.get("mm_name"),
            mm_risk_score=entry.get("mm_risk_score", 0.0),
            data_source="manual",
            confidence=0.9,  # 수동 입력 = 높은 신뢰도
            fetched_at=datetime.now(),
            has_tier1_vc=len(tier1) > 0,
            vc_risk_level=self._calculate_risk_level(tier1, tier2, entry.get("mm_risk_score", 0)),
        )

    async def _fetch_coingecko(self, cg_id: str) -> Optional[ProjectVCInfo]:
        """CoinGecko API에서 프로젝트 정보 조회."""
        url = f"https://api.coingecko.com/api/v3/coins/{cg_id}"
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "false",
            "community_data": "false",
            "developer_data": "true",  # 개발자 정보에 일부 투자 정보 포함
            "sparkline": "false",
        }

        try:
            data = await self._client.get(url, params=params)
            if not data:
                return None

            symbol = data.get("symbol", cg_id).upper()
            name = data.get("name", symbol)

            # CoinGecko는 직접적인 VC 정보를 제공하지 않음
            # description에서 파싱하거나, 카테고리로 추정
            categories = data.get("categories", [])

            # 카테고리 기반 추정 (매우 제한적)
            estimated_investors = []
            if "Binance Launchpool" in categories:
                estimated_investors.append("Binance Labs")
            if "Coinbase Ventures Portfolio" in categories:
                estimated_investors.append("Coinbase Ventures")
            if "Polychain Capital Portfolio" in categories:
                estimated_investors.append("Polychain Capital")
            if "a16z Portfolio" in categories:
                estimated_investors.append("a16z")
            if "Pantera Capital Portfolio" in categories:
                estimated_investors.append("Pantera Capital")

            tier1, tier2, tier3 = self._tier_classifier.classify_all(estimated_investors)

            return ProjectVCInfo(
                symbol=symbol,
                project_name=name,
                total_funding_usd=0.0,  # CoinGecko에서 제공 안함
                all_investors=estimated_investors,
                tier1_investors=tier1,
                tier2_investors=tier2,
                tier3_investors=tier3,
                data_source="coingecko",
                confidence=0.5 if estimated_investors else 0.3,  # 추정값이므로 낮은 신뢰도
                fetched_at=datetime.now(),
                has_tier1_vc=len(tier1) > 0,
                vc_risk_level=self._calculate_risk_level(tier1, tier2, 0),
            )
        except Exception as e:
            logger.warning("[VCCollector] CoinGecko API 실패: %s - %s", cg_id, e)
            return None

    async def _fetch_rootdata(self, symbol: str) -> Optional[ProjectVCInfo]:
        """Rootdata API에서 펀딩 정보 조회.

        Note: Rootdata API는 실제 엔드포인트 문서 확인 필요.
        여기서는 예상 구조로 구현.
        """
        if not self._rootdata_key:
            return None

        # Rootdata API 엔드포인트 (예상)
        url = "https://api.rootdata.com/v1/project/search"
        headers = {"Authorization": f"Bearer {self._rootdata_key}"}
        params = {"symbol": symbol}

        try:
            data = await self._client.get(url, headers=headers, params=params)
            if not data or not data.get("data"):
                return None

            project = data["data"][0] if isinstance(data["data"], list) else data["data"]

            # 펀딩 라운드 파싱
            funding_rounds = []
            for round_data in project.get("funding_rounds", []):
                investors = round_data.get("investors", [])
                investor_names = [inv.get("name", inv) if isinstance(inv, dict) else inv for inv in investors]

                funding_rounds.append(VCFundingRound(
                    round_type=round_data.get("round_type", "Unknown"),
                    amount_usd=round_data.get("amount", 0),
                    date=round_data.get("date", ""),
                    investors=investor_names,
                    lead_investor=round_data.get("lead_investor"),
                ))

            # 모든 투자자 수집
            all_investors = set()
            for fr in funding_rounds:
                all_investors.update(fr.investors)
            all_investors = list(all_investors)

            tier1, tier2, tier3 = self._tier_classifier.classify_all(all_investors)
            total_funding = sum(r.amount_usd for r in funding_rounds)

            return ProjectVCInfo(
                symbol=symbol,
                project_name=project.get("name", symbol),
                total_funding_usd=total_funding,
                funding_rounds=funding_rounds,
                all_investors=all_investors,
                tier1_investors=tier1,
                tier2_investors=tier2,
                tier3_investors=tier3,
                data_source="rootdata",
                confidence=0.85,  # API 데이터 = 높은 신뢰도
                fetched_at=datetime.now(),
                has_tier1_vc=len(tier1) > 0,
                vc_risk_level=self._calculate_risk_level(tier1, tier2, 0),
            )
        except Exception as e:
            logger.warning("[VCCollector] Rootdata API 실패: %s - %s", symbol, e)
            return None

    def _calculate_risk_level(
        self,
        tier1: list[str],
        tier2: list[str],
        mm_risk: float,
    ) -> str:
        """VC/MM 리스크 레벨 계산.

        Returns:
            "low", "medium", "high", "unknown"
        """
        # Tier 1 VC 있으면 리스크 낮음
        if len(tier1) >= 2:
            return "low"
        if len(tier1) >= 1:
            return "low" if mm_risk < 5 else "medium"

        # Tier 2 VC만 있으면 중간
        if len(tier2) >= 2:
            return "medium"
        if len(tier2) >= 1:
            return "medium" if mm_risk < 7 else "high"

        # VC 정보 없으면 MM 리스크로 판단
        if mm_risk >= 7:
            return "high"
        if mm_risk >= 4:
            return "medium"

        return "unknown"


# =============================================================================
# 편의 함수
# =============================================================================


async def collect_vc_info(
    symbol: str,
    coingecko_id: Optional[str] = None,
) -> ProjectVCInfo:
    """VC 정보 수집 (편의 함수).

    Args:
        symbol: 토큰 심볼
        coingecko_id: CoinGecko ID (선택)

    Returns:
        ProjectVCInfo
    """
    collector = VCMMCollector()
    try:
        return await collector.collect(symbol, coingecko_id)
    finally:
        await collector.close()


def format_vc_info_text(info: ProjectVCInfo) -> str:
    """VC 정보 텍스트 포맷 (텔레그램/UI용)."""
    lines = [
        f"💼 **{info.symbol} VC/MM 정보**",
        "━━━━━━━━━━━━━━━",
    ]

    # 펀딩 정보
    if info.total_funding_usd > 0:
        lines.append(f"💰 총 펀딩: ${info.total_funding_usd:,.0f}")

    # Tier 1 투자자
    if info.tier1_investors:
        t1_str = ", ".join(info.tier1_investors[:3])
        if len(info.tier1_investors) > 3:
            t1_str += f" +{len(info.tier1_investors) - 3}"
        lines.append(f"⭐ Tier 1: {t1_str}")

    # Tier 2 투자자
    if info.tier2_investors:
        t2_str = ", ".join(info.tier2_investors[:3])
        if len(info.tier2_investors) > 3:
            t2_str += f" +{len(info.tier2_investors) - 3}"
        lines.append(f"🔹 Tier 2: {t2_str}")

    # MM 정보
    if info.mm_confirmed and info.mm_name:
        risk_emoji = "🟢" if info.mm_risk_score < 4 else "🟡" if info.mm_risk_score < 7 else "🔴"
        lines.append(f"{risk_emoji} MM: {info.mm_name} (리스크 {info.mm_risk_score:.1f})")

    # 리스크 레벨
    risk_emoji = {
        "low": "🟢",
        "medium": "🟡",
        "high": "🔴",
        "unknown": "⚪",
    }
    lines.append(f"\n{risk_emoji.get(info.vc_risk_level, '⚪')} 리스크: {info.vc_risk_level.upper()}")

    # 신뢰도
    lines.append(f"📊 신뢰도: {info.confidence*100:.0f}% ({info.data_source})")

    return "\n".join(lines)
