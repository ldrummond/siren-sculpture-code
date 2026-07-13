from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import socket
import subprocess
from typing import Any

from siren_app.config import AppConfig, load_config
from siren_app.player import playback_window_command, queue_command
from siren_app.status import gather_status


logger = logging.getLogger(__name__)

MAX_LEGACY_ADVERTISEMENT_NAME_BYTES = 8
BLE_STARTUP_ATTEMPTS = 10
BLE_STARTUP_RETRY_SECONDS = 2
MAX_DIAGNOSTIC_TEXT_CHARS = 1200

AUDIO_STATUS_KEYS = (
    "state",
    "file_exists",
    "file_size_mb",
    "loop",
    "error",
    "manual_override",
    "manual_paused",
    "control_mode",
    "supervisor_mode",
    "updated_at",
    "normal_paused",
    "volume_percent",
    "playback_window",
    "config_schedule_active",
)

DIAGNOSTIC_SERVICES = (
    "bluetooth.service",
    "sculpture-ble-control.service",
    "sculpture-audio.service",
    "sculpture-healthcheck.timer",
)


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
            return self.status_response()
        return self.last_response

    def status_response(self) -> bytearray:
        try:
            return _json_bytes({"status": self._status(), "last_response": _last_response_summary(self.last_response)})
        except Exception as exc:
            logger.exception("Unable to build BLE status response")
            return _json_bytes({"ok": False, "error": f"status unavailable: {exc}"})

    def write_request(self, characteristic: Any, value: bytearray, **_kwargs: Any) -> None:
        uuid = _characteristic_uuid(characteristic)
        if uuid != self.command_uuid.lower():
            self.last_response = _json_bytes({"ok": False, "error": "unknown characteristic"})
            return
        try:
            command = json.loads(bytes(value).decode("utf-8"))
            if not isinstance(command, dict):
                raise ValueError("command must be a JSON object")
            self.last_response = _json_bytes(self._handle_command(command))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self.last_response = _json_bytes({"ok": False, "error": str(exc)})

    def _handle_command(self, command: dict[str, Any]) -> dict[str, Any]:
        action = str(command.get("action", "")).strip().lower()
        if action == "status":
            return {"ok": True, "status": self._status()}
        if action in {"diagnostics", "debug", "logs", "service_status"}:
            return {"ok": True, "diagnostics": _gather_diagnostics()}
        if action in {"reboot", "reboot_device", "restart_device"}:
            _schedule_reboot()
            return {"ok": True, "queued": "reboot", "message": "device reboot requested"}
        if action in {"set_volume", "volume"}:
            volume = _command_volume(command)
            queue_command(f"volume:{volume}")
            return {"ok": True, "queued": "set_volume", "volume_percent": volume}
        if action in {"set_playback_window", "set_playback_range"}:
            payload = _playback_window_payload(command)
            queue_command(playback_window_command(payload))
            return {"ok": True, "queued": "set_playback_window", "playback_window": payload}
        if action in {"clear_playback_window", "disable_playback_window"}:
            payload = {"enabled": False}
            queue_command(playback_window_command(payload))
            return {"ok": True, "queued": "clear_playback_window", "playback_window": payload}
        command_aliases = {
            "testing_mode": "testing_mode",
            "enter_testing_mode": "testing_mode",
            "manual_mode": "testing_mode",
            "sculpture_mode": "sculpture_mode",
            "enter_sculpture_mode": "sculpture_mode",
            "normal_mode": "sculpture_mode",
            "play": "test_play",
            "test_play": "test_play",
            "pause": "test_pause",
            "pause_manual": "test_pause",
            "test_pause": "test_pause",
            "restart": "test_restart",
            "test_restart": "test_restart",
            "resume": "test_play",
            "stop": "pause_sculpture",
            "pause_normal": "pause_sculpture",
            "normal_pause": "pause_sculpture",
            "pause_sculpture": "pause_sculpture",
            "play_sculpture": "play_sculpture",
            "resume_normal": "play_sculpture",
            "resume_normal_playback": "play_sculpture",
            "normal": "play_sculpture",
        }
        if action in command_aliases:
            queued = command_aliases[action]
            queue_command(queued)
            return {"ok": True, "queued": queued}
        raise ValueError(f"unsupported action: {action}")

    def _status(self) -> dict[str, Any]:
        status = gather_status(self.config)
        audio = status["audio"]
        return {
            "project": status["project"],
            "audio": {key: audio.get(key) for key in AUDIO_STATUS_KEYS if key in audio},
            "clock": status["clock"],
            "wittypi": _compact_wittypi_status(status.get("wittypi", {})),
        }


