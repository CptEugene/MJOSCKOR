namespace MaydayAudioHost;

internal sealed class TalkerBuffer
{
    private readonly int _skipThresholdPackets;
    private readonly int _maxBufferedPackets;
    private readonly int _maxConcealedPackets;
    private readonly int _maxAdaptivePackets;
    private readonly int _stablePacketWindow;
    private readonly SortedDictionary<uint, byte[]> _frames = [];
    private uint? _expectedPacket;
    private bool _primed;
    private int _concealedPackets;
    private int _frameSize;
    private int _targetBufferPackets;
    private int _stablePackets;
    private double _lastPacketAt;

    public TalkerBuffer(
        int skipThresholdPackets = 1,
        int maxBufferedPackets = 24,
        int maxConcealedPackets = 2,
        int maxAdaptivePackets = 4,
        int stablePacketWindow = 12
    )
    {
        _skipThresholdPackets = Math.Max(1, skipThresholdPackets);
        _maxAdaptivePackets = Math.Max(_skipThresholdPackets, maxAdaptivePackets);
        _stablePacketWindow = Math.Max(1, stablePacketWindow);
        _maxBufferedPackets = Math.Max(_maxAdaptivePackets + 1, maxBufferedPackets);
        _maxConcealedPackets = Math.Max(0, maxConcealedPackets);
        _targetBufferPackets = _skipThresholdPackets;
    }

    public string Push(uint packetNumber, byte[] pcmBytes, double nowSeconds)
    {
        if (pcmBytes.Length == 0)
        {
            return "empty";
        }

        _lastPacketAt = nowSeconds;
        _frameSize = pcmBytes.Length;
        if (_expectedPacket is null)
        {
            _expectedPacket = packetNumber;
        }
        else if (!_primed && packetNumber < _expectedPacket.Value)
        {
            _expectedPacket = packetNumber;
        }
        else if (_expectedPacket is not null && packetNumber < _expectedPacket.Value)
        {
            IncreaseTargetBuffer();
            return "late_drop";
        }

        _frames[packetNumber] = pcmBytes;
        if (_primed && _expectedPacket is not null && packetNumber > (_expectedPacket.Value + 1))
        {
            IncreaseTargetBuffer();
        }

        if (_frames.Count <= _maxBufferedPackets)
        {
            return "stored";
        }

        uint oldestPacket = _frames.Keys.First();
        _frames.Remove(oldestPacket);
        IncreaseTargetBuffer();
        if (_expectedPacket is not null && oldestPacket >= _expectedPacket.Value)
        {
            _expectedPacket = _frames.Count > 0 ? _frames.Keys.First() : null;
        }

        return "overflow_drop";
    }

    public (byte[]? Frame, int SkippedPackets) PopReady()
    {
        if (_expectedPacket is null)
        {
            return (null, 0);
        }

        if (!_primed)
        {
            if (_frames.Count < _targetBufferPackets)
            {
                return (null, 0);
            }

            _expectedPacket = _frames.Keys.First();
            _primed = true;
        }

        if (_frames.Remove(_expectedPacket.Value, out var frame))
        {
            _expectedPacket += 1;
            _concealedPackets = 0;
            NoteStablePacket();
            return (frame, 0);
        }

        if (_frames.Count == 0)
        {
            return (null, 0);
        }

        var earliestPacket = _frames.Keys.First();
        if (earliestPacket > _expectedPacket.Value && _frameSize > 0 && _concealedPackets < _maxConcealedPackets)
        {
            _concealedPackets += 1;
            IncreaseTargetBuffer();
            _expectedPacket += 1;
            return (new byte[_frameSize], 0);
        }

        if (earliestPacket > _expectedPacket.Value
            && (_frames.Count >= _skipThresholdPackets || (earliestPacket - _expectedPacket.Value) >= _skipThresholdPackets))
        {
            var skippedPackets = (int)(earliestPacket - _expectedPacket.Value);
            IncreaseTargetBuffer(Math.Min(2, Math.Max(1, skippedPackets)));
            _expectedPacket = earliestPacket;
            if (_frames.Remove(earliestPacket, out frame))
            {
                _expectedPacket = earliestPacket + 1;
                _concealedPackets = 0;
                return (frame, skippedPackets);
            }
        }

        return (null, 0);
    }

    public bool HasPending => _frames.Count > 0;

    public bool IsStale(double maxIdleSeconds, double nowSeconds)
    {
        if (_lastPacketAt <= 0.0)
        {
            return false;
        }

        return (nowSeconds - _lastPacketAt) > maxIdleSeconds;
    }

    private void IncreaseTargetBuffer(int amount = 1)
    {
        _targetBufferPackets = Math.Min(_maxAdaptivePackets, _targetBufferPackets + amount);
        _stablePackets = 0;
    }

    private void NoteStablePacket()
    {
        if (_targetBufferPackets <= _skipThresholdPackets)
        {
            _stablePackets = 0;
            return;
        }

        _stablePackets += 1;
        if (_stablePackets >= _stablePacketWindow)
        {
            _targetBufferPackets = Math.Max(_skipThresholdPackets, _targetBufferPackets - 1);
            _stablePackets = 0;
        }
    }
}
