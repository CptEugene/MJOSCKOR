from client.input.bindings import binding_specificity, normalize_binding, should_replace_pending_binding
from client.input.input_monitor import InputMonitor
from client.ui.binding_capture_dialog import BindingCaptureDialog


def test_normalize_binding_orders_modifiers_first() -> None:
    assert normalize_binding("mouse4+ctrl+1") == "CTRL+MOUSE4+1"


def test_binding_specificity_prefers_more_specific_combo() -> None:
    assert binding_specificity("CTRL+CAPSLOCK") > binding_specificity("CAPSLOCK")


def test_pending_binding_prefers_more_specific_capture() -> None:
    assert should_replace_pending_binding("MOUSE4", "CTRL+MOUSE4+1") is True
    assert should_replace_pending_binding("CTRL+MOUSE4+1", "MOUSE4") is False


def test_normalize_joystick_binding_keeps_token() -> None:
    assert normalize_binding("joy1_btn1+ctrl") == "CTRL+JOY1_BTN1"
    assert normalize_binding("joy1_hat1_up") == "JOY1_HAT1_UP"
    assert normalize_binding("joy2_axis3_pos") == "JOY2_AXIS3_POS"


def test_mouse_buttons_register_as_binding_tokens() -> None:
    monitor = InputMonitor()

    monitor._on_mouse_click(0, 0, "Button.x1", True)
    assert monitor.is_binding_pressed("MOUSE4")

    monitor._on_mouse_click(0, 0, "Button.x1", False)
    assert not monitor.is_binding_pressed("MOUSE4")


def test_joystick_buttons_register_as_binding_tokens() -> None:
    monitor = InputMonitor()

    monitor._replace_joystick_tokens({"JOY1_BTN1", "JOY1_HAT1_UP", "JOY2_BTN7", "JOY2_AXIS3_POS"})
    assert monitor.is_binding_pressed("JOY1_BTN1")
    assert monitor.is_binding_pressed("JOY1_HAT1_UP")
    assert monitor.is_binding_pressed("JOY2_BTN7")
    assert monitor.is_binding_pressed("JOY2_AXIS3_POS")

    monitor._replace_joystick_tokens({"JOY2_BTN7"})
    assert not monitor.is_binding_pressed("JOY1_BTN1")
    assert not monitor.is_binding_pressed("JOY1_HAT1_UP")
    assert not monitor.is_binding_pressed("JOY2_AXIS3_POS")
    assert monitor.is_binding_pressed("JOY2_BTN7")


def test_capture_prefers_new_joystick_button_over_stale_axes() -> None:
    selected = BindingCaptureDialog._choose_primary_token(
        ["JOY2_AXIS3_POS", "JOY3_AXIS4_POS", "JOY2_BTN4"],
        {"JOY2_BTN4"},
    )

    assert selected == "JOY2_BTN4"


def test_capture_keeps_single_primary_when_axes_are_also_active() -> None:
    current = BindingCaptureDialog._binding_from_tokens(
        BindingCaptureDialog,
        {"SHIFT", "JOY2_AXIS3_POS", "JOY3_AXIS4_POS", "S"},
        {"S"},
    )

    assert current == "SHIFT+S"
