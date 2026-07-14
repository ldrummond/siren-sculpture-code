# Witty Pi Schedule

Witty Pi should handle the hard power schedule for the installation:

- Wake the Raspberry Pi in the morning.
- Allow `systemd` to start the web and audio services.
- Initiate clean shutdown in the evening.
- Cut power after shutdown.
- Keep time through power interruptions with the RTC.

The Python app only guards playback inside the configured active window. It is
not the primary power scheduler.

## Clock Safety

The project applies a guarded patch to the standard Witty Pi daemon during
installation:

- A plausible RTC initializes system time during boot.
- An invalid RTC is never overwritten from an unverified system clock.
- `/run/sculpture-clock-trusted` records that boot-time clock validation passed.
- Sculpture Mode playback remains disabled while that marker is absent.
- Testing Mode remains available without a trusted clock.

`sculpture-wittypi-clock-sync.timer` re-enables operating-system NTP after the
vendor daemon and checks every 15 minutes. It writes system time to the RTC only
after `timedatectl` reports `NTPSynchronized=yes`, verifies the RTC write, and
then creates the trust marker. The timer writes the RTC at most once per boot.

When Wi-Fi is unavailable, the hosted Web Bluetooth controller can use **Set
Time From This Device** as a manual recovery path. It sends the browser device's
Unix timestamp, temporarily pauses scheduled playback by removing the trust
marker, sets Linux time, writes the Witty Pi RTC through `system_to_rtc`, and
restores trust only after the RTC readback is within 10 seconds. The operator
must confirm that the phone or computer clock is accurate.

If a future vendor release changes the daemon's synchronization block, the
installer stops with an error rather than applying an unverified patch.

After install:

- Confirm system time and Witty Pi RTC time.
- Confirm `systemctl status sculpture-wittypi-clock-sync.timer` is active.
- Confirm `/run/sculpture-clock-trusted` exists before relying on scheduled playback.
- Confirm the morning startup and evening shutdown schedule manually.
- Replace `schedule.wpi` if the installed Witty Pi software expects a different format.
- Configure low-voltage shutdown through Witty Pi tools if supported by the installed version.
