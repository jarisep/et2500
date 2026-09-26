// SPDX-License-Identifier: GPL-2.0-only
/*
 * ET2500 external CPLD watchdog. Experimental until board timing and control
 * bit semantics have been validated. No automatic device creation or arming.
 * I2C controls enable; a non-sleeping SoC GPIO supplies bounded feed pulses.
 */
#include <linux/gpio/consumer.h>
#include <linux/jiffies.h>
#include <linux/ktime.h>
#include <linux/workqueue.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/property.h>
#include <linux/regmap.h>
#include <linux/watchdog.h>
#include "pulse.h"
#include "board.h"

#define ET2500_CONTROL 0x0b
#define ET2500_ENABLE BIT(0)
#define ET2500_BOARD_TEMP 0x18
#define ET2500_SOC_TEMP 0x19

static bool nowayout = WATCHDOG_NOWAYOUT;
module_param(nowayout, bool, 0444);
MODULE_PARM_DESC(nowayout, "Prevent watchdog stop after activation");

struct et2500_wdt {
	struct watchdog_device wdd;
	struct regmap *map;
	struct gpio_desc *feed;
	struct mutex control_lock;
	struct mutex pulse_lock;
	struct delayed_work pulse_work;
	struct et2500_pulse pulse;
	u64 high_ns;
	u64 low_ns;
	bool feeding;
	bool safety_ref;
};

/* GPIO direction reprogramming matches the vendor operation. The GPIO
 * configuration API belongs in process context, never in an hrtimer callback.
 * This work item performs one transition and never sleeps for the pulse width.
 */
static void et2500_schedule(struct et2500_wdt *wd, u64 delay)
{
	queue_delayed_work(system_highpri_wq, &wd->pulse_work,
		msecs_to_jiffies(DIV_ROUND_UP_ULL(delay, NSEC_PER_MSEC)));
}

static void et2500_edge(struct work_struct *work)
{
	struct et2500_wdt *wd = container_of(to_delayed_work(work),
					   struct et2500_wdt, pulse_work);
	u64 delay;
	int ret;

	mutex_lock(&wd->pulse_lock);
	if (!wd->feeding)
		goto out;
	delay = et2500_pulse_edge(&wd->pulse, ktime_get_ns(),
				 wd->high_ns, wd->low_ns);
	ret = gpiod_direction_output(wd->feed, wd->pulse.phase == ET2500_HIGH);
	if (ret) {
		wd->feeding = false;
		dev_err_ratelimited(wd->wdd.parent, "Feed GPIO transition failed: %d\n", ret);
		goto out;
	}
	if (delay)
		et2500_schedule(wd, delay);
	else
		wd->pulse.next_rise = ktime_get_ns() + wd->low_ns;
out:
	mutex_unlock(&wd->pulse_lock);
}

static int et2500_ping(struct watchdog_device *wdd)
{
	struct et2500_wdt *wd = watchdog_get_drvdata(wdd);
	u64 delay;
	int ret = 0;

	mutex_lock(&wd->pulse_lock);
	if (!wd->feeding) {
		ret = -EIO;
	} else if (wd->pulse.phase != ET2500_IDLE) {
		ret = -EBUSY;
	} else {
		delay = et2500_pulse_begin(&wd->pulse, ktime_get_ns(), wd->high_ns);
		ret = gpiod_direction_output(wd->feed, wd->pulse.phase == ET2500_HIGH);
		if (!ret)
			et2500_schedule(wd, delay);
		else
			wd->pulse.phase = ET2500_IDLE;
	}
	mutex_unlock(&wd->pulse_lock);
	return ret;
}

/* Register must be ordinary readable R/W; verify this before hardware use. */
static int et2500_enable(struct et2500_wdt *wd, bool enable)
{
	unsigned int value;
	int ret;

	ret = regmap_update_bits(wd->map, ET2500_CONTROL, ET2500_ENABLE,
				enable ? ET2500_ENABLE : 0);
	if (ret)
		return ret;
	ret = regmap_read(wd->map, ET2500_CONTROL, &value);
	if (ret)
		return ret;
	return !!(value & ET2500_ENABLE) == enable ? 0 : -EIO;
}

static void et2500_cancel_pulse(struct et2500_wdt *wd)
{

	mutex_lock(&wd->pulse_lock);
	wd->feeding = false;
	mutex_unlock(&wd->pulse_lock);
	/* Never wait for callback completion while holding its lock. */
	cancel_delayed_work_sync(&wd->pulse_work);
	if (gpiod_direction_output(wd->feed, 0))
		dev_warn(wd->wdd.parent, "Watchdog disabled, GPIO low operation failed\n");
	wd->pulse.phase = ET2500_IDLE;
	wd->pulse.next_rise = ktime_get_ns() + wd->low_ns;
}