async def run_server() -> None:
    config = load_config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    if not bool(config.get("ble.control.enabled", True)):
        logger.info("Siren BLE control service disabled")
        return

    wifi_state = _wifi_power_state()
    if wifi_state["powered"]:
        logger.warning(
            "Wi-Fi appears to be enabled while BLE control is running. Disable Wi-Fi after testing to reduce power use. state=%s",
            wifi_state,
        )

    BlessServer, GATTCharacteristicProperties, GATTAttributePermissions = _load_bless_backend()
    _disable_bluez_experimental_advertisement_properties()

    service = SirenBleControlService(config)
    device_name = _bluetooth_device_name(config)
    adapter = str(config.get("ble.control.adapter", "hci0")).strip() or "hci0"
    logger.info("Starting BLE advertisement adapter=%s name=%s service_uuid=%s", adapter, device_name, service.service_uuid)

    server = None
    for attempt in range(1, BLE_STARTUP_ATTEMPTS + 1):
        try:
            server = BlessServer(name=device_name, adapter=adapter)
            server.read_request_func = service.read_request
            server.write_request_func = service.write_request
            await server.add_new_service(service.service_uuid)
            await server.add_new_characteristic(
                service.service_uuid,
                service.command_uuid,
                GATTCharacteristicProperties.write | GATTCharacteristicProperties.read,
                service.last_response,
                GATTAttributePermissions.writeable | GATTAttributePermissions.readable,
            )
            await server.add_new_characteristic(
                service.service_uuid,
                service.status_uuid,
                GATTCharacteristicProperties.read,
                service.status_response(),
                GATTAttributePermissions.readable,
            )
            await server.start()
            break
        except Exception as exc:
            if attempt >= BLE_STARTUP_ATTEMPTS:
                raise RuntimeError(
                    f"BlueZ failed to start sculpture BLE control on adapter {adapter}. Confirm bluetooth.service "
                    "is running, the adapter exists in 'bluetoothctl list', no other BLE service is advertising, "
                    f"and the advertised name is at most {MAX_LEGACY_ADVERTISEMENT_NAME_BYTES} UTF-8 bytes."
                ) from exc
            logger.warning("BLE startup attempt %s/%s failed on adapter %s: %s", attempt, BLE_STARTUP_ATTEMPTS, adapter, exc)
            await asyncio.sleep(BLE_STARTUP_RETRY_SECONDS)

    logger.info("Siren BLE control GATT service started")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        if server is not None:
            await server.stop()


def _bluetooth_device_name(config: AppConfig) -> str:
    configured = str(config.get("ble.control.device_name", "device")).strip()
    if configured and configured.lower() not in {"auto", "device", "hostname"}:
        return _truncate_utf8(_clean_ble_name(configured, "Siren"), MAX_LEGACY_ADVERTISEMENT_NAME_BYTES)
    hostname = socket.gethostname().split(".", 1)[0].strip()
    return _truncate_utf8(_clean_ble_name(hostname, "Siren"), MAX_LEGACY_ADVERTISEMENT_NAME_BYTES)


def _clean_ble_name(value: str, fallback: str) -> str:
    cleaned = "".join(char for char in value if char.isalnum() or char in "-_").strip("-_")
    return cleaned or fallback


def _truncate_utf8(value: str, max_bytes: int) -> str:
    result = ""
    for char in value:
        if len((result + char).encode("utf-8")) > max_bytes:
            break
        result += char
    return result or "Siren"


def _compact_wittypi_status(wittypi: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": wittypi.get("enabled"),
        "detected": wittypi.get("detected"),
        "temperature_c": wittypi.get("temperature_c"),
        "temperature_f": wittypi.get("temperature_f"),
        "rtc_time": wittypi.get("rtc_time"),
    }


def _playback_window_payload(command: dict[str, Any]) -> dict[str, Any]:
    start_time = _command_time(command, "start_time")
    stop_time = _command_time(command, "stop_time")
    payload: dict[str, Any] = {
        "enabled": True,
        "start_time": start_time,
        "stop_time": stop_time,
    }
    timezone = command.get("timezone")
    if timezone is not None and str(timezone).strip():
        payload["timezone"] = str(timezone).strip()
    return payload


def _command_time(command: dict[str, Any], key: str) -> str:
    value = command.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    value = value.strip()
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"{key} must use HH:MM")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"{key} must use HH:MM") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"{key} must use HH:MM")
    return f"{hour:02d}:{minute:02d}"


