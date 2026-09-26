# Validation on the development board

Tests completed on 2026-09-26 using the ET2500/CN102 configuration described in
the README. Results describe one board, not a universal hardware guarantee.

- W=1 ARM64 module builds and checkpatch passed during development.
- Shared pulse-state tests passed with address/undefined-behavior sanitizers.
- Explicit disable and magic close stopped the watchdog; exclusive-open and
  invalid-timeout checks passed.
- With a 30-second watchdog-core deadline, terminating the userspace test
  client caused the first reset firmware output about 29.947 seconds later.
- Firmware reported `CHIP_RESET_PIN` for watchdog expiry. This establishes an
  external chip-reset input, not necessarily a full power cycle of peripherals.
- Inactive driver unload/reload and the board-helper lifetime were checked.
- Fan temperature publication continued through the driver's sysfs attributes.
- Controlled normal reboots restored registration and PID1 supervision without
  failed watchdog/fan services. PID1 pings advanced across multiple deadlines.
- A boot-time validation race was fixed by waiting up to five seconds for
  active state, timeout and PID1 device ownership after the D-Bus call.
- Modules were rebuilt and normal boot verified after a kernel package update.

Do not infer an isolated CPU-overhead number from whole-host idle measurements.
Heavy CPU saturation, extreme temperature, I2C fault injection, suspend/resume
and nowayout recovery have not been exhaustively tested. The nominal feed window
is short; scheduler or GPIO failures can intentionally result in a reset.

`make test` runs only the hardware-independent state-machine test. It does not
exercise CPLD enable, GPIO pulses or reset hardware. Verify those only with
independent console access and a deliberate board-specific test plan.
