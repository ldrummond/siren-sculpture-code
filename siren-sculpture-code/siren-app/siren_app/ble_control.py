from __future__ import annotations

import json
import logging
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any

from siren_app.config import AppConfig
from siren_app.player import playback_window_command, queue_command
from siren_app.status import gather_status
from siren_app.wittypi import set_system_and_rtc_time


logger = logging.getLogger(__name__)

MAX_ADVERTISEMENT_NAME_BYTES = 8
BLE_STARTUP_ATTEMPTS = 10
BLE_STARTUP_RETRY_SECONDS = 2
MAX_BLE_JSON_BYTES = 480

AUDIO_STATUS_KEYS = (
    "state",
    "file_exists",
    "error",
    "manual_paused",
    "control_mode",
    "normal_paused",
    "volume_percent",
    "playback_window",
)

DIAGNOSTIC_SERVICES = (
    "bluetooth.service",
    "sculpture-ble-control.service",
    "sculpture-audio.service",
    "sculpture-healthcheck.timer",
)


def _json_bytes(payload: dict[str, Any]) -> bytearray:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(encoded) <= MAX_BLE_JSON_BYTES:
        return bytearray(encoded)
    logger.warning("BLE JSON response is too large: %s bytes", len(encoded))
    fallback = {
        "ok": False,
        "error": "Pi response exceeded the BLE size limit",
        "response_bytes": len(encoded),
    }
    return bytearray(json.dumps(fallback, separators=(",", ":")).encode("utf-8"))


