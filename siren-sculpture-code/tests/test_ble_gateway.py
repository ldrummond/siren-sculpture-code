from __future__ import annotations

import json

import pytest

from siren_app.ble_gateway import DeviceBleGateway


class FakeHandler:
    def __init__(self, service_uuid: str, command_uuid: str, status_uuid: str, name: str):
        self.service_uuid = service_uuid
        self.command_uuid = command_uuid
        self.status_uuid = status_uuid
        self.name = name
        self.writes: list[tuple[object, bytearray]] = []

    def read_request(self, _characteristic: object, **_kwargs: object) -> bytearray:
        return bytearray(self.name.encode("utf-8"))

    def write_request(self, characteristic: object, value: bytearray, **_kwargs: object) -> None:
        self.writes.append((characteristic, value))


def make_gateway() -> tuple[DeviceBleGateway, FakeHandler, FakeHandler]:
    provisioning = FakeHandler("shared", "provision-command", "provision-status", "provisioning")
    sculpture = FakeHandler("shared", "sculpture-command", "sculpture-status", "sculpture")
    gateway = DeviceBleGateway(provisioning, sculpture)  # type: ignore[arg-type]
    return gateway, provisioning, sculpture


def test_gateway_routes_reads_to_each_domain() -> None:
    gateway, _provisioning, _sculpture = make_gateway()

    assert gateway.read_request("provision-status") == bytearray(b"provisioning")
    assert gateway.read_request("sculpture-status") == bytearray(b"sculpture")


def test_gateway_routes_writes_to_each_domain() -> None:
    gateway, provisioning, sculpture = make_gateway()

    gateway.write_request("provision-command", bytearray(b"wifi"))
    gateway.write_request("sculpture-command", bytearray(b"play"))

    assert provisioning.writes == [("provision-command", bytearray(b"wifi"))]
    assert sculpture.writes == [("sculpture-command", bytearray(b"play"))]


def test_gateway_rejects_duplicate_characteristic_uuids() -> None:
    provisioning = FakeHandler("shared", "duplicate", "provision-status", "provisioning")
    sculpture = FakeHandler("shared", "duplicate", "sculpture-status", "sculpture")

    with pytest.raises(ValueError, match="must be unique"):
        DeviceBleGateway(provisioning, sculpture)  # type: ignore[arg-type]


def test_gateway_rejects_different_service_uuids() -> None:
    provisioning = FakeHandler("provisioning", "provision-command", "provision-status", "provisioning")
    sculpture = FakeHandler("sculpture", "sculpture-command", "sculpture-status", "sculpture")

    with pytest.raises(ValueError, match="same BLE service UUID"):
        DeviceBleGateway(provisioning, sculpture)  # type: ignore[arg-type]


def test_gateway_returns_json_error_for_unknown_read() -> None:
    gateway, _provisioning, _sculpture = make_gateway()

    assert json.loads(gateway.read_request("unknown")) == {
        "ok": False,
        "error": "unknown characteristic",
    }
