using TAC_COM.Audio.EffectsChains;

namespace MaydayAudioHost;

internal static class RadioConstants
{
    public const double OutputSampleRate = 48000.0;
}

internal interface IFilterProcessor
{
    double Process(double sample);
    void Reset();
}

internal interface IEffectProcessor
{
    double Process(double sample);
    void Reset();
}

internal sealed class FirstOrderFilter : IFilterProcessor
{
    private readonly double _b0;
    private readonly double _b1;
    private readonly double _a1;
    private double _xN1;
    private double _yN1;

    private FirstOrderFilter(double b0, double b1, double a1)
    {
        _b0 = b0;
        _b1 = b1;
        _a1 = a1;
    }

    public static FirstOrderFilter LowPass(double cutoff)
    {
        var w0 = 2.0 * Math.PI * cutoff / RadioConstants.OutputSampleRate;
        var sinW0 = Math.Sin(w0);
        var cosW0 = Math.Cos(w0);
        var a0 = sinW0 + 1.0 + cosW0;
        var a1 = sinW0 - 1.0 - cosW0;
        var b0 = sinW0;
        var b1 = sinW0;
        return new FirstOrderFilter(b0 / a0, b1 / a0, a1 / a0);
    }

    public static FirstOrderFilter HighPass(double cutoff)
    {
        var w0 = 2.0 * Math.PI * cutoff / RadioConstants.OutputSampleRate;
        var sinW0 = Math.Sin(w0);
        var cosW0 = Math.Cos(w0);
        var a0 = sinW0 + 1.0 + cosW0;
        var a1 = sinW0 - 1.0 - cosW0;
        var b0 = 1.0 + cosW0;
        var b1 = -1.0 - cosW0;
        return new FirstOrderFilter(b0 / a0, b1 / a0, a1 / a0);
    }

    public double Process(double sample)
    {
        _yN1 = (_b0 * sample) + (_b1 * _xN1) - (_a1 * _yN1);
        _xN1 = sample;
        return _yN1;
    }

    public void Reset()
    {
        _xN1 = 0.0;
        _yN1 = 0.0;
    }
}

internal sealed class BiQuadFilter : IFilterProcessor
{
    private readonly double _b0;
    private readonly double _b1;
    private readonly double _b2;
    private readonly double _a1;
    private readonly double _a2;
    private double _x1;
    private double _x2;
    private double _y1;
    private double _y2;

    private BiQuadFilter(double b0, double b1, double b2, double a1, double a2)
    {
        _b0 = b0;
        _b1 = b1;
        _b2 = b2;
        _a1 = a1;
        _a2 = a2;
    }

    public static BiQuadFilter HighPass(double freq, double q)
    {
        Normalize(ref freq, ref q);
        var w0 = 2.0 * Math.PI * freq / RadioConstants.OutputSampleRate;
        var alpha = Math.Sin(w0) / (2.0 * q);
        var cosW0 = Math.Cos(w0);
        return Build(
            ((1.0 + cosW0) * 0.5, -(1.0 + cosW0), (1.0 + cosW0) * 0.5),
            (1.0 + alpha, -2.0 * cosW0, 1.0 - alpha)
        );
    }

    public static BiQuadFilter LowPass(double freq, double q)
    {
        Normalize(ref freq, ref q);
        var w0 = 2.0 * Math.PI * freq / RadioConstants.OutputSampleRate;
        var alpha = Math.Sin(w0) / (2.0 * q);
        var cosW0 = Math.Cos(w0);
        return Build(
            ((1.0 - cosW0) * 0.5, 1.0 - cosW0, (1.0 - cosW0) * 0.5),
            (1.0 + alpha, -2.0 * cosW0, 1.0 - alpha)
        );
    }

    public static BiQuadFilter PeakingEq(double freq, double q, double gainDb)
    {
        Normalize(ref freq, ref q);
        var amplitude = Math.Pow(10.0, gainDb / 40.0);
        var w0 = 2.0 * Math.PI * freq / RadioConstants.OutputSampleRate;
        var alpha = Math.Sin(w0) / (2.0 * q);
        var cosW0 = Math.Cos(w0);
        return Build(
            (1.0 + alpha * amplitude, -2.0 * cosW0, 1.0 - alpha * amplitude),
            (1.0 + alpha / amplitude, -2.0 * cosW0, 1.0 - alpha / amplitude)
        );
    }

