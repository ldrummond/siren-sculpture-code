from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from provisioning_core.ble_service import (
    MAX_BLE_JSON_BYTES,
    ProvisioningBleService,
)
from provisioning_core.config import ProvisioningConfig


def make_config(tmp_path: Path) -> ProvisioningConfig:
    return ProvisioningConfig(
        data={
            "provisioning": {"enabled": True, "state_dir": str(tmp_path)},
            "network": {"interface": "wlan0"},
            "wifi": {"connection_name": "provisioned-wifi"},
            "ble": {
                "provisioning": {
                    "enabled": True,
                    "adapter": "hci0",
                    "device_name": "PiSetup",
                    "service_uuid": "9f0d0101-7b6d-4d2c-9f4f-6f70726f7601",
                    "command_characteristic_uuid": "9f0d0002-7b6d-4d2c-9f4f-6f70726f7601",
                    "status_characteristic_uuid": "9f0d0003-7b6d-4d2c-9f4f-6f70726f7601",
                }
            },
        },
        path=tmp_path / "provisioning.yaml",
    )


def decode(value: bytearray) -> dict[str, object]:
    decoded = json.loads(bytes(value).decode("utf-8"))
    assert isinstance(decoded, dict)
    return decoded


def test_update_wifi_credentials_saves_pending_file(tmp_path: Path) -> None:
    service = ProvisioningBleService(make_config(tmp_path))

    service.write_request(
        service.command_uuid,
        bytearray(json.dumps({"action": "update_wifi_credentials", "ssid": "Lab", "password": "secret"}), "utf-8"),
    )

    assert decode(service.last_response)["ok"] is True
    assert json.loads((tmp_path / "pending-wifi.json").read_text(encoding="utf-8"))["ssid"] == "Lab"


def test_non_object_command_returns_clean_error(tmp_path: Path) -> None:
    service = ProvisioningBleService(make_config(tmp_path))

    service.write_request(service.command_uuid, bytearray(b'["status"]'))

    assert decode(service.last_response) == {"ok": False, "error": "command must be a JSON object"}


def test_try_connect_wifi_runs_in_background(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProvisioningBleService(make_config(tmp_path))
    service.write_request(
        service.command_uuid,
        bytearray(json.dumps({"action": "update_wifi_credentials", "ssid": "Lab", "password": "secret"}), "utf-8"),
    )

    monkeypatch.setattr("provisioning_core.ble_service.connect_wifi", lambda *_args: True)
    monkeypatch.setattr("provisioning_core.ble_service.get_connectivity", lambda: "full")

    service.write_request(service.command_uuid, bytearray(json.dumps({"action": "try_connect_wifi"}), "utf-8"))

    assert decode(service.last_response) == {
        "ok": True,
        "state": "connecting",
        "ssid": "Lab",
        "message": "Wi-Fi connection started",
    }

    assert service._connection_thread is not None
    service._connection_thread.join(timeout=2)

    assert decode(service.last_response) == {
        "ok": True,
        "state": "connected",
        "ssid": "Lab",
        "message": "Wi-Fi connection completed",
        "connectivity": "full",
    }


def test_try_connect_wifi_reports_busy_while_background_job_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProvisioningBleService(make_config(tmp_path))
    service.write_request(
        service.command_uuid,
        bytearray(json.dumps({"action": "update_wifi_credentials", "ssid": "Lab"}), "utf-8"),
    )

    def slow_connect(*_args: object) -> bool:
        time.sleep(0.2)
        return True

    monkeypatch.setattr("provisioning_core.ble_service.connect_wifi", slow_connect)
    monkeypatch.setattr("provisioning_core.ble_service.get_connectivity", lambda: "full")

    service.write_request(service.command_uuid, bytearray(json.dumps({"action": "try_connect_wifi"}), "utf-8"))
    service.write_request(service.command_uuid, bytearray(json.dumps({"action": "try_connect_wifi"}), "utf-8"))

    assert decode(service.last_response) == {
        "ok": False,
        "state": "busy",
        "error": "Wi-Fi connection attempt already in progress",
    }

    assert service._connection_thread is not None
    service._connection_thread.join(timeout=2)


def test_connect_saved_wifi_runs_in_background(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProvisioningBleService(make_config(tmp_path))

    def slow_connect(*_args: object) -> bool:
        time.sleep(0.2)
        return True

    monkeypatch.setattr("provisioning_core.ble_service.connect_saved_wifi", slow_connect)
    monkeypatch.setattr("provisioning_core.ble_service.get_connectivity", lambda: "full")

    service.write_request(
        service.command_uuid,
        bytearray(json.dumps({"action": "connect_saved_wifi", "ssid": "Lab"}), "utf-8"),
    )

    assert decode(service.last_response) == {
        "ok": True,
        "state": "connecting",
        "ssid": "Lab",
        "message": "Wi-Fi connection started",
    }

    assert service._connection_thread is not None
    service._connection_thread.join(timeout=2)

    assert decode(service.last_response) == {
        "ok": True,
        "state": "connected",
        "ssid": "Lab",
        "message": "Wi-Fi connection completed",
        "connectivity": "full",
    }


def test_status_characteristic_reads_last_response_directly(tmp_path: Path) -> None:
    service = ProvisioningBleService(make_config(tmp_path))

    service.write_request(
        service.command_uuid,
        bytearray(json.dumps({"action": "update_wifi_credentials", "ssid": "Lab"}), "utf-8"),
    )

    assert decode(service.read_request(service.status_uuid)) == decode(service.last_response)


def test_scan_wifi_response_is_paged_under_ble_read_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    networks = [
        {"ssid": f"Studio Network {index:02d}", "signal": "88", "security": "WPA2 WPA3"}
        for index in range(20)
    ]
    service = ProvisioningBleService(make_config(tmp_path))
    monkeypatch.setattr("provisioning_core.ble_service.scan_wifi", lambda _config: networks)

    service.write_request(service.command_uuid, bytearray(json.dumps({"action": "scan_wifi"}), "utf-8"))
    first_page = decode(service.last_response)

    assert first_page["ok"] is True
    assert first_page["next_offset"] is not None
    assert len(service.last_response) <= MAX_BLE_JSON_BYTES

    service.write_request(
        service.command_uuid,
        bytearray(json.dumps({"action": "scan_wifi_page", "offset": first_page["next_offset"]}), "utf-8"),
    )
    second_page = decode(service.last_response)

    assert second_page["ok"] is True
    assert second_page["offset"] == first_page["next_offset"]
    assert len(service.last_response) <= MAX_BLE_JSON_BYTES
