from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from siren_app import wittypi


class FakeConfig:
    def __init__(self, software_dir: str = "/home/admin/wittypi") -> None:
        self.software_dir = software_dir

    def get(self, key: str, default: object = None) -> object:
        if key == "wittypi.software_dir":
            return self.software_dir
        return default


def test_read_temperature_c_parses_wittypi_utility_output(monkeypatch) -> None:
    monkeypatch.setattr(
        wittypi,
        "_run_utility_function",
        lambda config, function_name: "35.625\u00b0C / 96.125\u00b0F",
    )

    assert wittypi.read_temperature_c(FakeConfig()) == 35.625  # type: ignore[arg-type]


def test_read_temperature_c_handles_missing_output(monkeypatch) -> None:
    monkeypatch.setattr(wittypi, "_run_utility_function", lambda config, function_name: None)

    assert wittypi.read_temperature_c(FakeConfig()) is None  # type: ignore[arg-type]


def test_read_rtc_time_parses_wittypi_utility_output(monkeypatch) -> None:
    monkeypatch.setattr(
        wittypi,
        "_run_utility_function",
        lambda config, function_name: "2026-07-09 11:10:18 MDT",
    )

    result = wittypi.read_rtc_time(FakeConfig())  # type: ignore[arg-type]

    assert result is not None
    assert result.replace(tzinfo=None) == datetime(2026, 7, 9, 11, 10, 18)


def test_read_rtc_time_handles_unavailable_rtc(monkeypatch) -> None:
    monkeypatch.setattr(wittypi, "_run_utility_function", lambda config, function_name: "N/A")

    assert wittypi.read_rtc_time(FakeConfig()) is None  # type: ignore[arg-type]


def test_get_wittypi_status_includes_time_and_temperature(monkeypatch) -> None:
    monkeypatch.setattr(wittypi, "is_wittypi_installed", lambda config: True)
    monkeypatch.setattr(wittypi, "get_recent_wittypi_logs", lambda config: [])
    monkeypatch.setattr(wittypi, "read_temperature_c", lambda config: 25.0)
    monkeypatch.setattr(wittypi, "read_rtc_time", lambda config: datetime(2026, 7, 9, 11, 10, 18))

    status = wittypi.get_wittypi_status(FakeConfig())  # type: ignore[arg-type]

    assert status["temperature_c"] == 25.0
    assert status["temperature_f"] == 77.0
    assert status["rtc_time"].startswith("2026-07-09T11:10:18")


def test_run_utility_function_uses_configured_wittypi_dir(monkeypatch, tmp_path: Path) -> None:
    software_dir = tmp_path / "wittypi"
    software_dir.mkdir()
    (software_dir / "utilities.sh").write_text("", encoding="utf-8")
    calls = []

    class Result:
        returncode = 0
        stdout = "29\u00b0C / 84.2\u00b0F\n"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr(wittypi.subprocess, "run", fake_run)

    output = wittypi._run_utility_function(FakeConfig(str(software_dir)), "get_temperature")  # type: ignore[arg-type]

    assert output == "29\u00b0C / 84.2\u00b0F"
    assert calls[0][0] == ["bash", "-lc", "source ./utilities.sh >/dev/null 2>&1 && get_temperature"]
    assert calls[0][1]["cwd"] == software_dir


def test_run_utility_function_rejects_unknown_functions() -> None:
    with pytest.raises(ValueError):
        wittypi._run_utility_function(FakeConfig(), "rm -rf /")  # type: ignore[arg-type]