    private static void Normalize(ref double freq, ref double q)
    {
        freq = Math.Clamp(freq, 1.0, (RadioConstants.OutputSampleRate * 0.5) - 1.0);
        q = Math.Max(q, 0.05);
    }

    private static BiQuadFilter Build((double B0, double B1, double B2) numerator, (double A0, double A1, double A2) denominator)
    {
        return new BiQuadFilter(
            numerator.B0 / denominator.A0,
            numerator.B1 / denominator.A0,
            numerator.B2 / denominator.A0,
            denominator.A1 / denominator.A0,
            denominator.A2 / denominator.A0
        );
    }

    public double Process(double sample)
    {
        var output = (_b0 * sample) + (_b1 * _x1) + (_b2 * _x2) - (_a1 * _y1) - (_a2 * _y2);
        _x2 = _x1;
        _x1 = sample;
        _y2 = _y1;
        _y1 = output;
        return output;
    }

    public void Reset()
    {
        _x1 = 0.0;
        _x2 = 0.0;
        _y1 = 0.0;
        _y2 = 0.0;
    }
}

internal sealed class EnvelopeDetector
{
    private readonly double _coefficient;

    public EnvelopeDetector(double milliseconds, double sampleRate)
    {
        _coefficient = Math.Exp(-1.0 / (0.001 * milliseconds * sampleRate));
    }

    public double Run(double inputValue, double state)
    {
        return inputValue + (_coefficient * (state - inputValue));
    }
}

internal sealed class AttackReleaseEnvelope
{
    private readonly EnvelopeDetector _attack;
    private readonly EnvelopeDetector _release;

    public AttackReleaseEnvelope(double attackMilliseconds, double releaseMilliseconds, double sampleRate)
    {
        _attack = new EnvelopeDetector(attackMilliseconds, sampleRate);
        _release = new EnvelopeDetector(releaseMilliseconds, sampleRate);
    }

    public double Run(double inputValue, double state)
    {
        return inputValue > state ? _attack.Run(inputValue, state) : _release.Run(inputValue, state);
    }
}

internal sealed class SidechainCompressor
{
    private const double DcOffset = 1.0e-25;
    private readonly AttackReleaseEnvelope _envelope;
    private double _envelopeDb = DcOffset;

    public SidechainCompressor(double attackMilliseconds, double releaseMilliseconds, double sampleRate)
    {
        _envelope = new AttackReleaseEnvelope(attackMilliseconds, releaseMilliseconds, sampleRate);
    }

    public double MakeUpGainDb { get; set; }
    public double ThresholdDb { get; set; }
    public double Ratio { get; set; } = 1.0;

    public double Process(double sideIn, double signalIn)
    {
        var rectified = Math.Abs(sideIn) + DcOffset;
        var keyDb = 20.0 * Math.Log10(rectified);
        var overDb = Math.Max(0.0, keyDb - ThresholdDb) + DcOffset;
        _envelopeDb = _envelope.Run(overDb, _envelopeDb);
        overDb = _envelopeDb - DcOffset;
        var gainReduction = overDb * ((1.0 / Math.Max(Ratio, 1.0)) - 1.0);
        var linearGain = Math.Pow(10.0, gainReduction / 20.0) * Math.Pow(10.0, MakeUpGainDb / 20.0);
        return signalIn * linearGain;
    }

    public void Reset()
    {
        _envelopeDb = DcOffset;
    }
}

internal sealed class FiltersEffect : IEffectProcessor
{
    private readonly IFilterProcessor[] _filters;

    public FiltersEffect(params IFilterProcessor[] filters)
    {
        _filters = filters;
    }

    public double Process(double sample)
    {
        if (sample == 0.0)
        {
            return 0.0;
        }

        foreach (var filter in _filters)
        {
            sample = filter.Process(sample);
        }

        return sample;
    }

    public void Reset()
    {
        foreach (var filter in _filters)
        {
            filter.Reset();
        }
    }
}

internal sealed class SaturationEffect : IEffectProcessor
{
    private readonly double _gainLinear;
    private readonly double _thresholdLinear;

    public SaturationEffect(double gainDb, double thresholdDb)
    {
        _gainLinear = Math.Pow(10.0, gainDb / 20.0);
        _thresholdLinear = Math.Pow(10.0, thresholdDb / 20.0);
    }

