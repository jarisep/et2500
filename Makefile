# SPDX-License-Identifier: GPL-2.0-only
obj-m += et2500_cpld_wdt.o et2500_wdt_board.o
KDIR ?= /lib/modules/$(shell uname -r)/build
.PHONY: all clean test
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) W=1 modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
test:
	$(CC) -std=c11 -Wall -Wextra -Werror -fsanitize=undefined,address -g tests/pulse.c -o /tmp/et2500-pulse-test
	/tmp/et2500-pulse-test
