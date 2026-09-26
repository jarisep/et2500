/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include "../pulse.h"
int main(void)
{
	struct et2500_pulse p = {0};
	/* One authorized ping produces one pulse, then no scheduled continuation. */
	assert(et2500_pulse_begin(&p, 0, 700) == 700);
	assert(p.phase == ET2500_HIGH);
	assert(et2500_pulse_edge(&p, 700, 700, 300) == 0);
	assert(p.phase == ET2500_IDLE && p.next_rise == 1000);
	/* An early next ping preserves the physical minimum low duration. */
	assert(et2500_pulse_begin(&p, 800, 700) == 200);
	assert(p.phase == ET2500_WAIT_LOW);
	assert(et2500_pulse_edge(&p, 1000, 700, 300) == 700);
	assert(p.phase == ET2500_HIGH);
	assert(et2500_pulse_edge(&p, 1700, 700, 300) == 0);
	/* A delayed falling edge must not shorten the next low phase. */
	assert(et2500_pulse_begin(&p, 2000, 700) == 700);
	assert(et2500_pulse_edge(&p, 2900, 700, 300) == 0);
	assert(p.next_rise == 3200);
	assert(et2500_pulse_begin(&p, 3199, 700) == 1);
	assert(et2500_pulse_edge(&p, 3200, 700, 300) == 700);
	assert(et2500_pulse_edge(&p, 3900, 700, 300) == 0);
	/* Arbitrarily long idle time cannot itself generate another pulse. */
	assert(p.phase == ET2500_IDLE);
	assert(et2500_pulse_begin(&p, 1000000, 700) == 700);
	assert(et2500_pulse_edge(&p, 1000700, 700, 300) == 0);
	puts("PASS: bounded pulse, minimum low time, delayed edge, long idle");
}
