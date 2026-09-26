// SPDX-License-Identifier: GPL-2.0-only
/* Board registration for an existing boot DT without a CPLD watchdog node.
 * No register access. Adapter and verified margin must be supplied explicitly.
 */
#include <linux/gpio/machine.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/property.h>
#include "board.h"

static int adapter_nr = -1;
module_param(adapter_nr, int, 0444);
MODULE_PARM_DESC(adapter_nr, "CPLD mux channel 1 adapter number (required)");
static unsigned int hw_margin_ms;
module_param(hw_margin_ms, uint, 0444);
MODULE_PARM_DESC(hw_margin_ms, "Validated conservative hardware margin (required)");
static struct i2c_client *client;
static char dev_id[32];
static struct property_entry props[4];
static const struct software_node node = { .properties = props };
static struct et2500_board_data board = { .owner = THIS_MODULE };
static struct gpiod_lookup_table lookup = {
	.dev_id = dev_id,
	.table = {
		GPIO_LOOKUP("gpio_thunderx", 45, "feed", GPIO_ACTIVE_HIGH),
		{ }
	},
};

static int __init et2500_board_init(void)
{
	struct i2c_adapter *adapter;
	struct i2c_board_info info = {
		I2C_BOARD_INFO("et2500-cpld-wdt", 0x40),
		.swnode = &node,
		.platform_data = &board,
	};
	int ret;

	if (adapter_nr < 0 || hw_margin_ms <= 1000 || hw_margin_ms > 600000)
		return -EINVAL;
	adapter = i2c_get_adapter(adapter_nr);
	if (!adapter)
		return -ENODEV;
	/* A bus number alone is not enough: reject a wrong mux channel. */
	if (strcmp(adapter->name, "i2c-0-mux (chan_id 1)")) {
		i2c_put_adapter(adapter);
		return -EINVAL;
	}
	snprintf(dev_id, sizeof(dev_id), "%d-0040", adapter_nr);
	props[0] = (struct property_entry)PROPERTY_ENTRY_U32("hw-margin-ms", hw_margin_ms);
	props[1] = (struct property_entry)PROPERTY_ENTRY_U32("pulse-high-ms", 700);
	props[2] = (struct property_entry)PROPERTY_ENTRY_U32("pulse-low-ms", 300);
	gpiod_add_lookup_table(&lookup);
	client = i2c_new_client_device(adapter, &info);
	i2c_put_adapter(adapter);
	if (IS_ERR(client)) {
		ret = PTR_ERR(client);
		goto remove_lookup;
	}
	/* The main driver must already be loaded. Do not leave an unbound owner. */
	if (!device_is_bound(&client->dev)) {
		i2c_unregister_device(client);
		ret = -ENODEV;
		goto remove_lookup;
	}
	return 0;
remove_lookup:
	gpiod_remove_lookup_table(&lookup);
	return ret;
}

static void __exit et2500_board_exit(void)
{
	/* Main driver's binding reference prevents removal until it is unloaded. */
	i2c_unregister_device(client);
	gpiod_remove_lookup_table(&lookup);
}
module_init(et2500_board_init);
module_exit(et2500_board_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("ET2500 watchdog board registration for legacy firmware DT");
