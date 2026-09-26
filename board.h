/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ET2500_BOARD_H
#define ET2500_BOARD_H
struct module;
/* Optional lifetime guard for the temporary, non-DT board registration module. */
struct et2500_board_data {
	struct module *owner;
};
#endif
