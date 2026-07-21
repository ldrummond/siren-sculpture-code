from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
SCULPTURE_ROOT = PROJECT_ROOT / "siren-sculpture-code"
PROVISIONING_ROOT = PROJECT_ROOT / "rpi-ble-wifi-provisioning"


def test_fresh_install_sources_are_present() -> None:
    required = (
        SCULPTURE_ROOT / "scripts" / "initialize-pi.sh",
        SCULPTURE_ROOT / "scripts" / "install.sh",
        SCULPTURE_ROOT / "scripts" / "configure-bluetooth.sh",
        SCULPTURE_ROOT / "scripts" / "configure-networkmanager.sh",
        SCULPTURE_ROOT / "scripts" / "migrate_legacy_wifi.py",
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


def test_initializer_requires_known_working_ble_kernel_without_installing_it() -> None:
    initializer = (SCULPTURE_ROOT / "scripts" / "initialize-pi.sh").read_text()

    assert "7a0137617dd4a8496e566d23c01219923c409a79" in initializer
    assert "6.18.38-v7+" in initializer
    assert "check_pinned_rpi_firmware" in initializer
    assert "Initialization stopped" in initializer
    assert "install_pinned_rpi_firmware" not in initializer
    package_block = initializer.split("apt install -y \\\n", 1)[1].split("\n\nmkdir -p", 1)[0]
    assert "rpi-update" not in package_block
    assert "git-lfs" in package_block
    assert 'git lfs install --skip-repo' in initializer
    assert "SKIP_BOOTLOADER=1" in initializer


def test_regular_install_ensures_git_lfs_is_available() -> None:
    installer = (SCULPTURE_ROOT / "scripts" / "install.sh").read_text()

    assert "command -v git-lfs" in installer
    assert "apt install -y git-lfs" in installer
    assert 'git lfs install --skip-repo' in installer


def test_installers_configure_networkmanager_with_wifi_policy() -> None:
    for filename in ("initialize-pi.sh", "install.sh"):
        installer = (SCULPTURE_ROOT / "scripts" / filename).read_text()
        assert 'DISABLE_WIFI="${DISABLE_WIFI}" "${APP_DIR}/scripts/configure-networkmanager.sh"' in installer

    low_power = (SCULPTURE_ROOT / "scripts" / "configure-low-power.sh").read_text()
    assert "rfkill unblock wifi" in low_power
    assert "nmcli networking on" in low_power
    assert "nmcli radio wifi on" in low_power
