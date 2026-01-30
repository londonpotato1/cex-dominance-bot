"""핫월렛 트래커 테스트 (Phase 7 Week 5 + Week 6).

테스트 범위:
  - HotWalletTracker: 설정 로드, RPC 호출
  - 잔액 조회: native/ERC-20 토큰
  - 에러 처리: API 키 없음, RPC 실패
  - Week 6: 입금 감지, Telegram 알림 포맷, 심볼 매핑
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import os

# 테스트 대상 모듈
from collectors.hot_wallet_tracker import (
    HotWalletTracker,
    HotWalletResult,
    WalletBalance,
    DepositEvent,
    format_deposit_alert,
    get_symbol_from_address,
    _build_reverse_token_map,
    _snapshot_key,
)


# =============================================================================
# HotWalletTracker 테스트
# =============================================================================


class TestHotWalletTrackerInit:
    """HotWalletTracker 초기화 테스트."""

    def test_init_without_api_key(self):
        """API 키 없이 초기화."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("collectors.hot_wallet_tracker.get_api_key", return_value=None):
                tracker = HotWalletTracker(
                    config_dir=Path("/nonexistent/path")
                )
                assert tracker._alchemy_key is None

    def test_init_with_api_key(self):
        """API 키로 초기화."""
        with patch("collectors.hot_wallet_tracker.get_api_key", return_value="test_key"):
            tracker = HotWalletTracker(
                config_dir=Path(__file__).parent.parent / "config"
            )
            assert tracker._alchemy_key == "test_key"

    def test_load_hot_wallets_config(self):
        """hot_wallets.yaml 로드 테스트."""
        config_dir = Path(__file__).parent.parent / "config"
        with patch("collectors.hot_wallet_tracker.get_api_key", return_value="test"):
            tracker = HotWalletTracker(config_dir=config_dir)

        # 설정 파일이 있으면 거래소 데이터 로드됨
        if (config_dir / "hot_wallets.yaml").exists():
            assert "exchanges" in tracker._hot_wallets or tracker._hot_wallets == {}


class TestHotWalletTrackerRPC:
    """RPC 호출 테스트."""

    @pytest.fixture
    def tracker_with_mock_client(self):
        """모의 클라이언트를 사용하는 트래커."""
        mock_client = MagicMock()
        mock_client.post = AsyncMock()

        with patch("collectors.hot_wallet_tracker.get_api_key", return_value="test_key"):
            tracker = HotWalletTracker(
                config_dir=Path(__file__).parent.parent / "config",
                client=mock_client,
            )
        return tracker, mock_client

    @pytest.mark.asyncio
    async def test_get_native_balance_success(self, tracker_with_mock_client):
        """네이티브 잔액 조회 성공."""
        tracker, mock_client = tracker_with_mock_client

        # 모의 RPC 응답 (1 ETH = 10^18 wei)
        mock_client.post.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": "0xDE0B6B3A7640000"  # 1 ETH in hex
        }

        balance = await tracker._get_native_balance(
            "https://eth-mainnet.g.alchemy.com/v2/test",
            "0x1234567890123456789012345678901234567890"
        )

        assert balance == 10 ** 18  # 1 ETH in wei
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_native_balance_failure(self, tracker_with_mock_client):
        """네이티브 잔액 조회 실패."""
        tracker, mock_client = tracker_with_mock_client

        # 모의 RPC 실패 응답
        mock_client.post.return_value = None

        balance = await tracker._get_native_balance(
            "https://eth-mainnet.g.alchemy.com/v2/test",
            "0x1234567890123456789012345678901234567890"
        )

        assert balance is None

    @pytest.mark.asyncio
    async def test_get_token_balance_success(self, tracker_with_mock_client):
        """ERC-20 토큰 잔액 조회 성공."""
        tracker, mock_client = tracker_with_mock_client

        # 모의 RPC 응답 (1000 USDT with 6 decimals = 1000 * 10^6)
        mock_client.post.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": "0x3B9ACA00"  # 1,000,000,000 (1000 USDT)
        }

        balance = await tracker._get_token_balance(
            "https://eth-mainnet.g.alchemy.com/v2/test",
            "0x1234567890123456789012345678901234567890",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7"  # USDT
        )

        assert balance == 1_000_000_000
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_token_balance_zero(self, tracker_with_mock_client):
        """토큰 잔액 0 처리."""
        tracker, mock_client = tracker_with_mock_client

        mock_client.post.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": "0x"  # 잔액 0
        }

        balance = await tracker._get_token_balance(
            "https://eth-mainnet.g.alchemy.com/v2/test",
            "0x1234567890123456789012345678901234567890",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        )

        assert balance == 0


