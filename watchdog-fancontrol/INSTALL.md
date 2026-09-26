# Installation on an ET2500

These are external kernel modules: building a full new kernel is unnecessary.
Use root privileges only for installation and service operations. The commands
below assume Bash and the board/kernel described in [README.md](README.md).

## 1. Build

```sh
git clone https://github.com/jarisep/et2500.git
cd et2500/watchdog-fancontrol
test -e /lib/modules/"$(uname -r)"/build/Makefile
make > build.log 2>&1 && make test > test.log 2>&1
```

Requires gcc, make, matching kernel headers/build files, Python 3, kmod, systemd,
udev and i2c-tools. The pulse test additionally requires ASan/UBSan support from
the compiler. The board kernel needs watchdog core, I2C/regmap, the PCA954x mux,
GPIO and the LM75/TMP401 sensor drivers. See [HARDWARE.md](docs/HARDWARE.md).
Check the exit status and inspect logs on failure. `make test` accesses no
hardware. The supplied DT example is illustrative, not a validated upstream binding.

## 2. Prepare the board

The CPLD watchdog must be inactive before installation or module replacement.
The installer refuses a registered active ET2500 watchdog or a running vendor
`tpk_wdt` module/service. If the old vendor feeder is running, first establish a
board-specific, verified disable procedure: killing its process is not enough.
Do not activate two independent watchdog clients or overwrite another existing
systemd watchdog policy without reviewing it.

For upgrades of this driver's active installation, use the maintenance procedure
below first. Keep an independent serial console and a working rollback kernel.

## 3. Install and activate

As root, from the `watchdog-fancontrol/` directory:

```sh
bash ./install.sh
systemctl start cn102-external-watchdog.service
udevadm trigger --subsystem-match=watchdog
udevadm settle --timeout=10
systemctl restart autofan.service
systemctl daemon-reexec
systemctl restart cn102-host-watchdog.service
```

The installer targets the running kernel and checks module vermagic. It backs up
replaced files under `/var/backups/et2500-watchdog-TIMESTAMP/`, installs the
modules and fan integration, masks the legacy vendor service and enables boot
persistence. No module is unloaded by the installer.

The registration service creates the device but does not arm it. The supplied
manager drop-in sets `WatchdogDevice=/dev/watchdog-et2500` and
`RuntimeWatchdogSec=30s`; daemon-reexec or a subsequent boot can therefore arm
it. The host-policy oneshot ensures activation after the late-loaded driver is
available. There is no extra userspace daemon continuously feeding the watchdog.

## 4. Verify

```sh
systemctl --failed
systemctl status cn102-external-watchdog cn102-host-watchdog autofan --no-pager
systemctl show -p WatchdogDevice -p RuntimeWatchdogUSec -p WatchdogLastPingTimestampMonotonic
device=$(readlink -f /dev/watchdog-et2500)
cat /sys/class/watchdog/"${device##*/}"/{identity,state,timeout}
```

Expect `ET2500 CPLD watchdog`, `active`, `30`, and no failed installation units.
Repeat the manager ping-timestamp query after more than 60 seconds; it must
advance. The numeric watchdog index can change, so use the stable symlink.
Check `journalctl -u autofan` for continuing temperature updates. Perform a
controlled, serial-observed reboot and repeat the checks before relying on it.

## Maintenance and removal

Stopping the registration or host-policy oneshot does **not** stop PID1's
watchdog. Before replacing or unloading the running modules:

1. Set `RuntimeWatchdogSec=0` in
   `/etc/systemd/system.conf.d/50-et2500-watchdog.conf`.
2. Run as root:

```sh
systemctl disable cn102-host-watchdog.service
busctl set-property org.freedesktop.systemd1 /org/freedesktop/systemd1 \
  org.freedesktop.systemd1.Manager RuntimeWatchdogUSec t 0
systemctl daemon-reexec
device=$(readlink -f /dev/watchdog-et2500)
cat /sys/class/watchdog/"${device##*/}"/state
```

3. Verify `inactive` before proceeding. If it is still active, stop and investigate.
4. Stop the fan publisher, then unload the main module before its board helper:

```sh
systemctl stop autofan.service
rmmod et2500_cpld_wdt
rmmod et2500_wdt_board
systemctl stop cn102-external-watchdog.service
```

For an upgrade, rebuild and repeat step 3 (install and activate). The installer
restores the 30-second manager setting and boot enablement. For removal, disable
the registration service too; the supplied fan script can use its legacy I2C
fallback when no driver owns the CPLD. Restore any previous policy deliberately.
Never force module unload, delete an active I2C device or bypass ownership using
`i2cset -f`. With nowayout enabled, this normal disable workflow may not be available.

## A new kernel

Rebuild both modules for every new kernel. To stage another kernel while the
current watchdog stays active:

```sh
make KDIR=/path/to/new/kernel/build > build.log 2>&1
```

Check both modules' vermagic, copy them into that kernel's
`/lib/modules/NEW_RELEASE/extra/cn102/`, then run `depmod -a NEW_RELEASE` before
booting it. The provided installer deliberately supports the running kernel
only. Keep the services, udev rule, fan script and host-policy files. Preserve
your bootloader settings and old kernel/modules for rollback.
