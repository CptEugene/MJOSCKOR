from __future__ import annotations

import math


class OutputLimiter:
    def __init__(
        self,
        threshold: float = 0.82,
        release: float = 0.004,
        soft_clip_drive: float = 1.25,
    ) -> None:
        self.threshold = max(0.1, min(0.99, threshold))
        self.release = max(0.0001, min(1.0, release))
        self.soft_clip_drive = max(0.1, soft_clip_drive)
        self._gain = 1.0
        self._soft_clip_normalizer = math.tanh(self.soft_clip_drive)

    def reset(self) -> None:
        self._gain = 1.0

    def process(self, samples: list[float]) -> list[float]:
        if not samples:
            return []
        processed: list[float] = []
        gain = self._gain
        for sample in samples:
            absolute_sample = abs(sample)
            target_gain = 1.0
            if absolute_sample > self.threshold and absolute_sample > 1.0e-9:
                target_gain = self.threshold / absolute_sample
            if target_gain < gain:
                gain = target_gain
            else:
                gain += (1.0 - gain) * self.release
                gain = min(1.0, gain)
            limited = sample * gain
            if abs(limited) > self.threshold:
                scaled = limited / self.threshold
                limited = (
                    math.tanh(scaled * self.soft_clip_drive) / self._soft_clip_normalizer
                ) * self.threshold
            processed.append(max(-1.0, min(1.0, limited)))
        self._gain = gain
        return processed
