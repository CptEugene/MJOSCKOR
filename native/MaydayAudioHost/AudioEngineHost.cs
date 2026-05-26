using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text.Json;
using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace MaydayAudioHost;

internal static class AudioEngineHostConstants
{
    public const int CaptureSampleRate = 48000;
    public const int CaptureFrameSize = 960;
    public const int PlaybackSampleRate = 48000;
    public const int PlaybackFrameSize = 960;
    public const int PlaybackChannels = 2;
    public const int CaptureBufferMilliseconds = 20;
}

internal sealed class MultimediaTimerResolution : IDisposable
{
    private readonly uint _periodMilliseconds;
    private bool _enabled;

    private MultimediaTimerResolution(uint periodMilliseconds)
    {
        _periodMilliseconds = periodMilliseconds;
        _enabled = TimeBeginPeriod(periodMilliseconds) == 0;
    }

    public static MultimediaTimerResolution Begin(uint periodMilliseconds = 1)
    {
        return new MultimediaTimerResolution(periodMilliseconds);
    }

    public void Dispose()
    {
        if (!_enabled)
        {
            return;
        }

        TimeEndPeriod(_periodMilliseconds);
        _enabled = false;
    }

    [DllImport("winmm.dll", EntryPoint = "timeBeginPeriod")]
    private static extern uint TimeBeginPeriod(uint periodMilliseconds);

    [DllImport("winmm.dll", EntryPoint = "timeEndPeriod")]
    private static extern uint TimeEndPeriod(uint periodMilliseconds);
}

internal sealed class AudioEngineHost : IDisposable
{
    private const double KeepaliveIntervalSeconds = 2.0;
    private static bool VoiceEffectsEnabled => true;
    private static bool ToneEffectsEnabled => false;

    private readonly EngineOptions _options;
    private readonly object _stateLock = new();
    private readonly object _captureLock = new();
    private readonly ConcurrentQueue<byte[]> _effectFrames = new();
    private readonly List<byte> _pendingCaptureBytes = [];
    private readonly Dictionary<uint, TalkerState> _talkers = [];
    private readonly OutputLimiter _limiter = new();
    private readonly Queue<byte[]> _txPrerollFrames = new();
    private readonly ConcurrentQueue<byte[]> _txSendQueue = new();
    private readonly SemaphoreSlim _txSendSignal = new(0);
    private readonly TaskCompletionSource<int> _exitSignal = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly Dictionary<string, Arc210RxProcessor> _channelRxProcessors = [];
    private readonly Dictionary<string, double> _channelReceiveActivity = [];
    private readonly Dictionary<uint, uint> _lastRxPacketNumbers = [];

    private WasapiCapture? _capture;
    private MMDevice? _captureDevice;
    private EventDrivenResampler? _captureResampler;
    private WasapiOut? _output;
    private BufferedWaveProvider? _outputBuffer;
    private MMDevice? _outputDevice;
    private UdpClient? _udpClient;
    private IPEndPoint? _voiceEndPoint;
    private Task? _commandTask;
    private Task? _receiveTask;
    private Task? _playoutTask;
    private Task? _keepaliveTask;
    private Task? _txPacerTask;
    private CancellationTokenSource? _cts;
    private NativeOpusEncoder? _encoder;
    private MultimediaTimerResolution? _timerResolution;
    private bool _stopping;
    private uint _sessionId;
    private string _channelTag = "general";
    private string _selectedRole = "Soldier";
    private string _voiceHost = "127.0.0.1";
    private int _voicePort = 41001;
    private uint _packetNumber = 1;
    private bool _pttPressed;
    private bool _transmitting;
    private int _txReleaseFramesRemaining;
    private int _microphoneVolumePercent = 100;
    private int _speakerVolumePercent = 100;
    private int[] _channelReceiveVolumes = [100, 100, 100, 100];
    private string[] _channelPanModes = ["both", "both", "both", "both"];
    private double _nextKeepaliveAt;
    private bool _registrationRequested = true;
    private double _lastCaptureFrameAt;
    private double _captureStartedAt;
    private double _lastCaptureDataAt;
    private double _lastTxSendAt;
    private double _lastPlayoutWaitingLogAt;
    private double _lastRxDatagramLogAt;
    private double _lastRxDecodeErrorLogAt;
    private double _lastRxPlayoutLogAt;
    private double _lastPlaybackRestartLogAt;
    private double _lastTxBlockedLogAt;
    private double _lastPlayoutGapLogAt;
    private long _rxDatagramCount;
    private long _rxPlayoutFrameCount;
    private int _captureRestartCount;
    private bool _txFrameSentSincePtt;
    private double _nextTxSendDueAt;

    public AudioEngineHost(EngineOptions options)
    {
        _options = options;
        _voiceHost = string.IsNullOrWhiteSpace(options.VoiceHost) ? "127.0.0.1" : options.VoiceHost.Trim();
        _voicePort = options.VoicePort > 0 ? options.VoicePort : 41001;
        _sessionId = options.SessionId;
        if (!string.IsNullOrWhiteSpace(options.ChannelTag))
        {
            _channelTag = options.ChannelTag.Trim().ToLowerInvariant();
        }
    }

