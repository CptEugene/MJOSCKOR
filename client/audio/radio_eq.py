from __future__ import annotations

import math
from typing import Any, Mapping


OUTPUT_SAMPLE_RATE = 48_000.0
PCM_INPUT_SCALE = 32768.0
PCM_OUTPUT_POSITIVE_SCALE = 32767.0
PCM_OUTPUT_NEGATIVE_SCALE = 32768.0
DC_OFFSET = 1.0e-25

ARC210_CHANNEL_TAGS = ("squad", "hq", "atc", "general")
ARC210_TX_WET_MIX = 0.0
ARC210_RX_WET_MIX = 0.92
LEGACY_COMMS_BACKING_MIX = 0.0
NON_PILOT_RX_WET_MIX = 0.20
NON_PILOT_RX_OUTPUT_GAIN = 1.50
PILOT_RX_WET_MIX = 0.10
PILOT_RX_OUTPUT_GAIN = 1.05

# SRS ARC-210 reference taken from `DCS-SR-Client/RadioModels/arc210.json`.
SRS_ARC210_MODEL: dict[str, Any] = {
    "version": 1,
    "noiseGain": -33.0,
    "txEffect": {
        "$type": "chain",
        "effects": [
            {
                "$type": "filters",
                "filters": [
                    {"$type": "highpass", "frequency": 1700.0, "q": 0.53},
                    {"$type": "peak", "frequency": 2801.0, "q": 0.5, "gain": 5.0},
                    {"$type": "lowpass", "frequency": 5538.0},
                ],
            },
            {"$type": "saturation", "gain": 9.0, "threshold": -23.0},
            {
                "$type": "sidechainCompressor",
                "attack": 0.01,
                "makeUp": 6.0,
                "release": 0.2,
                "threshold": -33.0,
                "ratio": 1.18,
                "sidechainEffect": {
                    "$type": "filters",
                    "filters": [
                        {"$type": "highpass", "frequency": 709.0},
                    ],
                },
            },
            {
                "$type": "filters",
                "filters": [
                    {"$type": "highpass", "frequency": 456.0, "q": 0.36},
                    {"$type": "lowpass", "frequency": 5435.0, "q": 0.39},
                ],
            },
            {"$type": "gain", "gain": 12.0},
        ],
    },
    "rxEffect": {
        "$type": "filters",
        "filters": [
            {"$type": "highpass", "frequency": 270.0},
            {"$type": "lowpass", "frequency": 4500.0},
        ],
    },
    "encryptionEffect": {"$type": "cvsd"},
}

SRS_ARC210_TX_PROFILE = SRS_ARC210_MODEL["txEffect"]
SRS_ARC210_RX_PROFILE = SRS_ARC210_MODEL["rxEffect"]
MAYDAY_COMMS_MODEL: dict[str, Any] = {
    "version": 5,
    "baseModel": "Squadron42HelmetComms",
    "txEffect": {
        "$type": "identity",
    },
    "rxEffect": {
        "$type": "homeworldFleetComms",
        "preset": "HOMEWORLD_FLEET_COMMS",
        "highPass": 190.0,
        "lowPass": 4850.0,
        "lowMidCut": {"frequency": 420.0, "q": 0.85, "gain": -3.0},
        "midPresence": {"frequency": 1150.0, "q": 0.90, "gain": 4.2},
        "upperPresence": {"frequency": 2900.0, "q": 0.95, "gain": 2.1},
        "compressor": {"attack": 0.008, "release": 0.110, "threshold": -27.0, "ratio": 3.5, "makeUp": 3.0},
        "saturation": {"drive": 1.08, "mode": "softClip"},
        "space": {"type": "shortRoomPlate", "preDelay": 0.016, "decay": 0.52, "mix": 0.075},
        "noise": {"floor": -54.0, "follow": -60.0},
        "grain": {"level": -59.0},
    },
}

MAYDAY_COMMS_TX_PROFILE = MAYDAY_COMMS_MODEL["txEffect"]
MAYDAY_COMMS_RX_PROFILE = MAYDAY_COMMS_MODEL["rxEffect"]
RADIO_PROFILES = {channel_tag: MAYDAY_COMMS_TX_PROFILE for channel_tag in ARC210_CHANNEL_TAGS}


def _db_to_linear(value_db: float) -> float:
    return math.pow(10.0, value_db / 20.0)


def _linear_to_db(value_linear: float) -> float:
    return 20.0 * math.log10(max(value_linear, DC_OFFSET))


def _clamp_float(sample: float) -> float:
    return max(min(sample, 1.0), -1.0)


def _pcm16_to_float(sample: int) -> float:
    return float(sample) / PCM_INPUT_SCALE


def _float_to_pcm16(sample: float) -> int:
    clamped = _clamp_float(sample)
    if clamped >= 0.0:
        return int(clamped * PCM_OUTPUT_POSITIVE_SCALE)
    return int(clamped * PCM_OUTPUT_NEGATIVE_SCALE)


class _FilterProcessor:
    def process(self, sample: float) -> float:
        raise NotImplementedError

    def reset(self) -> None:
        return None


