# Host supervision with systemd

The optional policy selects `/dev/watchdog-et2500` and sets
`RuntimeWatchdogSec=30s`. PID1 owns and feeds the watchdog. No guest, VPN, port
link or Internet reachability condition participates in feeding decisions.
A partial service failure that leaves PID1 responsive is outside this policy.

The board driver can register after systemd's initial hardware-watchdog setup.
`cn102-host-watchdog.service` therefore follows registration and asks PID1 to
retry activation through its writable `RuntimeWatchdogUSec` D-Bus property.
The helper checks the device identity first, then waits up to five seconds for
active state, the 30-second timeout and PID1's matching character-device
file descriptor. It never opens or feeds the watchdog itself and exits after
verification. The observed D-Bus reply can precede actual activation at boot.

Tested with systemd 259.5. Other versions require verification of their D-Bus
property behavior. No separate feeding daemon is used. The manager's existing
reboot/kexec watchdog settings are not modified by the drop-in.

Stopping or disabling only the setup unit does not stop the watchdog. Follow
[the maintenance procedure](../INSTALL.md#maintenance-and-removal) to explicitly
disable PID1 protection and verify inactive state before module maintenance.
Rebuild both external modules for every kernel update, retain a rollback kernel
and check the activation service after a controlled reboot.
