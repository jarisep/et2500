# Hardware and design notes

## Verified board interface

| Component | Tested configuration |
| --- | --- |
| Parent I2C adapter | `i2c-0` |
| Mux | PCA954x at `0x71`, channel 1 |
| CPLD | `0x40` on that mux child |
| Enable control | register `0x0b`, bit 0; other bits preserved |
| Feed GPIO | `gpio_thunderx`, offset 45, active high |
| Board temperature | CPLD register `0x18` |
| SoC/maximum temperature | CPLD register `0x19` |
| Temperature sensors | LM75 at `0x48`, TMP401 at `0x18` |

The runtime I2C child number is discovered via
`/sys/bus/i2c/devices/0-0071/channel-1`; it is not hardcoded to i2c-3.
The board module validates the adapter name, supplies software properties and a
GPIO lookup, then creates the I2C client. It is unnecessary if a suitable real
DT node supplies equivalent properties; do not instantiate both.

## Pulse timing

Measured initial no-effective-feed grace: approximately 10.07 seconds.
After effective feeding stopped, first firmware output appeared approximately
1.64 seconds after the last falling edge. Those observations include firmware
startup delay and are not a precise electrical timeout specification.

Deployed values are `hw_margin_ms=1400`, high time 700 ms, minimum low time
300 ms. The watchdog core's maximum heartbeat is 2400 ms, including the pulse
window, yielding approximately 1200 ms between pings for a long software timeout.
The userspace/PID1 deadline is separately set to 30 seconds.

The implementation reprograms GPIO output direction at each transition, matching
the demonstrated vendor operation. Earlier GPIO character-device array-write
tests were inconclusive; they do not prove scalar `gpiod_set_value()` defective.
Each authorized ping schedules a bounded pulse. High-priority delayed work runs
brief callbacks; no callback sleeps through the 700/300 ms waveform, and there
is no autonomous perpetual feed loop masking userspace failure.

## Ownership and temperatures

Regmap read/modify/write and readback protect the watchdog enable bit. Start and
stop are serialized. Stop confirms hardware disable before cancelling work.
Ambiguous I2C failures pin the module and report failure; recovery is not
fault-injection tested. Probe refuses an already-armed CPLD.

The fan script discovers named sensors, validates readings, takes the maximum
TMP401 channel and publishes every five seconds. With the CPLD driver bound,
it writes `board_temperature` and `soc_temperature` sysfs attributes in
millidegrees Celsius (0..127000). Without a bound driver it retains the legacy
mux-child I2C path. It never forces access around an owning kernel driver.
The CPLD performs the underlying fan control; no RPM/PWM interface is added.

This temperature ABI is local to this project. An upstream proposal should
review a shared CPLD/MFD and thermal/hwmon design instead of assuming this ABI
is already accepted upstream.