    public async Task<int> RunAsync()
    {
        _cts = new CancellationTokenSource();
        _timerResolution = MultimediaTimerResolution.Begin();
        _encoder = new NativeOpusEncoder(AudioEngineHostConstants.CaptureSampleRate, 1);
        _udpClient = new UdpClient(AddressFamily.InterNetwork);
        _udpClient.Client.ReceiveBufferSize = 262144;
        _udpClient.Client.SendBufferSize = 262144;
        _udpClient.Client.Bind(new IPEndPoint(IPAddress.Any, 0));
        _voiceEndPoint = new IPEndPoint(IPAddress.Parse(_voiceHost), _voicePort);
        WriteDiagnostic($"UDP client bound local={_udpClient.Client.LocalEndPoint} remote={_voiceEndPoint}");
        _nextKeepaliveAt = 0.0;
        _registrationRequested = true;

        StartPlayback();
        StartCapture();

        _commandTask = Task.Run(ReadCommandsAsync);
        _receiveTask = Task.Run(() => ReceiveLoopAsync(_cts.Token));
        _playoutTask = Task.Run(() => PlayoutLoopAsync(_cts.Token));
        _keepaliveTask = Task.Run(() => KeepaliveLoopAsync(_cts.Token));
        _txPacerTask = Task.Run(() => TxPacerLoopAsync(_cts.Token));

        WriteEvent(
            new
            {
                @event = "ready",
                mode = "engine",
                capture_device_id = _captureDevice?.ID ?? "",
                capture_device_name = _captureDevice?.FriendlyName ?? "default",
                playback_device_id = _outputDevice?.ID ?? "",
                playback_device_name = _outputDevice?.FriendlyName ?? "default",
                sample_rate = AudioEngineHostConstants.CaptureSampleRate,
                frame_size = AudioEngineHostConstants.CaptureFrameSize,
            }
        );

        return await _exitSignal.Task.ConfigureAwait(false);
    }

    public void Dispose()
    {
        _encoder?.Dispose();
        _encoder = null;
        _timerResolution?.Dispose();
        _timerResolution = null;
        foreach (var talker in _talkers.Values)
        {
            talker.Dispose();
        }
        _talkers.Clear();
        _capture?.Dispose();
        _capture = null;
        _captureDevice?.Dispose();
        _captureDevice = null;
        _captureResampler?.Dispose();
        _captureResampler = null;
        _output?.Dispose();
        _output = null;
        _outputDevice?.Dispose();
        _outputDevice = null;
        _udpClient?.Dispose();
        _udpClient = null;
        _cts?.Dispose();
        _cts = null;
    }

    private void StartCapture()
    {
        _captureDevice = ResolveCaptureDevice(_options.InputEndpointId);
        _capture = new WasapiCapture(_captureDevice, true, AudioEngineHostConstants.CaptureBufferMilliseconds)
        {
            ShareMode = AudioClientShareMode.Shared,
        };
        _capture.DataAvailable += OnDataAvailable;
        _capture.RecordingStopped += OnRecordingStopped;
        _capture.StartRecording();
        _captureStartedAt = MonotonicSeconds();
        _lastCaptureDataAt = 0.0;
        WriteDiagnostic($"capture started device={_captureDevice.FriendlyName}");
    }

