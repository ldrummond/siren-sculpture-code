from __future__ import annotations

import sys
import types

import pytest

from siren_app.ble_control import SirenBleControlService, _bluetooth_device_name, _command_volume, _decode_response, _gather_diagnostics, _last_response_summary, _load_bless_backend, _playback_window_payload, _truncate_utf8, _wifi_power_state


def install_fake_bless(monkeypatch: pytest.MonkeyPatch, permissions_module: str) -> tuple[type, type, type]:
    bless = types.ModuleType("bless")
    characteristic = types.ModuleType("bless.backends.characteristic")
    service = types.ModuleType("bless.backends.service")

    class FakeBlessServer:
        pass

    class FakeProperties:
        read = object()
        write = object()

    class FakePermissions:
        readable = object()
        writeable = object()

    bless.BlessServer = FakeBlessServer
    characteristic.GATTCharacteristicProperties = FakeProperties
    if permissions_module == "characteristic":
        characteristic.GATTAttributePermissions = FakePermissions
    elif permissions_module == "service":
        service.GATTAttributePermissions = FakePermissions
    else:
        raise ValueError(permissions_module)

    monkeypatch.setitem(sys.modules, "bless", bless)
    monkeypatch.setitem(sys.modules, "bless.backends", types.ModuleType("bless.backends"))
    monkeypatch.setitem(sys.modules, "bless.backends.characteristic", characteristic)
    monkeypatch.setitem(sys.modules, "bless.backends.service", service)
    return FakeBlessServer, FakeProperties, FakePermissions


def clear_fake_bless(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "bless",
        "bless.backends",
        "bless.backends.characteristic",
        "bless.backends.service",
    ]:
        monkeypatch.delitem(sys.modules, name, raising=False)


def test_load_bless_backend_supports_permissions_from_characteristic(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_fake_bless(monkeypatch)
    expected = install_fake_bless(monkeypatch, "characteristic")

    assert _load_bless_backend() == expected


def test_load_bless_backend_supports_permissions_from_service(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_fake_bless(monkeypatch)
    expected = install_fake_bless(monkeypatch, "service")

    assert _load_bless_backend() == expected


def test_decode_response_handles_invalid_json() -> None:
    assert _decode_response(bytearray(b"")) == {"ok": False, "error": "invalid previous response"}


def test_status_response_returns_error_json_when_status_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_status", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert _decode_response(service.status_response()) == {"ok": False, "error": "status unavailable: boom"}


def test_last_response_summary_omits_nested_status() -> None:
    value = bytearray(b'{"ok":true,"status":{"audio":{"state":"playing"}}}')

    assert _last_response_summary(value) == {"ok": True, "message": "status returned"}


def test_bluetooth_device_name_uses_hostname_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            return "device" if key == "ble.control.device_name" else default

    monkeypatch.setattr("siren_app.ble_control.socket.gethostname", lambda: "siren2.local")

    assert _bluetooth_device_name(FakeConfig()) == "siren2"  # type: ignore[arg-type]


def test_bluetooth_device_name_allows_explicit_override() -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            return "FieldSiren" if key == "ble.control.device_name" else default

    assert _bluetooth_device_name(FakeConfig()) == "FieldSir"  # type: ignore[arg-type]



def test_reboot_command_schedules_reboot(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    called = []
    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]
    monkeypatch.setattr("siren_app.ble_control._schedule_reboot", lambda: called.append(True))

    assert service._handle_command({"action": "reboot"}) == {
        "ok": True,
        "queued": "reboot",
        "message": "device reboot requested",
    }
    assert called == [True]



def test_truncate_utf8_preserves_character_boundaries() -> None:
    assert _truncate_utf8("siren-two", 8) == "siren-tw"
    assert _truncate_utf8("abcéfg", 5) == "abcé"


def test_diagnostics_command_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    monkeypatch.setattr("siren_app.ble_control._gather_diagnostics", lambda: {"services": {}})
    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]

    assert service._handle_command({"action": "diagnostics"}) == {"ok": True, "diagnostics": {"services": {}}}


def test_wifi_power_state_marks_enabled_radio(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], timeout: float = 3, max_chars: int = 800) -> str:
        if command[:3] == ["nmcli", "radio", "wifi"]:
            return "enabled"
        return ""

    monkeypatch.setattr("siren_app.ble_control._run_command", fake_run)

    assert _wifi_power_state()["powered"] is True



def test_stop_maps_to_pause_sculpture(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    queued = []
    monkeypatch.setattr("siren_app.ble_control.queue_command", lambda command: queued.append(command))
    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]

    assert service._handle_command({"action": "stop"}) == {"ok": True, "queued": "pause_sculpture"}
    assert queued == ["pause_sculpture"]


def test_mode_commands_queue_explicit_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    queued = []
    monkeypatch.setattr("siren_app.ble_control.queue_command", lambda command: queued.append(command))
    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]

    assert service._handle_command({"action": "testing_mode"}) == {"ok": True, "queued": "testing_mode"}
    assert service._handle_command({"action": "sculpture_mode"}) == {"ok": True, "queued": "sculpture_mode"}
    assert service._handle_command({"action": "play_sculpture"}) == {"ok": True, "queued": "play_sculpture"}
    assert service._handle_command({"action": "test_restart"}) == {"ok": True, "queued": "test_restart"}
    assert queued == ["testing_mode", "sculpture_mode", "play_sculpture", "test_restart"]



def test_set_playback_window_queues_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    queued = []
    monkeypatch.setattr("siren_app.ble_control.queue_command", lambda command: queued.append(command))
    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]

    response = service._handle_command({"action": "set_playback_window", "start_time": "8:00", "stop_time": "21:00"})

    assert response == {
        "ok": True,
        "queued": "set_playback_window",
        "playback_window": {"enabled": True, "start_time": "08:00", "stop_time": "21:00"},
    }
    assert queued == ['playback_window:{"enabled":true,"start_time":"08:00","stop_time":"21:00"}']


def test_clear_playback_window_queues_disabled_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    queued = []
    monkeypatch.setattr("siren_app.ble_control.queue_command", lambda command: queued.append(command))
    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]

    assert service._handle_command({"action": "clear_playback_window"}) == {
        "ok": True,
        "queued": "clear_playback_window",
        "playback_window": {"enabled": False},
    }
    assert queued == ['playback_window:{"enabled":false}']


def test_playback_window_payload_rejects_invalid_time() -> None:
    with pytest.raises(ValueError, match="start_time must use HH:MM"):
        _playback_window_payload({"start_time": "25:00", "stop_time": "21:00"})


def test_set_volume_queues_volume_command(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    queued = []
    monkeypatch.setattr("siren_app.ble_control.queue_command", lambda command: queued.append(command))
    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]

    assert service._handle_command({"action": "set_volume", "volume_percent": 42}) == {
        "ok": True,
        "queued": "set_volume",
        "volume_percent": 42,
    }
    assert queued == ["volume:42"]


def test_command_volume_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        _command_volume({"volume_percent": 101})


def test_last_response_summary_compacts_diagnostics() -> None:
    value = bytearray(b'{"ok":true,"diagnostics":{"logs":{"audio":"very long"}}}')

    assert _last_response_summary(value) == {"ok": True, "message": "diagnostics returned"}