class TestHotWalletTrackerConfig:
    """설정 관련 테스트."""

    def test_get_rpc_url_without_key(self):
        """API 키 없을 때 RPC URL 반환 안 함."""
        with patch("collectors.hot_wallet_tracker.get_api_key", return_value=None):
            tracker = HotWalletTracker(
                config_dir=Path(__file__).parent.parent / "config"
            )
            url = tracker._get_rpc_url("ethereum")
            assert url is None

    def test_get_rpc_url_with_key(self):
        """API 키 있을 때 RPC URL 생성."""
        config_dir = Path(__file__).parent.parent / "config"

        with patch("collectors.hot_wallet_tracker.get_api_key", return_value="test_api_key"):
            tracker = HotWalletTracker(config_dir=config_dir)

            # external_apis.yaml이 있으면 URL 생성
            if (config_dir / "external_apis.yaml").exists():
                url = tracker._get_rpc_url("ethereum")
                if url:
                    assert "test_api_key" in url


class TestHotWalletResult:
    """HotWalletResult 데이터클래스 테스트."""

    def test_result_creation(self):
        """결과 객체 생성."""
        result = HotWalletResult(
            symbol="ETH",
            exchange="binance",
            total_balance_usd=1_000_000.0,
            balances=[
                WalletBalance(
                    address="0x1234",
                    label="Binance 14",
                    chain="ethereum",
                    balance_raw=10 ** 18,
                    balance_usd=2000.0,
                )
            ],
            chains_checked=["ethereum", "arbitrum"],
            confidence=0.95,
        )

        assert result.symbol == "ETH"
        assert result.exchange == "binance"
        assert result.total_balance_usd == 1_000_000.0
        assert len(result.balances) == 1
        assert len(result.chains_checked) == 2
        assert result.confidence == 0.95

    def test_empty_result(self):
        """빈 결과 객체."""
        result = HotWalletResult(
            symbol="UNKNOWN",
            exchange="unknown",
            total_balance_usd=0.0,
            confidence=0.0,
        )

        assert result.total_balance_usd == 0.0
        assert result.confidence == 0.0
        assert result.balances == []
        assert result.chains_checked == []


class TestWalletBalance:
    """WalletBalance 데이터클래스 테스트."""

    def test_native_token_balance(self):
        """네이티브 토큰 잔액."""
        balance = WalletBalance(
            address="0x28C6c06298d514Db089934071355E5743bf21d60",
            label="Binance 14",
            chain="ethereum",
            balance_raw=500 * 10 ** 18,  # 500 ETH
            balance_usd=1_000_000.0,
            token_address="",
            token_symbol="",
        )

        assert balance.token_address == ""
        assert balance.balance_raw == 500 * 10 ** 18

    def test_erc20_token_balance(self):
        """ERC-20 토큰 잔액."""
        balance = WalletBalance(
            address="0x28C6c06298d514Db089934071355E5743bf21d60",
            label="Binance 14",
            chain="ethereum",
            balance_raw=1_000_000 * 10 ** 6,  # 1M USDT
            balance_usd=1_000_000.0,
            token_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            token_symbol="USDT",
        )

        assert balance.token_address != ""
        assert balance.token_symbol == "USDT"


# =============================================================================
# 통합 테스트
# =============================================================================


@pytest.mark.asyncio
async def test_get_exchange_balance_no_api_key():
    """API 키 없을 때 거래소 잔액 조회."""
    with patch("collectors.hot_wallet_tracker.get_api_key", return_value=None):
        tracker = HotWalletTracker(
            config_dir=Path(__file__).parent.parent / "config"
        )

        result = await tracker.get_exchange_balance("binance")
        assert result is None


@pytest.mark.asyncio
async def test_get_exchange_balance_no_config():
    """설정 없을 때 거래소 잔액 조회."""
    with patch("collectors.hot_wallet_tracker.get_api_key", return_value="test_key"):
        tracker = HotWalletTracker(
            config_dir=Path("/nonexistent/path")
        )

        result = await tracker.get_exchange_balance("unknown_exchange")
        assert result is None