    private void StartPlayback()
    {
        _outputDevice = ResolveOutputDevice(_options.OutputEndpointId);
        _outputBuffer = new BufferedWaveProvider(
            WaveFormat.CreateIeeeFloatWaveFormat(
                AudioEngineHostConstants.PlaybackSampleRate,
                AudioEngineHostConstants.PlaybackChannels
            )
        )
        {
            ReadFully = true,
            DiscardOnBufferOverflow = true,
            BufferDuration = TimeSpan.FromSeconds(2),
        };
        _output = new WasapiOut(_outputDevice, AudioClientShareMode.Shared, true, 40);
        _output.Init(_outputBuffer);
        _output.PlaybackStopped += OnPlaybackStopped;
        _output.Play();
        WriteDiagnostic($"playback started device={_outputDevice.FriendlyName} state={_output.PlaybackState}");
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

                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                using var document = JsonDocument.Parse(line);
                if (!document.RootElement.TryGetProperty("command", out var commandProperty))
                {
                    continue;
                }

                var command = commandProperty.GetString() ?? string.Empty;
                switch (command.Trim().ToLowerInvariant())
                {
                    case "stop":
                        Stop();
                        return;
                    case "configure":
                        ApplyConfiguration(document.RootElement);
                        break;
                    case "ptt":
                        ApplyPtt(document.RootElement);
                        break;
                }
            }
        }
        catch (Exception ex)
        {
            WriteError(ex.Message);
            Stop();
        }
    }

    private void ApplyConfiguration(JsonElement root)
    {
        lock (_stateLock)
        {
            if (root.TryGetProperty("voice_host", out var hostProperty))
            {
                var candidate = hostProperty.GetString();
                if (!string.IsNullOrWhiteSpace(candidate))
                {
                    _voiceHost = candidate.Trim();
                }
            }

            if (root.TryGetProperty("voice_port", out var portProperty) && portProperty.TryGetInt32(out var voicePort) && voicePort > 0)
            {
                _voicePort = voicePort;
            }

            if (root.TryGetProperty("session_id", out var sessionProperty) && sessionProperty.TryGetUInt32(out var sessionId))
            {
                _sessionId = sessionId;
            }

            if (root.TryGetProperty("channel_tag", out var channelProperty))
            {
                var channelTag = channelProperty.GetString();
                if (!string.IsNullOrWhiteSpace(channelTag))
                {
                    _channelTag = channelTag.Trim().ToLowerInvariant();
                }
            }

            if (root.TryGetProperty("selected_role", out var roleProperty))
            {
                var selectedRole = roleProperty.GetString();
                if (!string.IsNullOrWhiteSpace(selectedRole))
                {
                    _selectedRole = selectedRole.Trim();
                    _channelRxProcessors.Clear();
                }
            }

            if (root.TryGetProperty("microphone_volume_percent", out var micVolumeProperty) && micVolumeProperty.TryGetInt32(out var micVolume))
            {
                _microphoneVolumePercent = Math.Clamp(micVolume, 0, 200);
            }

            if (root.TryGetProperty("speaker_volume_percent", out var speakerVolumeProperty) && speakerVolumeProperty.TryGetInt32(out var speakerVolume))
            {
                _speakerVolumePercent = Math.Clamp(speakerVolume, 0, 200);
            }

            if (root.TryGetProperty("channel_receive_volumes", out var channelVolumesProperty) && channelVolumesProperty.ValueKind == JsonValueKind.Array)
            {
                var updated = new int[4];
                for (int index = 0; index < updated.Length; index++)
                {
                    updated[index] = index < channelVolumesProperty.GetArrayLength() && channelVolumesProperty[index].TryGetInt32(out var value)
                        ? Math.Clamp(value, 0, 200)
                        : 100;
                }
                _channelReceiveVolumes = updated;
            }

            if (root.TryGetProperty("channel_pan_modes", out var panModesProperty) && panModesProperty.ValueKind == JsonValueKind.Array)
            {
                var updated = new string[4];
                for (int index = 0; index < updated.Length; index++)
                {
                    updated[index] = index < panModesProperty.GetArrayLength()
                        ? (panModesProperty[index].GetString() ?? "both").Trim().ToLowerInvariant()
                        : "both";
                }
                _channelPanModes = updated;
            }

            _voiceEndPoint = BuildVoiceEndpoint();
            _nextKeepaliveAt = 0.0;
            _registrationRequested = true;
        }
    }

    private void ApplyPtt(JsonElement root)
    {
        bool pressed = root.TryGetProperty("pressed", out var pressedProperty) && pressedProperty.GetBoolean();
        string? channelTag = root.TryGetProperty("channel_tag", out var channelProperty)
            ? channelProperty.GetString()
            : null;

        lock (_stateLock)
        {
            if (!string.IsNullOrWhiteSpace(channelTag))
            {
                _channelTag = channelTag.Trim().ToLowerInvariant();
            }

            if (pressed)
            {
                var wasTransmitting = _transmitting;
                _pttPressed = true;
                _txReleaseFramesRemaining = 0;
                if (!_transmitting)
                {
                    _transmitting = true;
                }
                if (!wasTransmitting)
                {
                    _txFrameSentSincePtt = false;
                    ClearTxSendQueue();
                    _nextTxSendDueAt = 0.0;
                    _registrationRequested = true;
                    _nextKeepaliveAt = 0.0;
                    EnqueueEffectFrames(ToneEffects.TxStartFrames(_channelTag));
                    WriteDiagnostic($"PTT pressed session={_sessionId} channel={_channelTag} endpoint={_voiceEndPoint}");
                }
            }
            else
            {
                _pttPressed = false;
                if (_transmitting)
                {
                    _txReleaseFramesRemaining = 5;
                }
            }
        }
    }

    private async Task KeepaliveLoopAsync(CancellationToken cancellationToken)
    {
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                await Task.Delay(500, cancellationToken).ConfigureAwait(false);
                if (_udpClient is null)
                {
                    continue;
                }

                uint sessionId;
                IPEndPoint? voiceEndpoint;
                lock (_stateLock)
                {
                    sessionId = _sessionId;
                    voiceEndpoint = _voiceEndPoint;
                }

                if (sessionId == 0 || voiceEndpoint is null)
                {
                    continue;
                }

                MonitorCaptureHealth();

                double now = MonotonicSeconds();
                bool registrationRequested;
                lock (_stateLock)
                {
                    registrationRequested = _registrationRequested;
                }

                if (!registrationRequested && now < _nextKeepaliveAt)
                {
                    continue;
                }

                var keepalive = VoicePacketCodec.Pack(sessionId, _channelTag, [], VoiceCodec.Pcm16, 0, CaptureTimestampMs());
                await _udpClient.SendAsync(keepalive, keepalive.Length, voiceEndpoint).ConfigureAwait(false);
                lock (_stateLock)
                {
                    _registrationRequested = false;
                    _nextKeepaliveAt = now + KeepaliveIntervalSeconds;
                }
            }
        }
        catch (OperationCanceledException)
        {
            return;
        }
        catch (Exception ex)
        {
            WriteError(ex.Message);
        }
    }

    private async Task ReceiveLoopAsync(CancellationToken cancellationToken)
    {
        if (_udpClient is null)
        {
            return;
        }

        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var result = await _udpClient.ReceiveAsync(cancellationToken).ConfigureAwait(false);
                if (!VoicePacketCodec.TryUnpack(result.Buffer, out var packet))
                {
                    continue;
                }

                if (packet.Payload.Length == 0)
                {
                    continue;
                }

                try
                {
                    HandleIncomingVoice(packet);
                }
                catch (Exception ex)
                {
                    var now = MonotonicSeconds();
                    if ((now - _lastRxDecodeErrorLogAt) >= 1.0)
                    {
                        _lastRxDecodeErrorLogAt = now;
                        WriteDiagnostic(
                            $"RX packet processing failed session={packet.SessionId} channel={packet.ChannelTag} codec={packet.Codec} bytes={packet.Payload.Length}: {ex.Message}"
                        );
                    }
                }
            }
        }
        catch (OperationCanceledException)
        {
            return;
        }
        catch (Exception ex)
        {
            WriteError(ex.Message);
        }
    }

    private void HandleIncomingVoice(VoicePacket packet)
    {
        lock (_talkers)
        {
            if (!_talkers.TryGetValue(packet.SessionId, out var talker))
            {
                talker = new TalkerState();
                _talkers[packet.SessionId] = talker;
            }

            var now = MonotonicSeconds();
            _rxDatagramCount += 1;
            if (_rxDatagramCount == 1 || (now - _lastRxDatagramLogAt) >= 1.0)
            {
                _lastRxDatagramLogAt = now;
                WriteDiagnostic(
                    $"RX voice packet received count={_rxDatagramCount} session={packet.SessionId} channel={packet.ChannelTag} codec={packet.Codec} seq={packet.PacketNumber} bytes={packet.Payload.Length}"
                );
            }
            bool newTransmission = talker.LastReceiveAtSeconds <= 0.0 || (now - talker.LastReceiveAtSeconds) > 0.4;
            var rxGapMs = talker.LastReceiveAtSeconds <= 0.0 ? 0 : (int)((now - talker.LastReceiveAtSeconds) * 1000.0);
            if (rxGapMs >= 120)
            {
                WriteDiagnostic($"RX packet gap {rxGapMs}ms session={packet.SessionId} channel={packet.ChannelTag}");
            }
            if (packet.PacketNumber > 0 && _lastRxPacketNumbers.TryGetValue(packet.SessionId, out var lastPacketNumber) && packet.PacketNumber > lastPacketNumber + 1)
            {
                WriteDiagnostic($"RX missing {packet.PacketNumber - lastPacketNumber - 1} packet(s) session={packet.SessionId} last={lastPacketNumber} current={packet.PacketNumber}");
            }
            if (packet.PacketNumber > 0)
            {
                _lastRxPacketNumbers[packet.SessionId] = packet.PacketNumber;
            }
            talker.LastReceiveAtSeconds = now;
            talker.ChannelTag = packet.ChannelTag;
            talker.SenderRole = string.IsNullOrWhiteSpace(packet.SenderRole) ? "Soldier" : packet.SenderRole;

            var decoded = packet.Codec == VoiceCodec.Opus
                ? talker.Decoder.Decode(packet.Payload, AudioEngineHostConstants.PlaybackFrameSize, newTransmission)
                : ResamplePcm16(
                    packet.Payload,
                    AudioEngineHostConstants.CaptureSampleRate,
                    AudioEngineHostConstants.PlaybackSampleRate
                );
            if (decoded.Length <= 0)
            {
                if ((now - _lastRxDecodeErrorLogAt) >= 1.0)
                {
                    _lastRxDecodeErrorLogAt = now;
                    WriteDiagnostic(
                        $"RX packet dropped after decode session={packet.SessionId} channel={packet.ChannelTag} codec={packet.Codec} seq={packet.PacketNumber} bytes={packet.Payload.Length}"
                    );
                }
                return;
            }
            if (newTransmission)
            {
                talker.Buffer = new TalkerBuffer(
                    skipThresholdPackets: 4,
                    maxBufferedPackets: 72,
                    maxConcealedPackets: 0,
                    maxAdaptivePackets: 8,
                    stablePacketWindow: 48
                );
                if (!talker.Active)
                {
                    talker.Active = true;
                    WriteEvent(new { @event = "talker_state", session_id = packet.SessionId, channel_tag = packet.ChannelTag, active = true });
                }
            }

            if (!_channelReceiveActivity.ContainsKey(packet.ChannelTag))
            {
                EnqueueRxStartFrames();
            }
            _channelReceiveActivity[packet.ChannelTag] = now;
            talker.Buffer.Push(packet.PacketNumber == 0 ? ++talker.LegacyPacketNumber : packet.PacketNumber, decoded, now);
        }
    }

    private async Task PlayoutLoopAsync(CancellationToken cancellationToken)
    {
        long frameTicks = Math.Max(
            1,
            (long)Math.Round(
                AudioEngineHostConstants.PlaybackFrameSize
                / (double)AudioEngineHostConstants.PlaybackSampleRate
                * Stopwatch.Frequency
            )
        );
        long nextTick = Stopwatch.GetTimestamp();
        double lastTickAt = 0.0;
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                long currentTick = Stopwatch.GetTimestamp();
                long delayTicks = nextTick - currentTick;
                if (delayTicks > 0)
                {
                    var delayMs = delayTicks * 1000.0 / Stopwatch.Frequency;
                    if (delayMs > 1.0)
                    {
                        await Task.Delay(TimeSpan.FromMilliseconds(Math.Min(delayMs, 5.0)), cancellationToken).ConfigureAwait(false);
                        continue;
                    }
                }
                else if (-delayTicks > frameTicks * 5)
                {
                    nextTick = currentTick;
                }
                nextTick += frameTicks;

                var tickNow = MonotonicSeconds();
                if (lastTickAt > 0.0)
                {
                    var tickGapMs = (int)((tickNow - lastTickAt) * 1000.0);
                    if (tickGapMs >= 35 && (tickNow - _lastPlayoutGapLogAt) >= 1.0)
                    {
                        _lastPlayoutGapLogAt = tickNow;
                        WriteDiagnostic($"RX playout scheduler gap {tickGapMs}ms");
                    }
                }
                lastTickAt = tickNow;

                if (_outputBuffer is null)
                {
                    continue;
                }

                var mix = new float[AudioEngineHostConstants.PlaybackFrameSize * AudioEngineHostConstants.PlaybackChannels];
                bool hasAudio = false;

                float effectGain = SpeakerOutputGain();
                while (_effectFrames.TryDequeue(out var effectFrame))
                {
                    MixStereoFloat(effectFrame, mix, effectGain);
                    hasAudio = true;
                    break;
                }

                List<uint> staleTalkers = [];
                lock (_talkers)
                {
                    var now = MonotonicSeconds();
                    Dictionary<(string ChannelTag, string SenderRole), List<byte[]>> channelFrames = [];
                    foreach (var pair in _talkers)
                    {
                        var talker = pair.Value;
                        var (frame, skippedPackets) = talker.Buffer.PopReady();
                        if (skippedPackets > 0)
                        {
                            WriteDiagnostic($"RX skipped {skippedPackets} packet(s) while catching up talker session={pair.Key}");
                        }
                        if (frame is null && talker.Buffer.HasPending && (now - _lastPlayoutWaitingLogAt) >= 1.0)
                        {
                            _lastPlayoutWaitingLogAt = now;
                            WriteDiagnostic($"RX playout waiting for buffered talker session={pair.Key}");
                        }
                        if (frame is not null)
                        {
                            var frameKey = (talker.ChannelTag, talker.SenderRole);
                            if (!channelFrames.TryGetValue(frameKey, out var frames))
                            {
                                frames = [];
                                channelFrames[frameKey] = frames;
                            }
                            frames.Add(frame);
                            hasAudio = true;
                        }

                        if (!talker.Buffer.HasPending && talker.Buffer.IsStale(1.2, now))
                        {
                            staleTalkers.Add(pair.Key);
                        }
                    }

                    foreach (var sessionId in staleTalkers)
                    {
                        if (_talkers.Remove(sessionId, out var talker))
                        {
                            talker.Dispose();
                            _lastRxPacketNumbers.Remove(sessionId);
                            WriteEvent(new { @event = "talker_state", session_id = sessionId, channel_tag = talker.ChannelTag, active = false });
                        }
                    }

                    foreach (var channelEntry in channelFrames)
                    {
                        MixChannelFrames(channelEntry.Value, channelEntry.Key.ChannelTag, channelEntry.Key.SenderRole, mix);
                    }

                    foreach (var staleChannel in _channelReceiveActivity.Where(pair => (now - pair.Value) > 1.0).Select(pair => pair.Key).ToArray())
                    {
                        _channelReceiveActivity.Remove(staleChannel);
                        foreach (var processorKey in _channelRxProcessors.Keys.Where(key => key.EndsWith($":{staleChannel}", StringComparison.OrdinalIgnoreCase)).ToArray())
                        {
                            _channelRxProcessors.Remove(processorKey);
                        }
                        EnqueueEffectFrames(ToneEffects.RxEndFrames(staleChannel));
                    }
                }

                if (!hasAudio)
                {
                    _limiter.Reset();
                    continue;
                }

                var limited = _limiter.Process(mix);
                byte[] bytes = FloatArrayToBytes(limited);
                EnsurePlaybackRunning();
                _outputBuffer.AddSamples(bytes, 0, bytes.Length);
                _rxPlayoutFrameCount += 1;
                var playoutNow = MonotonicSeconds();
                if (_rxPlayoutFrameCount == 1 || (playoutNow - _lastRxPlayoutLogAt) >= 1.0)
                {
                    _lastRxPlayoutLogAt = playoutNow;
                    WriteDiagnostic($"RX playout wrote audio frames={_rxPlayoutFrameCount} bytes={bytes.Length}");
                }
            }
        }
        catch (OperationCanceledException)
        {
            return;
        }
        catch (Exception ex)
        {
            WriteError(ex.Message);
        }
    }

    private void OnDataAvailable(object? sender, WaveInEventArgs args)
    {
        if (_stopping || _capture is null || args.BytesRecorded <= 0)
        {
            return;
        }

        lock (_captureLock)
        {
            _lastCaptureDataAt = MonotonicSeconds();
            _captureResampler ??= new EventDrivenResampler(_capture.WaveFormat, new WaveFormat(AudioEngineHostConstants.CaptureSampleRate, 16, 1));
            var resampledBytes = _captureResampler.ResampleBytes(args.Buffer, args.BytesRecorded);
            if (resampledBytes.Length <= 0)
            {
                return;
            }

            int frameBytes = AudioEngineHostConstants.CaptureFrameSize * 2;
            _pendingCaptureBytes.AddRange(resampledBytes);
            while (_pendingCaptureBytes.Count >= frameBytes)
            {
                var now = MonotonicSeconds();
                if (_lastCaptureFrameAt > 0.0)
                {
                    var captureGapMs = (int)((now - _lastCaptureFrameAt) * 1000.0);
                    if (captureGapMs >= 120 && _transmitting)
                    {
                        WriteDiagnostic($"TX capture gap {captureGapMs}ms while transmitting");
                    }
                }
                _lastCaptureFrameAt = now;

                byte[] frame = _pendingCaptureBytes.GetRange(0, frameBytes).ToArray();
                _pendingCaptureBytes.RemoveRange(0, frameBytes);

                WriteEvent(new { @event = "level", value = CalculateLevel(frame) });
                HandleCapturedFrame(frame);
            }
        }
    }

    private void HandleCapturedFrame(byte[] frame)
    {
        var prepared = ScalePcm16(frame, SliderGain(_microphoneVolumePercent));
        lock (_stateLock)
        {
            if (!_pttPressed && !_transmitting)
            {
                if (_txPrerollFrames.Count >= 3)
                {
                    _txPrerollFrames.Dequeue();
                }
                _txPrerollFrames.Enqueue(prepared);
                return;
            }

            if (_pttPressed)
            {
                if (_txPrerollFrames.Count > 0)
                {
                    while (_txPrerollFrames.Count > 0)
                    {
                        QueueVoiceFrame(_txPrerollFrames.Dequeue());
                    }
                }

                _transmitting = true;
                QueueVoiceFrame(prepared);
                return;
            }

            QueueVoiceFrame(prepared);
            if (_txReleaseFramesRemaining > 0)
            {
                _txReleaseFramesRemaining -= 1;
            }
            if (_txReleaseFramesRemaining <= 0)
            {
                _transmitting = false;
                EnqueueEffectFrames(ToneEffects.TxEndFrames(_channelTag));
            }
        }
    }

    private void QueueVoiceFrame(byte[] pcmBytes)
    {
        if (pcmBytes.Length == 0)
        {
            return;
        }

        const int maxQueuedFrames = 12;
        while (_txSendQueue.Count >= maxQueuedFrames && _txSendQueue.TryDequeue(out _))
        {
            WriteDiagnostic("TX pacing queue dropped stale frame");
        }

        _txSendQueue.Enqueue(pcmBytes);
        _txSendSignal.Release();
    }

    private void ClearTxSendQueue()
    {
        while (_txSendQueue.TryDequeue(out _))
        {
            // Drop stale audio when a new PTT transmission starts.
        }
    }

    private async Task TxPacerLoopAsync(CancellationToken cancellationToken)
    {
        double frameDurationSeconds = AudioEngineHostConstants.CaptureFrameSize / (double)AudioEngineHostConstants.CaptureSampleRate;
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                if (!_txSendQueue.TryDequeue(out var frame))
                {
                    await _txSendSignal.WaitAsync(cancellationToken).ConfigureAwait(false);
                    continue;
                }

                var now = MonotonicSeconds();
                if (_nextTxSendDueAt <= 0.0 || (now - _nextTxSendDueAt) > 0.25)
                {
                    _nextTxSendDueAt = now;
                }

                var delaySeconds = _nextTxSendDueAt - now;
                if (delaySeconds > 0.001)
                {
                    await Task.Delay(TimeSpan.FromSeconds(delaySeconds), cancellationToken).ConfigureAwait(false);
                }

                SendVoiceFrame(frame);
                _nextTxSendDueAt += frameDurationSeconds;
            }
        }
        catch (OperationCanceledException)
        {
            return;
        }
    }

    private void SendVoiceFrame(byte[] pcmBytes)
    {
        if (_udpClient is null || _voiceEndPoint is null || _sessionId == 0 || pcmBytes.Length == 0)
        {
            var blockedNow = MonotonicSeconds();
            if ((blockedNow - _lastTxBlockedLogAt) >= 1.0)
            {
                _lastTxBlockedLogAt = blockedNow;
                WriteDiagnostic(
                    $"TX blocked udp={_udpClient is not null} endpoint={_voiceEndPoint is not null} session={_sessionId} bytes={pcmBytes.Length}"
                );
            }
            return;
        }

        byte[] encoded = pcmBytes;
        VoiceCodec codec = VoiceCodec.Pcm16;
        if (_encoder is not null && _encoder.Available && _encoder.TryEncode(pcmBytes, AudioEngineHostConstants.CaptureFrameSize, out var opusBytes))
        {
            encoded = opusBytes;
            codec = VoiceCodec.Opus;
        }
        var packet = VoicePacketCodec.Pack(
            _sessionId,
            _channelTag,
            encoded,
            codec,
            NextPacketNumber(),
            CaptureTimestampMs(),
            _selectedRole
        );
        var now = MonotonicSeconds();
        if (_lastTxSendAt > 0.0)
        {
            var sendGapMs = (int)((now - _lastTxSendAt) * 1000.0);
            if (sendGapMs >= 120)
            {
                WriteDiagnostic($"TX send gap {sendGapMs}ms");
            }
        }
        _lastTxSendAt = now;
        _udpClient.Send(packet, packet.Length, _voiceEndPoint);
        if (!_txFrameSentSincePtt)
        {
            _txFrameSentSincePtt = true;
            WriteDiagnostic($"TX first voice frame sent session={_sessionId} channel={_channelTag}");
        }
        _registrationRequested = false;
        _nextKeepaliveAt = now + KeepaliveIntervalSeconds;
    }

    private void MonitorCaptureHealth()
    {
        if (_stopping || _capture is null)
        {
            return;
        }

        var now = MonotonicSeconds();
        var lastDataAt = _lastCaptureDataAt;
        var noInitialFrames = lastDataAt <= 0.0 && (now - _captureStartedAt) >= 1.5;
        var stalledWhileTransmitting = _pttPressed && lastDataAt > 0.0 && (now - lastDataAt) >= 1.0;
        if (!noInitialFrames && !stalledWhileTransmitting)
        {
            return;
        }
        if (_captureRestartCount >= 3)
        {
            if ((now - _lastTxBlockedLogAt) >= 1.0)
            {
                _lastTxBlockedLogAt = now;
                WriteDiagnostic(
                    $"capture watchdog cannot restart anymore restarts={_captureRestartCount} last_data={lastDataAt:0.000}"
                );
            }
            return;
        }

        RestartCaptureFromWatchdog(noInitialFrames ? "no_initial_frames" : "stalled_while_transmitting");
    }

    private void RestartCaptureFromWatchdog(string reason)
    {
        lock (_captureLock)
        {
            if (_stopping)
            {
                return;
            }

            _captureRestartCount += 1;
            WriteDiagnostic($"capture watchdog restarting reason={reason} count={_captureRestartCount}");
            try
            {
                if (_capture is not null)
                {
                    _capture.DataAvailable -= OnDataAvailable;
                    _capture.RecordingStopped -= OnRecordingStopped;
                    _capture.StopRecording();
                    _capture.Dispose();
                    _capture = null;
                }
                _captureResampler?.Dispose();
                _captureResampler = null;
                _pendingCaptureBytes.Clear();
                _capture = new WasapiCapture(
                    _captureDevice ?? ResolveCaptureDevice(_options.InputEndpointId),
                    true,
                    AudioEngineHostConstants.CaptureBufferMilliseconds
                )
                {
                    ShareMode = AudioClientShareMode.Shared,
                };
                _capture.DataAvailable += OnDataAvailable;
                _capture.RecordingStopped += OnRecordingStopped;
                _capture.StartRecording();
                _captureStartedAt = MonotonicSeconds();
                _lastCaptureDataAt = 0.0;
            }
            catch (Exception ex)
            {
                WriteError($"capture watchdog restart failed: {ex.Message}");
            }
        }
    }

    private void OnRecordingStopped(object? sender, StoppedEventArgs args)
    {
        if (args.Exception is not null)
        {
            WriteError(args.Exception.Message);
        }

        Stop();
    }

    private void OnPlaybackStopped(object? sender, StoppedEventArgs args)
    {
        if (args.Exception is not null)
        {
            WriteError(args.Exception.Message);
            return;
        }
        WriteDiagnostic("playback stopped without exception");
    }

    private void EnsurePlaybackRunning()
    {
        if (_output is null)
        {
            return;
        }

        if (_output.PlaybackState == PlaybackState.Playing)
        {
            return;
        }

        _output.Play();
        var now = MonotonicSeconds();
        if ((now - _lastPlaybackRestartLogAt) >= 1.0)
        {
            _lastPlaybackRestartLogAt = now;
            WriteDiagnostic($"playback restarted state={_output.PlaybackState}");
        }
    }

    private void Stop()
    {
        if (_stopping)
        {
            return;
        }

        _stopping = true;
        try
        {
            _cts?.Cancel();
        }
        catch
        {
            // ignored
        }

        try
        {
            _capture?.StopRecording();
        }
        catch
        {
            // ignored
        }

        try
        {
            _output?.Stop();
        }
        catch
        {
            // ignored
        }

        Dispose();
        _exitSignal.TrySetResult(0);
    }

    private IPEndPoint? BuildVoiceEndpoint()
    {
        if (!IPAddress.TryParse(_voiceHost, out var address))
        {
            return null;
        }

        return new IPEndPoint(address, _voicePort);
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
            if (string.Equals(device.ID, endpointId, StringComparison.OrdinalIgnoreCase))
            {
                return device;
            }
        }

        return WasapiCapture.GetDefaultCaptureDevice();
    }

    private static MMDevice ResolveOutputDevice(string endpointId)
    {
        using var enumerator = new MMDeviceEnumerator();
        if (string.IsNullOrWhiteSpace(endpointId))
        {
            return enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
        }

        var devices = enumerator.EnumerateAudioEndPoints(DataFlow.Render, DeviceState.Active);
        foreach (var device in devices)
        {
            if (string.Equals(device.ID, endpointId, StringComparison.OrdinalIgnoreCase))
            {
                return device;
            }
        }

        return enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
    }

    private void MixChannelFrames(List<byte[]> frames, string channelTag, string senderRole, float[] mix)
    {
        if (frames.Count == 0)
        {
            return;
        }

        float gain = ReceiveGain(channelTag);
        string panMode = ChannelPanMode(channelTag);
        var channelMix = new float[AudioEngineHostConstants.PlaybackFrameSize];
        foreach (var monoPcm16 in frames)
        {
            int samples = Math.Min(AudioEngineHostConstants.PlaybackFrameSize, monoPcm16.Length / 2);
            for (int index = 0; index < samples; index++)
            {
                short pcm = BitConverter.ToInt16(monoPcm16, index * 2);
                channelMix[index] += pcm / 32768f;
            }
        }

        if (VoiceEffectsEnabled)
        {
            var rxProcessor = GetChannelRxProcessor(channelTag, senderRole);
            channelMix = rxProcessor.ProcessFloatSamples(channelMix);
        }

        for (int index = 0; index < channelMix.Length; index++)
        {
            float sample = channelMix[index] * gain;
            int stereoIndex = index * 2;
            switch (panMode)
            {
                case "left":
                    mix[stereoIndex] += sample;
                    break;
                case "right":
                    mix[stereoIndex + 1] += sample;
                    break;
                default:
                    mix[stereoIndex] += sample;
                    mix[stereoIndex + 1] += sample;
                    break;
            }
        }
    }

    private Arc210RxProcessor GetChannelRxProcessor(string channelTag, string senderRole)
    {
        var normalizedRole = string.IsNullOrWhiteSpace(senderRole) ? "Soldier" : senderRole.Trim();
        var processorKey = $"{normalizedRole.ToLowerInvariant()}:{channelTag}";
        if (_channelRxProcessors.TryGetValue(processorKey, out var processor))
        {
            return processor;
        }

        processor = new Arc210RxProcessor(normalizedRole);
        _channelRxProcessors[processorKey] = processor;
        return processor;
    }

    private void EnqueueRxStartFrames()
    {
        foreach (var frame in ToneEffects.CommsStartFrames())
        {
            _effectFrames.Enqueue(frame);
        }
    }

    private void EnqueueEffectFrames(IEnumerable<byte[]> frames)
    {
        if (!ToneEffectsEnabled)
        {
            return;
        }

        foreach (var frame in frames)
        {
            _effectFrames.Enqueue(frame);
        }
    }

    private static void MixStereoFloat(byte[] stereoFloatBytes, float[] mix, float gain = 1.0f)
    {
        int count = Math.Min(mix.Length, stereoFloatBytes.Length / sizeof(float));
        for (int index = 0; index < count; index++)
        {
            mix[index] += BitConverter.ToSingle(stereoFloatBytes, index * sizeof(float)) * gain;
        }
    }

    private float ReceiveGain(string channelTag)
    {
        int index = channelTag switch
        {
            "squad" => 0,
            "hq" => 1,
            "atc" => 2,
            _ => 3,
        };

        int channelPercent = index < _channelReceiveVolumes.Length ? _channelReceiveVolumes[index] : 100;
        float speakerGain = SpeakerOutputGain();
        return ReceiveSliderGain(channelPercent) * speakerGain * 0.42f;
    }

    private string ChannelPanMode(string channelTag)
    {
        int index = channelTag switch
        {
            "squad" => 0,
            "hq" => 1,
            "atc" => 2,
            _ => 3,
        };
        return index < _channelPanModes.Length ? _channelPanModes[index] : "both";
    }

    private float SpeakerOutputGain()
    {
        return ReceiveSliderGain(_speakerVolumePercent);
    }

    private static float ReceiveSliderGain(int percent)
    {
        var normalized = Math.Max(0.0, percent / 100.0);
        if (normalized <= 1.0)
        {
            return (float)(normalized * normalized * normalized);
        }

        return (float)Math.Min(8.0, 1.0 + ((normalized - 1.0) * 7.0));
    }

    private static float SliderGain(int percent)
    {
        var normalized = Math.Max(0.0, percent / 100.0);
        if (normalized <= 1.0)
        {
            return (float)(normalized * normalized);
        }

        return (float)Math.Min(4.0, 1.0 + ((normalized - 1.0) * 3.0));
    }

    private static byte[] ScalePcm16(byte[] pcmBytes, float gain)
    {
        if (pcmBytes.Length == 0 || Math.Abs(gain - 1.0f) < 0.0001f)
        {
            return pcmBytes;
        }

        byte[] output = new byte[pcmBytes.Length];
        for (int index = 0; index < pcmBytes.Length; index += 2)
        {
            short sample = BitConverter.ToInt16(pcmBytes, index);
            int scaled = (int)Math.Round(sample * gain);
            scaled = Math.Clamp(scaled, short.MinValue, short.MaxValue);
            var bytes = BitConverter.GetBytes((short)scaled);
            output[index] = bytes[0];
            output[index + 1] = bytes[1];
        }
        return output;
    }

    private static double CalculateLevel(byte[] frameBytes)
    {
        if (frameBytes.Length < 2)
        {
            return 0.0;
        }

        double peak = 0.0;
        double sumSquares = 0.0;
        int sampleCount = frameBytes.Length / 2;
        for (int offset = 0; offset < frameBytes.Length; offset += 2)
        {
            short sample = BitConverter.ToInt16(frameBytes, offset);
            var normalized = Math.Abs(sample / 32767.0);
            peak = Math.Max(peak, normalized);
            sumSquares += normalized * normalized;
        }

        var rms = Math.Sqrt(sumSquares / sampleCount);
        return Math.Clamp(Math.Max(rms * 2.8, peak * 0.9), 0.0, 1.0);
    }

    private static uint CaptureTimestampMs()
    {
        return (uint)(Environment.TickCount64 & 0xFFFFFFFF);
    }

    private uint NextPacketNumber()
    {
        uint current = _packetNumber;
        _packetNumber = _packetNumber == uint.MaxValue ? 1u : _packetNumber + 1u;
        return current;
    }

    private static double MonotonicSeconds()
    {
        return Environment.TickCount64 / 1000.0;
    }

    private static byte[] FloatArrayToBytes(float[] samples)
    {
        byte[] bytes = new byte[samples.Length * sizeof(float)];
        Buffer.BlockCopy(samples, 0, bytes, 0, bytes.Length);
        return bytes;
    }

    private static byte[] ResamplePcm16(byte[] pcmBytes, int sourceRate, int targetRate)
    {
        if (pcmBytes.Length == 0 || sourceRate == targetRate)
        {
            return pcmBytes;
        }

        int inputSamples = pcmBytes.Length / 2;
        int outputSamples = (int)Math.Round(inputSamples * (targetRate / (double)sourceRate));
        byte[] output = new byte[outputSamples * 2];
        for (int index = 0; index < outputSamples; index++)
        {
            double sourceIndex = index * (inputSamples - 1.0) / Math.Max(1.0, outputSamples - 1.0);
            int leftIndex = (int)Math.Floor(sourceIndex);
            int rightIndex = Math.Min(inputSamples - 1, leftIndex + 1);
            double weight = sourceIndex - leftIndex;
            short left = BitConverter.ToInt16(pcmBytes, leftIndex * 2);
            short right = BitConverter.ToInt16(pcmBytes, rightIndex * 2);
            short sample = (short)Math.Round((left * (1.0 - weight)) + (right * weight));
            var bytes = BitConverter.GetBytes(sample);
            output[index * 2] = bytes[0];
            output[index * 2 + 1] = bytes[1];
        }
        return output;
    }

    private static void WriteEvent(object payload)
    {
        Console.Out.WriteLine(JsonSerializer.Serialize(payload));
        Console.Out.Flush();
    }

    private static void WriteError(string message)
    {
        var normalized = string.IsNullOrWhiteSpace(message) ? "audio_engine_error" : message.Trim();
        Console.Error.WriteLine(normalized);
        Console.Error.Flush();
        WriteEvent(new { @event = "error", message = normalized });
    }

    private static void WriteDiagnostic(string message)
    {
        var normalized = string.IsNullOrWhiteSpace(message) ? "diagnostic" : message.Trim();
        WriteEvent(new { @event = "diagnostic", message = normalized });
    }

    private sealed class TalkerState : IDisposable
    {
        public TalkerBuffer Buffer { get; set; } = new();
        public NativeOpusDecoder Decoder { get; } = new(AudioEngineHostConstants.PlaybackSampleRate, 1);
        public string ChannelTag { get; set; } = "general";
        public string SenderRole { get; set; } = "Soldier";
        public double LastReceiveAtSeconds { get; set; }
        public uint LegacyPacketNumber { get; set; }
        public bool Active { get; set; }

        public void Dispose()
        {
            Decoder.Dispose();
        }
    }
}
