from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from provisioning_core.config import ProvisioningConfig, load_config
from provisioning_core.network import NetworkCommandError, connect_wifi, get_connectivity, provisioning_status, scan_wifi


logger = logging.getLogger(__name__)


def _json_bytes(payload: dict[str, Any]) -> bytearray:
    return bytearray(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


class ProvisioningBleService:
    def __init__(self, config: ProvisioningConfig):
        self.config = config
        self.last_response = _json_bytes({"ok": True, "message": "ready"})
        self.service_uuid = str(config.get("ble.provisioning.service_uuid"))
        self.command_uuid = str(config.get("ble.provisioning.command_characteristic_uuid"))
        self.status_uuid = str(config.get("ble.provisioning.status_characteristic_uuid"))

    def read_request(self, characteristic: Any, **_kwargs: Any) -> bytearray:
        uuid = _characteristic_uuid(characteristic)
        if uuid == self.status_uuid.lower():
            return _json_bytes({"status": self._status(), "last_response": _decode_response(self.last_response)})
        return self.last_response

    def write_request(self, characteristic: Any, value: bytearray, **_kwargs: Any) -> None:
        uuid = _characteristic_uuid(characteristic)
        if uuid != self.command_uuid.lower():
            self.last_response = _json_bytes({"ok": False, "error": "unknown characteristic"})
            return
        try:
            command = json.loads(bytes(value).decode("utf-8"))
            self.last_response = _json_bytes(self._handle_command(command))
        except (UnicodeDecodeError, json.JSONDecodeError, NetworkCommandError, ValueError) as exc:
            self.last_response = _json_bytes({"ok": False, "error": str(exc)})

    def _handle_command(self, command: dict[str, Any]) -> dict[str, Any]:
        action = command.get("action")
        if action == "status":
            return {"ok": True, "status": self._status()}
        if action == "scan_wifi":
            return {"ok": True, "networks": scan_wifi(self.config)}
        if action == "update_wifi_credentials":
            ssid = str(command.get("ssid", "")).strip()
            password = str(command.get("password", ""))
            hidden = bool(command.get("hidden", False))
            self._save_pending_wifi(ssid, password, hidden)
            return {"ok": True, "message": "Wi-Fi settings saved; send try_connect_wifi to connect"}
        if action == "try_connect_wifi":
            ssid, password, hidden = self._load_pending_wifi()
            connect_wifi(self.config, ssid, password, hidden)
            return {"ok": True, "message": "Wi-Fi connection requested", "connectivity": get_connectivity()}
        if action == "connect_wifi":
            ssid = str(command.get("ssid", "")).strip()
            password = str(command.get("password", ""))
            hidden = bool(command.get("hidden", False))
            connect_wifi(self.config, ssid, password, hidden)
            return {"ok": True, "message": "Wi-Fi connection requested", "connectivity": get_connectivity()}
        raise ValueError(f"unsupported action: {action}")

    def _status(self) -> dict[str, Any]:
        status = provisioning_status(self.config)
        return {
            "connectivity": status["connectivity"],
            "interface": status["interface"],
            "active_connections": status["active_connections"],
            "pending_wifi": self._pending_wifi_exists(),
        }

    def _pending_wifi_path(self) -> Path:
        state_dir = Path(str(self.config.get("provisioning.state_dir", "/run/sculpture-provisioning")))
        return state_dir / "pending-wifi.json"

    def _save_pending_wifi(self, ssid: str, password: str, hidden: bool) -> None:
        if not ssid:
            raise ValueError("ssid is required")
        path = self._pending_wifi_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"ssid": ssid, "password": password, "hidden": hidden}),
            encoding="utf-8",
        )
        path.chmod(0o600)

    def _load_pending_wifi(self) -> tuple[str, str, bool]:
        path = self._pending_wifi_path()
        if not path.exists():
            raise ValueError("no pending Wi-Fi settings saved")
        data = json.loads(path.read_text(encoding="utf-8"))
        ssid = str(data.get("ssid", "")).strip()
        if not ssid:
            raise ValueError("pending Wi-Fi settings are missing ssid")
        return ssid, str(data.get("password", "")), bool(data.get("hidden", False))

    def _pending_wifi_exists(self) -> bool:
        return self._pending_wifi_path().exists()


async def run_server() -> None:
    config = load_config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    if not bool(config.get("ble.provisioning.enabled", True)):
        logger.info("Provisioning BLE service disabled")
        return

    try:
        from bless import BlessServer
        from bless.backends.characteristic import GATTCharacteristicProperties
        from bless.backends.service import GATTAttributePermissions
    except ImportError as exc:
        raise RuntimeError("bless is required for BLE peripheral services") from exc

    service = ProvisioningBleService(config)
    server = BlessServer(name=str(config.get("ble.provisioning.device_name", "SculptureProvisioning")))
    server.read_request_func = service.read_request
    server.write_request_func = service.write_request
    await server.add_new_service(service.service_uuid)
    await server.add_new_characteristic(
        service.service_uuid,
        service.command_uuid,
        GATTCharacteristicProperties.write,
        bytearray(),
        GATTAttributePermissions.writeable,
    )
    await server.add_new_characteristic(
        service.service_uuid,
        service.status_uuid,
        GATTCharacteristicProperties.read,
        service.last_response,
        GATTAttributePermissions.readable,
    )
    await server.start()
    logger.info("Provisioning BLE GATT service started")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await server.stop()


def _characteristic_uuid(characteristic: Any) -> str:
    return str(getattr(characteristic, "uuid", characteristic)).lower()


def _decode_response(value: bytearray) -> dict[str, Any]:
    try:
        decoded = json.loads(bytes(value).decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {"value": decoded}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "error": "invalid previous response"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Provisioning BLE GATT service")
    parser.parse_args()
    asyncio.run(run_server())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