    public double Process(double sample)
    {
        var sampleGain = sample * _gainLinear;
        if (Math.Abs(sampleGain) > _thresholdLinear)
        {
            var exp = Math.Exp(2.0 * sampleGain);
            return (exp - 1.0) / (exp + 1.0);
        }

        return sampleGain;
    }

    public void Reset()
    {
    }
}

internal sealed class GainEffect : IEffectProcessor
{
    private readonly double _gainLinear;

    public GainEffect(double gainDb)
    {
        _gainLinear = Math.Pow(10.0, gainDb / 20.0);
    }

    public double Process(double sample)
    {
        return sample * _gainLinear;
    }

    public void Reset()
    {
    }
}

internal sealed class RadioNoiseEffect : IEffectProcessor
{
    private readonly double _floorLinear;
    private readonly double _followLinear;
    private readonly AttackReleaseEnvelope _envelope;
    private readonly double _color;
    private double _presence;
    private uint _noiseState = 0x4D415944;
    private double _noiseLowpass;

    public RadioNoiseEffect(double floorDb, double followDb, double attackSeconds, double releaseSeconds, double color)
    {
        _floorLinear = Math.Pow(10.0, floorDb / 20.0);
        _followLinear = Math.Pow(10.0, followDb / 20.0);
        _envelope = new AttackReleaseEnvelope(attackSeconds * 1000.0, releaseSeconds * 1000.0, RadioConstants.OutputSampleRate);
        _color = Math.Clamp(color, 0.0, 0.995);
    }

    private double NextNoise()
    {
        _noiseState = (uint)((1664525u * _noiseState) + 1013904223u);
        var white = ((_noiseState / 4294967295.0) * 2.0) - 1.0;
        _noiseLowpass = (_noiseLowpass * _color) + (white * (1.0 - _color));
        return white - _noiseLowpass;
    }

    public double Process(double sample)
    {
        _presence = _envelope.Run(Math.Abs(sample), _presence);
        var noiseGain = _floorLinear + (_followLinear * Math.Min(1.0, _presence * 4.0));
        return sample + (NextNoise() * noiseGain);
    }

    public void Reset()
    {
        _presence = 0.0;
        _noiseState = 0x4D415944;
        _noiseLowpass = 0.0;
    }
}

internal sealed class SidechainCompressorEffect : IEffectProcessor
{
    private readonly SidechainCompressor _compressor;
    private readonly IEffectProcessor _sidechainEffect;

    public SidechainCompressorEffect(
        double attackSeconds,
        double makeUpDb,
        double releaseSeconds,
        double thresholdDb,
        double ratio,
        IEffectProcessor sidechainEffect
    )
    {
        _compressor = new SidechainCompressor(attackSeconds * 1000.0, releaseSeconds * 1000.0, RadioConstants.OutputSampleRate)
        {
            MakeUpGainDb = makeUpDb,
            ThresholdDb = thresholdDb,
            Ratio = ratio,
        };
        _sidechainEffect = sidechainEffect;
    }

    public double Process(double sample)
    {
        var sidechainSample = _sidechainEffect.Process(sample);
        return _compressor.Process(sidechainSample, sample);
    }

    public void Reset()
    {
        _compressor.Reset();
        _sidechainEffect.Reset();
    }
}

internal sealed class ChainEffect : IEffectProcessor
{
    private readonly IEffectProcessor[] _effects;

    public ChainEffect(params IEffectProcessor[] effects)
    {
        _effects = effects;
    }

    public double Process(double sample)
    {
        foreach (var effect in _effects)
        {
            sample = effect.Process(sample);
        }

        return sample;
    }

    public void Reset()
    {
        foreach (var effect in _effects)
        {
            effect.Reset();
        }
    }
}

internal sealed class CompressorEffect : IEffectProcessor
{
    private readonly SidechainCompressor _compressor;

    public CompressorEffect(double attackMilliseconds, double releaseMilliseconds, double thresholdDb, double ratio, double makeupGainDb)
    {
        _compressor = new SidechainCompressor(attackMilliseconds, releaseMilliseconds, RadioConstants.OutputSampleRate)
        {
            ThresholdDb = thresholdDb,
            Ratio = ratio,
            MakeUpGainDb = makeupGainDb,
        };
    }

    public double Process(double sample)
    {
        return _compressor.Process(sample, sample);
    }

