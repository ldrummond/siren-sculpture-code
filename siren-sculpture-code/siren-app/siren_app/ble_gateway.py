from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from provisioning_core.ble_service import ProvisioningBleService
from provisioning_core.config import load_config as load_provisioning_config

from siren_app.ble_control import (
    BLE_STARTUP_ATTEMPTS,
    BLE_STARTUP_RETRY_SECONDS,
    MAX_ADVERTISEMENT_NAME_BYTES,
    SirenBleControlService,
    _bluetooth_device_name,
    _disable_bluez_experimental_advertisement_properties,
    _load_bless_backend,
    _wifi_power_state,
)
from siren_app.config import load_config as load_sculpture_config
from siren_app.logging_config import setup_logging


logger = logging.getLogger(__name__)


def _json_bytes(payload: dict[str, Any]) -> bytearray:
    return bytearray(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _characteristic_uuid(characteristic: Any) -> str:
    return str(getattr(characteristic, "uuid", characteristic)).lower()


class DeviceBleGateway:
    """Routes one GATT server to the provisioning and sculpture handlers."""

    def __init__(
        self,
        provisioning: ProvisioningBleService,
        sculpture: SirenBleControlService,
    ) -> None:
        self.provisioning = provisioning
        self.sculpture = sculpture
        self.service_uuid = sculpture.service_uuid
        if provisioning.service_uuid.lower() != self.service_uuid.lower():
            raise ValueError("Provisioning and sculpture must use the same BLE service UUID")

        characteristic_uuids = (
            provisioning.command_uuid,
            provisioning.status_uuid,
            sculpture.command_uuid,
            sculpture.status_uuid,
        )
        normalized = [uuid.lower() for uuid in characteristic_uuids]
        if len(set(normalized)) != len(normalized):
            raise ValueError("BLE gateway characteristic UUIDs must be unique")

        self._provisioning_uuids = {
            provisioning.command_uuid.lower(),
            provisioning.status_uuid.lower(),
        }
        self._sculpture_uuids = {
            sculpture.command_uuid.lower(),
            sculpture.status_uuid.lower(),
        }

    def read_request(self, characteristic: Any, **kwargs: Any) -> bytearray:
        uuid = _characteristic_uuid(characteristic)
        if uuid in self._provisioning_uuids:
            return self.provisioning.read_request(characteristic, **kwargs)
        if uuid in self._sculpture_uuids:
            return self.sculpture.read_request(characteristic, **kwargs)
        return _json_bytes({"ok": False, "error": "unknown characteristic"})

    def write_request(self, characteristic: Any, value: bytearray, **kwargs: Any) -> None:
        uuid = _characteristic_uuid(characteristic)
        if uuid in self._provisioning_uuids:
            self.provisioning.write_request(characteristic, value, **kwargs)
            return
        if uuid in self._sculpture_uuids:
            self.sculpture.write_request(characteristic, value, **kwargs)
            return
        logger.warning("Ignoring write to unknown BLE characteristic %s", uuid)


async def run_server() -> None:
    sculpture_config = load_sculpture_config()
    provisioning_config = load_provisioning_config()
    setup_logging(sculpture_config)

    if not bool(sculpture_config.get("ble.control.enabled", True)):
        logger.info("Device BLE gateway disabled by sculpture configuration")
        return
    if not bool(provisioning_config.get("ble.provisioning.enabled", True)):
        logger.info("Device BLE gateway disabled by provisioning configuration")
        return

    wifi_state = _wifi_power_state()
    if wifi_state["powered"]:
        logger.warning(
            "Wi-Fi appears to be enabled while BLE is running. Disable it after provisioning to reduce power use. state=%s",
            wifi_state,
        )

    BlessServer, properties, permissions = _load_bless_backend()
    _disable_bluez_experimental_advertisement_properties()

    provisioning = ProvisioningBleService(provisioning_config)
    sculpture = SirenBleControlService(sculpture_config)
    sculpture.refresh_status_cache()
    gateway = DeviceBleGateway(provisioning, sculpture)
    device_name = _bluetooth_device_name(sculpture_config)
    adapter = str(sculpture_config.get("ble.control.adapter", "hci0")).strip() or "hci0"

    logger.info(
        "Starting shared BLE gateway adapter=%s name=%s service_uuid=%s",
        adapter,
        device_name,
        gateway.service_uuid,
    )

    server = None
    for attempt in range(1, BLE_STARTUP_ATTEMPTS + 1):
        try:
            server = BlessServer(name=device_name, adapter=adapter)
            server.read_request_func = gateway.read_request
            server.write_request_func = gateway.write_request
            await server.add_new_service(gateway.service_uuid)
            await server.add_new_characteristic(
                gateway.service_uuid,
                provisioning.command_uuid,
                properties.write,
                bytearray(),
                permissions.writeable,
            )
            await server.add_new_characteristic(
                gateway.service_uuid,
                provisioning.status_uuid,
                properties.read,
                provisioning.last_response,
                permissions.readable,
            )
            await server.add_new_characteristic(
                gateway.service_uuid,
                sculpture.command_uuid,
                properties.write | properties.read,
                sculpture.last_response,
                permissions.writeable | permissions.readable,
            )
            await server.add_new_characteristic(
                gateway.service_uuid,
                sculpture.status_uuid,
                properties.read,
                sculpture.status_response(),
                permissions.readable,
            )
            await server.start()
            sculpture.start_status_refresh()
            break
        except Exception as exc:
            if attempt >= BLE_STARTUP_ATTEMPTS:
                raise RuntimeError(
                    f"BlueZ failed to start the shared BLE gateway on adapter {adapter}. Confirm bluetooth.service "
                    "is running, the adapter exists, and no other process is advertising. The device name "
                    f"must be at most {MAX_ADVERTISEMENT_NAME_BYTES} UTF-8 bytes."
                ) from exc
            logger.warning(
                "BLE gateway startup attempt %s/%s failed on adapter %s: %s",
                attempt,
                BLE_STARTUP_ATTEMPTS,
                adapter,
                exc,
            )
            await asyncio.sleep(BLE_STARTUP_RETRY_SECONDS)

    logger.info("Shared provisioning and sculpture BLE GATT service started")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        sculpture.stop_status_refresh()
        if server is not None:
            await server.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Shared provisioning and sculpture BLE gateway")
    parser.parse_args()
    asyncio.run(run_server())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