# =============================================================================
# USD 환산 테스트
# =============================================================================


class TestUSDConversion:
    """USD 환산 로직 테스트."""

    @pytest.fixture
    def tracker(self):
        """테스트용 트래커 인스턴스."""
        mock_client = MagicMock()
        with patch("collectors.hot_wallet_tracker.get_api_key", return_value="test_key"):
            return HotWalletTracker(
                config_dir=Path(__file__).parent.parent / "config",
                client=mock_client,
            )

    def test_calculate_usdt_balance(self, tracker):
        """USDT 잔액 USD 환산."""
        # 1000 USDT (6 decimals)
        result = tracker._calculate_balance_usd(
            balance_raw=1_000_000_000,
            token_symbol="USDT",
        )
        assert result == 1000.0

    def test_calculate_usdc_balance(self, tracker):
        """USDC 잔액 USD 환산."""
        # 500 USDC (6 decimals)
        result = tracker._calculate_balance_usd(
            balance_raw=500_000_000,
            token_symbol="USDC",
        )
        assert result == 500.0

    def test_calculate_eth_without_price(self, tracker):
        """ETH 잔액 (가격 없음) USD 환산."""
        # 1 ETH (18 decimals), 가격 미설정 -> 0.0
        result = tracker._calculate_balance_usd(
            balance_raw=10 ** 18,
            token_symbol="ETH",
        )
        assert result == 0.0

    def test_calculate_eth_with_external_price(self, tracker):
        """ETH 잔액 (외부 가격) USD 환산."""
        # 2 ETH @ $3000
        result = tracker._calculate_balance_usd(
            balance_raw=2 * 10 ** 18,
            token_symbol="ETH",
            price_usd=3000.0,
        )
        assert result == 6000.0

    def test_calculate_zero_balance(self, tracker):
        """잔액 0 -> USD 0."""
        result = tracker._calculate_balance_usd(
            balance_raw=0,
            token_symbol="USDT",
        )
        assert result == 0.0

    def test_calculate_unknown_token_no_price(self, tracker):
        """알 수 없는 토큰 (가격 없음) -> 0."""
        result = tracker._calculate_balance_usd(
            balance_raw=10 ** 18,
            token_symbol="UNKNOWN_TOKEN",
        )
        assert result == 0.0


# =============================================================================
# 설정 파일 검증 테스트
# =============================================================================