class _FirstOrderFilter(_FilterProcessor):
    def __init__(self, b0: float, b1: float, a1: float) -> None:
        self._b0 = b0
        self._b1 = b1
        self._a1 = a1
        self._x_n1 = 0.0
        self._y_n1 = 0.0

    @classmethod
    def low_pass(cls, sample_rate: float, cutoff_frequency: float) -> "_FirstOrderFilter":
        w0 = 2.0 * math.pi * cutoff_frequency / sample_rate
        sin_w0 = math.sin(w0)
        cos_w0 = math.cos(w0)

        a0 = sin_w0 + 1.0 + cos_w0
        a1 = sin_w0 - 1.0 - cos_w0
        b0 = sin_w0
        b1 = sin_w0
        return cls(b0 / a0, b1 / a0, a1 / a0)

    @classmethod
    def high_pass(cls, sample_rate: float, cutoff_frequency: float) -> "_FirstOrderFilter":
        w0 = 2.0 * math.pi * cutoff_frequency / sample_rate
        sin_w0 = math.sin(w0)
        cos_w0 = math.cos(w0)

        a0 = sin_w0 + 1.0 + cos_w0
        a1 = sin_w0 - 1.0 - cos_w0
        b0 = 1.0 + cos_w0
        b1 = -1.0 - cos_w0
        return cls(b0 / a0, b1 / a0, a1 / a0)

    def process(self, sample: float) -> float:
        self._y_n1 = (self._b0 * sample) + (self._b1 * self._x_n1) - (self._a1 * self._y_n1)
        self._x_n1 = sample
        return self._y_n1

    def reset(self) -> None:
        self._x_n1 = 0.0
        self._y_n1 = 0.0


