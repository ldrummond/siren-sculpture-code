from __future__ import annotations

import logging
import os
import subprocess
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

    def as_dict(self) -> dict[str, str]:
        return {"ssid": self.ssid, "signal": self.signal, "security": self.security}


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


def scan_wifi(config: ProvisioningConfig) -> list[dict[str, str]]:
    interface = str(config.get("network.interface", "wlan0"))
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
        networks.append(WifiNetwork(ssid=ssid, signal=signal, security=security))
    return [network.as_dict() for network in networks]


def connect_wifi(config: ProvisioningConfig, ssid: str, password: str, hidden: bool = False) -> bool:
    if not ssid.strip():
        raise NetworkCommandError("SSID is required")
    interface = str(config.get("network.interface", "wlan0"))
    connection_name = str(config.get("wifi.connection_name", "sculpture-site-wifi"))
    command = [
        "device",
        "wifi",
        "connect",
        ssid,
        "ifname",
        interface,
        "name",
        connection_name,
    ]
    if password:
        command.extend(["password", password])
    if hidden:
        command.extend(["hidden", "yes"])

    logger.info("Connecting %s to Wi-Fi SSID %s", interface, ssid)
    _run_nmcli(command, sudo=True)
    return True


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
    parts = line.split(":")
    parts.extend([""] * (count - len(parts)))
    return [part.replace("\\:", ":") for part in parts[:count]]
