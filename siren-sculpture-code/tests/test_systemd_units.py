from pathlib import Path


SYSTEMD_DIR = Path(__file__).parents[1] / "siren-app" / "systemd"


def assert_journal_logging(unit_name: str) -> None:
    unit = (SYSTEMD_DIR / unit_name).read_text(encoding="utf-8")
    assert "StandardOutput=journal" in unit
    assert "StandardError=journal" in unit


def test_audio_service_owns_shared_runtime_directory() -> None:
    unit = (SYSTEMD_DIR / "sculpture-audio.service").read_text(encoding="utf-8")

    assert "RuntimeDirectory=sculpture-audio-controller" in unit
    assert "RuntimeDirectoryMode=0775" in unit
    assert "RuntimeDirectoryPreserve=yes" in unit
    assert "SCULPTURE_COMMAND_FILE=/run/sculpture-audio-controller/command" in unit
    assert "SCULPTURE_STATUS_FILE=/run/sculpture-audio-controller/status.json" in unit
    assert "After=sound.target wittypi.service" in unit
    assert "SCULPTURE_CLOCK_TRUST_FILE=/run/sculpture-clock-trusted" in unit
    assert "SCULPTURE_AUDIO_DEVICE_FILE=/run/sculpture-audio-controller/audio-device" in unit
    assert "ExecStartPre=+/opt/sculpture/siren-app/scripts/select-audio-device.sh" in unit
    assert_journal_logging("sculpture-audio.service")


def test_ble_gateway_uses_audio_group_and_shared_runtime_files() -> None:
    unit = (SYSTEMD_DIR / "sculpture-ble-control.service").read_text(encoding="utf-8")

    assert "Group=audio" in unit
    assert "After=bluetooth.service NetworkManager.service sculpture-audio.service" in unit
    assert "SCULPTURE_COMMAND_FILE=/run/sculpture-audio-controller/command" in unit
    assert "SCULPTURE_STATUS_FILE=/run/sculpture-audio-controller/status.json" in unit
    assert "UMask=0002" in unit
    assert "ExecStart=/opt/sculpture/.venv/bin/python -m siren_app.ble_gateway" in unit
    assert "ExecStartPre=" not in unit
    assert_journal_logging("sculpture-ble-control.service")


def test_wittypi_clock_timer_retries_network_sync_after_boot() -> None:
    service = (SYSTEMD_DIR / "sculpture-wittypi-clock-sync.service").read_text(encoding="utf-8")
    timer = (SYSTEMD_DIR / "sculpture-wittypi-clock-sync.timer").read_text(encoding="utf-8")

    assert "After=wittypi.service network-online.target" in service
    assert "ExecStart=/opt/sculpture/siren-app/scripts/sync-wittypi-clock.sh" in service
    assert "OnBootSec=45s" in timer
    assert "OnUnitActiveSec=15min" in timer
    assert_journal_logging("sculpture-wittypi-clock-sync.service")


def test_healthcheck_writes_to_journal() -> None:
    assert_journal_logging("sculpture-healthcheck.service")