class _BiQuadFilter(_FilterProcessor):
    def __init__(self, b0: float, b1: float, b2: float, a1: float, a2: float) -> None:
        self._b0 = b0
        self._b1 = b1
        self._b2 = b2
        self._a1 = a1
        self._a2 = a2
        self._x1 = 0.0
        self._x2 = 0.0
        self._y1 = 0.0
        self._y2 = 0.0

    @staticmethod
    def _normalized_params(freq: float, q: float) -> tuple[float, float]:
        normalized_freq = min(max(freq, 1.0), (OUTPUT_SAMPLE_RATE * 0.5) - 1.0)
        normalized_q = max(q, 0.05)
        return normalized_freq, normalized_q

    @classmethod
    def _build(cls, freq: float, q: float, numerator: tuple[float, float, float], denominator: tuple[float, float, float]) -> "_BiQuadFilter":
        del freq, q
        b0, b1, b2 = numerator
        a0, a1, a2 = denominator
        return cls(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

    @classmethod
    def high_pass(cls, freq: float, q: float) -> "_BiQuadFilter":
        freq, q = cls._normalized_params(freq, q)
        w0 = 2.0 * math.pi * freq / OUTPUT_SAMPLE_RATE
        alpha = math.sin(w0) / (2.0 * q)
        cos_w0 = math.cos(w0)
        return cls._build(
            freq,
            q,
            (
                (1.0 + cos_w0) * 0.5,
                -(1.0 + cos_w0),
                (1.0 + cos_w0) * 0.5,
            ),
            (
                1.0 + alpha,
                -2.0 * cos_w0,
                1.0 - alpha,
            ),
        )

    @classmethod
    def low_pass(cls, freq: float, q: float) -> "_BiQuadFilter":
        freq, q = cls._normalized_params(freq, q)
        w0 = 2.0 * math.pi * freq / OUTPUT_SAMPLE_RATE
        alpha = math.sin(w0) / (2.0 * q)
        cos_w0 = math.cos(w0)
        return cls._build(
            freq,
            q,
            (
                (1.0 - cos_w0) * 0.5,
                1.0 - cos_w0,
                (1.0 - cos_w0) * 0.5,
            ),
            (
                1.0 + alpha,
                -2.0 * cos_w0,
                1.0 - alpha,
            ),
        )

    @classmethod
    def peaking_eq(cls, freq: float, q: float, gain_db: float) -> "_BiQuadFilter":
        freq, q = cls._normalized_params(freq, q)
        amplitude = math.pow(10.0, gain_db / 40.0)
        w0 = 2.0 * math.pi * freq / OUTPUT_SAMPLE_RATE
        alpha = math.sin(w0) / (2.0 * q)
        cos_w0 = math.cos(w0)
        return cls._build(
            freq,
            q,
            (
                1.0 + alpha * amplitude,
                -2.0 * cos_w0,
                1.0 - alpha * amplitude,
            ),
            (
                1.0 + alpha / amplitude,
                -2.0 * cos_w0,
                1.0 - alpha / amplitude,
            ),
        )

    def process(self, sample: float) -> float:
        output = (
            (self._b0 * sample)
            + (self._b1 * self._x1)
            + (self._b2 * self._x2)
            - (self._a1 * self._y1)
            - (self._a2 * self._y2)
        )
        self._x2 = self._x1
        self._x1 = sample
        self._y2 = self._y1
        self._y1 = output
        return output

    def reset(self) -> None:
        self._x1 = 0.0
        self._x2 = 0.0
        self._y1 = 0.0
        self._y2 = 0.0


class _EnvelopeDetector:
    def __init__(self, milliseconds: float, sample_rate: float) -> None:
        self._milliseconds = milliseconds
        self._sample_rate = sample_rate
        self._coefficient = 0.0
        self._update_coefficient()

    def _update_coefficient(self) -> None:
        self._coefficient = math.exp(-1.0 / (0.001 * self._milliseconds * self._sample_rate))

    def run(self, input_value: float, state: float) -> float:
        return input_value + (self._coefficient * (state - input_value))


class _AttackReleaseEnvelope:
    def __init__(self, attack_milliseconds: float, release_milliseconds: float, sample_rate: float) -> None:
        self._attack = _EnvelopeDetector(attack_milliseconds, sample_rate)
        self._release = _EnvelopeDetector(release_milliseconds, sample_rate)

    def run(self, input_value: float, state: float) -> float:
        if input_value > state:
            return self._attack.run(input_value, state)
        return self._release.run(input_value, state)


class _SidechainCompressor:
    def __init__(self, attack_milliseconds: float, release_milliseconds: float, sample_rate: float) -> None:
        self._envelope = _AttackReleaseEnvelope(attack_milliseconds, release_milliseconds, sample_rate)
        self._envelope_db = DC_OFFSET
        self.make_up_gain = 0.0
        self.threshold = 0.0
        self.ratio = 1.0

    def process(self, side_in: float, signal_in: float) -> float:
        rectified = abs(side_in)
        rectified += DC_OFFSET
        key_db = _linear_to_db(rectified)

        over_db = key_db - self.threshold
        if over_db < 0.0:
            over_db = 0.0

        over_db += DC_OFFSET
        self._envelope_db = self._envelope.run(over_db, self._envelope_db)
        over_db = self._envelope_db - DC_OFFSET

        gain_reduction = over_db * ((1.0 / max(self.ratio, 1.0)) - 1.0)
        linear_gain = _db_to_linear(gain_reduction) * _db_to_linear(self.make_up_gain)
        return signal_in * linear_gain

    def reset(self) -> None:
        self._envelope_db = DC_OFFSET


class _CVSD:
    _BIT_MASK = 0b111
    _ZETA = 1.5
    _DELTA_MIN = 0.01
    _DELTA_MAX = 1.0

    def __init__(self) -> None:
        self.reference = 0.0
        self.bitref = 0
        self.delta = 0.0

    def transform(self, sample: float) -> float:
        bit = 0 if self.reference > sample else 1
        self.bitref <<= 1
        self.bitref |= bit
        self.bitref &= self._BIT_MASK

        if self.bitref == 0 or self.bitref == self._BIT_MASK:
            self.delta *= self._ZETA
        else:
            self.delta /= self._ZETA

        self.delta = max(min(self.delta, self._DELTA_MAX), self._DELTA_MIN)
        self.reference += (1.0 if bit else -1.0) * self.delta
        self.reference = max(min(self.reference, 1.0), -1.0)
        return self.reference

    def reset(self) -> None:
        self.reference = 0.0
        self.bitref = 0
        self.delta = 0.0


class _EffectProcessor:
    def process(self, sample: float) -> float:
        raise NotImplementedError

    def reset(self) -> None:
        return None


class _IdentityEffect(_EffectProcessor):
    def process(self, sample: float) -> float:
        return sample


class _FiltersEffect(_EffectProcessor):
    def __init__(self, filters: list[_FilterProcessor]) -> None:
        self._filters = filters

    def process(self, sample: float) -> float:
        if sample == 0.0:
            return 0.0
        for filter_processor in self._filters:
            sample = filter_processor.process(sample)
        return sample

    def reset(self) -> None:
        for filter_processor in self._filters:
            filter_processor.reset()


class _SaturationEffect(_EffectProcessor):
    def __init__(self, gain_db: float, threshold_db: float) -> None:
        self._gain_linear = _db_to_linear(gain_db)
        self._threshold_linear = _db_to_linear(threshold_db)

    def process(self, sample: float) -> float:
        sample_gain = sample * self._gain_linear
        if abs(sample_gain) > self._threshold_linear:
            exp_2_samples = math.exp(2.0 * sample_gain)
            return (exp_2_samples - 1.0) / (exp_2_samples + 1.0)
        return sample_gain


class _GainEffect(_EffectProcessor):
    def __init__(self, gain_db: float) -> None:
        self._gain_linear = _db_to_linear(gain_db)

    def process(self, sample: float) -> float:
        return sample * self._gain_linear


class _RadioNoiseEffect(_EffectProcessor):
    def __init__(self, floor_db: float, follow_db: float, attack: float, release: float, color: float) -> None:
        self._floor_linear = _db_to_linear(floor_db)
        self._follow_linear = _db_to_linear(follow_db)
        self._envelope = _AttackReleaseEnvelope(attack * 1000.0, release * 1000.0, OUTPUT_SAMPLE_RATE)
        self._presence = 0.0
        self._color = max(0.0, min(0.995, color))
        self._noise_state = 0x4D415944
        self._noise_lowpass = 0.0

    def _next_noise(self) -> float:
        self._noise_state = ((1664525 * self._noise_state) + 1013904223) & 0xFFFFFFFF
        white = ((self._noise_state / 4294967295.0) * 2.0) - 1.0
        self._noise_lowpass = (self._noise_lowpass * self._color) + (white * (1.0 - self._color))
        return white - self._noise_lowpass

    def process(self, sample: float) -> float:
        self._presence = self._envelope.run(abs(sample), self._presence)
        noise_gain = self._floor_linear + (self._follow_linear * min(1.0, self._presence * 4.0))
        return sample + (self._next_noise() * noise_gain)

    def reset(self) -> None:
        self._presence = 0.0
        self._noise_state = 0x4D415944
        self._noise_lowpass = 0.0


class _CVSDEffect(_EffectProcessor):
    def __init__(self) -> None:
        self._cvsd = _CVSD()

    def process(self, sample: float) -> float:
        return self._cvsd.transform(sample)

    def reset(self) -> None:
        self._cvsd.reset()


class _ChainEffect(_EffectProcessor):
    def __init__(self, effects: list[_EffectProcessor]) -> None:
        self._effects = effects

    def process(self, sample: float) -> float:
        for effect in self._effects:
            sample = effect.process(sample)
        return sample

    def reset(self) -> None:
        for effect in self._effects:
            effect.reset()


class _TacComCompressorEffect(_EffectProcessor):
    def __init__(self, attack_ms: float, release_ms: float, threshold_db: float, ratio: float, makeup_gain_db: float) -> None:
        self._compressor = _SidechainCompressor(attack_ms, release_ms, OUTPUT_SAMPLE_RATE)
        self._compressor.threshold = threshold_db
        self._compressor.ratio = ratio
        self._compressor.make_up_gain = makeup_gain_db

    def process(self, sample: float) -> float:
        return self._compressor.process(sample, sample)

    def reset(self) -> None:
        self._compressor.reset()


class _TacComDmoDistortionEffect(_EffectProcessor):
    def __init__(
        self,
        gain_db: float,
        offset_gain_db: float,
        edge: float,
        post_eq_center_frequency: float,
        post_eq_bandwidth: float,
        pre_lowpass_cutoff: float,
    ) -> None:
        self._pre_lowpass = _FirstOrderFilter.low_pass(OUTPUT_SAMPLE_RATE, pre_lowpass_cutoff)
        q = max(0.1, post_eq_center_frequency / max(1.0, post_eq_bandwidth))
        self._post_eq = _BiQuadFilter.peaking_eq(post_eq_center_frequency, q, max(0.0, edge - 50.0) * 0.08)
        self._drive = _db_to_linear((edge * 0.24) + gain_db + 24.0)
        self._output_gain = _db_to_linear(offset_gain_db)
        self._edge = max(0.0, min(1.0, edge / 100.0))

    def process(self, sample: float) -> float:
        driven = self._pre_lowpass.process(sample) * self._drive
        clipped = math.tanh(driven * (1.0 + (self._edge * 6.0)))
        folded = clipped - (math.copysign(1.0, clipped) * clipped * clipped * self._edge * 0.18)
        return self._post_eq.process(folded) * self._output_gain

    def reset(self) -> None:
        self._pre_lowpass.reset()
        self._post_eq.reset()


class _HalfWaveRectifyDistortionEffect(_EffectProcessor):
    def __init__(self, wet: float, dry: float, input_gain_db: float, output_gain_db: float) -> None:
        self._wet = max(0.0, min(1.0, wet))
        self._dry = max(0.0, min(1.0, dry))
        self._input_gain = _db_to_linear(input_gain_db)
        self._output_gain = _db_to_linear(output_gain_db)

    def process(self, sample: float) -> float:
        driven = sample * self._input_gain
        rectified = max(0.0, driven)
        return ((rectified * self._wet) + (sample * self._dry)) * self._output_gain


class _TriangleRingModulatorEffect(_EffectProcessor):
    def __init__(self, frequency: float, wet: float, dry: float, modulated_gain_db: float) -> None:
        self._frequency = frequency
        self._wet = max(0.0, min(1.0, wet))
        self._dry = max(0.0, min(1.0, dry))
        self._modulated_gain = _db_to_linear(modulated_gain_db)
        self._phase = 0.0

    def process(self, sample: float) -> float:
        self._phase = (self._phase + (self._frequency / OUTPUT_SAMPLE_RATE)) % 1.0
        triangle = (4.0 * abs(self._phase - 0.5)) - 1.0
        modulated = sample * triangle * self._modulated_gain
        return (sample * self._dry) + (modulated * self._wet)

    def reset(self) -> None:
        self._phase = 0.0


class _TacComHaProfileEffect(_EffectProcessor):
    """Legacy Python approximation. Native MaydayAudioHost uses the original TAC-COM HA chain."""

    def __init__(
        self,
        intensity: float = 1.0,
        input_gain_db: float = -10.0,
        output_gain_db: float = -3.0,
        input_gate_threshold_db: float = -50.0,
    ) -> None:
        intensity = max(0.0, min(1.0, intensity))
        self._input_gain = _db_to_linear(input_gain_db)
        self._output_gain = _db_to_linear(output_gain_db)
        self._input_gate_threshold = _db_to_linear(input_gate_threshold_db)
        self._input_gate_open_threshold = _db_to_linear(input_gate_threshold_db + 8.0)
        self._input_gate_envelope = 0.0
        self._primary_mix = 0.7 * intensity
        self._parallel_mix = 0.3 * intensity
        self._primary = _ChainEffect(
            [
                _FiltersEffect(
                    [
                        _FirstOrderFilter.high_pass(OUTPUT_SAMPLE_RATE, 800.0),
                        _FirstOrderFilter.low_pass(OUTPUT_SAMPLE_RATE, 3500.0),
                    ]
                ),
                _TacComDmoDistortionEffect(-15.0, -60.0, 55.0, 5500.0, 3500.0, 8000.0),
                _TacComCompressorEffect(30.0, 300.0, -20.0, 100.0, 10.0),
                _TacComCompressorEffect(50.0, 300.0, -40.0, 30.0, 45.0),
                _HalfWaveRectifyDistortionEffect(0.5, 0.5, 28.0, 8.0),
                _TacComCompressorEffect(30.0, 300.0, -10.0, 4.0, 5.0),
                _TriangleRingModulatorEffect(550.0, 0.04 * intensity, 1.0 - (0.04 * intensity), 45.0),
                _GainEffect(-7.0),
            ]
        )
        self._parallel = _ChainEffect(
            [
                _FiltersEffect(
                    [
                        _FirstOrderFilter.high_pass(OUTPUT_SAMPLE_RATE, 100.0),
                        _FirstOrderFilter.low_pass(OUTPUT_SAMPLE_RATE, 1500.0),
                    ]
                ),
                _TacComCompressorEffect(10.0, 300.0, -30.0, 40.0, 20.0),
                _TacComDmoDistortionEffect(-60.0, -45.0, 75.0, 1500.0, 4800.0, 8000.0),
                _GainEffect(-5.0),
            ]
        )

    def process(self, sample: float) -> float:
        chain_input = sample * self._input_gain * self._input_gate_gain(sample)
        primary = self._primary.process(chain_input)
        parallel = self._parallel.process(chain_input)
        dry_mix = max(0.0, 1.0 - self._primary_mix - self._parallel_mix)
        return ((primary * self._primary_mix) + (parallel * self._parallel_mix) + (sample * dry_mix)) * self._output_gain

    def reset(self) -> None:
        self._primary.reset()
        self._parallel.reset()
        self._input_gate_envelope = 0.0

    def _input_gate_gain(self, sample: float) -> float:
        magnitude = abs(sample)
        attack = math.exp(-1.0 / (0.004 * OUTPUT_SAMPLE_RATE))
        release = math.exp(-1.0 / (0.090 * OUTPUT_SAMPLE_RATE))
        coefficient = attack if magnitude > self._input_gate_envelope else release
        self._input_gate_envelope = magnitude + (coefficient * (self._input_gate_envelope - magnitude))
        if self._input_gate_envelope <= self._input_gate_threshold:
            return 0.0
        if self._input_gate_envelope >= self._input_gate_open_threshold:
            return 1.0
        return (self._input_gate_envelope - self._input_gate_threshold) / max(
            1.0e-9, self._input_gate_open_threshold - self._input_gate_threshold
        )


class _MaydayReferenceCommsProfileEffect(_EffectProcessor):
    """Reference RX profile matched from the user's plain/effected voice WAV pair."""

    def __init__(self, intensity: float = 1.0) -> None:
        self._intensity = max(0.0, min(1.0, intensity))
        self._voice_chain = _ChainEffect(
            [
                _FiltersEffect(
                    [
                        _FirstOrderFilter.high_pass(OUTPUT_SAMPLE_RATE, 85.0),
                        _BiQuadFilter.peaking_eq(120.0, 0.64, 2.2),
                        _BiQuadFilter.peaking_eq(430.0, 0.82, 2.8),
                        _BiQuadFilter.peaking_eq(850.0, 0.76, 4.8),
                        _BiQuadFilter.peaking_eq(1650.0, 0.88, 4.2),
                        _BiQuadFilter.peaking_eq(2850.0, 0.82, 5.2),
                        _BiQuadFilter.low_pass(5200.0, 0.58),
                    ]
                ),
                _TacComCompressorEffect(6.0, 120.0, -31.0, 4.8, 7.5),
                _TacComDmoDistortionEffect(-14.0, -28.0, 42.0, 2500.0, 4200.0, 7200.0),
                _HalfWaveRectifyDistortionEffect(0.14, 0.86, 13.0, -7.0),
                _TacComCompressorEffect(4.0, 160.0, -16.0, 2.2, 1.0),
                _GainEffect(12.5),
            ]
        )
        self._body_chain = _ChainEffect(
            [
                _FiltersEffect(
                    [
                        _FirstOrderFilter.high_pass(OUTPUT_SAMPLE_RATE, 35.0),
                        _FirstOrderFilter.low_pass(OUTPUT_SAMPLE_RATE, 1200.0),
                        _BiQuadFilter.peaking_eq(75.0, 0.65, 2.0),
                        _BiQuadFilter.peaking_eq(260.0, 0.72, 1.6),
                        _BiQuadFilter.peaking_eq(720.0, 0.82, 3.0),
                    ]
                ),
                _TacComCompressorEffect(16.0, 210.0, -34.0, 7.0, 7.0),
                _GainEffect(4.0),
            ]
        )
        self._noise_envelope = _AttackReleaseEnvelope(6.0, 140.0, OUTPUT_SAMPLE_RATE)
        self._presence = 0.0
        self._noise_state = 0x53435132
        self._noise_lowpass = 0.0

    def process(self, sample: float) -> float:
        self._presence = self._noise_envelope.run(abs(sample), self._presence)
        voice = self._voice_chain.process(sample)
        body = self._body_chain.process(sample)
        noise = self._next_colored_noise() * (0.0032 + (min(1.0, self._presence * 7.0) * 0.0080)) * self._intensity
        processed = (voice * (0.82 + (0.10 * self._intensity))) + (body * 0.18 * self._intensity) + noise
        return (processed * self._intensity) + (sample * (1.0 - self._intensity))

    def reset(self) -> None:
        self._voice_chain.reset()
        self._body_chain.reset()
        self._presence = 0.0
        self._noise_state = 0x53435132
        self._noise_lowpass = 0.0

    def _next_colored_noise(self) -> float:
        self._noise_state = ((1664525 * self._noise_state) + 1013904223) & 0xFFFFFFFF
        white = ((self._noise_state / 4294967295.0) * 2.0) - 1.0
        self._noise_lowpass = (self._noise_lowpass * 0.92) + (white * 0.08)
        return (self._noise_lowpass * 0.35) + (white * 0.65)


class _GentleSoftClipEffect(_EffectProcessor):
    def __init__(self, drive: float) -> None:
        self._drive = max(1.0, min(1.5, drive))
        self._normalizer = math.tanh(self._drive)

    def process(self, sample: float) -> float:
        if self._drive <= 1.001:
            return sample
        return math.tanh(sample * self._drive) / self._normalizer


class _ShortRoomReverbEffect(_EffectProcessor):
    def __init__(self, pre_delay_ms: float, decay_seconds: float, mix: float) -> None:
        self._pre_delay = [0.0] * self._milliseconds_to_samples(max(1.0, min(60.0, pre_delay_ms)))
        self._room_a = [0.0] * self._milliseconds_to_samples(43.0)
        self._room_b = [0.0] * self._milliseconds_to_samples(61.0)
        self._room_c = [0.0] * self._milliseconds_to_samples(79.0)
        self._allpass_a = [0.0] * self._milliseconds_to_samples(7.0)
        self._allpass_b = [0.0] * self._milliseconds_to_samples(11.0)
        decay = max(0.10, min(1.20, decay_seconds))
        self._feedback_a = self._feedback_for_delay(len(self._room_a), decay)
        self._feedback_b = self._feedback_for_delay(len(self._room_b), decay)
        self._feedback_c = self._feedback_for_delay(len(self._room_c), decay)
        self._mix = max(0.0, min(0.18, mix))
        self._pre_index = 0
        self._room_a_index = 0
        self._room_b_index = 0
        self._room_c_index = 0
        self._allpass_a_index = 0
        self._allpass_b_index = 0

    def process(self, sample: float) -> float:
        delayed_input = self._push_delay(self._pre_delay, "_pre_index", sample)
        early = (
            self._tap(self._pre_delay, self._pre_index, self._milliseconds_to_samples(3.0)) * 0.22
            + self._tap(self._pre_delay, self._pre_index, self._milliseconds_to_samples(8.0)) * 0.18
            + self._tap(self._pre_delay, self._pre_index, self._milliseconds_to_samples(13.0)) * 0.13
        )
        wet = (
            self._comb(self._room_a, "_room_a_index", delayed_input + early, self._feedback_a) * 0.34
            + self._comb(self._room_b, "_room_b_index", delayed_input, self._feedback_b) * 0.31
            + self._comb(self._room_c, "_room_c_index", delayed_input, self._feedback_c) * 0.26
            + early
        )
        wet = self._allpass(self._allpass_a, "_allpass_a_index", wet, 0.52)
        wet = self._allpass(self._allpass_b, "_allpass_b_index", wet, 0.46)
        wet = max(-1.0, min(1.0, wet))
        return (sample * (1.0 - self._mix)) + (wet * self._mix)

    def reset(self) -> None:
        self._pre_delay = [0.0] * len(self._pre_delay)
        self._room_a = [0.0] * len(self._room_a)
        self._room_b = [0.0] * len(self._room_b)
        self._room_c = [0.0] * len(self._room_c)
        self._allpass_a = [0.0] * len(self._allpass_a)
        self._allpass_b = [0.0] * len(self._allpass_b)
        self._pre_index = 0
        self._room_a_index = 0
        self._room_b_index = 0
        self._room_c_index = 0
        self._allpass_a_index = 0
        self._allpass_b_index = 0

    @staticmethod
    def _milliseconds_to_samples(milliseconds: float) -> int:
        return max(1, round(OUTPUT_SAMPLE_RATE * milliseconds / 1000.0))

    @staticmethod
    def _feedback_for_delay(delay_samples: int, decay_seconds: float) -> float:
        delay_seconds = delay_samples / OUTPUT_SAMPLE_RATE
        return max(0.18, min(0.88, math.pow(0.001, delay_seconds / decay_seconds)))

    def _push_delay(self, buffer: list[float], index_attr: str, input_sample: float) -> float:
        index = getattr(self, index_attr)
        output = buffer[index]
        buffer[index] = input_sample
        setattr(self, index_attr, (index + 1) % len(buffer))
        return output

    @staticmethod
    def _tap(buffer: list[float], write_index: int, delay_samples: int) -> float:
        read_index = write_index - max(1, min(len(buffer) - 1, delay_samples))
        while read_index < 0:
            read_index += len(buffer)
        return buffer[read_index % len(buffer)]

    def _comb(self, buffer: list[float], index_attr: str, input_sample: float, feedback: float) -> float:
        index = getattr(self, index_attr)
        delayed = buffer[index]
        buffer[index] = max(-1.0, min(1.0, input_sample + (delayed * feedback)))
        setattr(self, index_attr, (index + 1) % len(buffer))
        return delayed

    def _allpass(self, buffer: list[float], index_attr: str, input_sample: float, feedback: float) -> float:
        index = getattr(self, index_attr)
        delayed = buffer[index]
        output = -input_sample + delayed
        buffer[index] = input_sample + (delayed * feedback)
        setattr(self, index_attr, (index + 1) % len(buffer))
        return output


class _HomeworldFleetCommsEffect(_EffectProcessor):
    PRESET_NAME = "HOMEWORLD_FLEET_COMMS"

    def __init__(self) -> None:
        self._voice_chain = _ChainEffect(
            [
                _FiltersEffect(
                    [
                        _BiQuadFilter.high_pass(190.0, 0.72),
                        _BiQuadFilter.peaking_eq(420.0, 0.85, -3.0),
                        _BiQuadFilter.peaking_eq(1150.0, 0.90, 4.2),
                        _BiQuadFilter.peaking_eq(2900.0, 0.95, 2.1),
                        _BiQuadFilter.low_pass(4850.0, 0.62),
                        _FirstOrderFilter.low_pass(OUTPUT_SAMPLE_RATE, 5200.0),
                    ]
                ),
                _CompressorEffect(0.008, 3.0, 0.110, -27.0, 3.5),
                _GentleSoftClipEffect(1.08),
                _RadioNoiseEffect(-54.0, -60.0, 0.006, 0.140, 0.94),
            ]
        )
        self._space = _ShortRoomReverbEffect(16.0, 0.52, 0.075)
        self._grain_state = 0x48465743
        self._grain_lowpass = 0.0

    def process(self, sample: float) -> float:
        focused = self._voice_chain.process(sample)
        with_grain = focused + (self._next_grain() * 0.0011)
        return max(-0.98, min(0.98, self._space.process(with_grain)))

    def reset(self) -> None:
        self._voice_chain.reset()
        self._space.reset()
        self._grain_state = 0x48465743
        self._grain_lowpass = 0.0

    def _next_grain(self) -> float:
        self._grain_state = ((1664525 * self._grain_state) + 1013904223) & 0xFFFFFFFF
        white = ((self._grain_state / 4294967295.0) * 2.0) - 1.0
        self._grain_lowpass = (self._grain_lowpass * 0.86) + (white * 0.14)
        return (white * 0.55) + (self._grain_lowpass * 0.45)


class _MildFanRadioEffect(_EffectProcessor):
    PRESET_NAME = "MILD_FAN_RADIO"

    def __init__(
        self,
        fan_rate: float = 5.2,
        fan_depth: float = 0.27,
        fan_mix: float = 0.60,
        low_cut: float = 135.0,
        high_cut: float = 4800.0,
        mid_boost_freq: float = 750.0,
        mid_boost_gain: float = 7.5,
        low_mid_cut_freq: float = 300.0,
        low_mid_cut_gain: float = -6.0,
        saturation_drive: float = 1.18,
        output_gain_db: float = 0.0,
        bypass: bool = False,
    ) -> None:
        self._fan_rate = max(0.1, min(20.0, fan_rate))
        self._fan_depth = max(0.0, min(0.95, fan_depth))
        self._fan_mix = max(0.0, min(1.0, fan_mix))
        self._saturation_drive = max(1.0, min(3.0, saturation_drive))
        self._output_gain = _db_to_linear(output_gain_db)
        self._bypass = bypass
        self._phase = 0.0
        self._eq = _FiltersEffect(
            [
                _FirstOrderFilter.high_pass(OUTPUT_SAMPLE_RATE, low_cut),
                _BiQuadFilter.peaking_eq(low_mid_cut_freq, 0.80, low_mid_cut_gain),
                _BiQuadFilter.peaking_eq(mid_boost_freq, 0.90, mid_boost_gain),
                _BiQuadFilter.peaking_eq(3200.0, 0.80, -1.5),
                _FirstOrderFilter.low_pass(OUTPUT_SAMPLE_RATE, high_cut),
            ]
        )

    def process(self, sample: float) -> float:
        if self._bypass:
            return sample

        # 1-2. Keep the voice narrow and push the fan-like mid band.
        filtered = self._eq.process(sample)

        # 3. Sine tremolo: audible movement without chopping syllables.
        lfo = (math.sin(self._phase * 2.0 * math.pi) + 1.0) * 0.5
        tremolo_gain = 1.0 - (self._fan_depth * lfo)
        self._phase = (self._phase + (self._fan_rate / OUTPUT_SAMPLE_RATE)) % 1.0
        moving = (filtered * (1.0 - self._fan_mix)) + (filtered * tremolo_gain * self._fan_mix)

        # 4-6. Mild tanh saturation and peak protection. No bitcrusher or hard clipping.
        saturated = math.tanh(moving * self._saturation_drive) / math.tanh(self._saturation_drive)
        return max(-0.98, min(0.98, saturated * self._output_gain))

    def reset(self) -> None:
        self._phase = 0.0
        self._eq.reset()


class _CompressorEffect(_EffectProcessor):
    def __init__(self, attack: float, make_up: float, release: float, threshold: float, ratio: float) -> None:
        self._compressor = _SidechainCompressor(attack * 1000.0, release * 1000.0, OUTPUT_SAMPLE_RATE)
        self._compressor.make_up_gain = make_up
        self._compressor.threshold = threshold
        self._compressor.ratio = ratio

    def process(self, sample: float) -> float:
        return self._compressor.process(sample, sample)

    def reset(self) -> None:
        self._compressor.reset()


class _SidechainCompressorEffect(_EffectProcessor):
    def __init__(
        self,
        attack: float,
        make_up: float,
        release: float,
        threshold: float,
        ratio: float,
        sidechain_effect: _EffectProcessor,
    ) -> None:
        self._compressor = _SidechainCompressor(attack * 1000.0, release * 1000.0, OUTPUT_SAMPLE_RATE)
        self._compressor.make_up_gain = make_up
        self._compressor.threshold = threshold
        self._compressor.ratio = ratio
        self._sidechain = sidechain_effect

    def process(self, sample: float) -> float:
        sidechain_sample = self._sidechain.process(sample)
        return self._compressor.process(sidechain_sample, sample)

    def reset(self) -> None:
        self._compressor.reset()
        self._sidechain.reset()


def _build_filter(filter_spec: Mapping[str, Any]) -> _FilterProcessor:
    filter_type = str(filter_spec["$type"]).strip().lower()
    frequency = float(filter_spec["frequency"])
    q = filter_spec.get("q")

    if filter_type == "lowpass":
        if q is None:
            return _FirstOrderFilter.low_pass(OUTPUT_SAMPLE_RATE, frequency)
        return _BiQuadFilter.low_pass(frequency, float(q))

    if filter_type == "highpass":
        if q is None:
            return _FirstOrderFilter.high_pass(OUTPUT_SAMPLE_RATE, frequency)
        return _BiQuadFilter.high_pass(frequency, float(q))

    if filter_type == "peak":
        return _BiQuadFilter.peaking_eq(frequency, float(q), float(filter_spec["gain"]))

    raise ValueError(f"Unsupported radio filter type: {filter_type}")


def _build_effect(effect_spec: Mapping[str, Any]) -> _EffectProcessor:
    effect_type = str(effect_spec["$type"]).strip().lower()

    if effect_type == "chain":
        return _ChainEffect([_build_effect(effect) for effect in effect_spec["effects"]])

    if effect_type == "identity":
        return _IdentityEffect()

    if effect_type == "filters":
        return _FiltersEffect([_build_filter(filter_spec) for filter_spec in effect_spec["filters"]])

    if effect_type == "saturation":
        return _SaturationEffect(float(effect_spec["gain"]), float(effect_spec["threshold"]))

    if effect_type == "compressor":
        return _CompressorEffect(
            float(effect_spec["attack"]),
            float(effect_spec["makeUp"]),
            float(effect_spec["release"]),
            float(effect_spec["threshold"]),
            float(effect_spec["ratio"]),
        )

    if effect_type == "sidechaincompressor":
        return _SidechainCompressorEffect(
            float(effect_spec["attack"]),
            float(effect_spec["makeUp"]),
            float(effect_spec["release"]),
            float(effect_spec["threshold"]),
            float(effect_spec["ratio"]),
            _build_effect(effect_spec["sidechainEffect"]),
        )

    if effect_type == "gain":
        return _GainEffect(float(effect_spec["gain"]))

    if effect_type == "radionoise":
        return _RadioNoiseEffect(
            float(effect_spec["floor"]),
            float(effect_spec["follow"]),
            float(effect_spec["attack"]),
            float(effect_spec["release"]),
            float(effect_spec.get("color", 0.85)),
        )

    if effect_type == "cvsd":
        return _CVSDEffect()

    if effect_type == "homeworldFleetComms":
        return _HomeworldFleetCommsEffect()

    raise ValueError(f"Unsupported radio effect type: {effect_type}")


class MonoEffectProcessor:
    def __init__(
        self,
        effect_spec: Mapping[str, Any],
        wet_mix: float = 1.0,
        backing_effect_spec: Mapping[str, Any] | None = None,
        backing_mix: float = 0.0,
        output_gain: float = 1.0,
    ) -> None:
        self._effect = _build_effect(effect_spec)
        self._wet_mix = max(0.0, min(1.0, wet_mix))
        self._dry_mix = 1.0 - self._wet_mix
        self._backing_effect = _build_effect(backing_effect_spec) if backing_effect_spec is not None else None
        self._backing_mix = max(0.0, min(1.0, backing_mix))
        self._output_gain = max(0.0, float(output_gain))

    def reset(self) -> None:
        self._effect.reset()
        if self._backing_effect is not None:
            self._backing_effect.reset()

    def process_sample(self, sample: float, gain: float = 1.0) -> float:
        processed = self._effect.process(sample)
        mixed = (processed * self._wet_mix) + (sample * self._dry_mix)
        if self._backing_effect is not None and self._backing_mix > 0.0:
            backing = self._backing_effect.process(sample)
            mixed = (mixed * (1.0 - self._backing_mix)) + (backing * self._backing_mix)
        return mixed * gain * self._output_gain

    def process_float_samples(self, samples: list[float], gain: float = 1.0) -> list[float]:
        if not samples:
            return []
        return [self.process_sample(sample, gain=gain) for sample in samples]

    def process_pcm16(self, pcm_bytes: bytes, gain: float = 1.0) -> bytes:
        if not pcm_bytes:
            return pcm_bytes

        processed = bytearray()
        samples = [
            _pcm16_to_float(int.from_bytes(pcm_bytes[offset : offset + 2], "little", signed=True))
            for offset in range(0, len(pcm_bytes), 2)
        ]
        for processed_sample in self.process_float_samples(samples, gain=gain):
            pcm_sample = _float_to_pcm16(processed_sample)
            processed.extend(pcm_sample.to_bytes(2, "little", signed=True))
        return bytes(processed)


class Arc210RxProcessor(MonoEffectProcessor):
    def __init__(self, role: str = "Soldier") -> None:
        is_pilot = role.strip().lower() == "pilot"
        super().__init__(
            {"$type": "identity"},
            wet_mix=PILOT_RX_WET_MIX if is_pilot else NON_PILOT_RX_WET_MIX,
            output_gain=PILOT_RX_OUTPUT_GAIN if is_pilot else NON_PILOT_RX_OUTPUT_GAIN,
        )
        self._effect = self._build_role_profile(role)
        self._backing_effect = None
        self._backing_mix = 0.0

    @classmethod
    def _build_role_profile(cls, role: str) -> _EffectProcessor:
        if role.strip().lower() == "pilot":
            return _TacComHaProfileEffect(cls._role_intensity(role))
        return _HomeworldFleetCommsEffect()

    @classmethod
    def ha_hardened_waveform(cls, role: str = "Soldier") -> "Arc210RxProcessor":
        processor = cls(role)
        processor._effect = _TacComHaProfileEffect(cls._role_intensity(role))
        return processor

    @staticmethod
    def _role_intensity(role: str) -> float:
        return 1.0


def process_pcm16_mono(pcm_bytes: bytes, gain: float = 1.0, channel_tag: str = "general") -> bytes:
    del channel_tag
    if gain == 1.0:
        return pcm_bytes
    return MonoEffectProcessor({"$type": "identity"}, wet_mix=0.0).process_pcm16(pcm_bytes, gain=gain)


def process_rx_pcm16_mono(pcm_bytes: bytes, gain: float = 1.0) -> bytes:
    return Arc210RxProcessor().process_pcm16(pcm_bytes, gain=gain)
