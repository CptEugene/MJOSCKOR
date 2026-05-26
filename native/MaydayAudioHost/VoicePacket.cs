using System.Buffers.Binary;

namespace MaydayAudioHost;

internal enum VoiceCodec : byte
{
    Pcm16 = 1,
    Opus = 2
}

internal sealed record VoicePacket(
    uint SessionId,
    string ChannelTag,
    VoiceCodec Codec,
    uint PacketNumber,
    uint SentAtMs,
    string SenderRole,
    byte[] Payload
);

internal static class VoicePacketCodec
{
    private static readonly byte[] Magic = "MV"u8.ToArray();
    private static readonly byte[] RolePayloadMagic = "MR"u8.ToArray();
    private const byte Version = 2;
    private const int HeaderLength = 17;

    public static byte[] Pack(
        uint sessionId,
        string channelTag,
        ReadOnlySpan<byte> payload,
        VoiceCodec codec,
        uint packetNumber,
        uint sentAtMs,
        string senderRole = ""
    )
    {
        byte roleCode = RoleToCode(senderRole);
        int rolePrefixLength = roleCode == 0 ? 0 : 3;
        byte[] packet = new byte[HeaderLength + rolePrefixLength + payload.Length];
        packet[0] = Magic[0];
        packet[1] = Magic[1];
        packet[2] = Version;
        BinaryPrimitives.WriteUInt32BigEndian(packet.AsSpan(3, 4), sessionId);
        packet[7] = ChannelTagToCode(channelTag);
        packet[8] = (byte)codec;
        BinaryPrimitives.WriteUInt32BigEndian(packet.AsSpan(9, 4), packetNumber);
        BinaryPrimitives.WriteUInt32BigEndian(packet.AsSpan(13, 4), sentAtMs);
        if (roleCode != 0)
        {
            packet[HeaderLength] = RolePayloadMagic[0];
            packet[HeaderLength + 1] = RolePayloadMagic[1];
            packet[HeaderLength + 2] = roleCode;
        }
        payload.CopyTo(packet.AsSpan(HeaderLength + rolePrefixLength));
        return packet;
    }

    public static bool TryUnpack(ReadOnlySpan<byte> packet, out VoicePacket voicePacket)
    {
        voicePacket = new VoicePacket(0, "general", VoiceCodec.Pcm16, 0, 0, "", []);
        if (packet.Length < HeaderLength)
        {
            return false;
        }

        if (packet[0] != Magic[0] || packet[1] != Magic[1] || packet[2] != Version)
        {
            return false;
        }

        var sessionId = BinaryPrimitives.ReadUInt32BigEndian(packet.Slice(3, 4));
        var channelCode = packet[7];
        var codecCode = packet[8];
        var packetNumber = BinaryPrimitives.ReadUInt32BigEndian(packet.Slice(9, 4));
        var sentAtMs = BinaryPrimitives.ReadUInt32BigEndian(packet.Slice(13, 4));
        var (payload, senderRole) = DecodeRolePayload(packet[HeaderLength..]);
        voicePacket = new VoicePacket(
            sessionId,
            ChannelCodeToTag(channelCode),
            codecCode == (byte)VoiceCodec.Opus ? VoiceCodec.Opus : VoiceCodec.Pcm16,
            packetNumber,
            sentAtMs,
            senderRole,
            payload
        );
        return true;
    }

    private static byte ChannelTagToCode(string channelTag)
    {
        return channelTag.Trim().ToLowerInvariant() switch
        {
            "squad" => 1,
            "hq" => 2,
            "atc" => 3,
            "general" => 4,
            _ => 4,
        };
    }

    private static string ChannelCodeToTag(byte channelCode)
    {
        return channelCode switch
        {
            1 => "squad",
            2 => "hq",
            3 => "atc",
            4 => "general",
            _ => "general",
        };
    }

    private static byte RoleToCode(string role)
    {
        return role.Trim().ToLowerInvariant() switch
        {
            "commander" => 1,
            "officer" => 2,
            "pilot" => 3,
            "soldier" => 4,
            _ => 0,
        };
    }

    private static string CodeToRole(byte roleCode)
    {
        return roleCode switch
        {
            1 => "Commander",
            2 => "Officer",
            3 => "Pilot",
            4 => "Soldier",
            _ => "",
        };
    }

    private static (byte[] Payload, string SenderRole) DecodeRolePayload(ReadOnlySpan<byte> payload)
    {
        if (payload.Length >= 3 && payload[0] == RolePayloadMagic[0] && payload[1] == RolePayloadMagic[1])
        {
            return (payload[3..].ToArray(), CodeToRole(payload[2]));
        }
        return (payload.ToArray(), "");
    }
}
