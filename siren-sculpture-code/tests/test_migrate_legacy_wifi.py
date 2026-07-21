import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
SCRIPT = PROJECT_ROOT / "siren-sculpture-code" / "scripts" / "migrate_legacy_wifi.py"
SPEC = importlib.util.spec_from_file_location("migrate_legacy_wifi", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parses_supported_wpa_personal_open_and_escaped_ssids() -> None:
    networks, warnings = MODULE.parse_wpa_supplicant(
        r'''
        country=US
        network={
            ssid="Studio #1"
            psk="secret password"
            priority=8
        }
        network={
            ssid="Hidden\"Siren"
            psk=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
            scan_ssid=1
        }
        network={
            ssid="Guest"
            key_mgmt=NONE
        }
        '''
    )

    assert warnings == []
    assert [(item.ssid, item.key_mgmt) for item in networks] == [
        ("Studio #1", "WPA-PSK"),
        ('Hidden"Siren', "WPA-PSK"),
        ("Guest", "NONE"),
    ]
    assert networks[0].priority == 8
    assert networks[1].hidden is True


def test_skips_enterprise_and_disabled_networks() -> None:
    networks, warnings = MODULE.parse_wpa_supplicant(
        '''
        network={
            ssid="Enterprise"
            key_mgmt=WPA-EAP
            identity="person@example.com"
        }
        network={
            ssid="Old"
            psk="old-password"
            disabled=1
        }
        '''
    )

    assert networks == []
    assert len(warnings) == 1
    assert "WPA-EAP" in warnings[0]


def test_parses_wlan0_static_ipv4_settings() -> None:
    settings = MODULE.parse_dhcpcd_static_ipv4(
        '''
        interface eth0
        static ip_address=10.0.0.3/24
        interface wlan0
        static ip_address=192.168.4.20/24
        static routers=192.168.4.1
        static domain_name_servers=1.1.1.1 8.8.8.8
        '''
    )

    assert settings == MODULE.StaticIPv4(
        address="192.168.4.20/24",
        gateway="192.168.4.1",
        dns=("1.1.1.1", "8.8.8.8"),
    )