static int et2500_start(struct watchdog_device *wdd)
{
	struct et2500_wdt *wd = watchdog_get_drvdata(wdd);
	int ret, cleanup;

	mutex_lock(&wd->control_lock);
	/* Keep code/resources alive even if an enable write has an ambiguous error. */
	if (!wd->safety_ref) {
		__module_get(THIS_MODULE);
		wd->safety_ref = true;
	}
	mutex_lock(&wd->pulse_lock);
	wd->feeding = true;
	mutex_unlock(&wd->pulse_lock);
	ret = et2500_ping(wdd);
	if (!ret)
		ret = et2500_enable(wd, true);
	if (ret) {
		cleanup = et2500_enable(wd, false);
		if (!cleanup) {
			et2500_cancel_pulse(wd);
			wd->safety_ref = false;
			module_put(THIS_MODULE);
		} else {
			set_bit(WDOG_HW_RUNNING, &wdd->status);
			dev_crit(wdd->parent,
				 "Enable failed and disable unconfirmed; reset possible, module pinned\n");
		}
	}
	mutex_unlock(&wd->control_lock);
	return ret;
}

static int et2500_stop(struct watchdog_device *wdd)
{
	struct et2500_wdt *wd = watchdog_get_drvdata(wdd);
	int ret;

	mutex_lock(&wd->control_lock);
	ret = et2500_enable(wd, false);
	if (!ret) {
		et2500_cancel_pulse(wd);
		if (wd->safety_ref) {
			wd->safety_ref = false;
			module_put(THIS_MODULE);
		}
	} else {
		/* Do not claim the hardware stopped or cancel an in-flight pulse. */
		set_bit(WDOG_HW_RUNNING, &wdd->status);
	}
	mutex_unlock(&wd->control_lock);
	return ret;
}

/* The existing fan policy supplies measured temperatures to the same CPLD.
 * Expose bounded attributes so it need not force access to an owned I2C device.
 * Units: millidegrees Celsius; board range currently supported: 0..127 C.
 */
static ssize_t et2500_temperature_store(struct device *dev, const char *buf,
				       size_t count, unsigned int reg)
{
	struct et2500_wdt *wd = dev_get_drvdata(dev);
	unsigned int temperature;
	int ret;

	ret = kstrtouint(buf, 10, &temperature);
	if (ret)
		return ret;
	if (temperature > 127000)
		return -ERANGE;
	mutex_lock(&wd->control_lock);
	ret = regmap_write(wd->map, reg, DIV_ROUND_CLOSEST(temperature, 1000));
	mutex_unlock(&wd->control_lock);
	return ret ? ret : count;
}

static ssize_t board_temperature_store(struct device *dev,
		struct device_attribute *attr, const char *buf, size_t count)
{
	return et2500_temperature_store(dev, buf, count, ET2500_BOARD_TEMP);
}
static DEVICE_ATTR_WO(board_temperature);

static ssize_t soc_temperature_store(struct device *dev,
		struct device_attribute *attr, const char *buf, size_t count)
{
	return et2500_temperature_store(dev, buf, count, ET2500_SOC_TEMP);
}
static DEVICE_ATTR_WO(soc_temperature);

static struct attribute *et2500_attrs[] = {
	&dev_attr_board_temperature.attr,
	&dev_attr_soc_temperature.attr,
	NULL,
};
static const struct attribute_group et2500_group = {
	.attrs = et2500_attrs,
};

static const struct watchdog_info et2500_info = {
	.identity = "ET2500 CPLD watchdog",
	.options = WDIOF_KEEPALIVEPING | WDIOF_SETTIMEOUT | WDIOF_MAGICCLOSE,
};
static const struct watchdog_ops et2500_ops = {
	.owner = THIS_MODULE,
	.start = et2500_start,
	.stop = et2500_stop,
	.ping = et2500_ping,
};
static const struct regmap_config et2500_regmap = {
	.reg_bits = 8,
	.val_bits = 8,
	.max_register = ET2500_SOC_TEMP,
	.cache_type = REGCACHE_NONE,
};

static void et2500_cleanup(void *data)
{
	struct et2500_wdt *wd = data;

	/* Runs after watchdog-core unregister and worker teardown. */
	WARN_ON(wd->safety_ref);
	et2500_cancel_pulse(wd);
}

static void et2500_put_board(void *owner)
{
	module_put(owner);
}

