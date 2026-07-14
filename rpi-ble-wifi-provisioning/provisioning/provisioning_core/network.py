from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from provisioning_core.config import ProvisioningConfig


logger = logging.getLogger(__name__)


class NetworkCommandError(RuntimeError):
    """Raised when NetworkManager rejects a provisioning operation."""


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: str
    security: str
    saved: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"ssid": self.ssid, "signal": self.signal, "security": self.security, "saved": self.saved}


def provisioning_status(config: ProvisioningConfig) -> dict[str, Any]:
    return {
        "enabled": bool(config.get("provisioning.enabled", True)),
        "interface": str(config.get("network.interface", "wlan0")),
        "connectivity": get_connectivity(),
        "active_connections": active_connections(),
    }


def get_connectivity() -> str:
    result = _run_nmcli(["networking", "connectivity", "check"], check=False)
    return (result.stdout or "").strip() or "unknown"


def active_connections() -> list[dict[str, str]]:
    result = _run_nmcli(["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"], check=False)
    connections = []
    for line in result.stdout.splitlines():
        name, conn_type, device = _split_terse(line, 3)
        if name:
            connections.append({"name": name, "type": conn_type, "device": device})
    return connections


def scan_wifi(config: ProvisioningConfig) -> list[dict[str, Any]]:
    interface = str(config.get("network.interface", "wlan0"))
    saved_ssids = {connection["ssid"] for connection in saved_wifi_connections()}
    _run_nmcli(["device", "wifi", "rescan", "ifname", interface], check=False)
    result = _run_nmcli(["-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", interface])
    networks: list[WifiNetwork] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        ssid, signal, security = _split_terse(line, 3)
        ssid = ssid.strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        networks.append(WifiNetwork(ssid=ssid, signal=signal, security=security, saved=ssid in saved_ssids))
    return [network.as_dict() for network in networks]


def connect_wifi(config: ProvisioningConfig, ssid: str, password: str, hidden: bool = False) -> bool:
    if not ssid.strip():
        raise NetworkCommandError("SSID is required")
    interface = str(config.get("network.interface", "wlan0"))
    previous_connection = active_connection_for_interface(interface)
    connection_name = provisioned_connection_name(config, ssid)
    candidate_name = f"{connection_name}-candidate"
    connectivity_required = bool(config.get("network.connectivity_required", False))
    connectivity_timeout = int(config.get("network.connectivity_timeout_seconds", 30))
    autoconnect_priority = int(config.get("wifi.autoconnect_priority", 10))

    _delete_connection(candidate_name)
    command = [
        "device",
        "wifi",
        "connect",
        ssid,
        "ifname",
        interface,
        "name",
        candidate_name,
    ]
    if password:
        command.extend(["password", password])
    if hidden:
        command.extend(["hidden", "yes"])

    logger.info("Connecting %s to Wi-Fi SSID %s", interface, ssid)
    try:
        _run_nmcli(command, sudo=True)
        _run_nmcli(
            [
                "connection",
                "modify",
                candidate_name,
                "connection.autoconnect",
                "yes",
                "connection.autoconnect-priority",
                str(autoconnect_priority),
            ],
            sudo=True,
        )
        if connectivity_required:
            connectivity = wait_for_connectivity(connectivity_timeout)
            if connectivity != "full":
                raise NetworkCommandError(f"Wi-Fi connected but connectivity is {connectivity}")
        _promote_candidate_connection(candidate_name, connection_name)
    except NetworkCommandError as exc:
        _delete_connection(candidate_name)
        rollback_message = rollback_to_connection(previous_connection, interface)
        detail = f"{exc}; {rollback_message}" if rollback_message else str(exc)
        raise NetworkCommandError(detail) from exc
    return True


