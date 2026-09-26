# License and provenance

The source, scripts and accompanying project documentation in this component
are distributed under GNU GPL version 2 only (`GPL-2.0-only`). The complete
license is in [../LICENSE](../LICENSE). Existing copyright and license notices must be retained.

Hardware register assignments and the legacy feed waveform were researched
using Asterfusion's publicly distributed ET2500 watchdog code, board scripts
and controlled observations on an ET2500. The reference patch is:

- Repository: https://github.com/asterfusion/DPU_linux_kernel
- Revision: `3f635c5ff3b7457f18e33bc647e72051b129fad7`
- File: `patches/0002-add-tpk_wdt.patch`
- Patch author: lilinwei (Asterfusion); subject: `add tpk_wdt`
- Reference source declares `MODULE_LICENSE("GPL")`.

This repository contains a replacement watchdog implementation and a rewritten
fan-temperature publisher, rather than redistributing the original vendor
patch. The original vendor code is not included. Its module metadata alone
should not be treated as a complete license notice for arbitrary vendor files.

The code uses the Linux watchdog, GPIO, I2C and regmap APIs. The host policy uses
systemd's watchdog manager properties. This project is independent of and is
not endorsed by Asterfusion, Marvell or the Linux kernel project.
