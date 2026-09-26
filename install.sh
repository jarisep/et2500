#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Install for the RUNNING kernel. Never unload or arm a watchdog here.
set -euo pipefail
cd -- "$(dirname -- "$0")"
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
kernel=$(uname -r)
for identity in /sys/class/watchdog/watchdog*/identity; do
    [[ -r $identity ]] || continue
    if [[ $(<"$identity") == 'ET2500 CPLD watchdog' &&
          $(<"${identity%identity}state") != inactive ]]; then
        echo 'Disable PID1 protection using INSTALL.md before maintenance.' >&2
        exit 1
    fi
done
if systemctl is-active --quiet tpk_wdt.service || lsmod | grep -q '^tpk_wdt '; then
    echo 'Vendor watchdog is present: use the documented migration first.' >&2
    exit 1
fi
for module in et2500_cpld_wdt et2500_wdt_board; do
    [[ $(modinfo -F vermagic "$module.ko") == "$kernel "* ]] || {
        echo "Rebuild $module for $kernel first." >&2; exit 1;
    }
done
backup="/var/backups/et2500-watchdog-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup"
for path in /usr/bin/autofan.sh /etc/systemd/system/autofan.service \
    /etc/systemd/system/autofan.service.d/restart-delay.conf \
    /etc/systemd/system/cn102-external-watchdog.service \
    /etc/systemd/system/cn102-host-watchdog.service \
    /etc/systemd/system.conf.d/50-et2500-watchdog.conf \
    /etc/udev/rules.d/70-et2500-watchdog.rules \
    /usr/local/libexec/cn102-register-watchdog \
    /usr/local/libexec/cn102-enable-host-watchdog \
    "/lib/modules/$kernel/extra/cn102/et2500_cpld_wdt.ko" \
    "/lib/modules/$kernel/extra/cn102/et2500_wdt_board.ko"; do
    if [[ -e $path ]]; then cp -a --parents "$path" "$backup/"; fi
done
install -d "/lib/modules/$kernel/extra/cn102" /usr/local/libexec \
    /etc/systemd/system/autofan.service.d /etc/systemd/system.conf.d \
    /etc/udev/rules.d
install -m 644 et2500_cpld_wdt.ko et2500_wdt_board.ko "/lib/modules/$kernel/extra/cn102/"
depmod -a "$kernel"
install -m 755 register.sh /usr/local/libexec/cn102-register-watchdog
install -m 755 host-policy/enable-host-watchdog.py /usr/local/libexec/cn102-enable-host-watchdog
install -m 755 autofan.sh /usr/bin/autofan.sh
install -m 644 autofan.service cn102-external-watchdog.service \
    host-policy/cn102-host-watchdog.service /etc/systemd/system/
install -m 644 autofan-restart-delay.conf /etc/systemd/system/autofan.service.d/restart-delay.conf
install -m 644 host-policy/50-et2500-watchdog.conf /etc/systemd/system.conf.d/
install -m 644 70-et2500-watchdog.rules /etc/udev/rules.d/
systemctl mask tpk_wdt.service
systemctl daemon-reload
udevadm control --reload-rules
systemctl enable cn102-external-watchdog.service cn102-host-watchdog.service autofan.service
echo "Installed; backup: $backup"
echo 'No module was unloaded or watchdog explicitly armed. Follow INSTALL.md to activate.'
