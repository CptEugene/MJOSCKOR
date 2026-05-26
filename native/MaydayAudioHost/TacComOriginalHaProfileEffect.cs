using CSCore;
using NWaves.Effects;
using NWaves.Operations;
using TAC_COM.Audio.DSP.EffectReferenceWrappers;
using TAC_COM.Audio.EffectsChains;
using TAC_COM.Models;

namespace MaydayAudioHost;

internal interface IBlockEffectProcessor : IEffectProcessor
{
    float[] ProcessBlock(float[] samples);
}

internal sealed class TacComOriginalProfileEffect : IBlockEffectProcessor
{
    private readonly MutableSampleSource _primaryInput = new((int)RadioConstants.OutputSampleRate);
    private readonly MutableSampleSource _parallelInput = new((int)RadioConstants.OutputSampleRate);
    private readonly ISampleSource _primaryChain;
    private readonly ISampleSource _parallelChain;
    private readonly float _wetMix;
    private readonly float _inputGain;
    private readonly float _outputGain;
    private readonly bool _inputGateEnabled;
    private readonly float _inputGateThreshold;
    private readonly float _inputGateOpenThreshold;
    private float _inputGateEnvelope;

    public TacComOriginalProfileEffect(
        BaseChain chain,
        float wetMix = 1.0f,
        float inputGainDb = 0.0f,
        float outputGainDb = 0.0f,
        float inputGateThresholdDb = -120.0f
    )
    {
        _wetMix = Math.Clamp(wetMix, 0.0f, 1.0f);
        _inputGain = MathF.Pow(10.0f, inputGainDb / 20.0f);
        _outputGain = MathF.Pow(10.0f, outputGainDb / 20.0f);
        _inputGateEnabled = inputGateThresholdDb > -119.0f;
        _inputGateThreshold = MathF.Pow(10.0f, inputGateThresholdDb / 20.0f);
        _inputGateOpenThreshold = MathF.Pow(10.0f, (inputGateThresholdDb + 8.0f) / 20.0f);
        _primaryChain = BuildPrimaryChain(_primaryInput, chain);
        _parallelChain = BuildParallelChain(_parallelInput, chain);
    }

    public double Process(double sample)
    {
        return ProcessBlock([(float)sample])[0];
    }

    public float[] ProcessBlock(float[] samples)
    {
        if (samples.Length == 0)
        {
            return samples;
        }

        var chainInput = new float[samples.Length];
        for (int index = 0; index < samples.Length; index++)
        {
            chainInput[index] = samples[index] * _inputGain * InputGateGain(samples[index]);
        }

        _primaryInput.SetSamples(chainInput);
        _parallelInput.SetSamples(chainInput);

        var primary = ReadExact(_primaryChain, samples.Length);
        var parallel = ReadExact(_parallelChain, samples.Length);
        var output = new float[samples.Length];

        for (int index = 0; index < output.Length; index++)
        {
            // TAC-COM profiles use the Profile defaults: PrimaryMix 0.8, ParallelMix 0.2,
            // then Mixer.DivideResult=true for the two wet paths.
            var tacComWet = Math.Clamp(((primary[index] * 0.8f) + (parallel[index] * 0.2f)) / 2.0f, -1.0f, 1.0f);
            var mixed = (tacComWet * _wetMix) + (samples[index] * (1.0f - _wetMix));
            output[index] = Math.Clamp(mixed * _outputGain, -1.0f, 1.0f);
        }

        return output;
    }

    public void Reset()
    {
        _primaryInput.SetSamples([]);
        _parallelInput.SetSamples([]);
        _inputGateEnvelope = 0.0f;
    }

    private float InputGateGain(float sample)
    {
        if (!_inputGateEnabled)
        {
            return 1.0f;
        }

        var magnitude = MathF.Abs(sample);
        var attack = MathF.Exp(-1.0f / (0.004f * (float)RadioConstants.OutputSampleRate));
        var release = MathF.Exp(-1.0f / (0.090f * (float)RadioConstants.OutputSampleRate));
        var coefficient = magnitude > _inputGateEnvelope ? attack : release;
        _inputGateEnvelope = magnitude + (coefficient * (_inputGateEnvelope - magnitude));

        if (_inputGateEnvelope <= _inputGateThreshold)
        {
            return 0.0f;
        }
        if (_inputGateEnvelope >= _inputGateOpenThreshold)
        {
            return 1.0f;
        }

        return (_inputGateEnvelope - _inputGateThreshold) / Math.Max(1.0e-9f, _inputGateOpenThreshold - _inputGateThreshold);
    }

    private static ISampleSource BuildPrimaryChain(ISampleSource source, BaseChain chain)
    {
        var current = ApplyEffects(source, chain.GetPreCompressionEffects());
        current = new DynamicsProcessorWrapper(current)
        {
            Mode = DynamicsMode.Limiter,
            MinAmplitude = -120,
            Threshold = -20,
            Ratio = 100,
            Attack = 30,
            Release = 300,
            MakeupGain = 10,
        };
        current = new DynamicsProcessorWrapper(current)
        {
            Mode = DynamicsMode.Compressor,
            MinAmplitude = -120,
            Threshold = -40,
            Ratio = 30,
            Attack = 50,
            Release = 300,
            MakeupGain = 45,
        };
        return ApplyEffects(current, chain.GetPostCompressionEffects());
    }

