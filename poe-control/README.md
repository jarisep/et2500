# ET2500 PoE control

Self-contained Python HTTP service and front-panel UI. See INSTALL.md for per-site setup. No separate web server or Python packages.

## Port settings and telemetry

The UI shows saved settings separately from live controller settings and actual
power delivery. Enable/disable, power profile, legacy detection and priority can
be viewed and changed even with PoE disabled or no attached device. Empty but
enabled ports remain enabled in the saved configuration.

The selected profile is a ceiling, not measured consumption. The 60 W profile
permits 60 W with four-pair delivery and 30 W with two-pair delivery. A profile
does not prove that the board, PSU or PD supports its maximum. The 150 W display
is the vendor software's reference budget, not a measured PSU identification.
The UI offers 15/30/60 W profiles and retains an existing 90/30 W profile without
offering it as a new selection. Profile changes clear extra-power allowance.

Actual detection is shown as IEEE, single/dual-signature IEEE where reported,
or legacy/non-IEEE. Delivered pair count is decoded from the actual status:
0x83 and 0x85 use two pairs even though the controller port has a four-pair
matrix. A/B is displayed only when explicitly reported (0x82 means A only);
other states say Not reported. No IEEE generation or A/B wiring is inferred
from a mode setting. Measurements show watts, volts, milliamps and Linux link
speed/duplex. LEDs require fresh telemetry and measured power above zero.

Legacy detection is not force power and does not select a 24 V supply. Verify
the attached device before enabling it. Profile/detection changes may restart
that port; other ports are untouched. Global reset, force power, matrix changes,
controller firmware updates and automatic repeated writes are not implemented.

## Persistent settings and startup restoration

The existing `cn102-poe-web.service` owns both restoration and HTTP control.
There is no second competing UART daemon. Its systemd StateDirectory is
`/var/lib/cn102-poe` (0700), with `ports.json` (0600). Back up this file along with
the service and application. Do not copy one site's port settings to another.

- On the first start without a state file, read all 12 ports and adopt their
  current administrative settings without changing power.
- Save every requested change atomically using a temporary file, file fsync,
  rename and directory fsync, before issuing the hardware command.
- At subsequent service/OS starts, read and validate every port before writing.
  Apply only differing settings. Unchanged ports receive no write, avoiding
  unnecessary camera restarts. Each write is acknowledged and read back.
- Preserve enabled state, operation mode (including legacy), priority, CFG2 and
  extra-power allowance. Reject force-power enable modes and unsupported
  operation profiles rather than guessing.
- A malformed/incomplete saved file prevents startup and is not overwritten.
  A failed initial controller scan cannot cause partial automatic adoption.
- If a write or readback fails after saving, the UI returns an explicit error.
  Saved intent remains, and a settings mismatch is visible after refresh.
  Startup retries saved intent; the normal poll loop never repeatedly writes.
- Stopping/restarting the web service does not globally disable PoE. Restart
  restores differing settings only. The service does not save to controller
  flash. Settings changed outside this application are not automatically
  adopted and will be replaced by saved settings on its next start.

Startup restoration occurs before opening the HTTP listener, under the same
exclusive process lock. The service starts at boot, runs as `cn102-poe`, and
systemd retries startup if the controller or bind address is not ready. A total
power-loss/cold-boot test has not yet been performed with this version.

## Installation and access

Installed files: `/opt/cn102-poe-web/`.
Unit: `/etc/systemd/system/cn102-poe-web.service`. Configure its environment
file before enabling it; follow INSTALL.md.
Transport: `/usr/bin/API_BT_Share_workspace`, UART `/dev/ttyAMA1`, 19200 8N1.
Runtime lock: `/run/cn102-poe/transport.lock`.

Install the supplied unit with `StateDirectory=cn102-poe`, keep the `cn102-poe`
user in `dialout`, install application/static files, then:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now cn102-poe-web
# For upgrades of an already running instance:
sudo systemctl restart cn102-poe-web
sudo journalctl -u cn102-poe-web -n 30 --no-pager
```

No authentication. Bind to a trusted management IP and restrict the client subnet
with the supplied environment configuration. Keep the service off WAN.
Same-origin, Host, JSON and CSRF checks are browser protections, not authentication.
Every allowed client can read and change settings. See INSTALL.md.

Do not run the old vendor CLI concurrently: it ignores the application lock.
Stop this service first for manual UART diagnostics. No CPLD/I2C, watchdog,
network forwarding or physical LED registers are touched by this application.

## Protocol provenance

Asterfusion `PoeCommand.cc`, `StructFormatter.cc` and `Utils.cc`, reviewed at
commit d57b2eb635264938257a52d32938b3e1d9773fa6:
https://github.com/asterfusion/Helium_DPU/tree/main/ET2500/Platform/POE_DeviceControl

Additional field/status verification: Microchip PD69200 BT Serial Communication
Protocol rev 3.23, sections 4.3.6/4.3.7 and Table 4:
https://ww1.microchip.com/downloads/en/softwarelibrary/poe_pd6920x_p3_42/PD69200_BT-PoE_SerComm_Protocol%20323%20v1_PD-000353781.pdf

Physical copper ports1–8 map to controller channels4–11, ports9–12 to0–3.
The API validates 15-byte frame length, checksum, echo, command and write ACK.
Subprocesses have a 2.5-second deadline. No shell wrapper is invoked.

## Verification, 2026-10-01

17 tests cover real captured frames, corrupted frames/ACKs, actual pair decoding,
disabled-port settings, write/readback validation, first adoption, restore after
simulated controller reset, no-op restarts, corrupt/partial state, persistence
failure before hardware access, saved intent after hardware failure, and HTTP
request/origin checks. Run `python3 -m unittest -q` in this directory.

Hardware validation covered initial adoption, saving settings on a disabled
port, restoring those settings after changing the controller configuration,
and a no-op service restart. Other powered ports remained operational.
Browser checks covered configured values, actual delivered pair count and
disabled-port controls. A full cold-boot test is still pending.

Source and artwork attribution: see NOTICE.md. UI port labels are physical
numbers, not inferred network roles.