class SirenBleControlService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.last_response = _json_bytes({"ok": True, "message": "ready"})
        self.service_uuid = str(config.get("ble.control.service_uuid"))
        self.command_uuid = str(config.get("ble.control.command_characteristic_uuid"))
        self.status_uuid = str(config.get("ble.control.status_characteristic_uuid"))
        self._clock_sync_lock = threading.Lock()
        self._clock_sync_status: dict[str, Any] = {"state": "idle"}
        self._wifi_power_lock = threading.Lock()
        self._wifi_power_status: dict[str, Any] = {"state": "idle"}
        self._status_cache_lock = threading.Lock()
        self._status_cache = _json_bytes({"ok": True, "status": {"refreshing": True}})
        self._status_refresh_stop = threading.Event()
        self._status_refresh_thread: threading.Thread | None = None

    def read_request(self, characteristic: Any, **_kwargs: Any) -> bytearray:
        uuid = _characteristic_uuid(characteristic)
        if uuid == self.status_uuid.lower():
            return self.status_response()
        return self.last_response

    def status_response(self) -> bytearray:
        with self._status_cache_lock:
            return bytearray(self._status_cache)

    def refresh_status_cache(self) -> None:
        try:
            response = _json_bytes({"status": self._status()})
        except Exception as exc:
            logger.exception("Unable to build BLE status response")
            response = _json_bytes({"ok": False, "error": f"status unavailable: {exc}"})
        with self._status_cache_lock:
            self._status_cache = response

    def start_status_refresh(self) -> None:
        if self._status_refresh_thread and self._status_refresh_thread.is_alive():
            return
        self._status_refresh_stop.clear()
        self._status_refresh_thread = threading.Thread(
            target=self._status_refresh_loop,
            name="sculpture-status-refresh",
            daemon=True,
        )
        self._status_refresh_thread.start()

    def stop_status_refresh(self) -> None:
        self._status_refresh_stop.set()
        if self._status_refresh_thread:
            self._status_refresh_thread.join(timeout=1)

    def _status_refresh_loop(self) -> None:
        refresh_seconds = max(1.0, float(self.config.get("ble.control.status_refresh_seconds", 5)))
        while not self._status_refresh_stop.wait(refresh_seconds):
            self.refresh_status_cache()

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
            return _decode_response(self.status_response())
        if action == "network_status":
            return {"ok": True, "wifi": _wifi_network_status()}
        if action == "set_wifi_power":
            return self._start_wifi_power_change(_command_wifi_enabled(command))
        if action == "wifi_power_status":
            return self._get_wifi_power_change_status()
        if action == "set_device_time":
            return self._start_clock_sync(_command_epoch_seconds(command))
        if action == "clock_sync_status":
            return self._get_clock_sync_status()
        if action == "diagnostics":
            return {"ok": True, "diagnostics": _gather_diagnostics()}
        if action == "reboot":
            _schedule_reboot()
            return {"ok": True, "queued": "reboot", "message": "device reboot requested"}
        if action == "set_volume":
            volume = _command_volume(command)
            command_id = queue_command(f"volume:{volume}")
            return {"ok": True, "queued": "set_volume", "command_id": command_id, "volume_percent": volume}
        if action == "set_playback_window":
            payload = _playback_window_payload(command)
            command_id = queue_command(playback_window_command(payload))
            return {
                "ok": True,
                "queued": "set_playback_window",
                "command_id": command_id,
                "playback_window": payload,
            }
        if action == "clear_playback_window":
            payload = {"enabled": False}
            command_id = queue_command(playback_window_command(payload))
            return {
                "ok": True,
                "queued": "clear_playback_window",
                "command_id": command_id,
                "playback_window": payload,
            }
        audio_actions = {
            "testing_mode",
            "sculpture_mode",
            "test_play",
            "test_pause",
            "test_restart",
            "play_sculpture",
            "pause_sculpture",
        }
        if action in audio_actions:
            command_id = queue_command(action)
            return {"ok": True, "queued": action, "command_id": command_id}
        raise ValueError(f"unsupported action: {action}")

    def _start_clock_sync(self, epoch_seconds: float) -> dict[str, Any]:
        with self._clock_sync_lock:
            if self._clock_sync_status.get("state") == "pending":
                return {"ok": False, "error": "clock synchronization is already running", "clock_sync": dict(self._clock_sync_status)}
            self._clock_sync_status = {"state": "pending", "source": "ble-client"}

        received_at = time.monotonic()
        worker = threading.Thread(
            target=self._run_clock_sync,
            args=(epoch_seconds, received_at),
            name="sculpture-clock-sync",
            daemon=True,
        )
        worker.start()
        return {"ok": True, "clock_sync": {"state": "pending", "source": "ble-client"}}

    def _run_clock_sync(self, epoch_seconds: float, received_at: float) -> None:
        adjusted_epoch = epoch_seconds + max(0.0, time.monotonic() - received_at)
        try:
            result = set_system_and_rtc_time(self.config, adjusted_epoch, source="ble-client")
            status = {"state": "success", **result}
        except Exception as exc:
            logger.exception("BLE clock synchronization failed")
            status = {"state": "error", "error": _truncate_text(str(exc), 120)}
        with self._clock_sync_lock:
            self._clock_sync_status = status

    def _get_clock_sync_status(self) -> dict[str, Any]:
        with self._clock_sync_lock:
            status = dict(self._clock_sync_status)
        return {"ok": status.get("state") != "error", "clock_sync": status}

    def _start_wifi_power_change(self, enabled: bool) -> dict[str, Any]:
        with self._wifi_power_lock:
            if self._wifi_power_status.get("state") == "pending":
                return {
                    "ok": False,
                    "error": "Wi-Fi power change is already running",
                    "wifi_power": dict(self._wifi_power_status),
                }
            self._wifi_power_status = {"state": "pending", "enabled": enabled}

        worker = threading.Thread(
            target=self._run_wifi_power_change,
            args=(enabled,),
            name="sculpture-wifi-power",
            daemon=True,
        )
        worker.start()
        return {"ok": True, "wifi_power": {"state": "pending", "enabled": enabled}}

    def _run_wifi_power_change(self, enabled: bool) -> None:
        try:
            wifi = _set_wifi_power(enabled)
            status = {"state": "success", "enabled": enabled, "wifi": wifi}
        except Exception as exc:
            logger.exception("BLE Wi-Fi power change failed")
            status = {"state": "error", "enabled": enabled, "error": _truncate_text(str(exc), 120)}
        with self._wifi_power_lock:
            self._wifi_power_status = status

    def _get_wifi_power_change_status(self) -> dict[str, Any]:
        with self._wifi_power_lock:
            status = dict(self._wifi_power_status)
        return {"ok": status.get("state") != "error", "wifi_power": status}

    def _status(self) -> dict[str, Any]:
        status = gather_status(self.config)
        audio = status["audio"]
        return {
            "audio": _compact_audio_status(audio),
            "clock": _compact_clock_status(status.get("clock", {})),
            "wittypi": _compact_wittypi_status(status.get("wittypi", {})),
        }


def _bluetooth_device_name(config: AppConfig) -> str:
    configured = str(config.get("ble.control.device_name", "device")).strip()
    if configured and configured.lower() not in {"auto", "device", "hostname"}:
        return _truncate_utf8(_clean_ble_name(configured, "Siren"), MAX_ADVERTISEMENT_NAME_BYTES)
    hostname = socket.gethostname().split(".", 1)[0].strip()
    return _truncate_utf8(_clean_ble_name(hostname, "Siren"), MAX_ADVERTISEMENT_NAME_BYTES)


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
        "temperature_c": wittypi.get("temperature_c"),
        "rtc_time": wittypi.get("rtc_time"),
    }


