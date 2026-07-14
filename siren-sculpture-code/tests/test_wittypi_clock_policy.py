from pathlib import Path


PROJECT_DIR = Path(__file__).parents[1]
SCRIPTS_DIR = PROJECT_DIR / "siren-app" / "scripts"


def test_clock_patch_removes_unsafe_invalid_rtc_write() -> None:
    script = (SCRIPTS_DIR / "patch-wittypi-clock-policy.sh").read_text(encoding="utf-8")
    managed_block = script.split('managed_block = """', 1)[1].split('"""', 1)[0]

    assert "SCULPTURE_CLOCK_POLICY_V1" in managed_block
    assert "RTC time is invalid; leave RTC unchanged" in managed_block
    assert "system_to_rtc" not in managed_block
    assert "rtc_to_system" in managed_block


def test_network_sync_requires_ntp_before_writing_rtc() -> None:
    script = (SCRIPTS_DIR / "sync-wittypi-clock.sh").read_text(encoding="utf-8")

    ntp_check = script.index("NTPSynchronized")
    rtc_write = script.index("system_to_rtc")
    assert ntp_check < rtc_write
    assert "leaving the Witty Pi RTC unchanged" in script
    assert 'touch "${CLOCK_TRUST_FILE}" "${NETWORK_SYNC_FILE}"' in script


def test_wittypi_configuration_applies_clock_policy_patch() -> None:
    script = (SCRIPTS_DIR / "configure-wittypi.sh").read_text(encoding="utf-8")

    assert '"${APP_DIR}/siren-app/scripts/patch-wittypi-clock-policy.sh"' in script
