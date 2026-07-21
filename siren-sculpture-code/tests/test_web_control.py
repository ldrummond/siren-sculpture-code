from pathlib import Path


CONTROL_PAGE = Path(__file__).parents[1] / "web-bluetooth" / "siren-control.html"


def test_mode_toggle_remains_visible_in_testing_mode() -> None:
    html = CONTROL_PAGE.read_text(encoding="utf-8")
    sculpture_controls = html.split('<div class="row" id="sculptureControls">', 1)[1].split("</div>", 1)[0]

    assert html.count('id="modeToggle"') == 1
    assert 'id="modeToggle"' not in sculpture_controls
    assert "document.getElementById('sculptureControls').hidden = testing;" in html


def test_pending_synchronization_is_written_to_control_log() -> None:
    html = CONTROL_PAGE.read_text(encoding="utf-8")

    assert "scheduledSyncAt = typeof audio.sync_at === 'number' ? audio.sync_at : null;" in html
    assert "Synchronization reset scheduled for" in html


def test_interface_waits_for_queued_command_confirmation() -> None:
    html = CONTROL_PAGE.read_text(encoding="utf-8")

    assert "COMMAND_CONFIRMATION_TIMEOUT_MS = 15000" in html
    assert "await waitForCommandConfirmation(response.command_id, action)" in html
    assert "audio.cmd === commandId" in html
    assert "Waiting for ${formatAction(action)} to finish..." in html
