using System.Runtime.InteropServices;

namespace MaydayAudioHost;

internal sealed class NativeSpeexPreprocessor : IDisposable
{
    private const int SpeexSetDenoise = 0;
    private const int SpeexSetAgc = 2;
    private const int SpeexSetAgcIncrement = 26;
    private const int SpeexSetAgcDecrement = 28;
    private const int SpeexSetAgcMaxGain = 30;
    private const int SpeexSetNoiseSuppress = 18;
    private const int SpeexSetAgcTarget = 46;

    private readonly IntPtr _state;
    private readonly int _frameBytes;
    private readonly bool _available;

    public bool Available => _available;

    public NativeSpeexPreprocessor(
        int frameSize,
        int sampleRate,
        bool denoise = true,
        int denoiseAttenuation = -30,
        bool agcEnabled = false,
        int? agcTarget = null,
        int? agcIncrement = null,
        int? agcDecrement = null,
        int? agcMaxGain = null
    )
    {
        _frameBytes = frameSize * 2;
        try
        {
            _state = SpeexNativeMethods.speex_preprocess_state_init(frameSize, sampleRate);
            if (_state == IntPtr.Zero)
            {
                _available = false;
                return;
            }

            SetInt(SpeexSetDenoise, denoise ? 1 : 0);
            SetInt(SpeexSetNoiseSuppress, denoiseAttenuation);
            SetInt(SpeexSetAgc, agcEnabled ? 1 : 0);
            if (agcTarget.HasValue)
            {
                SetInt(SpeexSetAgcTarget, agcTarget.Value);
            }
            if (agcIncrement.HasValue)
            {
                SetInt(SpeexSetAgcIncrement, agcIncrement.Value);
            }
            if (agcDecrement.HasValue)
            {
                SetInt(SpeexSetAgcDecrement, agcDecrement.Value);
            }
            if (agcMaxGain.HasValue)
            {
                SetInt(SpeexSetAgcMaxGain, agcMaxGain.Value);
            }

            _available = true;
        }
        catch
        {
            _available = false;
        }
    }

    public byte[] Process(byte[] pcmBytes)
    {
        if (!_available || pcmBytes.Length == 0 || _state == IntPtr.Zero)
        {
            return pcmBytes;
        }

        if (pcmBytes.Length == _frameBytes)
        {
            return ProcessSingleFrame(pcmBytes);
        }

        byte[] output = new byte[pcmBytes.Length];
        int offset = 0;
        while (offset < pcmBytes.Length)
        {
            int length = Math.Min(_frameBytes, pcmBytes.Length - offset);
            if (length != _frameBytes)
            {
                Buffer.BlockCopy(pcmBytes, offset, output, offset, length);
                break;
            }

            byte[] frame = new byte[_frameBytes];
            Buffer.BlockCopy(pcmBytes, offset, frame, 0, _frameBytes);
            byte[] processed = ProcessSingleFrame(frame);
            Buffer.BlockCopy(processed, 0, output, offset, processed.Length);
            offset += _frameBytes;
        }
        return output;
    }

    public void Dispose()
    {
        if (_state != IntPtr.Zero)
        {
            SpeexNativeMethods.speex_preprocess_state_destroy(_state);
        }
    }

    private byte[] ProcessSingleFrame(byte[] pcmBytes)
    {
        byte[] buffer = new byte[pcmBytes.Length];
        Buffer.BlockCopy(pcmBytes, 0, buffer, 0, pcmBytes.Length);
        SpeexNativeMethods.speex_preprocess_run(_state, buffer);
        return buffer;
    }

    private void SetInt(int command, int value)
    {
        int rawValue = value;
        int result = SpeexNativeMethods.speex_preprocess_ctl(_state, command, ref rawValue);
        if (result != 0)
        {
            throw new InvalidOperationException($"speex ctl {command} failed with code {result}");
        }
    }
}

internal static partial class SpeexNativeMethods
{
    [DllImport("speexdsp.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr speex_preprocess_state_init(int frameSize, int sampleRate);

    [DllImport("speexdsp.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern int speex_preprocess_ctl(IntPtr state, int request, ref int value);

    [DllImport("speexdsp.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern int speex_preprocess_run(IntPtr state, byte[] pcmBytes);

    [DllImport("speexdsp.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern void speex_preprocess_state_destroy(IntPtr state);
}
