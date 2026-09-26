# License and provenance

The application code and documentation in this directory are distributed under
Apache License 2.0; see [LICENSE](LICENSE). Modifications and the web application
were prepared for this project in 2026. Preserve existing attribution notices.

The ET2500 port mapping, command templates, status sets and power-mode decoding
were reimplemented from Asterfusion's `PoeCommand.cc`, `StructFormatter.cc` and
`Utils.cc` in [Helium_DPU / ET2500 / Platform / POE_DeviceControl](https://github.com/asterfusion/Helium_DPU/tree/d57b2eb635264938257a52d32938b3e1d9773fa6/ET2500/Platform/POE_DeviceControl).
The reviewed revision is `d57b2eb635264938257a52d32938b3e1d9773fa6`.
Its repository root carries the [Apache 2.0 license](https://github.com/asterfusion/Helium_DPU/blob/d57b2eb635264938257a52d32938b3e1d9773fa6/LICENSE).

Changes include a Python implementation of protocol handling with checksum,
length, echo and ACK validation; serialized access and bounded subprocesses;
validated web controls and mode readback; a standalone HTTP server and browser
interface; live Linux link readings; and systemd packaging. The original vendor
C++ application is not bundled. The required `API_BT_Share_workspace` executable
is an external vendor-supplied dependency, not redistributed or relicensed here.

## Front-panel illustration

`front-panel-no-antennas.png` is an edited version of the Asterfusion ET2500
product diagram supplied by the project owner. AI-assisted edits removed antenna
connectors and diagram annotations; JavaScript/SVG adds interactive port overlays.
The original diagram's publication/license source has not been established.
The Apache license declaration above applies to application code and documentation,
not a grant of rights to underlying third-party artwork or the Asterfusion logo.
The illustration is included as a hardware reference; downstream users should
verify the artwork rights for their intended redistribution or replace it.

This is an independent project, without endorsement from Asterfusion or Marvell.
