from client.audio.radio_eq import (
    ARC210_CHANNEL_TAGS,
    ARC210_RX_WET_MIX,
    ARC210_TX_WET_MIX,
    Arc210RxProcessor,
    LEGACY_COMMS_BACKING_MIX,
    MAYDAY_COMMS_MODEL,
    NON_PILOT_RX_OUTPUT_GAIN,
    NON_PILOT_RX_WET_MIX,
    PILOT_RX_OUTPUT_GAIN,
    RADIO_PROFILES,
    SRS_ARC210_MODEL,
    process_pcm16_mono,
    process_rx_pcm16_mono,
)


def _pcm_frame() -> bytes:
    return b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in (-1200, -300, 0, 300, 1200) * 192)


def test_arc210_model_matches_srs_reference_structure() -> None:
    tx_effects = SRS_ARC210_MODEL["txEffect"]["effects"]
    rx_filters = SRS_ARC210_MODEL["rxEffect"]["filters"]

    assert SRS_ARC210_MODEL["version"] == 1
    assert SRS_ARC210_MODEL["noiseGain"] == -33.0
    assert tx_effects[0]["filters"][0] == {"$type": "highpass", "frequency": 1700.0, "q": 0.53}
    assert tx_effects[0]["filters"][1] == {"$type": "peak", "frequency": 2801.0, "q": 0.5, "gain": 5.0}
    assert tx_effects[0]["filters"][2] == {"$type": "lowpass", "frequency": 5538.0}
    assert tx_effects[1] == {"$type": "saturation", "gain": 9.0, "threshold": -23.0}
    assert tx_effects[2]["$type"] == "sidechainCompressor"
    assert tx_effects[2]["sidechainEffect"]["filters"][0] == {"$type": "highpass", "frequency": 709.0}
    assert tx_effects[3]["filters"][0] == {"$type": "highpass", "frequency": 456.0, "q": 0.36}
    assert tx_effects[3]["filters"][1] == {"$type": "lowpass", "frequency": 5435.0, "q": 0.39}
    assert tx_effects[4] == {"$type": "gain", "gain": 12.0}
    assert rx_filters == [
        {"$type": "highpass", "frequency": 270.0},
        {"$type": "lowpass", "frequency": 4500.0},
    ]


def test_arc210_channels_share_same_active_tx_model() -> None:
    for channel_tag in ARC210_CHANNEL_TAGS:
        assert RADIO_PROFILES[channel_tag] is MAYDAY_COMMS_MODEL["txEffect"]
    assert ARC210_TX_WET_MIX == 0.0
    assert ARC210_RX_WET_MIX == 0.92
    assert LEGACY_COMMS_BACKING_MIX == 0.0
    assert NON_PILOT_RX_WET_MIX == 0.20
    assert NON_PILOT_RX_OUTPUT_GAIN == 1.50
    assert PILOT_RX_OUTPUT_GAIN == 1.05


def test_mayday_comms_tx_chain_is_disabled() -> None:
    assert MAYDAY_COMMS_MODEL["version"] == 5
    assert MAYDAY_COMMS_MODEL["baseModel"] == "Squadron42HelmetComms"
    assert MAYDAY_COMMS_MODEL["txEffect"] == {"$type": "identity"}


def test_mayday_comms_rx_model_describes_homeworld_fleet_comms_preset() -> None:
    rx_effect = MAYDAY_COMMS_MODEL["rxEffect"]

    assert rx_effect["$type"] == "homeworldFleetComms"
    assert rx_effect["preset"] == "HOMEWORLD_FLEET_COMMS"
    assert rx_effect["highPass"] == 190.0
    assert rx_effect["lowPass"] == 4850.0
    assert rx_effect["lowMidCut"] == {"frequency": 420.0, "q": 0.85, "gain": -3.0}
    assert rx_effect["midPresence"] == {"frequency": 1150.0, "q": 0.90, "gain": 4.2}
    assert rx_effect["upperPresence"] == {"frequency": 2900.0, "q": 0.95, "gain": 2.1}
    assert rx_effect["compressor"] == {"attack": 0.008, "release": 0.110, "threshold": -27.0, "ratio": 3.5, "makeUp": 3.0}
    assert rx_effect["saturation"] == {"drive": 1.08, "mode": "softClip"}
    assert rx_effect["space"] == {"type": "shortRoomPlate", "preDelay": 0.016, "decay": 0.52, "mix": 0.075}
    assert rx_effect["noise"] == {"floor": -54.0, "follow": -60.0}
    assert rx_effect["grain"] == {"level": -59.0}


def test_srs_arc210_processing_is_channel_invariant() -> None:
    pcm_frame = _pcm_frame()

    outputs = {
        channel_tag: process_pcm16_mono(pcm_frame, gain=1.0, channel_tag=channel_tag)
        for channel_tag in ARC210_CHANNEL_TAGS
    }

    assert len({output for output in outputs.values()}) == 1
    assert outputs["general"] == pcm_frame
    assert process_rx_pcm16_mono(pcm_frame) != pcm_frame


def test_non_pilot_rx_uses_homeworld_fleet_comms_profile() -> None:
    processor = Arc210RxProcessor("Soldier")

    assert processor._effect.PRESET_NAME == "HOMEWORLD_FLEET_COMMS"  # noqa: SLF001
    assert processor._wet_mix == 0.20  # noqa: SLF001
    assert processor._output_gain == 1.50  # noqa: SLF001


def test_pilot_rx_uses_taccom_with_reduced_gain() -> None:
    processor = Arc210RxProcessor("Pilot")

    assert processor._wet_mix == 0.10  # noqa: SLF001
    assert processor._output_gain == 1.05  # noqa: SLF001


def test_tx_processing_applies_only_requested_gain() -> None:
    pcm_frame = _pcm_frame()

    assert process_pcm16_mono(pcm_frame, gain=1.0) == pcm_frame
    assert process_pcm16_mono(pcm_frame, gain=0.5) != pcm_frame


def test_rx_processor_preserves_state_across_chunked_processing() -> None:
    pcm_frame = _pcm_frame()
    split_offset = 514
    split_offset -= split_offset % 2

    whole = Arc210RxProcessor().process_pcm16(pcm_frame)
    chunked_processor = Arc210RxProcessor()
    chunked = (
        chunked_processor.process_pcm16(pcm_frame[:split_offset])
        + chunked_processor.process_pcm16(pcm_frame[split_offset:])
    )

    assert chunked == whole


def test_rx_processor_reset_restores_fresh_state() -> None:
    pcm_frame = _pcm_frame()
    processor = Arc210RxProcessor()

    _ = processor.process_pcm16(pcm_frame)
    processor.reset()

    assert processor.process_pcm16(pcm_frame) == Arc210RxProcessor().process_pcm16(pcm_frame)
