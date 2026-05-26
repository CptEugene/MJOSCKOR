using System.Runtime.InteropServices;

namespace MaydayAudioHost;

internal sealed class NativeOpusEncoder : IDisposable
{
    private const int ApplicationVoip = 2048;
    private const int OpusSetInbandFec = 4012;
    private readonly IntPtr _encoder;

    public bool Available => _encoder != IntPtr.Zero;

    public NativeOpusEncoder(int sampleRate, int channels)
    {
        int error;
        _encoder = NativeMethods.opus_encoder_create(sampleRate, channels, ApplicationVoip, out error);
        if (_encoder != IntPtr.Zero)
        {
            NativeMethods.opus_encoder_ctl(_encoder, OpusSetInbandFec, 0);
        }
    }

    public byte[] Encode(byte[] pcmBytes, int frameSize)
    {
        return TryEncode(pcmBytes, frameSize, out var encoded) ? encoded : pcmBytes;
    }

    public bool TryEncode(byte[] pcmBytes, int frameSize, out byte[] encoded)
    {
        if (_encoder == IntPtr.Zero || pcmBytes.Length == 0)
        {
            encoded = pcmBytes;
            return false;
        }

        byte[] output = new byte[4000];
        int encodedLength = NativeMethods.opus_encode(_encoder, pcmBytes, frameSize, output, output.Length);
        if (encodedLength <= 0)
        {
            encoded = pcmBytes;
            return false;
        }

        Array.Resize(ref output, encodedLength);
        encoded = output;
        return true;
    }

    public void Dispose()
    {
        if (_encoder != IntPtr.Zero)
        {
            NativeMethods.opus_encoder_destroy(_encoder);
        }
    }
}

internal sealed class NativeOpusDecoder : IDisposable
{
    private const int OpusResetState = 4028;
    private readonly IntPtr _decoder;

    public bool Available => _decoder != IntPtr.Zero;

    public NativeOpusDecoder(int sampleRate, int channels)
    {
        int error;
        _decoder = NativeMethods.opus_decoder_create(sampleRate, channels, out error);
    }

    public byte[] Decode(byte[] payload, int frameSize, bool newTransmission)
    {
        if (_decoder == IntPtr.Zero || payload.Length == 0)
        {
            return [];
        }

        if (newTransmission)
        {
            NativeMethods.opus_decoder_ctl(_decoder, OpusResetState);
        }

        byte[] output = new byte[frameSize * 2];
        int decodedSamples = NativeMethods.opus_decode(_decoder, payload, payload.Length, output, frameSize, 0);
        if (decodedSamples <= 0)
        {
            return [];
        }

        Array.Resize(ref output, decodedSamples * 2);
        return output;
    }

    public void Dispose()
    {
        if (_decoder != IntPtr.Zero)
        {
            NativeMethods.opus_decoder_destroy(_decoder);
        }
    }
}

internal static partial class NativeMethods
{
    [DllImport("opus.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr opus_encoder_create(int sampleRate, int channels, int application, out int error);

    [DllImport("opus.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern void opus_encoder_destroy(IntPtr encoder);

    [DllImport("opus.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern int opus_encode(IntPtr encoder, byte[] pcm, int frameSize, byte[] data, int maxDataBytes);

    [DllImport("opus.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern int opus_encoder_ctl(IntPtr encoder, int request, int value);

    [DllImport("opus.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr opus_decoder_create(int sampleRate, int channels, out int error);

    [DllImport("opus.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern void opus_decoder_destroy(IntPtr decoder);

    [DllImport("opus.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern int opus_decode(IntPtr decoder, byte[] data, int len, byte[] pcm, int frameSize, int decodeFec);

    [DllImport("opus.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern int opus_decoder_ctl(IntPtr decoder, int request);
}
