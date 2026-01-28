"""WebSocket 베이스 클래스 — 재연결/핑퐁/Gap Recovery.

지수 백오프 재연결: 1s → 2s → 4s → ... → 60s (max)
Gap Recovery: 끊김 > gap_threshold초이면 REST로 보충.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


class RobustWebSocket(ABC):
    """24시간 끊김 없는 WebSocket 연결을 보장하는 베이스 클래스."""

    def __init__(
        self,
        url: str,
        *,
        ping_interval: float = 30.0,
        reconnect_delay_base: float = 1.0,
        reconnect_delay_max: float = 60.0,
        gap_threshold: float = 5.0,
    ) -> None:
        self.url = url
        self.ping_interval = ping_interval
        self.reconnect_delay_base = reconnect_delay_base
        self.reconnect_delay_max = reconnect_delay_max
        self.gap_threshold = gap_threshold

        self._ws: Optional[WebSocketClientProtocol] = None
        self._last_msg_time: float = 0.0
        self._disconnect_time: Optional[float] = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # 추상 메서드 (서브클래스 구현 필수)
    # ------------------------------------------------------------------

    @abstractmethod
    async def on_message(self, data: bytes | str) -> None:
        """수신 메시지 처리."""

    @abstractmethod
    async def on_reconnected(self) -> None:
        """재연결 후 복구 작업 (스냅샷 리셋, gap recovery 등)."""

    @abstractmethod
    async def subscribe(self) -> None:
        """초기 구독 메시지 전송."""

    # ------------------------------------------------------------------
    # 공개 메서드
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """WebSocket 연결 상태."""
        return self._ws is not None

    @property
    def last_msg_time(self) -> float:
        """마지막 메시지 수신 시각 (monotonic)."""
        return self._last_msg_time

    async def run(self) -> None:
        """메인 실행 루프: 연결 → 수신/핑 → 끊김 시 재연결."""
        self._running = True
        delay = self.reconnect_delay_base

        while self._running:
            try:
                await self._connect()
                delay = self.reconnect_delay_base  # 연결 성공 시 리셋

                tasks = [
                    asyncio.create_task(self._recv_loop()),
                    asyncio.create_task(self._ping_loop()),
                ]
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                # 완료된 태스크의 예외 전파
                for t in done:
                    t.result()
            except (
                websockets.ConnectionClosed,
                websockets.InvalidStatusCode,
                ConnectionError,
                OSError,
            ) as e:
                self._disconnect_time = time.monotonic()
                logger.warning(
                    "[%s] 연결 끊김: %s — %0.1f초 후 재연결",
                    self._name, e, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_delay_max)
            except asyncio.CancelledError:
                logger.info("[%s] 실행 취소됨", self._name)
                break
            except Exception:
                self._disconnect_time = time.monotonic()
                logger.exception("[%s] 예상치 못한 에러", self._name)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_delay_max)

    async def close(self) -> None:
        """연결 종료."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("[%s] WebSocket 종료", self._name)

    async def send(self, data: str) -> None:
        """메시지 전송."""
        if self._ws:
            await self._ws.send(data)

    # ------------------------------------------------------------------
    # Gap Recovery
    # ------------------------------------------------------------------

    async def gap_recovery(self, disconnect_duration: float) -> None:
        """끊김 시간 판단 후 REST로 누락 데이터 보충.

        gap 판단 로직은 베이스에서 공통 처리.
        실제 REST 호출은 서브클래스의 _fetch_gap_data()에서 구현.
        """
        if disconnect_duration < self.gap_threshold:
            logger.debug(
                "[%s] Gap %0.1f초 < 임계값 %0.1f초, 복구 생략",
                self._name, disconnect_duration, self.gap_threshold,
            )
            return
        logger.info(
            "[%s] Gap Recovery 시작: %0.1f초 끊김, REST 보충",
            self._name, disconnect_duration,
        )
        await self._fetch_gap_data(disconnect_duration)

    @abstractmethod
    async def _fetch_gap_data(self, gap_seconds: float) -> None:
        """REST API로 누락 데이터 보충 (서브클래스 구현 필수).

        Args:
            gap_seconds: 끊김 지속 시간(초).
        """

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------

    @property
    def _name(self) -> str:
        return self.__class__.__name__

    async def _connect(self) -> None:
        """WebSocket 연결 + 구독."""
        logger.info("[%s] 연결 중: %s", self._name, self.url)
        self._ws = await websockets.connect(
            self.url,
            ping_interval=None,  # 자체 핑 루프 사용
            ping_timeout=None,
            close_timeout=10,
            max_size=2**20,      # 1MB
        )
        logger.info("[%s] 연결 성공", self._name)

        await self.subscribe()

        # 재연결이면 gap recovery 수행
        if self._disconnect_time is not None:
            gap = time.monotonic() - self._disconnect_time
            self._disconnect_time = None
            await self.on_reconnected()
            await self.gap_recovery(gap)

    async def _recv_loop(self) -> None:
        """메시지 수신 루프."""
        assert self._ws is not None
        async for msg in self._ws:
            self._last_msg_time = time.monotonic()
            try:
                await self.on_message(msg)
            except Exception:
                logger.exception("[%s] 메시지 처리 에러", self._name)

    async def _ping_loop(self) -> None:
        """주기적 ping 전송 (idle timeout 방지)."""
        assert self._ws is not None
        while True:
            await asyncio.sleep(self.ping_interval)
            try:
                pong = await self._ws.ping()
                await asyncio.wait_for(pong, timeout=10)
            except asyncio.TimeoutError:
                logger.warning("[%s] Ping 응답 타임아웃", self._name)
                await self._ws.close()
                return
            except Exception:
                return
