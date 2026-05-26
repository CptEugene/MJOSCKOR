using System.Text.Json;
using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace MaydayAudioHost;

internal sealed class CaptureHost : IDisposable
{
    private readonly CaptureOptions _options;
    private readonly List<byte> _pendingBytes = [];
    private readonly object _pendingLock = new();
    private readonly TaskCompletionSource<int> _exitSignal = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private WasapiCapture? _capture;
    private MMDevice? _device;
    private EventDrivenResampler? _resampler;
    private bool _stopping;

    public CaptureHost(CaptureOptions options)
    {
        _options = options;
    }

    public async Task<int> RunAsync()
    {
        _device = ResolveCaptureDevice(_options.EndpointId);
        _capture = new WasapiCapture(_device, true, AudioEngineHostConstants.CaptureBufferMilliseconds)
        {
            ShareMode = AudioClientShareMode.Shared,
        };
        _capture.DataAvailable += OnDataAvailable;
        _capture.RecordingStopped += OnRecordingStopped;
        _capture.StartRecording();

        WriteEvent(
            new
            {
                @event = "ready",
                device_id = _device.ID,
                device_name = _device.FriendlyName,
                sample_rate = _options.SampleRate,
                frame_size = _options.FrameSize,
            }
        );

        _ = Task.Run(ReadCommandsAsync);

        return await _exitSignal.Task.ConfigureAwait(false);
    }

    public void Dispose()
    {
        if (_capture is not null)
        {
            _capture.DataAvailable -= OnDataAvailable;
            _capture.RecordingStopped -= OnRecordingStopped;
            _capture.Dispose();
            _capture = null;
        }

        _resampler?.Dispose();
        _resampler = null;
        _device?.Dispose();
        _device = null;
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

                if (!TryParseStopCommand(line))
                {
                    continue;
                }

                Stop();
                return;
            }
        }
        catch (Exception ex)
        {
            WriteError(ex.Message);
            Stop();
        }
    }

    private static bool TryParseStopCommand(string line)
    {
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

            return string.Equals(commandProperty.GetString(), "stop", StringComparison.OrdinalIgnoreCase);
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
        if (_capture is null)
        {
            _exitSignal.TrySetResult(0);
            return;
        }

        try
        {
            _capture.StopRecording();
        }
        catch (Exception ex)
        {
            WriteError(ex.Message);
            _exitSignal.TrySetResult(1);
        }
    }

    private void OnRecordingStopped(object? sender, StoppedEventArgs args)
    {
        if (args.Exception is not null)
        {
            WriteError(args.Exception.Message);
        }

        Dispose();
        _exitSignal.TrySetResult(args.Exception is null ? 0 : 1);
    }

    private void OnDataAvailable(object? sender, WaveInEventArgs args)
    {
        if (_stopping || _capture is null || args.BytesRecorded <= 0)
        {
            return;
        }

        _resampler ??= new EventDrivenResampler(
            _capture.WaveFormat,
            new WaveFormat(_options.SampleRate, 16, 1)
        );
        var resampledBytes = _resampler.ResampleBytes(args.Buffer, args.BytesRecorded);
        if (resampledBytes.Length <= 0)
        {
            return;
        }

        lock (_pendingLock)
        {
            _pendingBytes.AddRange(resampledBytes);
            var frameByteCount = _options.FrameSize * 2;
            while (_pendingBytes.Count >= frameByteCount)
            {
                if (_stopping)
                {
                    _pendingBytes.Clear();
                    return;
                }
                var frame = _pendingBytes.GetRange(0, frameByteCount).ToArray();
                _pendingBytes.RemoveRange(0, frameByteCount);
                EmitFrame(frame);
            }
        }
    }

    private void EmitFrame(byte[] frameBytes)
    {
        if (_stopping)
        {
            return;
        }
        WriteEvent(new { @event = "level", value = CalculateLevel(frameBytes) });
        WriteEvent(new { @event = "frame", pcm_base64 = Convert.ToBase64String(frameBytes) });
    }

    private static double CalculateLevel(byte[] frameBytes)
    {
        if (frameBytes.Length < 2)
        {
            return 0.0;
        }

        double peak = 0.0;
        double sumSquares = 0.0;
        var sampleCount = frameBytes.Length / 2;
        for (var offset = 0; offset < frameBytes.Length; offset += 2)
        {
            short sample = BitConverter.ToInt16(frameBytes, offset);
            var normalized = Math.Abs(sample / 32767.0);
            peak = Math.Max(peak, normalized);
            sumSquares += normalized * normalized;
        }

        var rms = Math.Sqrt(sumSquares / sampleCount);
        return Math.Clamp(Math.Max(rms * 2.8, peak * 0.9), 0.0, 1.0);
    }

    private static MMDevice ResolveCaptureDevice(string endpointId)
    {
        if (string.IsNullOrWhiteSpace(endpointId))
        {
            return WasapiCapture.GetDefaultCaptureDevice();
        }

        using var enumerator = new MMDeviceEnumerator();
        var devices = enumerator.EnumerateAudioEndPoints(DataFlow.Capture, DeviceState.Active);
        foreach (var device in devices)
        {
            if (!string.Equals(device.ID, endpointId, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            return device;
        }

        return WasapiCapture.GetDefaultCaptureDevice();
    }

    private static void WriteEvent(object payload)
    {
        Console.Out.WriteLine(JsonSerializer.Serialize(payload));
        Console.Out.Flush();
    }

    private static void WriteError(string message)
    {
        var normalized = string.IsNullOrWhiteSpace(message) ? "capture_host_error" : message.Trim();
        Console.Error.WriteLine(normalized);
        Console.Error.Flush();
        WriteEvent(new { @event = "error", message = normalized });
    }
}
