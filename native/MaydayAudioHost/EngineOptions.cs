namespace MaydayAudioHost;

internal sealed record EngineOptions(
    string InputEndpointId,
    string OutputEndpointId,
    string VoiceHost,
    int VoicePort,
    uint SessionId,
    string ChannelTag
);