    public void Reset()
    {
        _compressor.Reset();
    }
}

internal sealed class TacComDmoDistortionEffect : IEffectProcessor
{
    private readonly FirstOrderFilter _preLowpass;
    private readonly BiQuadFilter _postEq;
    private readonly double _drive;
    private readonly double _outputGain;
    private readonly double _edge;

    public TacComDmoDistortionEffect(
        double gainDb,
        double offsetGainDb,
        double edge,
        double postEqCenterFrequency,
        double postEqBandwidth,
        double preLowpassCutoff
    )
    {
        _preLowpass = FirstOrderFilter.LowPass(preLowpassCutoff);
        _postEq = BiQuadFilter.PeakingEq(postEqCenterFrequency, Math.Max(0.1, postEqCenterFrequency / Math.Max(1.0, postEqBandwidth)), Math.Max(0.0, edge - 50.0) * 0.08);
        _drive = Math.Pow(10.0, ((edge * 0.24) + gainDb + 24.0) / 20.0);
        _outputGain = Math.Pow(10.0, offsetGainDb / 20.0);
        _edge = Math.Clamp(edge / 100.0, 0.0, 1.0);
    }

    public double Process(double sample)
    {
        var driven = _preLowpass.Process(sample) * _drive;
        var clipped = Math.Tanh(driven * (1.0 + (_edge * 6.0)));
        var folded = clipped - (Math.Sign(clipped) * clipped * clipped * _edge * 0.18);
        return _postEq.Process(folded) * _outputGain;
    }

    public void Reset()
    {
        _preLowpass.Reset();
        _postEq.Reset();
    }
}

internal sealed class HalfWaveRectifyDistortionEffect : IEffectProcessor
{
    private readonly double _wet;
    private readonly double _dry;
    private readonly double _inputGain;
    private readonly double _outputGain;

    public HalfWaveRectifyDistortionEffect(double wet, double dry, double inputGainDb, double outputGainDb)
    {
        _wet = Math.Clamp(wet, 0.0, 1.0);
        _dry = Math.Clamp(dry, 0.0, 1.0);
        _inputGain = Math.Pow(10.0, inputGainDb / 20.0);
        _outputGain = Math.Pow(10.0, outputGainDb / 20.0);
    }

    public double Process(double sample)
    {
        var driven = sample * _inputGain;
        var rectified = Math.Max(0.0, driven);
        return ((rectified * _wet) + (sample * _dry)) * _outputGain;
    }

    public void Reset()
    {
    }
}

internal sealed class TriangleRingModulatorEffect : IEffectProcessor
{
    private readonly double _frequency;
    private readonly double _wet;
    private readonly double _dry;
    private readonly double _modulatedGain;
    private double _phase;

    public TriangleRingModulatorEffect(double frequency, double wet, double dry, double modulatedGainDb)
    {
        _frequency = frequency;
        _wet = Math.Clamp(wet, 0.0, 1.0);
        _dry = Math.Clamp(dry, 0.0, 1.0);
        _modulatedGain = Math.Pow(10.0, modulatedGainDb / 20.0);
    }

    public double Process(double sample)
    {
        _phase += _frequency / RadioConstants.OutputSampleRate;
        _phase -= Math.Floor(_phase);
        var triangle = 4.0 * Math.Abs(_phase - 0.5) - 1.0;
        var modulated = sample * triangle * _modulatedGain;
        return (sample * _dry) + (modulated * _wet);
    }

    public void Reset()
    {
        _phase = 0.0;
    }
}

internal sealed class TacComHaProfileEffect : IEffectProcessor
{
    private readonly IEffectProcessor _primary;
    private readonly IEffectProcessor _parallel;
    private readonly double _primaryMix;
    private readonly double _parallelMix;