static int et2500_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	const struct et2500_board_data *board = dev_get_platdata(dev);
	struct et2500_wdt *wd;
	u32 margin, high = 700, low = 300;
	unsigned int control;
	int ret;

	/* No guessed hardware timeout, and no binding from a bare new_device echo. */
	ret = device_property_read_u32(dev, "hw-margin-ms", &margin);
	if (ret)
		return dev_err_probe(dev, ret, "Measured hw-margin-ms is required\n");
	if (device_property_present(dev, "pulse-high-ms")) {
		ret = device_property_read_u32(dev, "pulse-high-ms", &high);
		if (ret)
			return ret;
	}
	if (device_property_present(dev, "pulse-low-ms")) {
		ret = device_property_read_u32(dev, "pulse-low-ms", &low);
		if (ret)
			return ret;
	}
	if (!high || !low || high > 1000 || low > 1000 ||
	    margin <= high + low || margin > 600000)
		return dev_err_probe(dev, -EINVAL, "Unsafe pulse/timeout relationship\n");
	if (board && board->owner) {
		if (!try_module_get(board->owner))
			return -ENODEV;
		ret = devm_add_action_or_reset(dev, et2500_put_board, board->owner);
		if (ret)
			return ret;
	}
	wd = devm_kzalloc(dev, sizeof(*wd), GFP_KERNEL);
	if (!wd)
		return -ENOMEM;
	wd->map = devm_regmap_init_i2c(client, &et2500_regmap);
	if (IS_ERR(wd->map))
		return PTR_ERR(wd->map);
	ret = regmap_read(wd->map, ET2500_CONTROL, &control);
	if (ret)
		return ret;
	/* Do not silently adopt already-armed, undocumented hardware. */
	if (control & ET2500_ENABLE)
		return dev_err_probe(dev, -EBUSY, "CPLD watchdog already armed\n");
	wd->feed = devm_gpiod_get(dev, "feed", GPIOD_ASIS);
	if (IS_ERR(wd->feed))
		return PTR_ERR(wd->feed);
	if (gpiod_is_active_low(wd->feed))
		return dev_err_probe(dev, -EINVAL, "Requires active-high GPIO\n");
	ret = gpiod_direction_output(wd->feed, 0);
	if (ret)
		return ret;
	mutex_init(&wd->control_lock);
	mutex_init(&wd->pulse_lock);
	INIT_DELAYED_WORK(&wd->pulse_work, et2500_edge);
	wd->high_ns = (u64)high * NSEC_PER_MSEC;
	wd->low_ns = (u64)low * NSEC_PER_MSEC;
	wd->pulse.next_rise = ktime_get_ns() + wd->low_ns;
	wd->wdd.info = &et2500_info;
	wd->wdd.ops = &et2500_ops;
	wd->wdd.parent = dev;
	/* Account for a watchdog that refreshes at the falling edge of the pulse. */
	wd->wdd.max_hw_heartbeat_ms = margin + high + low;
	wd->wdd.min_hw_heartbeat_ms = high + low;
	wd->wdd.min_timeout = DIV_ROUND_UP(margin + high + low, 1000);
	wd->wdd.timeout = max(30U, wd->wdd.min_timeout);
	ret = watchdog_init_timeout(&wd->wdd, 0, dev);
	if (ret)
		return ret;
	watchdog_set_drvdata(&wd->wdd, wd);
	i2c_set_clientdata(client, wd);
	watchdog_set_nowayout(&wd->wdd, nowayout);
	watchdog_stop_on_reboot(&wd->wdd);
	watchdog_stop_on_unregister(&wd->wdd);
	ret = devm_add_action_or_reset(dev, et2500_cleanup, wd);
	if (ret)
		return ret;
	ret = devm_device_add_group(dev, &et2500_group);
	if (ret)
		return ret;
	return devm_watchdog_register_device(dev, &wd->wdd);
}

static const struct of_device_id et2500_of_match[] = {
	{ .compatible = "asterfusion,et2500-cpld-wdt" },
	{ }
};
MODULE_DEVICE_TABLE(of, et2500_of_match);
static const struct i2c_device_id et2500_ids[] = {
	{ "et2500-cpld-wdt" },
	{ }
};
MODULE_DEVICE_TABLE(i2c, et2500_ids);
static struct i2c_driver et2500_driver = {
	.driver = {
		.name = "et2500-cpld-wdt",
		.of_match_table = et2500_of_match,
		.suppress_bind_attrs = true,
	},
	.probe = et2500_probe,
	.id_table = et2500_ids,
};
module_i2c_driver(et2500_driver);
MODULE_DESCRIPTION("ET2500 external CPLD/GPIO watchdog");
MODULE_LICENSE("GPL");
