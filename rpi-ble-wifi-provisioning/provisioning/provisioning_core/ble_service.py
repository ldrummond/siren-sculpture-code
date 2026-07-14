from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from provisioning_core.config import ProvisioningConfig
from provisioning_core.network import (
    NetworkCommandError,
    connect_saved_wifi,
    connect_wifi,
    get_connectivity,
    provisioning_status,
    scan_wifi,
)


logger = logging.getLogger(__name__)
MAX_BLE_JSON_BYTES = 480


def _json_bytes(payload: dict[str, Any]) -> bytearray:
    return bytearray(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


class ProvisioningBleService:
    def __init__(self, config: ProvisioningConfig):
        self.config = config
        self.last_response = _json_bytes({"ok": True, "message": "ready"})
        self.scan_results: list[dict[str, Any]] = []
        self._response_lock = threading.Lock()
        self._connection_thread: threading.Thread | None = None
        self._deferred_thread_start: threading.Thread | None = None
        self.service_uuid = str(config.get("ble.provisioning.service_uuid"))
        self.command_uuid = str(config.get("ble.provisioning.command_characteristic_uuid"))
        self.status_uuid = str(config.get("ble.provisioning.status_characteristic_uuid"))

    def read_request(self, characteristic: Any, **_kwargs: Any) -> bytearray:
        return self._last_response()

    def write_request(self, characteristic: Any, value: bytearray, **_kwargs: Any) -> None:
        uuid = _characteristic_uuid(characteristic)
        if uuid != self.command_uuid.lower():
            self._set_response({"ok": False, "error": "unknown characteristic"})
            return
        try:
            command = json.loads(bytes(value).decode("utf-8"))
            if not isinstance(command, dict):
                raise ValueError("command must be a JSON object")
            self._set_response(self._handle_command(command))
            self._start_deferred_thread()
        except (UnicodeDecodeError, json.JSONDecodeError, NetworkCommandError, ValueError) as exc:
            self._set_response({"ok": False, "error": str(exc)})

    def _handle_command(self, command: dict[str, Any]) -> dict[str, Any]:
        action = command.get("action")
        if action == "status":
            return {"ok": True, "status": self._status()}
        if action == "scan_wifi":
            self.scan_results = scan_wifi(self.config)
            return _scan_page(self.scan_results, _command_offset(command))
        if action == "scan_wifi_page":
            if not self.scan_results:
                self.scan_results = scan_wifi(self.config)
            return _scan_page(self.scan_results, _command_offset(command))
        if action == "update_wifi_credentials":
            ssid = str(command.get("ssid", "")).strip()
            password = str(command.get("password", ""))
            hidden = bool(command.get("hidden", False))
            self._save_pending_wifi(ssid, password, hidden)
            return {"ok": True, "message": "Wi-Fi settings saved; send try_connect_wifi to connect"}
        if action == "try_connect_wifi":
            ssid, password, hidden = self._load_pending_wifi()
            return self._start_connect_wifi(ssid, password, hidden, clear_pending_on_success=True)
        if action == "connect_wifi":
            ssid = str(command.get("ssid", "")).strip()
            password = str(command.get("password", ""))
            hidden = bool(command.get("hidden", False))
            return self._start_connect_wifi(ssid, password, hidden, clear_pending_on_success=False)
        if action == "connect_saved_wifi":
            ssid = str(command.get("ssid", "")).strip()
            return self._start_connect_wifi(ssid, "", False, clear_pending_on_success=False, use_saved_profile=True)
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
        state_dir = Path(str(self.config.get("provisioning.state_dir", "/run/sculpture-ble-provisioning")))
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

    def _clear_pending_wifi(self) -> None:
        path = self._pending_wifi_path()
        if path.exists():
            path.unlink()

    def _last_response(self) -> bytearray:
        with self._response_lock:
            return bytearray(self.last_response)

    def _set_response(self, payload: dict[str, Any]) -> None:
        with self._response_lock:
            self.last_response = _json_bytes(payload)

    def _start_connect_wifi(
        self,
        ssid: str,
        password: str,
        hidden: bool,
        clear_pending_on_success: bool,
        use_saved_profile: bool = False,
    ) -> dict[str, Any]:
        if self._connection_thread and self._connection_thread.is_alive():
            return {"ok": False, "state": "busy", "error": "Wi-Fi connection attempt already in progress"}

        if not ssid.strip():
            raise ValueError("ssid is required")

        self._connection_thread = threading.Thread(
            target=self._connect_wifi_background,
            args=(ssid, password, hidden, clear_pending_on_success, use_saved_profile),
            daemon=True,
        )
        self._deferred_thread_start = self._connection_thread
        return {"ok": True, "state": "connecting", "ssid": ssid, "message": "Wi-Fi connection started"}

    def _start_deferred_thread(self) -> None:
        if self._deferred_thread_start is None:
            return
        thread = self._deferred_thread_start
        self._deferred_thread_start = None
        thread.start()

    def _connect_wifi_background(
        self,
        ssid: str,
        password: str,
        hidden: bool,
        clear_pending_on_success: bool,
        use_saved_profile: bool,
    ) -> None:
        try:
            if use_saved_profile:
                connect_saved_wifi(self.config, ssid)
            else:
                connect_wifi(self.config, ssid, password, hidden)
            if clear_pending_on_success:
                self._clear_pending_wifi()
            self._set_response(
                {
                    "ok": True,
                    "state": "connected",
                    "ssid": ssid,
                    "message": "Wi-Fi connection completed",
                    "connectivity": get_connectivity(),
                }
            )
        except Exception as exc:
            logger.exception("Wi-Fi connection attempt failed")
            self._set_response({"ok": False, "state": "failed", "ssid": ssid, "error": str(exc)})


def _characteristic_uuid(characteristic: Any) -> str:
    return str(getattr(characteristic, "uuid", characteristic)).lower()


def _command_offset(command: dict[str, Any]) -> int:
    try:
        offset = int(command.get("offset", 0))
    except (TypeError, ValueError):
        raise ValueError("offset must be an integer")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    return offset


def _scan_page(networks: list[dict[str, Any]], offset: int) -> dict[str, Any]:
    total = len(networks)
    page: list[dict[str, Any]] = []
    index = min(offset, total)

    while index < total:
        candidate = [*page, networks[index]]
        payload = {
            "ok": True,
            "networks": candidate,
            "offset": offset,
            "next_offset": index + 1 if index + 1 < total else None,
            "total": total,
        }
        if page and len(_json_bytes(payload)) > MAX_BLE_JSON_BYTES:
            break
        page = candidate
        index += 1

    next_offset = index if index < total else None
    return {
        "ok": True,
        "networks": page,
        "offset": offset,
        "next_offset": next_offset,
        "total": total,
    }


def _decode_response(value: bytearray) -> dict[str, Any]:
    try:
        decoded = json.loads(bytes(value).decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {"value": decoded}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "error": "invalid previous response"}
