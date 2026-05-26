using System.Text;

namespace MaydayAudioHost;

internal static class Program
{
    public static async Task<int> Main(string[] args)
    {
        Console.InputEncoding = Encoding.UTF8;
        Console.OutputEncoding = Encoding.UTF8;

        try
        {
            var mode = StartupOptions.ReadMode(args);
            if (string.Equals(mode, "capture", StringComparison.OrdinalIgnoreCase))
            {
                var options = CaptureOptions.Parse(args);
                using var host = new CaptureHost(options);
                return await host.RunAsync().ConfigureAwait(false);
            }
            if (string.Equals(mode, "playback", StringComparison.OrdinalIgnoreCase))
            {
                var options = PlaybackOptions.Parse(args);
                using var host = new PlaybackHost(options);
                return await host.RunAsync().ConfigureAwait(false);
            }
            if (string.Equals(mode, "engine", StringComparison.OrdinalIgnoreCase))
            {
                var options = EngineStartupOptions.Parse(args);
                using var host = new AudioEngineHost(options);
                return await host.RunAsync().ConfigureAwait(false);
            }
            Console.Error.WriteLine("unsupported mode");
            return 1;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }
}

internal static class EngineStartupOptions
{
    public static EngineOptions Parse(string[] args)
    {
        var inputEndpointId = "";
        var outputEndpointId = "";
        var voiceHost = "127.0.0.1";
        var voicePort = 41001;
        uint sessionId = 0;
        var channelTag = "general";

        for (var index = 0; index < args.Length; index++)
        {
            var value = args[index];
            if (string.Equals(value, "--input-endpoint-id", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                inputEndpointId = args[++index];
                continue;
            }

            if (string.Equals(value, "--output-endpoint-id", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                outputEndpointId = args[++index];
                continue;
            }

            if (string.Equals(value, "--voice-host", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                voiceHost = args[++index];
                continue;
            }

            if (string.Equals(value, "--voice-port", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                voicePort = int.Parse(args[++index]);
                continue;
            }

            if (string.Equals(value, "--session-id", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                sessionId = uint.Parse(args[++index]);
                continue;
            }

            if (string.Equals(value, "--channel-tag", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                channelTag = args[++index];
            }
        }

        return new EngineOptions(inputEndpointId, outputEndpointId, voiceHost, voicePort, sessionId, channelTag);
    }
}

internal static class StartupOptions
{
    public static string ReadMode(string[] args)
    {
        for (var index = 0; index < args.Length - 1; index++)
        {
            if (!string.Equals(args[index], "--mode", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            return args[index + 1];
        }

        return "capture";
    }
}

internal sealed record CaptureOptions(string Mode, string EndpointId, int SampleRate, int FrameSize)
{
    public static CaptureOptions Parse(string[] args)
    {
        var mode = "capture";
        var endpointId = "";
        var sampleRate = 16_000;
        var frameSize = 640;

        for (var index = 0; index < args.Length; index++)
        {
            var value = args[index];
            if (string.Equals(value, "--mode", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                mode = args[++index];
                continue;
            }

            if (string.Equals(value, "--endpoint-id", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                endpointId = args[++index];
                continue;
            }

            if (string.Equals(value, "--sample-rate", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                sampleRate = int.Parse(args[++index]);
                continue;
            }

            if (string.Equals(value, "--frame-size", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                frameSize = int.Parse(args[++index]);
            }
        }

        return new CaptureOptions(mode, endpointId, sampleRate, frameSize);
    }
}

internal sealed record PlaybackOptions(string Mode, string EndpointId, int SampleRate, int Channels)
{
    public static PlaybackOptions Parse(string[] args)
    {
        var mode = "playback";
        var endpointId = "";
        var sampleRate = 48_000;
        var channels = 2;

        for (var index = 0; index < args.Length; index++)
        {
            var value = args[index];
            if (string.Equals(value, "--mode", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                mode = args[++index];
                continue;
            }

            if (string.Equals(value, "--endpoint-id", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                endpointId = args[++index];
                continue;
            }

            if (string.Equals(value, "--sample-rate", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                sampleRate = int.Parse(args[++index]);
                continue;
            }

            if (string.Equals(value, "--channels", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                channels = int.Parse(args[++index]);
            }
        }

        return new PlaybackOptions(mode, endpointId, sampleRate, channels);
    }
}
