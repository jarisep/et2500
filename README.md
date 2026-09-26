# ET2500

Linux modules, tools and hardware notes for the Asterfusion ET2500 with a
Marvell OCTEON 10 CN102 processor. Each component has its own source,
installation instructions and validation notes.

## Components

| Directory | Contents |
| --- | --- |
| [poe-control/](poe-control/) | Standalone PoE web control with a physical port view and systemd service |
| [watchdog-fancontrol/](watchdog-fancontrol/) | External CPLD/GPIO watchdog, fan-temperature publisher and optional systemd host-supervision policy |

For watchdog and fan setup, start with the
[component overview](watchdog-fancontrol/README.md) and
[installation guide](watchdog-fancontrol/INSTALL.md). Build and installation
commands run from the component directory, not the repository root.

## License

Licenses are component-specific:

| Component | License |
| --- | --- |
| Watchdog and fan control | GPL-2.0-only: [LICENSE](LICENSE), [provenance](watchdog-fancontrol/NOTICE.md) |
| PoE application code and documentation | Apache-2.0: [license](poe-control/LICENSE), [provenance and artwork notice](poe-control/NOTICE.md) |

The root GPL license applies to the watchdog/fan component; it does not override
the separately licensed PoE component.

This is an independent project, not an official Asterfusion or Marvell release.
