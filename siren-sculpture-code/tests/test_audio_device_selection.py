from __future__ import annotations

import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "siren-app" / "scripts" / "select-audio-device.sh"


def run_selector(
    tmp_path: Path,
    cards: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cards_file = tmp_path / "aplay-list"
    device_file = tmp_path / "run" / "audio-device"
    cards_file.write_text(cards, encoding="utf-8")
    env = {
        **os.environ,
        "APLAY_LIST_FILE": str(cards_file),
        "SCULPTURE_AUDIO_DEVICE_FILE": str(device_file),
        "SCULPTURE_SKIP_AUDIO_PROBE": "1",
        **(extra_env or {}),
    }
    return subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True, check=False)


def test_usb_audio_is_preferred_over_headphones(tmp_path: Path) -> None:
    result = run_selector(
        tmp_path,
        "card 0: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]\n"
        "card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]\n",
    )

    assert result.returncode == 0
    assert (tmp_path / "run" / "audio-device").read_text(encoding="utf-8") == "plughw:CARD=Device,DEV=0\n"
    assert "Selected USB audio output" in result.stdout


def test_headphones_are_used_when_usb_is_absent(tmp_path: Path) -> None:
    result = run_selector(
        tmp_path,
        "card 0: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]\n",
    )

    assert result.returncode == 0
    assert (tmp_path / "run" / "audio-device").read_text(encoding="utf-8") == "plughw:CARD=Headphones,DEV=0\n"
    assert "Selected on-board headphones audio output" in result.stdout


def test_headphones_are_used_when_usb_cannot_be_opened(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_aplay = fake_bin / "aplay"
    fake_aplay.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *CARD=Device*) exit 1 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_aplay.chmod(0o755)

    result = run_selector(
        tmp_path,
        "card 0: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]\n"
        "card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]\n",
        {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "SCULPTURE_SKIP_AUDIO_PROBE": "0",
        },
    )

    assert result.returncode == 0
    assert (tmp_path / "run" / "audio-device").read_text(encoding="utf-8") == "plughw:CARD=Headphones,DEV=0\n"
    assert "USB audio output was detected but could not be opened" in result.stderr


def test_selector_fails_when_no_supported_output_exists(tmp_path: Path) -> None:
    result = run_selector(
        tmp_path,
        "card 2: vc4hdmi [vc4-hdmi], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]\n",
    )

    assert result.returncode == 1
    assert "No supported audio output found" in result.stderr
