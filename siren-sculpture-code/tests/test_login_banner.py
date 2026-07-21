from pathlib import Path


BANNER = Path(__file__).parents[1] / "scripts" / "sculpture-login-banner.sh"


def test_ssh_banner_has_welcome_control_and_repository_messages() -> None:
    script = BANNER.read_text(encoding="utf-8")

    assert "Connected to '$(hostname)'" in script
    assert "Run 'sculpture-control'" in script
    assert "siren-sculpture-code is up to date" in script
    assert "siren-sculpture-code is NOT UP TO DATE" in script
    assert 'timeout "${_sculpture_fetch_timeout}"' in script
    assert "the Pi may be offline" in script


def test_stale_checkout_instructions_use_valid_safe_git_commands() -> None:
    script = BANNER.read_text(encoding="utf-8")

    assert "git pull --ff-only" in script
    assert "git lfs pull" in script
    assert "./sync-on-pi.sh" in script
    assert "--fs-only" not in script
