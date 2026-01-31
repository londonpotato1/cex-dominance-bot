"""텔레그램 알림 시스템 테스트."""

import pytest
import sqlite3
from unittest.mock import AsyncMock, patch, MagicMock
from alerts.telegram import TelegramAlert
from analysis.gate import AlertLevel
from store.writer import DatabaseWriter


@pytest.fixture
def mock_writer():
    """DatabaseWriter mock."""
    writer = MagicMock(spec=DatabaseWriter)
    writer.enqueue_sync = MagicMock()
    return writer


@pytest.fixture
def read_conn():
    """읽기 전용 sqlite3 연결."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # alert_debounce 테이블 생성
    conn.execute(
        "CREATE TABLE alert_debounce ("
        "key TEXT PRIMARY KEY, "
        "last_sent_at REAL, "
        "expires_at REAL"
        ")"
    )
    conn.commit()
    return conn


@pytest.fixture
def telegram_alert(mock_writer, read_conn):
    """TelegramAlert 인스턴스 (봇 토큰/채팅 ID 설정됨)."""
    return TelegramAlert(
        writer=mock_writer,
        read_conn=read_conn,
        bot_token="test_token",
        chat_id="test_chat_id",
    )


@pytest.fixture
def telegram_alert_unconfigured(mock_writer, read_conn):
    """TelegramAlert 인스턴스 (봇 미설정)."""
    return TelegramAlert(
        writer=mock_writer,
        read_conn=read_conn,
        bot_token=None,
        chat_id=None,
    )


class TestTelegramAlert:
    """TelegramAlert 기본 기능 테스트."""

    def test_is_configured(self, telegram_alert, telegram_alert_unconfigured):
        """텔레그램 봇 설정 여부 확인."""
        assert telegram_alert.is_configured is True
        assert telegram_alert_unconfigured.is_configured is False

    @pytest.mark.asyncio
    async def test_info_level_no_send(self, telegram_alert):
        """INFO 레벨은 로그만 출력."""
        with patch.object(telegram_alert, "_send_telegram", new_callable=AsyncMock) as mock_send:
            await telegram_alert.send(AlertLevel.INFO, "테스트 메시지")
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_critical_immediate_send(self, telegram_alert):
        """CRITICAL 레벨은 즉시 전송 (prefix 없이 메시지만)."""
        with patch.object(telegram_alert, "_send_telegram", new_callable=AsyncMock) as mock_send:
            await telegram_alert.send(AlertLevel.CRITICAL, "긴급 알림")
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            # CRITICAL/HIGH는 prefix 없이 메시지 그대로 전송
            assert "긴급 알림" in args[0]

    @pytest.mark.asyncio
    async def test_high_immediate_send(self, telegram_alert):
        """HIGH 레벨은 즉시 전송."""
        with patch.object(telegram_alert, "_send_telegram", new_callable=AsyncMock) as mock_send:
            await telegram_alert.send(AlertLevel.HIGH, "중요 알림")
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_medium_with_debounce(self, telegram_alert, read_conn):
        """MEDIUM 레벨은 디바운스 적용."""
        import time
        
        with patch.object(telegram_alert, "_send_telegram", new_callable=AsyncMock) as mock_send:
            # 첫 번째 전송
            await telegram_alert.send(AlertLevel.MEDIUM, "테스트", key="test_key")
            assert mock_send.call_count == 1

            # 디바운스 레코드 직접 삽입 (mock_writer는 실제로 DB에 쓰지 않음)
            now = time.time()
            read_conn.execute(
                "INSERT OR REPLACE INTO alert_debounce (key, last_sent_at, expires_at) VALUES (?, ?, ?)",
                ("test_key", now, now + 300),  # 5분 후 만료
            )
            read_conn.commit()

            # 두 번째 전송 (디바운스로 차단)
            await telegram_alert.send(AlertLevel.MEDIUM, "테스트", key="test_key")
            assert mock_send.call_count == 1  # 여전히 1번만

    @pytest.mark.asyncio
    async def test_low_level_batch(self, telegram_alert):
        """LOW 레벨은 배치 버퍼에 추가."""
        with patch.object(telegram_alert, "_send_telegram", new_callable=AsyncMock) as mock_send:
            await telegram_alert.send(AlertLevel.LOW, "배치 메시지 1")
            await telegram_alert.send(AlertLevel.LOW, "배치 메시지 2")

            # 아직 전송 안됨
            mock_send.assert_not_called()

            # 강제 flush
            await telegram_alert.flush_batch()
            mock_send.assert_called_once()

            # 버퍼가 비워짐
            assert len(telegram_alert._batch_buffer) == 0

    @pytest.mark.asyncio
    async def test_unconfigured_dry_run(self, telegram_alert_unconfigured):
        """봇 미설정 시 dry-run (로그만)."""
        with patch.object(telegram_alert_unconfigured, "_send_telegram", new_callable=AsyncMock) as mock_send:
            await telegram_alert_unconfigured.send(AlertLevel.CRITICAL, "테스트")
            mock_send.assert_called_once()  # _send_telegram은 호출되지만
            # 내부에서 is_configured 체크로 실제 전송은 안됨

    @pytest.mark.asyncio
    async def test_send_telegram_success(self, telegram_alert):
        """텔레그램 메시지 전송 성공."""
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__.return_value = mock_response
            mock_post.return_value = mock_response

            await telegram_alert._send_telegram("테스트 메시지")

            # 호출 확인
            assert mock_post.called

    @pytest.mark.asyncio
    async def test_send_telegram_failure(self, telegram_alert):
        """텔레그램 메시지 전송 실패 시 경고 로그."""
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 400
            mock_response.text = AsyncMock(return_value="Bad Request")
            mock_response.__aenter__.return_value = mock_response
            mock_post.return_value = mock_response

            # 예외 발생하지 않아야 함 (경고 로그만)
            await telegram_alert._send_telegram("테스트 메시지")


class TestLevelPrefix:
    """레벨별 이모지 접두사 테스트."""

    def test_critical_prefix(self):
        assert TelegramAlert._level_prefix(AlertLevel.CRITICAL) == "[CRITICAL]"

    def test_high_prefix(self):
        assert TelegramAlert._level_prefix(AlertLevel.HIGH) == "[HIGH]"

    def test_medium_prefix(self):
        assert TelegramAlert._level_prefix(AlertLevel.MEDIUM) == "[MEDIUM]"

    def test_low_prefix(self):
        assert TelegramAlert._level_prefix(AlertLevel.LOW) == "[LOW]"

    def test_info_prefix(self):
        assert TelegramAlert._level_prefix(AlertLevel.INFO) == "[INFO]"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
