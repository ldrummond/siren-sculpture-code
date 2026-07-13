# Witty Pi Schedule

Witty Pi should handle the hard power schedule for the installation:

- Wake the Raspberry Pi in the morning.
- Allow `systemd` to start the web and audio services.
- Initiate clean shutdown in the evening.
- Cut power after shutdown.
- Keep time through power interruptions with the RTC.

The Python app only guards playback inside the configured active window. It is
not the primary power scheduler.

After install:

- Confirm system time and Witty Pi RTC time.
- Confirm the morning startup and evening shutdown schedule manually.
- Replace `schedule.wpi` if the installed Witty Pi software expects a different format.
- Configure low-voltage shutdown through Witty Pi tools if supported by the installed version.
