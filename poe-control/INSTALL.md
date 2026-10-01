# Installation

These commands run on the ET2500 Linux host, from the `poe-control` directory.
Python 3.9 or newer and systemd are required. No Python packages need installing.
First verify the Asterfusion transport and UART exist:

```sh
test -x /usr/bin/API_BT_Share_workspace
ls -l /dev/ttyAMA1
```

The UART must be accessible to the `dialout` group. Do not change the console
UART permissions blindly: confirm this is the board's PoE UART. Stop any other
PoE program using it; this service does not coordinate with vendor utilities.

## Install files

```sh
getent group dialout >/dev/null || sudo groupadd --system dialout
id cn102-poe >/dev/null 2>&1 || sudo useradd --system --gid dialout --no-create-home --shell /usr/sbin/nologin cn102-poe
sudo install -d -m 0755 /opt/cn102-poe-web
sudo install -m 0644 server.py app.js style.css index.html front-panel-no-antennas.png /opt/cn102-poe-web/
sudo install -m 0644 cn102-poe-web.service /etc/systemd/system/
# Preserve an existing configuration when upgrading.
if ! sudo test -e /etc/cn102-poe-web.conf; then
    sudo install -m 0644 cn102-poe-web.conf.example /etc/cn102-poe-web.conf
fi
sudoedit /etc/cn102-poe-web.conf
```

Set `POE_BIND` to the host's specific management IPv4 address, `POE_ALLOW` to the
trusted client subnet in CIDR notation, and `POE_PORT` to an unused port (8088 by
default). Loopback defaults are suitable only for local access. Do not set
`POE_BIND=0.0.0.0`: strict Host checks require a specific IP. Permit this TCP port
from the chosen subnet in your existing host firewall if needed. Do not open it
on WAN. Ensure the management address is stable, for example with a DHCP reservation.

## Start and verify

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now cn102-poe-web.service
sudo systemctl status cn102-poe-web.service --no-pager
sudo journalctl -u cn102-poe-web.service -n 30 --no-pager
```

Open `http://MANAGEMENT_IP:8088/` using your configured address and port. Wait for
a complete controller scan; confirm port labels, actual link states and power
readings before using any controls. First startup adopts all current port
settings. Subsequent starts restore saved settings, including power enablement,
only on ports that differ. Back up `/var/lib/cn102-poe/ports.json`; do not reuse
another site's configuration. If an instance already runs under this service name,
`enable --now` does not reload its files; use `sudo systemctl restart
cn102-poe-web.service` after installing an update.

For a foreground diagnostic run, stop the service first and create a writable
runtime and state directories owned by its service user. `python3 server.py --help` lists the
bind, allowlist, backend, lock and state-file options; `--allow` can be repeated.
The shipped unit accepts one CIDR. It uses the same defaults for the vendor executable and
`/run/cn102-poe/transport.lock`.

## Stop or remove

```sh
sudo systemctl disable --now cn102-poe-web.service
```

Stopping the application does not turn off PoE. After stopping, its files may be
removed from `/opt/cn102-poe-web`, together with its unit and configuration, then
run `sudo systemctl daemon-reload`. Preserve the vendor transport and unrelated
BSP services. This application has no dependency on the watchdog/fan component.

## Persistent settings

The systemd unit creates `/var/lib/cn102-poe` with service-user ownership.
Every UI change is saved atomically in `ports.json` before hardware access.
Normal service restarts do not restart unchanged PoE ports. If a file is invalid,
the service refuses to apply it or overwrite it; inspect the journal.
An unsuccessful hardware write leaves saved intent for the next service start.
The UI distinguishes saved settings from controller settings. Preserve this
directory across application upgrades; removing it causes fresh adoption of
controller settings at the next start, not restoration of earlier preferences.
