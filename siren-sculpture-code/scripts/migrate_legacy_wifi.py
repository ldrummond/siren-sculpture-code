#!/usr/bin/env python3
"""Conservatively migrate legacy Raspberry Pi Wi-Fi settings to NetworkManager."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


WPA_CONFIGS = (
    Path("/etc/wpa_supplicant/wpa_supplicant.conf"),
    Path("/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"),
)
DHCPCD_CONFIG = Path("/etc/dhcpcd.conf")


@dataclass(frozen=True)
class LegacyNetwork:
    ssid: str
    psk: str | None
    key_mgmt: str
    hidden: bool = False
    priority: int = 0


@dataclass(frozen=True)
class StaticIPv4:
    address: str
    gateway: str | None = None
    dns: tuple[str, ...] = ()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        body = value[1:-1]

        def replace(match: re.Match[str]) -> str:
            escaped = match.group(1)
            simple = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
            if escaped in simple:
                return simple[escaped]
            if escaped.startswith("x") and len(escaped) == 3:
                return chr(int(escaped[1:], 16))
            return escaped

        return re.sub(r"\\(x[0-9A-Fa-f]{2}|.)", replace, body)
    return value


def _without_comment(line: str) -> str:
    quoted = False
    escaped = False
    result: list[str] = []
    for character in line:
        if escaped:
            result.append(character)
            escaped = False
        elif character == "\\" and quoted:
            result.append(character)
            escaped = True
        elif character == '"':
            result.append(character)
            quoted = not quoted
        elif character == "#" and not quoted:
            break
        else:
            result.append(character)
    return "".join(result).strip()


def parse_wpa_supplicant(text: str) -> tuple[list[LegacyNetwork], list[str]]:
    networks: list[LegacyNetwork] = []
    warnings: list[str] = []
    block: dict[str, str] | None = None

    for raw_line in text.splitlines():
        line = _without_comment(raw_line)
        if not line:
            continue
        if block is None:
            if re.fullmatch(r"network\s*=\s*\{", line):
                block = {}
            continue
        if line == "}":
            if block.get("disabled", "0") == "1":
                block = None
                continue
            ssid = _unquote(block.get("ssid", ""))
            key_mgmt = block.get("key_mgmt", "WPA-PSK").strip()
            psk_value = block.get("psk")
            psk = _unquote(psk_value) if psk_value is not None else None
            try:
                priority = int(block.get("priority", "0"))
            except ValueError:
                priority = 0
                warnings.append(f"Ignored invalid priority for legacy SSID {ssid!r}.")
            if not ssid:
                warnings.append("Skipped a legacy network with no readable SSID.")
            elif key_mgmt == "NONE":
                networks.append(
                    LegacyNetwork(ssid, None, key_mgmt, block.get("scan_ssid") == "1", priority)
                )
            elif key_mgmt in {"WPA-PSK", "SAE"} and psk:
                networks.append(
                    LegacyNetwork(ssid, psk, key_mgmt, block.get("scan_ssid") == "1", priority)
                )
            else:
                warnings.append(f"Skipped unsupported legacy Wi-Fi security for SSID {ssid!r}: {key_mgmt}.")
            block = None
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            block[key.strip()] = value.strip()

    if block is not None:
        warnings.append("Skipped an incomplete network block in the legacy Wi-Fi configuration.")
    return networks, warnings


def parse_dhcpcd_static_ipv4(text: str, interface: str = "wlan0") -> StaticIPv4 | None:
    active_interface: str | None = None
    settings: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = _without_comment(raw_line)
        if not line:
            continue
        if line.startswith("interface "):
            active_interface = line.split(None, 1)[1].strip()
            continue
        if active_interface != interface or not line.startswith("static ") or "=" not in line:
            continue
        key, value = line[len("static ") :].split("=", 1)
        settings[key.strip()] = value.strip()

    address = settings.get("ip_address")
    if not address:
        return None
    gateways = settings.get("routers", "").split()
    return StaticIPv4(
        address=address,
        gateway=gateways[0] if gateways else None,
        dns=tuple(settings.get("domain_name_servers", "").split()),
    )


def _run_nmcli(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("nmcli", *arguments),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def networkmanager_has_wifi_profiles() -> bool:
    result = _run_nmcli("-t", "-f", "TYPE", "connection", "show")
    return any(line.strip() in {"wifi", "802-11-wireless"} for line in result.stdout.splitlines())


def migrate_network(network: LegacyNetwork, static_ipv4: StaticIPv4 | None) -> None:
    connection_name = f"Legacy Wi-Fi - {network.ssid}"
    _run_nmcli(
        "connection", "add", "type", "wifi", "con-name", connection_name,
        "ifname", "*", "ssid", network.ssid,
    )
    try:
        changes = [
            "connection", "modify", connection_name,
            "connection.autoconnect", "yes",
            "connection.autoconnect-priority", str(network.priority),
        ]
        if network.hidden:
            changes.extend(("802-11-wireless.hidden", "yes"))
        if network.key_mgmt != "NONE":
            changes.extend(
                ("wifi-sec.key-mgmt", "sae" if network.key_mgmt == "SAE" else "wpa-psk", "wifi-sec.psk", network.psk or "")
            )
        if static_ipv4 is not None:
            changes.extend(("ipv4.method", "manual", "ipv4.addresses", static_ipv4.address))
            if static_ipv4.gateway:
                changes.extend(("ipv4.gateway", static_ipv4.gateway))
            if static_ipv4.dns:
                changes.extend(("ipv4.dns", ",".join(static_ipv4.dns)))
        _run_nmcli(*changes)
    except Exception:
        _run_nmcli("connection", "delete", connection_name, check=False)
        raise


def main() -> int:
    if networkmanager_has_wifi_profiles():
        print("Existing NetworkManager Wi-Fi profile found; legacy migration was not needed.")
        return 0

    config_path = next((path for path in WPA_CONFIGS if path.is_file()), None)
    if config_path is None:
        print("No legacy wpa_supplicant Wi-Fi configuration found.")
        return 0

    networks, warnings = parse_wpa_supplicant(config_path.read_text(errors="replace"))
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if not networks:
        print(f"WARNING: No supported Wi-Fi profiles could be migrated from {config_path}.", file=sys.stderr)
        return 0

    static_ipv4 = None
    if DHCPCD_CONFIG.is_file():
        static_ipv4 = parse_dhcpcd_static_ipv4(DHCPCD_CONFIG.read_text(errors="replace"))

    migrated = 0
    for network in sorted(networks, key=lambda item: item.priority, reverse=True):
        try:
            migrate_network(network, static_ipv4)
            migrated += 1
        except subprocess.CalledProcessError as error:
            detail = error.stderr.strip() or "nmcli rejected the profile"
            print(f"WARNING: Could not migrate SSID {network.ssid!r}: {detail}", file=sys.stderr)

    if migrated:
        suffix = " with legacy wlan0 static IPv4 settings" if static_ipv4 else ""
        print(f"Migrated {migrated} legacy Wi-Fi profile(s) into NetworkManager{suffix}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