def connect_saved_wifi(config: ProvisioningConfig, ssid: str) -> bool:
    ssid = ssid.strip()
    if not ssid:
        raise NetworkCommandError("SSID is required")

    interface = str(config.get("network.interface", "wlan0"))
    previous_connection = active_connection_for_interface(interface)
    connectivity_required = bool(config.get("network.connectivity_required", False))
    connectivity_timeout = int(config.get("network.connectivity_timeout_seconds", 30))
    connection_name = saved_connection_name_for_ssid(config, ssid)
    if not connection_name:
        raise NetworkCommandError(f"No saved Wi-Fi credentials found for SSID {ssid}")

    logger.info("Connecting %s to saved Wi-Fi SSID %s", interface, ssid)
    try:
        _run_nmcli(["connection", "up", "id", connection_name, "ifname", interface], sudo=True)
        if connectivity_required:
            connectivity = wait_for_connectivity(connectivity_timeout)
            if connectivity != "full":
                raise NetworkCommandError(f"Saved Wi-Fi connected but connectivity is {connectivity}")
    except NetworkCommandError as exc:
        rollback_message = rollback_to_connection(previous_connection, interface)
        detail = f"{exc}; {rollback_message}" if rollback_message else str(exc)
        raise NetworkCommandError(detail) from exc
    return True


def saved_wifi_connections() -> list[dict[str, str]]:
    result = _run_nmcli(["-t", "-f", "NAME,TYPE,802-11-wireless.ssid", "connection", "show"], check=False)
    connections = []
    for line in result.stdout.splitlines():
        name, conn_type, ssid = _split_terse(line, 3)
        if conn_type == "wifi" and name and ssid:
            connections.append({"name": name, "ssid": ssid})
    return connections


def saved_connection_name_for_ssid(config: ProvisioningConfig, ssid: str) -> str | None:
    connections = [connection for connection in saved_wifi_connections() if connection["ssid"] == ssid]
    if not connections:
        return None

    preferred_name = provisioned_connection_name(config, ssid)
    for connection in connections:
        if connection["name"] == preferred_name:
            return connection["name"]
    return connections[0]["name"]


def active_connection_for_interface(interface: str) -> str | None:
    for connection in active_connections():
        if connection["device"] == interface:
            return connection["name"]
    return None


def rollback_to_connection(connection_name: str | None, interface: str) -> str:
    if not connection_name:
        return "no previous Wi-Fi connection was active"
    try:
        _run_nmcli(["connection", "up", "id", connection_name, "ifname", interface], sudo=True)
    except NetworkCommandError as exc:
        return f"rollback to {connection_name} failed: {exc}"
    return f"rolled back to {connection_name}"


def wait_for_connectivity(timeout_seconds: int) -> str:
    deadline = time.monotonic() + max(timeout_seconds, 0)
    connectivity = get_connectivity()
    while connectivity != "full" and time.monotonic() < deadline:
        time.sleep(2)
        connectivity = get_connectivity()
    return connectivity


def provisioned_connection_name(config: ProvisioningConfig, ssid: str) -> str:
    prefix = str(config.get("wifi.connection_name", "provisioned-wifi")).strip() or "provisioned-wifi"
    return f"{prefix}-{_connection_slug(ssid)}"


def _connection_slug(ssid: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in ssid.strip())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:48] or "wifi"


def _promote_candidate_connection(candidate_name: str, connection_name: str) -> None:
    _delete_connection(connection_name)
    _run_nmcli(["connection", "modify", candidate_name, "connection.id", connection_name], sudo=True)


def _delete_connection(connection_name: str) -> None:
    if _connection_exists(connection_name):
        _run_nmcli(["connection", "delete", "id", connection_name], sudo=True, check=False)


def _connection_exists(connection_name: str) -> bool:
    result = _run_nmcli(["-t", "-f", "NAME", "connection", "show"], check=False)
    return any(_split_terse(line, 1)[0] == connection_name for line in result.stdout.splitlines())


def _run_nmcli(args: list[str], sudo: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["nmcli", *args]
    if sudo and os.geteuid() != 0:
        command = ["sudo", "-n", *command]
    logger.debug("Running command: %s", " ".join(command))
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=90)
    except OSError as exc:
        raise NetworkCommandError(f"Unable to run nmcli: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise NetworkCommandError("nmcli command timed out") from exc

    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "nmcli command failed").strip()
        raise NetworkCommandError(message)
    return result


def _split_terse(line: str, count: int) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False

    for char in line:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == ":" and len(parts) < count - 1:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)

    if escaped:
        current.append("\\")
    parts.append("".join(current))
    parts.extend([""] * (count - len(parts)))
    return parts[:count]
