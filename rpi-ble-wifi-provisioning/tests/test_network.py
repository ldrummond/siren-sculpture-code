from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from provisioning_core.config import ProvisioningConfig
from provisioning_core.network import (
    NetworkCommandError,
    _split_terse,
    connect_saved_wifi,
    connect_wifi,
    provisioned_connection_name,
    scan_wifi,
    saved_connection_name_for_ssid,
    saved_wifi_connections,
)


def test_split_terse_preserves_escaped_colons() -> None:
    assert _split_terse(r"Studio\:WiFi:82:WPA2", 3) == ["Studio:WiFi", "82", "WPA2"]


def test_split_terse_keeps_extra_delimiters_in_last_field() -> None:
    assert _split_terse("ssid:signal:security:extra", 3) == ["ssid", "signal", "security:extra"]


def make_config() -> ProvisioningConfig:
    return ProvisioningConfig(
        data={
            "network": {
                "interface": "wlan0",
                "connectivity_required": False,
                "connectivity_timeout_seconds": 1,
            },
            "wifi": {
                "connection_name": "provisioned-wifi",
                "autoconnect_priority": 10,
            },
        },
        path=Path("provisioning.yaml"),
    )


def completed(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["nmcli"], 0, stdout=stdout, stderr="")


def test_provisioned_connection_name_is_per_ssid() -> None:
    assert provisioned_connection_name(make_config(), "Studio WiFi") == "provisioned-wifi-studio-wifi"


def test_connect_wifi_uses_candidate_profile_then_promotes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_nmcli(args: list[str], sudo: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:5] == ["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show"]:
            return completed("current:wifi:wlan0\n")
        if args[:5] == ["-t", "-f", "NAME", "connection", "show"]:
            return completed("current\n")
        return completed()

    monkeypatch.setattr("provisioning_core.network._run_nmcli", fake_run_nmcli)

    assert connect_wifi(make_config(), "Studio WiFi", "secret") is True

    assert [
        "device",
        "wifi",
        "connect",
        "Studio WiFi",
        "ifname",
        "wlan0",
        "name",
        "provisioned-wifi-studio-wifi-candidate",
        "password",
        "secret",
    ] in calls
    assert [
        "connection",
        "modify",
        "provisioned-wifi-studio-wifi-candidate",
        "connection.id",
        "provisioned-wifi-studio-wifi",
    ] in calls


def test_connect_wifi_rolls_back_previous_connection_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_nmcli(args: list[str], sudo: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:5] == ["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show"]:
            return completed("current:wifi:wlan0\n")
        if args[:5] == ["-t", "-f", "NAME", "connection", "show"]:
            return completed("provisioned-wifi-studio-wifi-candidate\ncurrent\n")
        if args[:3] == ["device", "wifi", "connect"]:
            raise NetworkCommandError("bad password")
        return completed()

    monkeypatch.setattr("provisioning_core.network._run_nmcli", fake_run_nmcli)

    with pytest.raises(NetworkCommandError, match="rolled back to current"):
        connect_wifi(make_config(), "Studio WiFi", "wrong")

    assert ["connection", "delete", "id", "provisioned-wifi-studio-wifi-candidate"] in calls
    assert ["connection", "up", "id", "current", "ifname", "wlan0"] in calls


def test_saved_wifi_connections_reads_networkmanager_wifi_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_nmcli(args: list[str], sudo: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
        assert args == ["-t", "-f", "NAME,TYPE,802-11-wireless.ssid", "connection", "show"]
        return completed("Lab Profile:wifi:Lab\nEthernet:ethernet:\nStudio\\:Profile:wifi:Studio:Wifi\n")

    monkeypatch.setattr("provisioning_core.network._run_nmcli", fake_run_nmcli)

    assert saved_wifi_connections() == [
        {"name": "Lab Profile", "ssid": "Lab"},
        {"name": "Studio:Profile", "ssid": "Studio:Wifi"},
    ]


def test_scan_wifi_marks_saved_networks(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_nmcli(args: list[str], sudo: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
        if args == ["-t", "-f", "NAME,TYPE,802-11-wireless.ssid", "connection", "show"]:
            return completed("Lab Profile:wifi:Lab\n")
        if args[:3] == ["device", "wifi", "rescan"]:
            return completed()
        if args == ["-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", "wlan0"]:
            return completed("Lab:89:WPA2\nGuest:72:WPA2\n")
        raise AssertionError(f"unexpected nmcli args: {args}")

    monkeypatch.setattr("provisioning_core.network._run_nmcli", fake_run_nmcli)

    assert scan_wifi(make_config()) == [
        {"ssid": "Lab", "signal": "89", "security": "WPA2", "saved": True},
        {"ssid": "Guest", "signal": "72", "security": "WPA2", "saved": False},
    ]


def test_saved_connection_name_prefers_provisioned_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "provisioning_core.network.saved_wifi_connections",
        lambda: [
            {"name": "Lab Profile", "ssid": "Lab"},
            {"name": "provisioned-wifi-lab", "ssid": "Lab"},
        ],
    )

    assert saved_connection_name_for_ssid(make_config(), "Lab") == "provisioned-wifi-lab"


def test_connect_saved_wifi_activates_existing_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_nmcli(args: list[str], sudo: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:5] == ["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show"]:
            return completed("current:wifi:wlan0\n")
        if args == ["-t", "-f", "NAME,TYPE,802-11-wireless.ssid", "connection", "show"]:
            return completed("Lab Profile:wifi:Lab\n")
        return completed()

    monkeypatch.setattr("provisioning_core.network._run_nmcli", fake_run_nmcli)

    assert connect_saved_wifi(make_config(), "Lab") is True
    assert ["connection", "up", "id", "Lab Profile", "ifname", "wlan0"] in calls
