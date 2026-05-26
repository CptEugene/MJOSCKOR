using CSCore;
using NAudio.Wave;
using NAudio.Wave.SampleProviders;
using NWaves.Effects;
using NWaves.Operations;
using TAC_COM.Audio.DSP.EffectReferenceWrappers;
using TAC_COM.Audio.EffectsChains;
using TAC_COM.Models;

if (args.Length < 1)
{
    Console.Error.WriteLine("Usage: TacComPreview <input.wav> [output-dir]");
    return 1;
}

var inputPath = Path.GetFullPath(args[0]);
var outputDir = args.Length >= 2 ? Path.GetFullPath(args[1]) : Path.GetDirectoryName(inputPath)!;
Directory.CreateDirectory(outputDir);

var samples = ReadMono48k(inputPath);
var roles = new (string Name, float Wet)[]
{
    ("Commander", 1.00f),
    ("Officer", 1.00f),
    ("Soldier", 1.00f),
};

foreach (var role in roles)
{
    var processor = new MaydayTunedTacComPreviewEffect(role.Wet);
    var output = new float[samples.Length];
    for (var offset = 0; offset < samples.Length; offset += PreviewConstants.FrameSize)
    {
        var count = Math.Min(PreviewConstants.FrameSize, samples.Length - offset);
        var block = new float[count];
        Array.Copy(samples, offset, block, 0, count);
        var processed = processor.ProcessBlock(block);
        Array.Copy(processed, 0, output, offset, count);
    }

    var outputPath = Path.Combine(outputDir, $"mayday_{role.Name}_TACCOM_TUNED_preview.wav");
    WritePcm16(outputPath, output);
    Console.WriteLine(outputPath);
}

return 0;

static float[] ReadMono48k(string inputPath)
{
    using var reader = new AudioFileReader(inputPath);
    ISampleProvider provider = reader;
    if (reader.WaveFormat.Channels > 1)
    {
        provider = new StereoToMonoSampleProvider(provider)
        {
            LeftVolume = 0.5f,
            RightVolume = 0.5f,
        };
    }

    if (provider.WaveFormat.SampleRate != PreviewConstants.SampleRate)
    {
        provider = new WdlResamplingSampleProvider(provider, PreviewConstants.SampleRate);
    }

    var output = new List<float>();
    var buffer = new float[PreviewConstants.SampleRate];
    int read;
    while ((read = provider.Read(buffer, 0, buffer.Length)) > 0)
    {
        for (var index = 0; index < read; index++)
        {
            output.Add(Math.Clamp(buffer[index], -1.0f, 1.0f));
        }
    }

    return output.ToArray();
}

static void WritePcm16(string outputPath, float[] samples)
{
    using var writer = new WaveFileWriter(outputPath, new NAudio.Wave.WaveFormat(PreviewConstants.SampleRate, 16, 1));
    var bytes = new byte[samples.Length * 2];
    for (var index = 0; index < samples.Length; index++)
    {
        var sample = Math.Clamp(samples[index], -1.0f, 1.0f);
        short pcm = sample >= 0.0f
            ? (short)(sample * 32767.0f)
            : (short)(sample * 32768.0f);
        var offset = index * 2;
        bytes[offset] = (byte)(pcm & 0xff);
        bytes[offset + 1] = (byte)((pcm >> 8) & 0xff);
    }
    writer.Write(bytes, 0, bytes.Length);
}

internal interface IEffectProcessor
{
    double Process(double sample);
    void Reset();
}

internal static class PreviewConstants
{
    public const int SampleRate = 48000;
    public const int FrameSize = 960;
}

internal interface IPreviewFilter
{
    double Process(double sample);
}

internal sealed class PreviewFirstOrderFilter : IPreviewFilter
{
    private readonly double _b0;
    private readonly double _b1;
    private readonly double _a1;
    private double _xN1;
    private double _yN1;

    private PreviewFirstOrderFilter(double b0, double b1, double a1)
    {
        _b0 = b0;
        _b1 = b1;
        _a1 = a1;
    }

    public static PreviewFirstOrderFilter LowPass(double cutoff)
    {
        var x = Math.Exp(-2.0 * Math.PI * cutoff / PreviewConstants.SampleRate);
        return new PreviewFirstOrderFilter(1.0 - x, 0.0, -x);
    }

    public static PreviewFirstOrderFilter HighPass(double cutoff)
    {
        var x = Math.Exp(-2.0 * Math.PI * cutoff / PreviewConstants.SampleRate);
        return new PreviewFirstOrderFilter((1.0 + x) * 0.5, -((1.0 + x) * 0.5), -x);
    }

    public double Process(double sample)
    {
        _yN1 = (_b0 * sample) + (_b1 * _xN1) - (_a1 * _yN1);
        _xN1 = sample;
        return _yN1;
    }
}

