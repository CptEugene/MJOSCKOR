from client.services.admin_chat_commands import parse_admin_chat_command


def test_parse_play_command() -> None:
    command = parse_admin_chat_command("/play briefing_theme.mp3")
    assert command is not None
    assert command.kind == "soundtrack_play"
    assert command.track_id == "briefing_theme.mp3"


def test_parse_stop_command() -> None:
    command = parse_admin_chat_command("/stop")
    assert command is not None
    assert command.kind == "soundtrack_stop"


def test_parse_video_play_command() -> None:
    command = parse_admin_chat_command("/video mission_intro.mp4")
    assert command is not None
    assert command.kind == "video_overlay_play"
    assert command.video_id == "mission_intro.mp4"


def test_parse_video_stop_command() -> None:
    command = parse_admin_chat_command("/stopvideo")
    assert command is not None
    assert command.kind == "video_overlay_stop"


def test_parse_notice_update_command() -> None:
    command = parse_admin_chat_command("/notice Server restart at 2200")
    assert command is not None
    assert command.kind == "notice_update"
    assert command.notice_text == "Server restart at 2200"


def test_parse_mission_overlay_command() -> None:
    command = parse_admin_chat_command("/텍스트 Proceed to rally point")
    assert command is not None
    assert command.kind == "mission_overlay"
    assert command.text == "Proceed to rally point"
    assert command.color == "white"
    assert command.font_scale == 1.0


def test_parse_green_mission_overlay_command() -> None:
    command = parse_admin_chat_command("/텍스트g Emergency extraction now")
    assert command is not None
    assert command.kind == "mission_overlay"
    assert command.text == "Emergency extraction now"
    assert command.color == "green"
    assert command.font_scale == 2.0


def test_parse_unknown_command_returns_none() -> None:
    assert parse_admin_chat_command("/hello fleet") is None
    assert parse_admin_chat_command("regular chat") is None


def test_admin_command_aliases_are_disabled() -> None:
    assert parse_admin_chat_command("/stopmusic") is None
    assert parse_admin_chat_command("/musicstop") is None
    assert parse_admin_chat_command("/movie mission_intro.mp4") is None
    assert parse_admin_chat_command("/videostop") is None
    assert parse_admin_chat_command("/stopmovie") is None
    assert parse_admin_chat_command("/mission Proceed to rally point") is None
    assert parse_admin_chat_command("/center Proceed to rally point") is None
    assert parse_admin_chat_command("/announce Proceed to rally point") is None
    assert parse_admin_chat_command("/택스트g Hold position") is None