    public TacComHaProfileEffect(double intensity = 1.0)
    {
        intensity = Math.Clamp(intensity, 0.0, 1.0);
        _primaryMix = 0.7 * intensity;
        _parallelMix = 0.3 * intensity;
        _primary = new ChainEffect(
            new FiltersEffect(
                FirstOrderFilter.HighPass(800.0),
                FirstOrderFilter.LowPass(3500.0)
            ),
            new TacComDmoDistortionEffect(-15.0, -60.0, 55.0, 5500.0, 3500.0, 8000.0),
            new CompressorEffect(30.0, 300.0, -20.0, 100.0, 10.0),
            new CompressorEffect(50.0, 300.0, -40.0, 30.0, 45.0),
            new HalfWaveRectifyDistortionEffect(0.5, 0.5, 28.0, 8.0),
            new CompressorEffect(30.0, 300.0, -10.0, 4.0, 5.0),
            new TriangleRingModulatorEffect(550.0, 0.04 * intensity, 1.0 - (0.04 * intensity), 45.0),
            new GainEffect(-7.0)
        );
        _parallel = new ChainEffect(
            new FiltersEffect(
                FirstOrderFilter.HighPass(100.0),
                FirstOrderFilter.LowPass(1500.0)
            ),
            new CompressorEffect(10.0, 300.0, -30.0, 40.0, 20.0),
            new TacComDmoDistortionEffect(-60.0, -45.0, 75.0, 1500.0, 4800.0, 8000.0),
            new GainEffect(-5.0)
        );
    }

    public double Process(double sample)
    {
        var primary = _primary.Process(sample);
        var parallel = _parallel.Process(sample);
        var dryMix = Math.Max(0.0, 1.0 - _primaryMix - _parallelMix);
        return (primary * _primaryMix) + (parallel * _parallelMix) + (sample * dryMix);
    }

    public void Reset()
    {
        _primary.Reset();
        _parallel.Reset();
    }
}

internal sealed class MaydayReferenceCommsProfileEffect : IEffectProcessor
{
    private readonly IEffectProcessor _voiceChain;
    private readonly IEffectProcessor _bodyChain;
    private readonly AttackReleaseEnvelope _noiseEnvelope = new(6.0, 140.0, RadioConstants.OutputSampleRate);
    private readonly double _intensity;
    private uint _noiseState = 0x53435132;
    private double _noiseLowpass;
    private double _presence;

    public MaydayReferenceCommsProfileEffect(double intensity = 1.0)
    {
        _intensity = Math.Clamp(intensity, 0.0, 1.0);
        _voiceChain = new ChainEffect(
            new FiltersEffect(
                FirstOrderFilter.HighPass(85.0),
                BiQuadFilter.PeakingEq(120.0, 0.64, 2.2),
                BiQuadFilter.PeakingEq(430.0, 0.82, 2.8),
                BiQuadFilter.PeakingEq(850.0, 0.76, 4.8),
                BiQuadFilter.PeakingEq(1650.0, 0.88, 4.2),
                BiQuadFilter.PeakingEq(2850.0, 0.82, 5.2),
                BiQuadFilter.LowPass(5200.0, 0.58)
            ),
            new CompressorEffect(6.0, 120.0, -31.0, 4.8, 7.5),
            new TacComDmoDistortionEffect(-14.0, -28.0, 42.0, 2500.0, 4200.0, 7200.0),
            new HalfWaveRectifyDistortionEffect(0.14, 0.86, 13.0, -7.0),
            new CompressorEffect(4.0, 160.0, -16.0, 2.2, 1.0),
            new GainEffect(12.5)
        );
        _bodyChain = new ChainEffect(
            new FiltersEffect(
                FirstOrderFilter.HighPass(35.0),
                FirstOrderFilter.LowPass(1200.0),
                BiQuadFilter.PeakingEq(75.0, 0.65, 2.0),
                BiQuadFilter.PeakingEq(260.0, 0.72, 1.6),
                BiQuadFilter.PeakingEq(720.0, 0.82, 3.0)
            ),
            new CompressorEffect(16.0, 210.0, -34.0, 7.0, 7.0),
            new GainEffect(4.0)
        );
    }

    public double Process(double sample)
    {
        _presence = _noiseEnvelope.Run(Math.Abs(sample), _presence);
        var voice = _voiceChain.Process(sample);
        var body = _bodyChain.Process(sample);
        var noise = NextColoredNoise() * (0.0032 + (Math.Min(1.0, _presence * 7.0) * 0.0080)) * _intensity;
        var processed = (voice * (0.82 + (0.10 * _intensity))) + (body * 0.18 * _intensity) + noise;
        return (processed * _intensity) + (sample * (1.0 - _intensity));
    }

    public void Reset()
    {
        _voiceChain.Reset();
        _bodyChain.Reset();
        _presence = 0.0;
        _noiseState = 0x53435132;
        _noiseLowpass = 0.0;
    }

