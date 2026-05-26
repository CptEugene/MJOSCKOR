using System.Text.Json;
using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace MaydayAudioHost;

internal sealed class PlaybackHost : IDisposable
{
    private readonly PlaybackOptions _options;
    private readonly TaskCompletionSource<int> _exitSignal = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private WasapiOut? _output;
    private BufferedWaveProvider? _buffer;
    private MMDevice? _device;
    private bool _stopping;

    public PlaybackHost(PlaybackOptions options)
    {
        _options = options;
    }

    public async Task<int> RunAsync()
    {
        _device = ResolveOutputDevice(_options.EndpointId);
        _buffer = new BufferedWaveProvider(WaveFormat.CreateIeeeFloatWaveFormat(_options.SampleRate, _options.Channels))
        {
            ReadFully = false,
            DiscardOnBufferOverflow = true,
            BufferDuration = TimeSpan.FromSeconds(2),
        };
        _output = new WasapiOut(_device, AudioClientShareMode.Shared, true, 40);
        _output.Init(_buffer);
        _output.PlaybackStopped += OnPlaybackStopped;
        _output.Play();

        WriteEvent(
            new
            {
                @event = "ready",
                device_id = _device.ID,
                device_name = _device.FriendlyName,
                sample_rate = _options.SampleRate,
                channels = _options.Channels,
            }
        );

        await ReadCommandsAsync().ConfigureAwait(false);
        return await _exitSignal.Task.ConfigureAwait(false);
    }

    public void Dispose()
    {
        if (_output is not null)
        {
            _output.PlaybackStopped -= OnPlaybackStopped;
            _output.Dispose();
            _output = null;
        }

        _device?.Dispose();
        _device = null;
        _buffer = null;
    }

    private async Task ReadCommandsAsync()
    {
        try
        {
            while (true)
            {
                var line = await Console.In.ReadLineAsync().ConfigureAwait(false);
                if (line is null)
                {
                    Stop();
                    return;
                }

                if (!TryParseCommand(line, out var command, out var payload))
                {
                    continue;
                }

                if (string.Equals(command, "stop", StringComparison.OrdinalIgnoreCase))
                {
                    Stop();
                    return;
                }

                if (!string.Equals(command, "play", StringComparison.OrdinalIgnoreCase) || string.IsNullOrWhiteSpace(payload))
                {
                    continue;
                }

                var pcmBytes = Convert.FromBase64String(payload);
                _buffer?.AddSamples(pcmBytes, 0, pcmBytes.Length);
            }
        }
        catch (Exception ex)
        {
            WriteError(ex.Message);
            Stop();
        }
    }

    private static bool TryParseCommand(string line, out string command, out string payload)
    {
        command = string.Empty;
        payload = string.Empty;
        if (string.IsNullOrWhiteSpace(line))
        {
            return false;
        }

        try
        {
            using var document = JsonDocument.Parse(line);
            if (!document.RootElement.TryGetProperty("command", out var commandProperty))
            {
                return false;
            }

            command = commandProperty.GetString() ?? string.Empty;
            if (document.RootElement.TryGetProperty("pcm_base64", out var payloadProperty))
            {
                payload = payloadProperty.GetString() ?? string.Empty;
            }
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private void Stop()
    {
        if (_stopping)
        {
            return;
        }

        _stopping = true;
        if (_output is null)
        {
            _exitSignal.TrySetResult(0);
            return;
        }

        try
        {
            _output.Stop();
            Dispose();
            _exitSignal.TrySetResult(0);
        }
        catch (Exception ex)
        {
            WriteError(ex.Message);
            _exitSignal.TrySetResult(1);
        }
    }

    private void OnPlaybackStopped(object? sender, StoppedEventArgs args)
    {
        if (args.Exception is not null)
        {
            WriteError(args.Exception.Message);
        }

        Dispose();
        _exitSignal.TrySetResult(args.Exception is null ? 0 : 1);
    }

    private static MMDevice ResolveOutputDevice(string endpointId)
    {
        if (string.IsNullOrWhiteSpace(endpointId))
        {
            using var enumerator = new MMDeviceEnumerator();
            return enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
        }

        using var directEnumerator = new MMDeviceEnumerator();
        var devices = directEnumerator.EnumerateAudioEndPoints(DataFlow.Render, DeviceState.Active);
        foreach (var device in devices)
        {
            if (!string.Equals(device.ID, endpointId, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            return device;
        }

        return directEnumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
    }

    private static void WriteEvent(object payload)
    {
        Console.Out.WriteLine(JsonSerializer.Serialize(payload));
        Console.Out.Flush();
    }

    private static void WriteError(string message)
    {
        var normalized = string.IsNullOrWhiteSpace(message) ? "playback_host_error" : message.Trim();
        Console.Error.WriteLine(normalized);
        Console.Error.Flush();
        WriteEvent(new { @event = "error", message = normalized });
    }
}
