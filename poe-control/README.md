# ET2500 PoE control

A standalone web interface for the Asterfusion ET2500 PoE controller. Python's
standard library serves both the API and the browser interface: no nginx,
Node.js, pip packages, CDN or external fonts are required.

## Features

- Twelve copper ports with power, voltage, current, priority and power-mode controls.
- Physical front-panel view: blue means link up; orange means measured PoE delivery.
  Enabling PoE alone does not light the power indicator. Stale samples suppress LEDs.
- Four SFP link indicators, read-only; no PoE on SFP ports.
- Enable/disable, priority, and 15/30/60 W modes. Mode changes require an identified,
  supplying device; 60 W requires four-pair delivery.
- Confirmation before disabling power, validated controller replies, and readback
  of priority/mode changes. Writes are never automatically retried.
- A single serialized UART worker, bounded transport timeouts, background polling
  and an unprivileged, sandboxed systemd service.

Start with [INSTALL.md](INSTALL.md). The vendor UART executable
`API_BT_Share_workspace` must already be installed; it is **not included**.
This application replaces the vendor PoE command/UI layer, not that transport.

## Hardware assumptions

The physical ports 1–12 map to controller channels
`4,5,6,7,8,9,10,11,0,1,2,3`. Link information is read from Linux interfaces
`Ethernet0` through `Ethernet15`. If your interface naming or board revision
is different, check the mapping before controlling power. The generic copper
labels do not assume which ports are LAN, WAN or management.

The supported vendor transport uses `/dev/ttyAMA1` at 19200 baud, 8N1. Do not
run another PoE utility against that UART concurrently: the application lock
coordinates only cooperating instances of this service. Existing BSP controller
initialization may still be required after power-on; this service deliberately
does not run the vendor global initialization, LED/MMIO or watchdog routines.

Controller polling runs approximately every 8 seconds with viewers and every
60 seconds without them, plus transaction time. Link data follows those samples.
The displayed 150 W budget is a vendor software reference, not a measured PSU
rating or a software-enforced global power cap. Power-mode limits reflect the
vendor protocol, not a calibrated measurement guarantee.

## Access model

There is intentionally **no authentication or TLS**. Anyone on the configured
allowed network can control PoE. Bind to a specific trusted management IPv4
address, restrict the allowed CIDR, and do not expose the service to the Internet.
The default is loopback only. Requests must use that literal IP and port; DNS
aliases, wildcard binds and reverse proxies are not supported by the Host/Origin
checks. The per-process browser token is CSRF protection, not an access credential.

No hardware writes are performed merely by opening the page or restarting the
service. There is no application-level configuration persistence or replay;
retention of controller settings across power loss depends on the hardware/BSP.
Recent changes are kept in memory and successful actions are logged to journald.

## Validation

```sh
python3 -m unittest -q
```

Tests use captured protocol frames and a mock controller, including malformed
replies, power-mode selection, HTTP access checks and packaged assets. They do
not access the UART or change power. The original deployment was exercised on
an ET2500; publication-specific changes (loopback defaults, configurable systemd
address and generic port labels) are covered by local checks, not a new hardware
qualification across all port/device combinations.

## License

Code and documentation in this component: Apache-2.0. See [LICENSE](LICENSE)
and [NOTICE.md](NOTICE.md) for upstream provenance and the separate front-panel
illustration notice. This component does not inherit the watchdog's GPL license.