def _compact_audio_status(audio: dict[str, Any]) -> dict[str, Any]:
    compact = {key: audio.get(key) for key in AUDIO_STATUS_KEYS if key in audio}
    if audio.get("last_command_id"):
        compact["cmd"] = audio["last_command_id"]
    for source_key, compact_key in (
        ("sync_restart_at", "sync_at"),
        ("last_sync_restart_at", "synced_at"),
    ):
        sync_time = audio.get(source_key)
        if not isinstance(sync_time, str):
            continue
        try:
            compact[compact_key] = round(datetime.fromisoformat(sync_time).timestamp())
        except ValueError:
            pass
    if compact.get("error"):
        compact["error"] = _truncate_text(str(compact["error"]), 24)
    playback_window = compact.get("playback_window")
    if isinstance(playback_window, dict):
        compact["playback_window"] = {
            key: playback_window.get(key)
            for key in ("enabled", "start_time", "stop_time", "active")
            if key in playback_window
        }
    return compact


def _compact_clock_status(clock: dict[str, Any]) -> dict[str, Any]:
    return {
        key: clock.get(key)
        for key in ("system_time", "clock_trusted", "clock_ok")
        if key in clock
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
    value = command.get("volume_percent")
    if value is None:
        raise ValueError("volume_percent is required")
    try:
        volume = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("volume_percent must be an integer") from exc
    if not 0 <= volume <= 100:
        raise ValueError("volume_percent must be between 0 and 100")
    return volume


def _command_wifi_enabled(command: dict[str, Any]) -> bool:
    enabled = command.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    return enabled


def _command_epoch_seconds(command: dict[str, Any]) -> float:
    value = command.get("epoch_ms")
    if value is None:
        raise ValueError("epoch_ms is required")
    try:
        epoch_seconds = float(value) / 1000.0
        timestamp = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError) as exc:
        raise ValueError("epoch_ms must be a valid Unix timestamp") from exc
    if not 2020 <= timestamp.year <= 2099:
        raise ValueError("time must be between 2020 and 2099")
    return epoch_seconds


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
            "clock": _service_state("sculpture-wittypi-clock-sync.timer"),
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
    return _run_command(["journalctl", "-u", service, "-b", "-p", "warning", "-n", "1", "--no-pager", "--output=cat"], max_chars=72)


def _wifi_power_state() -> dict[str, Any]:
    radio = _run_command(["nmcli", "radio", "wifi"])
    rfkill = _run_command(["rfkill", "list", "wifi"])
    radio_state = radio.strip().lower()
    if radio_state in {"enabled", "disabled"}:
        powered = radio_state == "enabled"
    else:
        powered = False
    if "Soft blocked: yes" in rfkill or "Hard blocked: yes" in rfkill:
        powered = False
    elif radio_state not in {"enabled", "disabled"} and "Soft blocked: no" in rfkill and "Hard blocked: no" in rfkill:
        powered = True
    return {"powered": powered, "nmcli_radio": radio, "rfkill": rfkill}


def _wifi_network_status() -> dict[str, Any]:
    powered = _wifi_power_state()["powered"]
    if not powered:
        return {"enabled": False, "connected": False, "ssid": None}

    output = _run_command(
        ["nmcli", "--terse", "--escape", "no", "--fields", "IN-USE,SSID", "device", "wifi", "list", "--rescan", "no"],
        max_chars=512,
    )
    for line in output.splitlines():
        fields = line.split(":", 1)
        if len(fields) != 2:
            continue
        in_use, network_name = fields
        if in_use == "*":
            ssid = network_name.strip()
            return {"enabled": True, "connected": True, "ssid": ssid if ssid and ssid != "--" else None}
    return {"enabled": True, "connected": False, "ssid": None}


def _set_wifi_power(enabled: bool) -> dict[str, Any]:
    if shutil.which("nmcli") is None:
        raise RuntimeError("nmcli is unavailable; NetworkManager is required")

    if enabled:
        if shutil.which("rfkill") is not None:
            _run_checked_command(["rfkill", "unblock", "wifi"])
        _run_checked_command(["nmcli", "radio", "wifi", "on"])
    else:
        _run_checked_command(["nmcli", "radio", "wifi", "off"])
        if shutil.which("rfkill") is not None:
            _run_checked_command(["rfkill", "block", "wifi"])

    wifi = _wifi_network_status()
    if wifi["enabled"] != enabled:
        requested = "on" if enabled else "off"
        raise RuntimeError(f"Wi-Fi did not turn {requested}")
    return wifi


def _run_checked_command(command: list[str], timeout: float = 10) -> None:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Unable to run {' '.join(command)}: {exc}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "command failed").strip()
        raise RuntimeError(f"{' '.join(command)} failed: {_truncate_text(message, 120)}")


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
