using NAudio.Wave;
using NAudio.Wave.SampleProviders;

namespace MaydayAudioHost;

internal sealed class EventDrivenResampler : IDisposable
{
    private readonly BufferedWaveProvider _buffer;
    private readonly IWaveProvider _waveProvider;
    private readonly int _bufferMultiplier;

    public EventDrivenResampler(WaveFormat input, WaveFormat output)
    {
        _buffer = new BufferedWaveProvider(input)
        {
            ReadFully = false,
        };
        _bufferMultiplier = output.BitsPerSample > input.BitsPerSample ? 2 : 1;
        var resampler = new WdlResamplingSampleProvider(_buffer.ToSampleProvider(), output.SampleRate);
        _waveProvider = resampler.ToMono().ToWaveProvider16();
    }

    public byte[] ResampleBytes(byte[] inputBytes, int length)
    {
        if (length <= 0)
        {
            return Array.Empty<byte>();
        }

        _buffer.AddSamples(inputBytes, 0, length);
        var outputBuffer = new byte[length * _bufferMultiplier];
        var read = _waveProvider.Read(outputBuffer, 0, outputBuffer.Length);
        if (read <= 0)
        {
            return Array.Empty<byte>();
        }

        if (read == outputBuffer.Length)
        {
            return outputBuffer;
        }

        var result = new byte[read];
        Buffer.BlockCopy(outputBuffer, 0, result, 0, read);
        return result;
    }

    public void Dispose()
    {
        _buffer.ClearBuffer();
    }
}
