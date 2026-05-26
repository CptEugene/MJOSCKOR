from shared.constants.channels import DEFAULT_CHANNEL_ASSIGNMENTS, normalize_channel_assignments


def test_default_channel_assignments_start_unconfigured() -> None:
    assert DEFAULT_CHANNEL_ASSIGNMENTS == [0, 0, 0, 0]
    assert normalize_channel_assignments(None) == [0, 0, 0, 0]


def test_channel_assignment_zero_is_valid_until_user_configures_channel() -> None:
    assert normalize_channel_assignments([0, 0, 0, 0]) == [0, 0, 0, 0]
    assert normalize_channel_assignments([999, 999, 999, 999]) == [10, 5, 5, 1]