def _command_volume(command: dict[str, Any]) -> int:
    value = command.get("volume_percent", command.get("volume"))
    if value is None:
        raise ValueError("volume_percent is required")
    try:
        volume = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("volume_percent must be an integer") from exc
    if not 0 <= volume <= 100:
        raise ValueError("volume_percent must be between 0 and 100")
    return volume


def _schedule_reboot() -> None:
    subprocess.Popen(
        ["/bin/sh", "-c", "sleep 2; systemctl reboot"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _load_bless_backend() -> tuple[Any, Any, Any]:
    try:
        from bless import BlessServer
        from bless.backends.characteristic import GATTCharacteristicProperties
    except ImportError as exc:
        raise RuntimeError("bless is required for BLE peripheral services") from exc

    try:
        from bless.backends.characteristic import GATTAttributePermissions
    except ImportError:
        try:
            from bless.backends.service import GATTAttributePermissions
        except ImportError as exc:
            raise RuntimeError("installed bless package does not expose GATTAttributePermissions") from exc

    return BlessServer, GATTCharacteristicProperties, GATTAttributePermissions


def _disable_bluez_experimental_advertisement_properties() -> None:
    try:
        from bless.backends.bluezdbus.dbus.advertisement import BlueZLEAdvertisement
    except ImportError:
        return

    for property_name in ("TxPower", "MinInterval", "MaxInterval"):
        prop = getattr(BlueZLEAdvertisement, property_name, None)
        if prop is not None and hasattr(prop, "disabled"):
            prop.disabled = True


def _gather_diagnostics() -> dict[str, Any]:
    return {
        "h": socket.gethostname().split(".", 1)[0],
        "k": _run_command(["uname", "-r"], max_chars=64),
        "wifi": _wifi_power_state()["powered"],
        "bt": "Powered: yes" in _run_command(["bluetoothctl", "show"], max_chars=180),
        "svc": {
            "bt": _service_state("bluetooth.service"),
            "ble": _service_state("sculpture-ble-control.service"),
            "audio": _service_state("sculpture-audio.service"),
            "health": _service_state("sculpture-healthcheck.timer"),
        },
        "err": {
            "ble": _journal_tail("sculpture-ble-control.service"),
            "audio": _journal_tail("sculpture-audio.service"),
        },
    }


def _service_state(service: str) -> str:
    active = _run_command(["systemctl", "is-active", service], max_chars=16)
    enabled = _run_command(["systemctl", "is-enabled", service], max_chars=16)
    return f"{active}/{enabled}"


def _journal_tail(service: str) -> str:
    return _run_command(["journalctl", "-u", service, "-b", "-p", "warning", "-n", "1", "--no-pager", "--output=cat"], max_chars=90)


def _wifi_power_state() -> dict[str, Any]:
    radio = _run_command(["nmcli", "radio", "wifi"])
    rfkill = _run_command(["rfkill", "list", "wifi"])
    powered = radio.strip().lower() == "enabled"
    if "Soft blocked: no" in rfkill and "Hard blocked: no" in rfkill:
        powered = True
    return {"powered": powered, "nmcli_radio": radio, "rfkill": rfkill}


def _run_command(command: list[str], timeout: float = 3, max_chars: int = 800) -> str:
    if not command or shutil.which(command[0]) is None:
        return "unavailable"
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _truncate_text(str(exc), max_chars)
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0 and output:
        output = f"exit {result.returncode}: {output}"
    elif result.returncode != 0:
        output = f"exit {result.returncode}"
    return _truncate_text(output, max_chars)


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 14].rstrip() + " ...[truncated]"


def _characteristic_uuid(characteristic: Any) -> str:
    return str(getattr(characteristic, "uuid", characteristic)).lower()


def _decode_response(value: bytearray) -> dict[str, Any]:
    try:
        decoded = json.loads(bytes(value).decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {"value": decoded}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "error": "invalid previous response"}


def _last_response_summary(value: bytearray) -> dict[str, Any]:
    response = _decode_response(value)
    if "diagnostics" in response:
        return {"ok": bool(response.get("ok", True)), "message": "diagnostics returned"}
    if "status" not in response:
        return response
    summary = {key: response[key] for key in ("ok", "queued", "error", "volume_percent") if key in response}
    if not summary:
        summary["ok"] = bool(response.get("ok", True))
    summary["message"] = "status returned"
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Siren BLE control service")
    parser.parse_args()
    asyncio.run(run_server())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
