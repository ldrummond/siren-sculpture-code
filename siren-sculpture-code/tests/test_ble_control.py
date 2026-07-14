from __future__ import annotations

import sys
import time
import types
from datetime import datetime, timezone

import pytest

from siren_app.ble_control import MAX_BLE_JSON_BYTES, SirenBleControlService, _bluetooth_device_name, _command_epoch_seconds, _command_volume, _decode_response, _json_bytes, _last_response_summary, _load_bless_backend, _playback_window_payload, _truncate_utf8, _wifi_network_status, _wifi_power_state


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


def test_oversized_ble_response_returns_valid_compact_json() -> None:
    response = _json_bytes({"message": "x" * 1000})

    assert len(response) <= MAX_BLE_JSON_BYTES
    assert _decode_response(response) == {
        "ok": False,
        "error": "Pi response exceeded the BLE size limit",
        "response_bytes": 1014,
    }


def test_status_response_stays_within_ble_read_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_status",
        lambda: {
            "audio": {
                "state": "playing",
                "file_exists": True,
                "error": "x" * 24,
                "manual_paused": False,
                "control_mode": "sculpture",
                "normal_paused": False,
                "volume_percent": 80,
                "playback_window": {
                    "enabled": True,
                    "start_time": "08:00",
                    "stop_time": "21:00",
                    "active": True,
                },
            },
            "clock": {"system_time": "2026-07-10T11:11:01-06:00", "clock_trusted": True, "clock_ok": True},
            "wittypi": {
                "temperature_c": 24.5,
                "temperature_f": 76.1,
                "rtc_time": "2026-07-10T11:11:01-06:00",
            },
        },
    )

    response = service.status_response()

    assert len(response) <= MAX_BLE_JSON_BYTES
    assert "status" in _decode_response(response)


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


def test_network_status_command_returns_compact_wifi_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    wifi = {"enabled": True, "connected": True, "ssid": "Sculpture Network"}
    monkeypatch.setattr("siren_app.ble_control._wifi_network_status", lambda: wifi)
    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]

    response = service._handle_command({"action": "network_status"})

    assert response == {"ok": True, "wifi": wifi}
    assert len(_json_bytes(response)) <= MAX_BLE_JSON_BYTES


def test_command_epoch_seconds_accepts_browser_epoch_milliseconds() -> None:
    epoch_ms = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc).timestamp() * 1000

    assert _command_epoch_seconds({"epoch_ms": epoch_ms}) == epoch_ms / 1000


def test_command_epoch_seconds_rejects_implausible_time() -> None:
    with pytest.raises(ValueError, match="between 2020 and 2099"):
        _command_epoch_seconds({"epoch_ms": 0})


def test_clock_sync_command_runs_asynchronous_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    called = []

    def fake_sync(config, epoch_seconds, source="ble-client"):
        called.append((config, epoch_seconds, source))
        return {
            "source": source,
            "system_time": "2026-07-14T12:00:00+00:00",
            "rtc_time": "2026-07-14T12:00:00+00:00",
            "drift_seconds": 0,
        }

    monkeypatch.setattr("siren_app.ble_control.set_system_and_rtc_time", fake_sync)
    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]
    epoch_ms = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc).timestamp() * 1000

    response = service._handle_command({"action": "set_device_time", "epoch_ms": epoch_ms})
    assert response["clock_sync"]["state"] == "pending"

    for _ in range(100):
        status = service._handle_command({"action": "clock_sync_status"})
        if status["clock_sync"]["state"] != "pending":
            break
        time.sleep(0.01)

    assert status["ok"] is True
    assert status["clock_sync"]["state"] == "success"
    assert called[0][2] == "ble-client"


def test_wifi_power_state_marks_enabled_radio(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], timeout: float = 3, max_chars: int = 800) -> str:
        if command[:3] == ["nmcli", "radio", "wifi"]:
            return "enabled"
        return ""

    monkeypatch.setattr("siren_app.ble_control._run_command", fake_run)

    assert _wifi_power_state()["powered"] is True


def test_wifi_power_state_honors_disabled_networkmanager_radio(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], timeout: float = 3, max_chars: int = 800) -> str:
        if command[:3] == ["nmcli", "radio", "wifi"]:
            return "disabled"
        return "Soft blocked: no\nHard blocked: no"

    monkeypatch.setattr("siren_app.ble_control._run_command", fake_run)

    assert _wifi_power_state()["powered"] is False


def test_wifi_network_status_reports_active_ssid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("siren_app.ble_control._wifi_power_state", lambda: {"powered": True})
    monkeypatch.setattr(
        "siren_app.ble_control._run_command",
        lambda command, timeout=3, max_chars=800: " :Neighbor Network\n*:Sculpture Network",
    )

    assert _wifi_network_status() == {
        "enabled": True,
        "connected": True,
        "ssid": "Sculpture Network",
    }


def test_wifi_network_status_reports_powered_but_disconnected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("siren_app.ble_control._wifi_power_state", lambda: {"powered": True})
    monkeypatch.setattr("siren_app.ble_control._run_command", lambda command, timeout=3, max_chars=800: " :Neighbor Network")

    assert _wifi_network_status() == {"enabled": True, "connected": False, "ssid": None}



def test_unsupported_audio_alias_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            values = {
                "ble.control.service_uuid": "service",
                "ble.control.command_characteristic_uuid": "command",
                "ble.control.status_characteristic_uuid": "status",
            }
            return values.get(key, default)

    service = SirenBleControlService(FakeConfig())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="unsupported action: stop"):
        service._handle_command({"action": "stop"})


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
