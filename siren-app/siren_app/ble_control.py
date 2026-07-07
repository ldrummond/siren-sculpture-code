from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from siren_app.config import AppConfig, load_config
from siren_app.player import queue_command
from siren_app.status import gather_status


logger = logging.getLogger(__name__)


def _json_bytes(payload: dict[str, Any]) -> bytearray:
    return bytearray(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


class SirenBleControlService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.last_response = _json_bytes({"ok": True, "message": "ready"})
        self.service_uuid = str(config.get("ble.control.service_uuid"))
        self.command_uuid = str(config.get("ble.control.command_characteristic_uuid"))
        self.status_uuid = str(config.get("ble.control.status_characteristic_uuid"))

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
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self.last_response = _json_bytes({"ok": False, "error": str(exc)})

    def _handle_command(self, command: dict[str, Any]) -> dict[str, Any]:
        action = str(command.get("action", "")).strip().lower()
        if action == "status":
            return {"ok": True, "status": self._status()}
        command_aliases = {
            "play": "play",
            "pause": "pause",
            "stop": "stop",
            "restart": "restart",
            "resume": "play",
            "resume_normal": "resume_normal",
            "resume_normal_playback": "resume_normal",
            "normal": "resume_normal",
        }
        if action in command_aliases:
            queued = command_aliases[action]
            queue_command(queued)
            return {"ok": True, "queued": queued}
        raise ValueError(f"unsupported action: {action}")

    def _status(self) -> dict[str, Any]:
        status = gather_status(self.config)
        return {
            "project": status["project"],
            "audio": status["audio"],
            "clock_ok": status["clock"]["clock_ok"],
        }


async def run_server() -> None:
    config = load_config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    if not bool(config.get("ble.control.enabled", True)):
        logger.info("Siren BLE control service disabled")
        return

    try:
        from bless import BlessServer
        from bless.backends.characteristic import GATTCharacteristicProperties
        from bless.backends.service import GATTAttributePermissions
    except ImportError as exc:
        raise RuntimeError("bless is required for BLE peripheral services") from exc

    service = SirenBleControlService(config)
    server = BlessServer(name=str(config.get("ble.control.device_name", "SculptureControl")))
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
    logger.info("Siren BLE control GATT service started")
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
    parser = argparse.ArgumentParser(description="Siren BLE control service")
    parser.parse_args()
    asyncio.run(run_server())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
