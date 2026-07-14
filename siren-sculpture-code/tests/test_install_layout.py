from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
SCULPTURE_ROOT = PROJECT_ROOT / "siren-sculpture-code"
PROVISIONING_ROOT = PROJECT_ROOT / "rpi-ble-wifi-provisioning"


def test_fresh_install_sources_are_present() -> None:
    required = (
        SCULPTURE_ROOT / "scripts" / "initialize-pi.sh",
        SCULPTURE_ROOT / "scripts" / "install.sh",
        SCULPTURE_ROOT / "scripts" / "configure-bluetooth.sh",
        SCULPTURE_ROOT / "siren-app" / "siren_app" / "ble_gateway.py",
        PROVISIONING_ROOT / "pyproject.toml",
        PROVISIONING_ROOT / "provisioning" / "provisioning_core" / "ble_service.py",
        PROVISIONING_ROOT / "provisioning" / "settings" / "provisioning.yaml",
    )

    assert all(path.is_file() for path in required)


def test_standalone_provisioning_lifecycle_is_absent() -> None:
    obsolete = (
        PROVISIONING_ROOT / "install.sh",
        PROVISIONING_ROOT / "deploy.sh",
        PROVISIONING_ROOT / "cleanup.sh",
        PROVISIONING_ROOT / "provisioning" / "systemd" / "rpi-ble-wifi-provisioning.service",
        SCULPTURE_ROOT / "scripts" / "check-service-conflicts.sh",
    )

    assert not any(path.exists() for path in obsolete)