internal sealed class PreviewBiQuadFilter : IPreviewFilter
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

    private PreviewBiQuadFilter(double b0, double b1, double b2, double a1, double a2)
    {
        _b0 = b0;
        _b1 = b1;
        _b2 = b2;
        _a1 = a1;
        _a2 = a2;
    }

    public static PreviewBiQuadFilter PeakingEq(double freq, double q, double gainDb)
    {
        freq = Math.Clamp(freq, 1.0, (PreviewConstants.SampleRate * 0.5) - 1.0);
        q = Math.Max(q, 0.05);
        var amplitude = Math.Pow(10.0, gainDb / 40.0);
        var w0 = 2.0 * Math.PI * freq / PreviewConstants.SampleRate;
        var alpha = Math.Sin(w0) / (2.0 * q);
        var cosW0 = Math.Cos(w0);
        return Build(
            (1.0 + alpha * amplitude, -2.0 * cosW0, 1.0 - alpha * amplitude),
            (1.0 + alpha / amplitude, -2.0 * cosW0, 1.0 - alpha / amplitude)
        );
    }

    private static PreviewBiQuadFilter Build((double B0, double B1, double B2) numerator, (double A0, double A1, double A2) denominator)
    {
        return new PreviewBiQuadFilter(
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
}

internal sealed class MaydayTunedTacComPreviewEffect
{
    private readonly MutableSampleSource _input = new();
    private readonly ISampleSource _tacComChain;
    private readonly IPreviewFilter[] _eq =
    [
        PreviewFirstOrderFilter.HighPass(125.0),
        PreviewBiQuadFilter.PeakingEq(300.0, 0.80, -4.0),
        PreviewBiQuadFilter.PeakingEq(750.0, 0.90, 5.0),
        PreviewBiQuadFilter.PeakingEq(3200.0, 0.80, -1.0),
        PreviewFirstOrderFilter.LowPass(5200.0),
    ];
    private readonly float _effectMix;
    private double _tremoloPhase;

    public MaydayTunedTacComPreviewEffect(float effectMix)
    {
        _effectMix = Math.Clamp(effectMix, 0.0f, 1.0f);
        _tacComChain = ApplyEffects(_input, BuildTacComEffects());
    }

    public float[] ProcessBlock(float[] samples)
    {
        if (samples.Length == 0)
        {
            return samples;
        }

        var prepared = new float[samples.Length];
        for (var index = 0; index < samples.Length; index++)
        {
            var shaped = (double)samples[index];
            foreach (var filter in _eq)
            {
                shaped = filter.Process(shaped);
            }
            shaped = ApplyTremolo(shaped);
            prepared[index] = (float)Math.Clamp(shaped, -1.0, 1.0);
        }

        _input.SetSamples(prepared);
        var processed = ReadExact(_tacComChain, prepared.Length);
        var output = new float[samples.Length];
        for (var index = 0; index < output.Length; index++)
        {
            output[index] = Math.Clamp((processed[index] * _effectMix) + (samples[index] * (1.0f - _effectMix)), -1.0f, 1.0f);
        }
        return output;
    }

    private double ApplyTremolo(double sample)
    {
        const double rate = 5.2;
        const double depth = 0.20;
        const double mix = 0.40;
        var lfo = (Math.Sin(_tremoloPhase * 2.0 * Math.PI) + 1.0) * 0.5;
        var tremoloGain = 1.0 - (depth * lfo);
        _tremoloPhase += rate / PreviewConstants.SampleRate;
        _tremoloPhase -= Math.Floor(_tremoloPhase);
        return (sample * (1.0 - mix)) + (sample * tremoloGain * mix);
    }

    private static EffectReference[] BuildTacComEffects()
    {
        return
        [
            new(typeof(HighpassFilterWrapper))
            {
                Parameters = new Dictionary<string, object>
                {
                    { "Frequency", 125f },
                },
            },
            new(typeof(LowpassFilterWrapper))
            {
                Parameters = new Dictionary<string, object>
                {
                    { "Frequency", 5200f },
                },
            },
            new(typeof(NwavesDistortionWrapper))
            {
                Parameters = new Dictionary<string, object>
                {
                    { "Mode", DistortionMode.SoftClipping },
                    { "Wet", 0.35f },
                    { "Dry", 0.65f },
                    { "InputGainDB", 10 },
                    { "OutputGainDB", -1 },
                },
            },
            new(typeof(FlangerWrapper))
            {
                Parameters = new Dictionary<string, object>
                {
                    { "Wet", 0.35f },
                    { "Dry", 0.65f },
                    { "LfoFrequency", 0.9f },
                    { "Width", 0.0022f },
                    { "Depth", 0.12f },
                    { "Feedback", 0.08f },
                },
            },
        ];
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

internal sealed class TacComOriginalGmsProfileEffect
{
    private readonly MutableSampleSource _primaryInput = new();
    private readonly MutableSampleSource _parallelInput = new();
    private readonly ISampleSource _primaryChain;
    private readonly ISampleSource _parallelChain;
    private readonly float _wetMix;

    public TacComOriginalGmsProfileEffect(float wetMix)
    {
        var chain = new GMSChain();
        _wetMix = Math.Clamp(wetMix, 0.0f, 1.0f);
        _primaryChain = BuildPrimaryChain(_primaryInput, chain);
        _parallelChain = BuildParallelChain(_parallelInput, chain);
    }

    public float[] ProcessBlock(float[] samples)
    {
        if (samples.Length == 0)
        {
            return samples;
        }

        _primaryInput.SetSamples(samples);
        _parallelInput.SetSamples(samples);

        var primary = ReadExact(_primaryChain, samples.Length);
        var parallel = ReadExact(_parallelChain, samples.Length);
        var output = new float[samples.Length];

        for (var index = 0; index < output.Length; index++)
        {
            var tacComWet = Math.Clamp(((primary[index] * 0.8f) + (parallel[index] * 0.2f)) / 2.0f, -1.0f, 1.0f);
            output[index] = Math.Clamp((tacComWet * _wetMix) + (samples[index] * (1.0f - _wetMix)), -1.0f, 1.0f);
        }

        return output;
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
    private readonly CSCore.WaveFormat _waveFormat = new(PreviewConstants.SampleRate, 32, 1, AudioEncoding.IeeeFloat);
    private float[] _samples = [];
    private int _position;

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
    public CSCore.WaveFormat WaveFormat => _waveFormat;
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