    private double NextColoredNoise()
    {
        _noiseState = (uint)((1664525u * _noiseState) + 1013904223u);
        var white = ((_noiseState / 4294967295.0) * 2.0) - 1.0;
        _noiseLowpass = (_noiseLowpass * 0.92) + (white * 0.08);
        return (_noiseLowpass * 0.35) + (white * 0.65);
    }
}

internal sealed class HomeworldFleetCommsEffect : IEffectProcessor
{
    public const string PresetName = "HOMEWORLD_FLEET_COMMS";

    private readonly ChainEffect _voiceChain;
    private readonly ShortRoomReverbEffect _space;
    private uint _grainState = 0x48465743;
    private double _grainLowpass;

    public HomeworldFleetCommsEffect()
    {
        _voiceChain = new ChainEffect(
            new FiltersEffect(
                BiQuadFilter.HighPass(190.0, 0.72),
                BiQuadFilter.PeakingEq(420.0, 0.85, -3.0),
                BiQuadFilter.PeakingEq(1150.0, 0.90, 4.2),
                BiQuadFilter.PeakingEq(2900.0, 0.95, 2.1),
                BiQuadFilter.LowPass(4850.0, 0.62),
                FirstOrderFilter.LowPass(5200.0)
            ),
            new CompressorEffect(8.0, 110.0, -27.0, 3.5, 3.0),
            new GentleSoftClipEffect(1.08),
            new RadioNoiseEffect(-54.0, -60.0, 0.006, 0.140, 0.94)
        );
        _space = new ShortRoomReverbEffect(
            preDelayMilliseconds: 16.0,
            decaySeconds: 0.52,
            mix: 0.075
        );
    }

    public double Process(double sample)
    {
        var focused = _voiceChain.Process(sample);
        var grain = NextGrain() * 0.0011;
        var withGrain = focused + grain;
        var spaced = _space.Process(withGrain);
        return Math.Clamp(spaced, -0.98, 0.98);
    }

    public void Reset()
    {
        _voiceChain.Reset();
        _space.Reset();
        _grainState = 0x48465743;
        _grainLowpass = 0.0;
    }

    private double NextGrain()
    {
        _grainState = (uint)((1664525u * _grainState) + 1013904223u);
        var white = ((_grainState / 4294967295.0) * 2.0) - 1.0;
        _grainLowpass = (_grainLowpass * 0.86) + (white * 0.14);
        return (white * 0.55) + (_grainLowpass * 0.45);
    }
}

internal sealed class GentleSoftClipEffect : IEffectProcessor
{
    private readonly double _drive;
    private readonly double _normalizer;

    public GentleSoftClipEffect(double drive)
    {
        _drive = Math.Clamp(drive, 1.0, 1.5);
        _normalizer = Math.Tanh(_drive);
    }

    public double Process(double sample)
    {
        if (_drive <= 1.001)
        {
            return sample;
        }

        return Math.Tanh(sample * _drive) / _normalizer;
    }

    public void Reset()
    {
    }
}

internal sealed class ShortRoomReverbEffect : IEffectProcessor
{
    private readonly double[] _preDelay;
    private readonly double[] _roomA;
    private readonly double[] _roomB;
    private readonly double[] _roomC;
    private readonly double[] _allpassA;
    private readonly double[] _allpassB;
    private readonly double _feedbackA;
    private readonly double _feedbackB;
    private readonly double _feedbackC;
    private readonly double _mix;
    private int _preIndex;
    private int _roomAIndex;
    private int _roomBIndex;
    private int _roomCIndex;
    private int _allpassAIndex;
    private int _allpassBIndex;

    public ShortRoomReverbEffect(double preDelayMilliseconds, double decaySeconds, double mix)
    {
        _preDelay = new double[MillisecondsToSamples(Math.Clamp(preDelayMilliseconds, 1.0, 60.0))];
        _roomA = new double[MillisecondsToSamples(43.0)];
        _roomB = new double[MillisecondsToSamples(61.0)];
        _roomC = new double[MillisecondsToSamples(79.0)];
        _allpassA = new double[MillisecondsToSamples(7.0)];
        _allpassB = new double[MillisecondsToSamples(11.0)];
        var decay = Math.Clamp(decaySeconds, 0.10, 1.20);
        _feedbackA = FeedbackForDelay(_roomA.Length, decay);
        _feedbackB = FeedbackForDelay(_roomB.Length, decay);
        _feedbackC = FeedbackForDelay(_roomC.Length, decay);
        _mix = Math.Clamp(mix, 0.0, 0.18);
    }

