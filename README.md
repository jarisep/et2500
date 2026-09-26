# ET2500

Linux modules, tools and hardware notes for the Asterfusion ET2500 with a
Marvell OCTEON 10 CN102 processor. Each component has its own source,
installation instructions and validation notes.

## Components

| Directory | Contents |
| --- | --- |
| [watchdog-fancontrol/](watchdog-fancontrol/) | External CPLD/GPIO watchdog, fan-temperature publisher and optional systemd host-supervision policy |

For watchdog and fan setup, start with the
[component overview](watchdog-fancontrol/README.md) and
[installation guide](watchdog-fancontrol/INSTALL.md). Build and installation
commands run from the component directory, not the repository root.

## License

GPL-2.0-only. See [LICENSE](LICENSE) and the
[watchdog/fan provenance notes](watchdog-fancontrol/NOTICE.md).

This is an independent project, not an official Asterfusion or Marvell release.