class TestConfigFileValidation:
    """설정 파일 유효성 검증."""

    def test_hot_wallets_yaml_structure(self):
        """hot_wallets.yaml 구조 검증."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "hot_wallets.yaml"
        if not config_path.exists():
            pytest.skip("hot_wallets.yaml 없음")

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 필수 키 검증
        assert "exchanges" in data
        assert isinstance(data["exchanges"], dict)

        # 거래소별 구조 검증
        for ex_id, ex_data in data["exchanges"].items():
            assert "wallets" in ex_data
            for chain, wallets in ex_data["wallets"].items():
                assert isinstance(wallets, list)
                for wallet in wallets:
                    assert "address" in wallet
                    # 주소 형식 검증 (0x로 시작, 42자)
                    addr = wallet["address"]
                    assert addr.startswith("0x"), f"Invalid address format: {addr}"
                    assert len(addr) == 42, f"Invalid address length: {addr}"

    def test_common_tokens_structure(self):
        """common_tokens 구조 검증."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "hot_wallets.yaml"
        if not config_path.exists():
            pytest.skip("hot_wallets.yaml 없음")

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if "common_tokens" in data:
            tokens = data["common_tokens"]
            for symbol, chains in tokens.items():
                assert isinstance(chains, dict)
                for chain, addr in chains.items():
                    # 토큰 주소 형식 검증
                    assert addr.startswith("0x")
                    assert len(addr) == 42

    def test_external_apis_alchemy_config(self):
        """external_apis.yaml Alchemy 설정 검증."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "external_apis.yaml"
        if not config_path.exists():
            pytest.skip("external_apis.yaml 없음")

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Alchemy 설정 검증
        assert "alchemy" in data
        alchemy = data["alchemy"]
        assert "networks" in alchemy

        # 네트워크별 URL 템플릿 검증
        for chain, config in alchemy["networks"].items():
            assert "url_template" in config
            assert "{api_key}" in config["url_template"]


# =============================================================================
# Week 6: 입금 감지 테스트
# =============================================================================


class TestDepositEvent:
    """DepositEvent 데이터클래스 테스트."""

    def test_deposit_event_creation(self):
        """입금 이벤트 생성."""
        event = DepositEvent(
            exchange="binance",
            chain="ethereum",
            wallet_address="0x28C6c06298d514Db089934071355E5743bf21d60",
            wallet_label="Binance 14",
            token_symbol="USDT",
            token_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            amount_raw=1_000_000_000_000,  # 1M USDT
            amount_human=1_000_000.0,
            amount_usd=1_000_000.0,
            previous_balance=500_000_000_000,
            current_balance=1_500_000_000_000,
        )

        assert event.exchange == "binance"
        assert event.token_symbol == "USDT"
        assert event.amount_usd == 1_000_000.0
        assert event.confidence == 1.0  # 기본값

    def test_deposit_event_with_custom_timestamp(self):
        """커스텀 타임스탬프로 이벤트 생성."""
        ts = datetime(2026, 1, 30, 12, 0, 0)
        event = DepositEvent(
            exchange="okx",
            chain="arbitrum",
            wallet_address="0x6cC5F688a315f3dC28A7781717a9A798a59fDA7b",
            wallet_label="OKX",
            token_symbol="ETH",
            token_address="",
            amount_raw=10**18,
            amount_human=1.0,
            amount_usd=3000.0,
            previous_balance=0,
            current_balance=10**18,
            timestamp=ts,
        )

        assert event.timestamp == ts


class TestDepositDetection:
    """입금 감지 로직 테스트."""

    @pytest.fixture
    def tracker_with_mock(self):
        """모의 클라이언트를 사용하는 트래커 (알림 콜백 포함)."""
        mock_client = MagicMock()
        mock_client.post = AsyncMock()
        mock_callback = AsyncMock()

        with patch("collectors.hot_wallet_tracker.get_api_key", return_value="test_key"):
            tracker = HotWalletTracker(
                config_dir=Path(__file__).parent.parent / "config",
                client=mock_client,
                alert_callback=mock_callback,
                min_deposit_usd=100.0,  # 테스트용 낮은 threshold
            )
        return tracker, mock_client, mock_callback

    @pytest.mark.asyncio
    async def test_check_balance_change_first_call(self, tracker_with_mock):
        """첫 번째 호출: 스냅샷만 저장, 이벤트 없음."""
        tracker, mock_client, _ = tracker_with_mock

        # 모의 RPC 응답
        mock_client.post.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": "0x3B9ACA00"  # 1 USDT
        }

        event = await tracker._check_balance_change(
            exchange="binance",
            chain="ethereum",
            address="0x28C6c06298d514Db089934071355E5743bf21d60",
            label="Test",
            token_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            token_symbol="USDT",
            rpc_url="https://test.com",
        )

        # 첫 호출은 이벤트 없음 (기준점 설정)
        assert event is None
        assert tracker.get_snapshot_count() == 1

    @pytest.mark.asyncio
    async def test_check_balance_change_deposit_detected(self, tracker_with_mock):
        """잔액 증가 감지."""
        tracker, mock_client, _ = tracker_with_mock

        key = _snapshot_key(
            "binance", "ethereum",
            "0x28C6c06298d514Db089934071355E5743bf21d60",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        )

        # 이전 스냅샷 설정 (100 USDT)
        tracker._balance_snapshots[key] = (100_000_000, 0)

        # 새 잔액 (1100 USDT = +1000 USDT)
        mock_client.post.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": "0x41A99E200"  # 1,100,000,000
        }

        event = await tracker._check_balance_change(
            exchange="binance",
            chain="ethereum",
            address="0x28C6c06298d514Db089934071355E5743bf21d60",
            label="Test",
            token_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            token_symbol="USDT",
            rpc_url="https://test.com",
        )

        assert event is not None
        assert event.amount_usd == 1000.0  # +1000 USDT
        assert event.token_symbol == "USDT"

    @pytest.mark.asyncio
    async def test_check_balance_change_withdrawal_ignored(self, tracker_with_mock):
        """잔액 감소 (출금) 무시."""
        tracker, mock_client, _ = tracker_with_mock

        key = _snapshot_key(
            "binance", "ethereum",
            "0x28C6c06298d514Db089934071355E5743bf21d60",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        )

        # 이전 스냅샷 (1000 USDT)
        tracker._balance_snapshots[key] = (1_000_000_000, 0)

        # 새 잔액 (500 USDT = -500 USDT)
        mock_client.post.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": "0x1DCD6500"  # 500,000,000
        }

        event = await tracker._check_balance_change(
            exchange="binance",
            chain="ethereum",
            address="0x28C6c06298d514Db089934071355E5743bf21d60",
            label="Test",
            token_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            token_symbol="USDT",
            rpc_url="https://test.com",
        )

        # 출금은 이벤트 없음
        assert event is None

    @pytest.mark.asyncio
    async def test_check_balance_change_below_threshold(self, tracker_with_mock):
        """최소 금액 미만 무시."""
        tracker, mock_client, _ = tracker_with_mock

        key = _snapshot_key(
            "binance", "ethereum",
            "0x28C6c06298d514Db089934071355E5743bf21d60",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        )

        # 이전 스냅샷 (100 USDT)
        tracker._balance_snapshots[key] = (100_000_000, 0)

        # 새 잔액 (150 USDT = +50 USDT < $100 threshold)
        mock_client.post.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": "0x8F0D180"  # 150,000,000
        }

        event = await tracker._check_balance_change(
            exchange="binance",
            chain="ethereum",
            address="0x28C6c06298d514Db089934071355E5743bf21d60",
            label="Test",
            token_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            token_symbol="USDT",
            rpc_url="https://test.com",
        )

        # threshold 미만은 이벤트 없음
        assert event is None

    @pytest.mark.asyncio
    async def test_handle_deposit_calls_callback(self, tracker_with_mock):
        """입금 처리 시 콜백 호출."""
        tracker, _, mock_callback = tracker_with_mock

        event = DepositEvent(
            exchange="binance",
            chain="ethereum",
            wallet_address="0x1234",
            wallet_label="Test",
            token_symbol="USDT",
            token_address="0x5678",
            amount_raw=1_000_000_000,
            amount_human=1000.0,
            amount_usd=1000.0,
            previous_balance=0,
            current_balance=1_000_000_000,
        )

        await tracker._handle_deposit(event)

        mock_callback.assert_called_once_with(event)


# =============================================================================
# Week 6: Telegram 알림 포맷 테스트
# =============================================================================


class TestTelegramAlertFormat:
    """Telegram 알림 포맷 테스트."""

    def test_format_small_deposit(self):
        """소액 입금 ($10만) 포맷."""
        event = DepositEvent(
            exchange="binance",
            chain="ethereum",
            wallet_address="0x1234",
            wallet_label="Binance 14",
            token_symbol="USDT",
            token_address="0x5678",
            amount_raw=100_000_000_000,
            amount_human=100_000.0,
            amount_usd=100_000.0,
            previous_balance=0,
            current_balance=100_000_000_000,
            timestamp=datetime(2026, 1, 30, 12, 30, 45),
        )

        msg = format_deposit_alert(event)

        assert "바이낸스" in msg
        assert "이더리움" in msg
        assert "USDT" in msg
        assert "$100,000" in msg
        assert "12:30:45" in msg
        # 소액이므로 [긴급] 태그 없음
        assert "[긴급]" not in msg

    def test_format_large_deposit(self):
        """대량 입금 ($100만) 포맷."""
        event = DepositEvent(
            exchange="okx",
            chain="arbitrum",
            wallet_address="0x6cC5",
            wallet_label="OKX",
            token_symbol="USDC",
            token_address="0xaf88",
            amount_raw=1_000_000_000_000,
            amount_human=1_000_000.0,
            amount_usd=1_000_000.0,
            previous_balance=0,
            current_balance=1_000_000_000_000,
        )

        msg = format_deposit_alert(event)

        assert "OKX" in msg
        assert "아비트럼" in msg
        assert "[대량]" in msg
        assert "$1,000,000" in msg

    def test_format_whale_deposit(self):
        """고래 입금 ($1000만+) 포맷."""
        event = DepositEvent(
            exchange="coinbase",
            chain="base",
            wallet_address="0x3304",
            wallet_label="Coinbase Base",
            token_symbol="USDC",
            token_address="0x8335",
            amount_raw=10_000_000_000_000,
            amount_human=10_000_000.0,
            amount_usd=10_000_000.0,
            previous_balance=0,
            current_balance=10_000_000_000_000,
        )

        msg = format_deposit_alert(event)

        assert "코인베이스" in msg
        assert "베이스" in msg
        assert "[긴급]" in msg
        assert "🚨" in msg or "🐋" in msg

    def test_format_includes_krw(self):
        """KRW 환산 포함 확인."""
        event = DepositEvent(
            exchange="bybit",
            chain="ethereum",
            wallet_address="0xf89d",
            wallet_label="Bybit",
            token_symbol="ETH",
            token_address="",
            amount_raw=10**18,
            amount_human=1.0,
            amount_usd=3000.0,
            previous_balance=0,
            current_balance=10**18,
        )

        msg = format_deposit_alert(event)

        assert "만원" in msg or "억원" in msg


# =============================================================================
# Week 6: 심볼 매핑 테스트
# =============================================================================


class TestSymbolMapping:
    """심볼-토큰 매핑 테스트."""

    def test_snapshot_key_generation(self):
        """스냅샷 키 생성."""
        key = _snapshot_key(
            "binance", "ethereum",
            "0x28C6c06298d514Db089934071355E5743bf21d60",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        )

        assert "binance" in key
        assert "ethereum" in key
        assert "0x28c6" in key.lower()
        assert "0xdac1" in key.lower()

    def test_snapshot_key_native_token(self):
        """네이티브 토큰 스냅샷 키."""
        key = _snapshot_key(
            "binance", "ethereum",
            "0x28C6c06298d514Db089934071355E5743bf21d60",
            "native",
        )

        assert "native" in key

    def test_build_reverse_token_map(self):
        """역방향 토큰 매핑 빌드."""
        config = {
            "common_tokens": {
                "USDT": {
                    "ethereum": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                    "arbitrum": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
                },
                "USDC": {
                    "ethereum": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                },
            }
        }

        mapping = _build_reverse_token_map(config)

        assert mapping["0xdac17f958d2ee523a2206206994597c13d831ec7"] == "USDT"
        assert mapping["0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"] == "USDT"
        assert mapping["0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"] == "USDC"

    def test_get_symbol_from_address(self):
        """주소로 심볼 조회."""
        config = {
            "common_tokens": {
                "USDT": {
                    "ethereum": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                },
            }
        }

        # 캐시 초기화
        import collectors.hot_wallet_tracker as module
        module._TOKEN_ADDRESS_TO_SYMBOL = {}

        symbol = get_symbol_from_address(
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            config,
        )

        assert symbol == "USDT"

    def test_get_symbol_from_address_unknown(self):
        """알 수 없는 주소."""
        import collectors.hot_wallet_tracker as module
        module._TOKEN_ADDRESS_TO_SYMBOL = {}

        symbol = get_symbol_from_address(
            "0x0000000000000000000000000000000000000000",
            {"common_tokens": {}},
        )

        assert symbol is None


# =============================================================================
# Week 6: 모니터링 테스트
# =============================================================================


class TestMonitoring:
    """모니터링 기능 테스트."""

    def test_stop_monitoring(self):
        """모니터링 중지."""
        mock_client = MagicMock()
        with patch("collectors.hot_wallet_tracker.get_api_key", return_value="test_key"):
            tracker = HotWalletTracker(
                config_dir=Path(__file__).parent.parent / "config",
                client=mock_client,
            )

        tracker._monitoring = True
        tracker.stop_monitoring()

        assert tracker._monitoring is False

    def test_get_snapshot_count(self):
        """스냅샷 카운트."""
        mock_client = MagicMock()
        with patch("collectors.hot_wallet_tracker.get_api_key", return_value="test_key"):
            tracker = HotWalletTracker(
                config_dir=Path(__file__).parent.parent / "config",
                client=mock_client,
            )

        assert tracker.get_snapshot_count() == 0

        tracker._balance_snapshots["key1"] = (100, 0)
        tracker._balance_snapshots["key2"] = (200, 0)

        assert tracker.get_snapshot_count() == 2
