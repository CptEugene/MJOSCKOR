from __future__ import annotations

from time import monotonic


class TalkerAudioBuffer:
    def __init__(
        self,
        skip_threshold_packets: int = 1,
        max_buffered_packets: int = 24,
        max_concealed_packets: int = 2,
        max_adaptive_packets: int = 4,
        stable_packet_window: int = 12,
    ) -> None:
        self.skip_threshold_packets = max(1, skip_threshold_packets)
        self.max_adaptive_packets = max(self.skip_threshold_packets, max_adaptive_packets)
        self.stable_packet_window = max(1, stable_packet_window)
        self.max_buffered_packets = max(self.max_adaptive_packets + 1, max_buffered_packets)
        self.max_concealed_packets = max(0, max_concealed_packets)
        self._frames: dict[int, bytes] = {}
        self._expected_packet: int | None = None
        self._last_packet_at = 0.0
        self._primed = False
        self._concealed_packets = 0
        self._frame_size = 0
        self._target_buffer_packets = self.skip_threshold_packets
        self._stable_packets = 0

    @property
    def target_buffer_packets(self) -> int:
        return self._target_buffer_packets

    def push(self, packet_number: int, pcm_bytes: bytes) -> str:
        if not pcm_bytes:
            return "empty"
        if packet_number <= 0:
            raise ValueError("packet_number must be positive")
        self._last_packet_at = monotonic()
        self._frame_size = len(pcm_bytes)
        if self._expected_packet is None:
            self._expected_packet = packet_number
        elif not self._primed and packet_number < self._expected_packet:
            self._expected_packet = packet_number
        elif self._expected_packet is not None and packet_number < self._expected_packet:
            self._increase_target_buffer()
            return "late_drop"
        self._frames[packet_number] = pcm_bytes
        if self._primed and self._expected_packet is not None and packet_number > (self._expected_packet + 1):
            self._increase_target_buffer()
        overflowed = False
        if len(self._frames) > self.max_buffered_packets:
            oldest_packet = min(self._frames)
            self._frames.pop(oldest_packet, None)
            overflowed = True
            self._increase_target_buffer()
            if self._expected_packet is not None and oldest_packet >= self._expected_packet:
                self._expected_packet = min(self._frames) if self._frames else None
        return "overflow_drop" if overflowed else "stored"

    def pop_ready(self) -> tuple[bytes | None, int]:
        if self._expected_packet is None:
            return None, 0
        if not self._primed:
            if len(self._frames) < self._target_buffer_packets:
                return None, 0
            self._expected_packet = min(self._frames)
            self._primed = True
        frame = self._frames.pop(self._expected_packet, None)
        if frame is not None:
            self._expected_packet += 1
            self._concealed_packets = 0
            self._note_stable_packet()
            if not self._frames:
                return frame, 0
            return frame, 0
        if not self._frames:
            return None, 0
        earliest_packet = min(self._frames)
        if (
            earliest_packet > self._expected_packet
            and self._frame_size > 0
            and self._concealed_packets < self.max_concealed_packets
        ):
            self._concealed_packets += 1
            self._increase_target_buffer()
            self._expected_packet += 1
            return b"\x00" * self._frame_size, 0
        if earliest_packet > self._expected_packet and (
            len(self._frames) >= self.skip_threshold_packets
            or (earliest_packet - self._expected_packet) >= self.skip_threshold_packets
        ):
            skipped_packets = earliest_packet - self._expected_packet
            self._increase_target_buffer(amount=min(2, max(1, skipped_packets)))
            self._expected_packet = earliest_packet
            frame = self._frames.pop(earliest_packet, None)
            if frame is not None:
                self._expected_packet = earliest_packet + 1
                self._concealed_packets = 0
            return frame, skipped_packets
        return None, 0

    def has_pending(self) -> bool:
        return bool(self._frames)

    def is_stale(self, max_idle_seconds: float, now: float | None = None) -> bool:
        if self._last_packet_at <= 0.0:
            return False
        current = monotonic() if now is None else now
        return (current - self._last_packet_at) > max_idle_seconds

    def _increase_target_buffer(self, amount: int = 1) -> None:
        self._target_buffer_packets = min(self.max_adaptive_packets, self._target_buffer_packets + amount)
        self._stable_packets = 0

    def _note_stable_packet(self) -> None:
        if self._target_buffer_packets <= self.skip_threshold_packets:
            self._stable_packets = 0
            return
        self._stable_packets += 1
        if self._stable_packets >= self.stable_packet_window:
            self._target_buffer_packets = max(self.skip_threshold_packets, self._target_buffer_packets - 1)
            self._stable_packets = 0
