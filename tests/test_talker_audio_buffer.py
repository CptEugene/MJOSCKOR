from client.audio.talker_buffer import TalkerAudioBuffer


def test_talker_audio_buffer_orders_out_of_order_packets() -> None:
    buffer = TalkerAudioBuffer(skip_threshold_packets=2)

    assert buffer.push(2, b"second") == "stored"
    assert buffer.pop_ready() == (None, 0)

    assert buffer.push(1, b"first") == "stored"
    assert buffer.pop_ready() == (b"first", 0)
    assert buffer.pop_ready() == (b"second", 0)


def test_talker_audio_buffer_skips_missing_packet_after_threshold() -> None:
    buffer = TalkerAudioBuffer(skip_threshold_packets=2, max_concealed_packets=0)

    assert buffer.push(10, b"ten") == "stored"
    assert buffer.push(11, b"eleven") == "stored"
    assert buffer.pop_ready() == (b"ten", 0)
    assert buffer.pop_ready() == (b"eleven", 0)

    assert buffer.push(13, b"thirteen") == "stored"
    assert buffer.pop_ready() == (None, 0)

    assert buffer.push(14, b"fourteen") == "stored"
    assert buffer.pop_ready() == (b"thirteen", 1)
    assert buffer.pop_ready() == (b"fourteen", 0)


def test_talker_audio_buffer_inserts_silence_for_small_gap() -> None:
    buffer = TalkerAudioBuffer(skip_threshold_packets=2, max_concealed_packets=2)

    assert buffer.push(10, b"ten") == "stored"
    assert buffer.push(11, b"eleven") == "stored"
    assert buffer.pop_ready() == (b"ten", 0)
    assert buffer.pop_ready() == (b"eleven", 0)

    assert buffer.push(13, b"thirteen") == "stored"
    assert buffer.pop_ready() == (b"\x00" * len(b"thirteen"), 0)
    assert buffer.pop_ready() == (b"thirteen", 0)


def test_talker_audio_buffer_reports_late_drop() -> None:
    buffer = TalkerAudioBuffer(skip_threshold_packets=2)

    assert buffer.push(1, b"one") == "stored"
    assert buffer.push(2, b"two") == "stored"
    assert buffer.pop_ready() == (b"one", 0)
    assert buffer.pop_ready() == (b"two", 0)
    assert buffer.push(1, b"late") == "late_drop"


def test_talker_audio_buffer_reports_stale() -> None:
    buffer = TalkerAudioBuffer()
    buffer.push(1, b"frame")
    assert not buffer.is_stale(0.5, now=buffer._last_packet_at + 0.1)
    assert buffer.is_stale(0.5, now=buffer._last_packet_at + 0.6)


def test_talker_audio_buffer_default_primes_on_first_packet() -> None:
    buffer = TalkerAudioBuffer()

    assert buffer.push(1, b"frame") == "stored"
    assert buffer.pop_ready() == (b"frame", 0)


def test_talker_audio_buffer_adapts_up_on_gap_and_recovers_when_stable() -> None:
    buffer = TalkerAudioBuffer(
        skip_threshold_packets=1,
        max_concealed_packets=0,
        max_adaptive_packets=4,
        stable_packet_window=2,
    )

    assert buffer.target_buffer_packets == 1
    assert buffer.push(1, b"one") == "stored"
    assert buffer.pop_ready() == (b"one", 0)

    assert buffer.push(3, b"three") == "stored"
    assert buffer.pop_ready() == (b"three", 1)
    assert buffer.target_buffer_packets == 2

    assert buffer.push(4, b"four") == "stored"
    assert buffer.push(5, b"five") == "stored"
    assert buffer.pop_ready() == (b"four", 0)
    assert buffer.pop_ready() == (b"five", 0)
    assert buffer.target_buffer_packets == 1
