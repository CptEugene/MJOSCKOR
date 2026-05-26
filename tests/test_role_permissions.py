from client.services.audio_runtime import AudioRuntime
from server.app.server_core import MaydayServerCore
from server.network.session_store import ClientSession
from shared.constants.paths import runtime_paths
from shared.models.fleet_tree import ROLE_PERMISSIONS, RoleName


def test_pilot_cannot_transmit_hq() -> None:
    permission = ROLE_PERMISSIONS[RoleName.PILOT].channel("ch2")
    assert permission.tx is False
    assert permission.rx is False


def test_audio_runtime_blocks_disallowed_rx_channel() -> None:
    runtime = AudioRuntime()
    runtime.set_slot_joined(True)
    runtime.set_selected_role("Soldier")
    assert runtime._can_rx("squad") is True
    assert runtime._can_rx("hq") is False
    assert runtime._can_rx("atc") is True
    assert runtime._can_rx("general") is True


def test_audio_runtime_blocks_all_rx_until_slot_joined() -> None:
    runtime = AudioRuntime()
    runtime.set_selected_role("Commander")
    assert runtime._can_rx("squad") is False
    assert runtime._can_rx("general") is False


def test_server_blocks_role_disabled_receive_even_when_channel_numbers_match() -> None:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    source = ClientSession(1, None, None)
    source.slot_id = "source-slot"
    source.node_id = "source-node"
    source.role = RoleName.COMMANDER.value
    source.channel_tag = "hq"
    source.active_channel_number = 1

    dest = ClientSession(2, None, None)
    dest.slot_id = "dest-slot"
    dest.node_id = "dest-node"
    dest.role = RoleName.SOLDIER.value
    dest.channel_assignments = [1, 1, 1, 1]

    assert server.relay_block_reason(source, dest) == "dest_role_channel_blocked"


def test_server_blocks_role_disabled_transmit_even_when_channel_number_is_set() -> None:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    source = ClientSession(1, None, None)
    source.slot_id = "source-slot"
    source.node_id = "source-node"
    source.role = RoleName.PILOT.value
    source.channel_tag = "hq"
    source.active_channel_number = 1

    dest = ClientSession(2, None, None)
    dest.slot_id = "dest-slot"
    dest.node_id = "dest-node"
    dest.role = RoleName.COMMANDER.value
    dest.channel_assignments = [1, 1, 1, 1]

    assert server.relay_block_reason(source, dest) == "source_role_channel_blocked"
