# ET2500 watchdog and fan control

Linux external-watchdog modules and a fan-temperature publisher for the
Asterfusion ET2500 with a Marvell OCTEON 10 CN102 processor.

The watchdog uses Linux watchdog core and `/dev/watchdog-et2500`. An optional
systemd configuration lets PID1 supervise host liveness with a 30-second timeout.
The fan script publishes sensor temperatures to the board's CPLD through the
same kernel driver, avoiding competing userspace access to its I2C address.

## Components

| File | Purpose |
| --- | --- |
| `et2500_cpld_wdt.c` | Watchdog core integration, CPLD enable/disable and GPIO feed pulses |
| `et2500_wdt_board.c` | Register the device on the existing vendor device tree |
| `autofan.sh` | Publish LM75/TMP401 temperatures to the CPLD |
| `register.sh` | Discover the mux child bus and load both modules without arming |
| `host-policy/` | Optional systemd PID1 policy, plus bounded startup verification |
| `install.sh` | Back up and install modules, fan integration and host policy |
| `tests/pulse.c` | Hardware-independent pulse-state unit test |

Start with [INSTALL.md](INSTALL.md). The installer enables the supplied services
for subsequent boots; installation and watchdog activation are separate steps.
It also replaces `/usr/bin/autofan.sh` and the fan service after backing up local
files. Review it before using it on an existing installation.

## Design

- No permanently running feeder thread or busy polling in the driver.
- Each authorized ping schedules one bounded GPIO pulse using delayed work.
- I2C controls enable/disable and temperature publication, not routine feeding.
- Linux watchdog core provides deadlines, exclusive open and magic close.
- The optional health policy watches PID1/host liveness, not guests, VPNs or
  network reachability. It does not detect every partial service failure.
- Fan control here means publishing temperatures to the existing CPLD logic;
  this is not a generic fan PWM or tachometer driver.

## Hardware scope and testing

Tested on one ET2500 with a Marvell/Yocto Linux 6.18.52 kernel, ARM64 64 KiB pages,
Ubuntu 26.04 and systemd 259. The board helper depends on the vendor mux topology
and `gpio_thunderx` offset 45. Other kernels, firmware versions and boards need
review; this is not an upstream kernel driver or an official vendor release.

**An incorrect watchdog setup can reset the machine.** The observed initial
unfed grace was about 10 seconds, but after effective feeding stopped the reset
followed in about 1.6 seconds. These are different intervals. Preserve the
measured timing unless you have independently characterized the hardware.

See [hardware and design notes](docs/HARDWARE.md),
[validation and limits](docs/VALIDATION.md), and [host policy](host-policy/README.md).
No destructive reset-test program is included in the normal build/test target.

## License and origin

GPL-2.0-only. See [LICENSE](../LICENSE) and [NOTICE.md](NOTICE.md).
The hardware protocol and vendor waveform were researched from Asterfusion's
published implementation and verified on the test board. This project provides
replacement watchdog and fan integration using the standard Linux watchdog API.