    public double Process(double sample)
    {
        var delayedInput = PushDelay(_preDelay, ref _preIndex, sample);
        var early =
            Tap(_preDelay, _preIndex, MillisecondsToSamples(3.0)) * 0.22
            + Tap(_preDelay, _preIndex, MillisecondsToSamples(8.0)) * 0.18
            + Tap(_preDelay, _preIndex, MillisecondsToSamples(13.0)) * 0.13;
        var wet =
            Comb(_roomA, ref _roomAIndex, delayedInput + early, _feedbackA) * 0.34
            + Comb(_roomB, ref _roomBIndex, delayedInput, _feedbackB) * 0.31
            + Comb(_roomC, ref _roomCIndex, delayedInput, _feedbackC) * 0.26
            + early;
        wet = Allpass(_allpassA, ref _allpassAIndex, wet, 0.52);
        wet = Allpass(_allpassB, ref _allpassBIndex, wet, 0.46);
        wet = Math.Clamp(wet, -1.0, 1.0);
        return (sample * (1.0 - _mix)) + (wet * _mix);
    }

    public void Reset()
    {
        Array.Clear(_preDelay);
        Array.Clear(_roomA);
        Array.Clear(_roomB);
        Array.Clear(_roomC);
        Array.Clear(_allpassA);
        Array.Clear(_allpassB);
        _preIndex = 0;
        _roomAIndex = 0;
        _roomBIndex = 0;
        _roomCIndex = 0;
        _allpassAIndex = 0;
        _allpassBIndex = 0;
    }

    private static int MillisecondsToSamples(double milliseconds)
    {
        return Math.Max(1, (int)Math.Round(RadioConstants.OutputSampleRate * milliseconds / 1000.0));
    }

    private static double FeedbackForDelay(int delaySamples, double decaySeconds)
    {
        var delaySeconds = delaySamples / RadioConstants.OutputSampleRate;
        return Math.Clamp(Math.Pow(0.001, delaySeconds / decaySeconds), 0.18, 0.88);
    }

    private static double PushDelay(double[] buffer, ref int index, double input)
    {
        var output = buffer[index];
        buffer[index] = input;
        index = (index + 1) % buffer.Length;
        return output;
    }

    private static double Tap(double[] buffer, int writeIndex, int delaySamples)
    {
        var readIndex = writeIndex - Math.Clamp(delaySamples, 1, buffer.Length - 1);
        while (readIndex < 0)
        {
            readIndex += buffer.Length;
        }
        return buffer[readIndex % buffer.Length];
    }

    private static double Comb(double[] buffer, ref int index, double input, double feedback)
    {
        var delayed = buffer[index];
        buffer[index] = Math.Clamp(input + (delayed * feedback), -1.0, 1.0);
        index = (index + 1) % buffer.Length;
        return delayed;
    }

    private static double Allpass(double[] buffer, ref int index, double input, double feedback)
    {
        var delayed = buffer[index];
        var output = -input + delayed;
        buffer[index] = input + (delayed * feedback);
        index = (index + 1) % buffer.Length;
        return output;
    }
}

internal class MonoEffectProcessor
{
    private readonly IEffectProcessor _effect;
    private readonly IEffectProcessor? _backingEffect;
    private readonly double _wetMix;
    private readonly double _dryMix;
    private readonly double _backingMix;
    private readonly double _outputGain;

    public MonoEffectProcessor(
        IEffectProcessor effect,
        double wetMix = 1.0,
        IEffectProcessor? backingEffect = null,
        double backingMix = 0.0,
        double outputGain = 1.0
    )
    {
        _effect = effect;
        _backingEffect = backingEffect;
        _wetMix = Math.Clamp(wetMix, 0.0, 1.0);
        _dryMix = 1.0 - _wetMix;
        _backingMix = Math.Clamp(backingMix, 0.0, 1.0);
        _outputGain = Math.Max(0.0, outputGain);
    }

    public void Reset()
    {
        _effect.Reset();
        _backingEffect?.Reset();
    }