    private static ISampleSource BuildParallelChain(ISampleSource source, BaseChain chain)
    {
        var current = ApplyEffects(source, chain.GetPreCompressionParallelEffects());
        current = new DynamicsProcessorWrapper(current)
        {
            Mode = DynamicsMode.Compressor,
            MinAmplitude = -70,
            Threshold = -30,
            Ratio = 40,
            Attack = 10,
            Release = 300,
            MakeupGain = 20,
        };
        return ApplyEffects(current, chain.GetPostCompressionParallelEffects());
    }

    private static ISampleSource ApplyEffects(ISampleSource source, IEnumerable<EffectReference> effects)
    {
        var current = source;
        foreach (var effect in effects)
        {
            current = effect.CreateInstance(current);
        }
        return current;
    }

    private static float[] ReadExact(ISampleSource source, int sampleCount)
    {
        var output = new float[sampleCount];
        var offset = 0;
        while (offset < sampleCount)
        {
            var read = source.Read(output, offset, sampleCount - offset);
            if (read <= 0)
            {
                Array.Clear(output, offset, sampleCount - offset);
                break;
            }
            offset += read;
        }
        return output;
    }
}

internal sealed class MutableSampleSource : ISampleSource
{
    private readonly WaveFormat _waveFormat;
    private float[] _samples = [];
    private int _position;

    public MutableSampleSource(int sampleRate)
    {
        _waveFormat = new WaveFormat(sampleRate, 32, 1, AudioEncoding.IeeeFloat);
    }

    public void SetSamples(float[] samples)
    {
        _samples = samples;
        _position = 0;
    }

    public int Read(float[] buffer, int offset, int count)
    {
        var available = Math.Max(0, _samples.Length - _position);
        var samplesToCopy = Math.Min(count, available);
        if (samplesToCopy > 0)
        {
            Array.Copy(_samples, _position, buffer, offset, samplesToCopy);
            _position += samplesToCopy;
        }
        return samplesToCopy;
    }

    public bool CanSeek => false;
    public WaveFormat WaveFormat => _waveFormat;
    public long Position
    {
        get => _position;
        set => _position = Math.Clamp((int)value, 0, _samples.Length);
    }
    public long Length => _samples.Length;

    public void Dispose()
    {
    }
}

internal sealed record MildFanRadioPresetOptions(
    double FanRate = 5.2,
    double FanDepth = 0.27,
    double FanMix = 0.60,
    double LowCut = 135.0,
    double HighCut = 4800.0,
    double MidBoostFrequency = 750.0,
    double MidBoostGain = 7.5,
    double LowMidCutFrequency = 300.0,
    double LowMidCutGain = -6.0,
    double PresenceFrequency = 3200.0,
    double PresenceGain = -1.5,
    double SaturationDrive = 1.18,
    double OutputGainDb = 0.0,
    bool Bypass = false
);

internal sealed class MildFanRadioEffect : IBlockEffectProcessor
{
    public const string PresetName = "MILD_FAN_RADIO";

    private readonly MildFanRadioPresetOptions _options;
    private readonly FiltersEffect _eq;
    private readonly double _outputGain;
    private double _tremoloPhase;

    public MildFanRadioEffect(MildFanRadioPresetOptions? options = null)
    {
        _options = options ?? new MildFanRadioPresetOptions();
        _outputGain = Math.Pow(10.0, _options.OutputGainDb / 20.0);
        _eq = new FiltersEffect(
            FirstOrderFilter.HighPass(_options.LowCut),
            BiQuadFilter.PeakingEq(_options.LowMidCutFrequency, 0.80, _options.LowMidCutGain),
            BiQuadFilter.PeakingEq(_options.MidBoostFrequency, 0.90, _options.MidBoostGain),
            BiQuadFilter.PeakingEq(_options.PresenceFrequency, 0.80, _options.PresenceGain),
            FirstOrderFilter.LowPass(_options.HighCut)
        );
    }

    public double Process(double sample)
    {
        return ProcessBlock([(float)sample])[0];
    }

    public float[] ProcessBlock(float[] samples)
    {
        if (samples.Length == 0 || _options.Bypass)
        {
            return samples;
        }

        var output = new float[samples.Length];
        for (int index = 0; index < samples.Length; index++)
        {
            var sample = samples[index];
            var filtered = ApplyNarrowVoiceEq(sample);
            var moving = ApplyFanTremolo(filtered);
            var saturated = ApplySoftSaturation(moving);
            output[index] = (float)ApplyPeakProtection(saturated * _outputGain);
        }

        return output;
    }

    public void Reset()
    {
        _eq.Reset();
        _tremoloPhase = 0.0;
    }

    private double ApplyNarrowVoiceEq(double sample)
    {
        return _eq.Process(sample);
    }

    private double ApplyFanTremolo(double sample)
    {
        var rate = Math.Clamp(_options.FanRate, 0.1, 20.0);
        var depth = Math.Clamp(_options.FanDepth, 0.0, 0.95);
        var mix = Math.Clamp(_options.FanMix, 0.0, 1.0);
        var lfo = (Math.Sin(_tremoloPhase * 2.0 * Math.PI) + 1.0) * 0.5;
        var tremoloGain = 1.0 - (depth * lfo);
        _tremoloPhase += rate / RadioConstants.OutputSampleRate;
        _tremoloPhase -= Math.Floor(_tremoloPhase);
        return (sample * (1.0 - mix)) + (sample * tremoloGain * mix);
    }

    private double ApplySoftSaturation(double sample)
    {
        var drive = Math.Clamp(_options.SaturationDrive, 1.0, 3.0);
        return Math.Tanh(sample * drive) / Math.Tanh(drive);
    }

    private static double ApplyPeakProtection(double sample)
    {
        return Math.Clamp(sample, -0.98, 0.98);
    }
}
