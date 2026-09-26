#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Register the verified board watchdog; opening its device is a separate policy.
set -eu
for candidate in /sys/class/watchdog/watchdog*/identity; do
    if [ -r "$candidate" ] && [ "$(cat "$candidate")" = 'ET2500 CPLD watchdog' ]; then
        exit 0
    fi
done
attempt=0
while [ ! -e /sys/bus/i2c/devices/0-0071/channel-1 ]; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 15 ] || { echo 'CPLD mux channel is unavailable' >&2; exit 1; }
    sleep 1
done
channel=$(readlink -f /sys/bus/i2c/devices/0-0071/channel-1)
child=${channel##*/i2c-}
case "$child" in ''|*[!0-9]*) exit 1;; esac
modprobe et2500_cpld_wdt
# Conservative margin for the approximately 1.6 s fed-state timeout measured
# on this ET2500. The approximately 10 s initial grace is NOT the feed timeout.
modprobe et2500_wdt_board adapter_nr="$child" hw_margin_ms=1400
for candidate in /sys/class/watchdog/watchdog*/identity; do
    if [ -r "$candidate" ] && [ "$(cat "$candidate")" = 'ET2500 CPLD watchdog' ]; then
        exit 0
    fi
done
echo 'ET2500 watchdog did not register' >&2
exit 1