    public float[] ProcessFloatSamples(float[] samples, float gain = 1.0f)
    {
        if (samples.Length == 0)
        {
            return samples;
        }

        if (_effect is IBlockEffectProcessor blockEffect)
        {
            var processedBlock = blockEffect.ProcessBlock(samples);
            var blockOutput = new float[samples.Length];
            for (int index = 0; index < samples.Length; index++)
            {
                var sample = samples[index];
                var processed = index < processedBlock.Length ? processedBlock[index] : 0.0f;
                var mixed = (processed * _wetMix) + (sample * _dryMix);
                blockOutput[index] = (float)Math.Clamp(mixed * gain * _outputGain, -1.0, 1.0);
            }
            return blockOutput;
        }

        var output = new float[samples.Length];
        for (int index = 0; index < samples.Length; index++)
        {
            var sample = samples[index];
            var processed = _effect.Process(sample);
            var mixed = (processed * _wetMix) + (sample * _dryMix);
            if (_backingEffect is not null && _backingMix > 0.0)
            {
                var backing = _backingEffect.Process(sample);
                mixed = (mixed * (1.0 - _backingMix)) + (backing * _backingMix);
            }
            output[index] = (float)(mixed * gain * _outputGain);
        }
        return output;
    }

    public byte[] ProcessPcm16(byte[] pcmBytes, float gain = 1.0f)
    {
        if (pcmBytes.Length == 0)
        {
            return pcmBytes;
        }

        if (_effect is IBlockEffectProcessor)
        {
            var samples = new float[pcmBytes.Length / 2];
            for (int offset = 0, index = 0; offset < pcmBytes.Length; offset += 2, index++)
            {
                samples[index] = BitConverter.ToInt16(pcmBytes, offset) / 32768f;
            }

            var processedSamples = ProcessFloatSamples(samples, gain);
            var processedBytes = new byte[pcmBytes.Length];
            for (int index = 0, offset = 0; index < processedSamples.Length; index++, offset += 2)
            {
                var mixed = Math.Clamp(processedSamples[index], -1.0f, 1.0f);
                short pcm = mixed >= 0.0f
                    ? (short)(mixed * 32767.0f)
                    : (short)(mixed * 32768.0f);
                var bytes = BitConverter.GetBytes(pcm);
                processedBytes[offset] = bytes[0];
                processedBytes[offset + 1] = bytes[1];
            }
            return processedBytes;
        }

        byte[] output = new byte[pcmBytes.Length];
        for (int offset = 0; offset < pcmBytes.Length; offset += 2)
        {
            short sample = BitConverter.ToInt16(pcmBytes, offset);
            var sampleFloat = sample / 32768.0;
            var processed = _effect.Process(sampleFloat);
            var mixed = (processed * _wetMix) + (sampleFloat * _dryMix);
            if (_backingEffect is not null && _backingMix > 0.0)
            {
                var backing = _backingEffect.Process(sampleFloat);
                mixed = (mixed * (1.0 - _backingMix)) + (backing * _backingMix);
            }
            mixed *= gain * _outputGain;
            mixed = Math.Clamp(mixed, -1.0, 1.0);
            short pcm = mixed >= 0.0
                ? (short)(mixed * 32767.0)
                : (short)(mixed * 32768.0);
            var bytes = BitConverter.GetBytes(pcm);
            output[offset] = bytes[0];
            output[offset + 1] = bytes[1];
        }
        return output;
    }
}

internal sealed class Arc210RxProcessor : MonoEffectProcessor
{
    public Arc210RxProcessor(string role = "Soldier") : base(
        BuildRoleProfile(role),
        wetMix: IsPilotRole(role) ? 0.10 : 0.20,
        outputGain: IsPilotRole(role) ? 1.05 : 1.50
    )
    {
    }

    private static bool IsPilotRole(string role)
    {
        return string.Equals(role.Trim(), "Pilot", StringComparison.OrdinalIgnoreCase);
    }

    private static IEffectProcessor BuildRoleProfile(string role)
    {
        if (IsPilotRole(role))
        {
            return new TacComOriginalProfileEffect(new HAChain(), inputGainDb: -10.0f, outputGainDb: -3.0f, inputGateThresholdDb: -50.0f);
        }
        return new HomeworldFleetCommsEffect();
    }

    public static IEffectProcessor HaHardenedWaveform(string role)
    {
        return new TacComOriginalProfileEffect(new HAChain(), inputGainDb: -10.0f, outputGainDb: -3.0f, inputGateThresholdDb: -50.0f);
    }
}
