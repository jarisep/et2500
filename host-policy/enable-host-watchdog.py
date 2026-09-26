#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Select only the verified external device and let PID1 own its health deadline."""
import os
from pathlib import Path
import stat
import subprocess
import time

node = Path('/dev/watchdog-et2500')
subprocess.run(['udevadm', 'settle', '--timeout=10'], check=True)
resolved = node.resolve(strict=True)
identity = Path('/sys/class/watchdog') / resolved.name
if (identity / 'identity').read_text().strip() != 'ET2500 CPLD watchdog':
    raise SystemExit('Refusing unexpected watchdog identity')
info = node.stat()
if not stat.S_ISCHR(info.st_mode):
    raise SystemExit('Watchdog is not a character device')
configured = subprocess.check_output(
    ['systemctl', 'show', '-p', 'WatchdogDevice', '--value'], text=True).strip()
if configured != str(node):
    raise SystemExit('PID1 has not loaded the explicit ET2500 device selection')
# Retry opening the device after the late-loaded board driver becomes available.
# systemd's D-Bus setter invokes watchdog_setup even if the timeout is unchanged.
subprocess.run(['busctl', 'set-property', 'org.freedesktop.systemd1',
                '/org/freedesktop/systemd1', 'org.freedesktop.systemd1.Manager',
                'RuntimeWatchdogUSec', 't', '30000000'], check=True)
# At boot PID1 can apply the property after replying to the D-Bus call.
# Observe all postconditions without opening or feeding the device ourselves.
deadline = time.monotonic() + 5
while True:
    owned = False
    for fd in Path('/proc/1/fd').iterdir():
        try:
            target = fd.stat()
            if stat.S_ISCHR(target.st_mode) and target.st_rdev == info.st_rdev:
                owned = True
                break
        except FileNotFoundError:
            pass
    if (owned and (identity / 'state').read_text().strip() == 'active'
            and (identity / 'timeout').read_text().strip() == '30'):
        break
    if time.monotonic() >= deadline:
        raise SystemExit('ET2500 watchdog activation not confirmed within 5 seconds')
    time.sleep(0.1)
print('ET2500 host watchdog active: PID1 owns device, timeout 30 seconds')
