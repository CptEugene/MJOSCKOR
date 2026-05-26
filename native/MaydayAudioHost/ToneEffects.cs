using NAudio.Wave;

namespace MaydayAudioHost;

internal static class ToneEffects
{
    private static readonly Dictionary<string, byte[]> Cache = [];

    public static IEnumerable<byte[]> CommsStartFrames()
    {
        return BuildFrames(LoadMonoPcm("comms"), gain: 0.80f);
    }

    public static IEnumerable<byte[]> TxStartFrames(string channelTag)
    {
        if (!IsGeneralChannel(channelTag))
        {
            return Array.Empty<byte[]>();
        }
        return BuildFrames(LoadMonoPcm(ChannelPrefix(channelTag), "start"));
    }

    public static IEnumerable<byte[]> TxEndFrames(string channelTag)
    {
        if (!IsGeneralChannel(channelTag))
        {
            return Array.Empty<byte[]>();
        }
        return BuildFrames(LoadMonoPcm(ChannelPrefix(channelTag), "end"));
    }

    public static IEnumerable<byte[]> RxStartFrames(string channelTag)
    {
        if (!IsGeneralChannel(channelTag))
        {
            return Array.Empty<byte[]>();
        }
        return BuildFrames(LoadMonoPcm(ChannelPrefix(channelTag), "start"));
    }

    public static IEnumerable<byte[]> RxEndFrames(string channelTag)
    {
        if (!IsGeneralChannel(channelTag))
        {
            return Array.Empty<byte[]>();
        }
        return BuildFrames(LoadMonoPcm(ChannelPrefix(channelTag), "end"));
    }

    private static IEnumerable<byte[]> BuildFrames(byte[] monoPcm16, float gain = 0.10f)
    {
        if (monoPcm16.Length == 0)
        {
            yield break;
        }

        int inputSamples = monoPcm16.Length / 2;
        int frameBytes = AudioEngineHostConstants.PlaybackFrameSize * 2;
        for (int offset = 0; offset < monoPcm16.Length; offset += frameBytes)
        {
            var output = new float[AudioEngineHostConstants.PlaybackFrameSize * AudioEngineHostConstants.PlaybackChannels];
            int monoSamples = Math.Min(AudioEngineHostConstants.PlaybackFrameSize, (monoPcm16.Length - offset) / 2);
            for (int index = 0; index < monoSamples; index++)
            {
                short sample = BitConverter.ToInt16(monoPcm16, offset + (index * 2));
                float value = (sample / 32768f) * gain;
                int stereoIndex = index * 2;
                output[stereoIndex] = value;
                output[stereoIndex + 1] = value;
            }

            byte[] bytes = new byte[output.Length * sizeof(float)];
            Buffer.BlockCopy(output, 0, bytes, 0, bytes.Length);
            yield return bytes;
        }
    }

    private static byte[] LoadMonoPcm(string key)
    {
        if (Cache.TryGetValue(key, out var cached))
        {
            return cached;
        }

        string? path = ResolveSoundPath($"{key}.wav");
        if (path is null || !File.Exists(path))
        {
            return Cache[key] = [];
        }

        using var reader = new WaveFileReader(path);
        if (reader.WaveFormat.BitsPerSample != 16)
        {
            return Cache[key] = [];
        }

        byte[] pcm = new byte[reader.Length];
        int read = reader.Read(pcm, 0, pcm.Length);
        if (read < pcm.Length)
        {
            Array.Resize(ref pcm, read);
        }

        int channels = Math.Max(1, reader.WaveFormat.Channels);
        if (channels == 1)
        {
            return Cache[key] = ResampleMonoPcm16(pcm, reader.WaveFormat.SampleRate);
        }

        int frameCount = pcm.Length / (2 * channels);
        byte[] mono = new byte[frameCount * 2];
        for (int frameIndex = 0; frameIndex < frameCount; frameIndex++)
        {
            int sum = 0;
            for (int channel = 0; channel < channels; channel++)
            {
                int offset = (frameIndex * channels * 2) + (channel * 2);
                sum += BitConverter.ToInt16(pcm, offset);
            }
            short averaged = (short)(sum / channels);
            var bytes = BitConverter.GetBytes(averaged);
            mono[frameIndex * 2] = bytes[0];
            mono[(frameIndex * 2) + 1] = bytes[1];
        }

        return Cache[key] = ResampleMonoPcm16(mono, reader.WaveFormat.SampleRate);
    }

    private static byte[] LoadMonoPcm(string prefix, string suffix)
    {
        return LoadMonoPcm($"{prefix}_{suffix}");
    }

    private static byte[] ResampleMonoPcm16(byte[] pcm, int sourceSampleRate)
    {
        if (sourceSampleRate == AudioEngineHostConstants.PlaybackSampleRate || pcm.Length == 0)
        {
            return pcm;
        }

        int sourceSamples = pcm.Length / 2;
        int targetSamples = Math.Max(1, (int)Math.Round(sourceSamples * AudioEngineHostConstants.PlaybackSampleRate / (double)sourceSampleRate));
        byte[] output = new byte[targetSamples * 2];
        for (int index = 0; index < targetSamples; index++)
        {
            double sourcePosition = index * (sourceSamples - 1.0) / Math.Max(1, targetSamples - 1);
            int leftIndex = (int)Math.Floor(sourcePosition);
            int rightIndex = Math.Min(sourceSamples - 1, leftIndex + 1);
            double fraction = sourcePosition - leftIndex;
            short left = BitConverter.ToInt16(pcm, leftIndex * 2);
            short right = BitConverter.ToInt16(pcm, rightIndex * 2);
            short sample = (short)Math.Clamp(Math.Round(left + ((right - left) * fraction)), short.MinValue, short.MaxValue);
            var bytes = BitConverter.GetBytes(sample);
            output[index * 2] = bytes[0];
            output[(index * 2) + 1] = bytes[1];
        }
        return output;
    }

    private static string ChannelPrefix(string channelTag)
    {
        return channelTag.Trim().ToLowerInvariant() switch
        {
            "squad" => "CH1",
            "hq" => "CH2",
            "atc" => "CH23",
            _ => "CH4",
        };
    }

    private static bool IsGeneralChannel(string channelTag)
    {
        return string.Equals(channelTag.Trim(), "general", StringComparison.OrdinalIgnoreCase);
    }

    private static string? ResolveSoundPath(string fileName)
    {
        string baseDirectory = AppContext.BaseDirectory;
        string[] candidates =
        [
            Path.Combine(baseDirectory, "..", "sound", fileName),
            Path.Combine(baseDirectory, "..", "..", "assets", "sound", fileName),
            Path.Combine(baseDirectory, "..", "..", "..", "..", "..", "assets", "sound", fileName),
        ];

        foreach (var candidate in candidates)
        {
            string fullPath = Path.GetFullPath(candidate);
            if (File.Exists(fullPath))
            {
                return fullPath;
            }
        }

        return null;
    }
}
