from pathlib import Path


CONTROL_PAGE = Path(__file__).parents[1] / "web-bluetooth" / "siren-control.html"


def test_mode_toggle_remains_visible_in_testing_mode() -> None:
    html = CONTROL_PAGE.read_text(encoding="utf-8")
    sculpture_controls = html.split('<div class="row" id="sculptureControls">', 1)[1].split("</div>", 1)[0]

    assert html.count('id="modeToggle"') == 1
    assert 'id="modeToggle"' not in sculpture_controls
    assert "document.getElementById('sculptureControls').hidden = testing;" in html


def test_pending_synchronization_is_shown_beside_sculpture_control() -> None:
    html = CONTROL_PAGE.read_text(encoding="utf-8")
    sculpture_controls = html.split('<div class="row" id="sculptureControls">', 1)[1].split("</div>", 1)[0]

    assert "scheduledSyncAt = typeof audio.sync_at === 'number' ? audio.sync_at : null;" in html
    assert 'id="syncResetChip"' in sculpture_controls
    assert "Will restart audio to synchronize sirens at:" in html
    assert "lastSynchronizedAt = typeof audio.synced_at === 'number' ? audio.synced_at : null;" in html
    assert "Synchronized at ${resetTime}" in html
    assert "chip.classList.add('scheduled');" in html
    assert "chip.classList.add('on');" in html
    assert "updateSynchronizationChip();" in html
    assert "Synchronization reset scheduled for" not in html


def test_interface_waits_for_queued_command_confirmation() -> None:
    html = CONTROL_PAGE.read_text(encoding="utf-8")

    assert "COMMAND_CONFIRMATION_TIMEOUT_MS = 15000" in html
    assert "await waitForCommandConfirmation(response.command_id, action)" in html
    assert "audio.cmd === commandId" in html
    assert "Waiting for ${formatAction(action)} to finish..." in html


def test_untrusted_clock_shows_autoplay_resync_warning() -> None:
    html = CONTROL_PAGE.read_text(encoding="utf-8")

    assert 'id="clockAlert"' in html
    assert 'id="clockStatus"' in html
    assert "Sculpture Mode is autoplaying" in html
    assert "To use clock-based playback" in html
    assert "Send Time to Resync" in html
    assert "if (trusted === false)" in html
