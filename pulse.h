/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ET2500_PULSE_H
#define ET2500_PULSE_H
/* Caller serializes all access. No autonomous rearming after the falling edge. */
enum et2500_phase { ET2500_IDLE, ET2500_WAIT_LOW, ET2500_HIGH };
struct et2500_pulse {
	enum et2500_phase phase;
	unsigned long long next_rise;
};
/* Return delay to the next transition; caller rejects non-IDLE requests. */
static inline unsigned long long
et2500_pulse_begin(struct et2500_pulse *p, unsigned long long now,
		   unsigned long long high)
{
	if (now < p->next_rise) {
		p->phase = ET2500_WAIT_LOW;
		return p->next_rise - now;
	}
	p->phase = ET2500_HIGH;
	return high;
}
static inline unsigned long long
et2500_pulse_edge(struct et2500_pulse *p, unsigned long long now,
		  unsigned long long high, unsigned long long low)
{
	if (p->phase == ET2500_WAIT_LOW) {
		p->phase = ET2500_HIGH;
		return high;
	}
	p->phase = ET2500_IDLE;
	p->next_rise = now + low;
	return 0;
}
#endif
