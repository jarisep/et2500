#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# ET2500: use the kernel CPLD owner when present; preserve legacy access otherwise.
# Address the mux child bus so the kernel selects channel 1 atomically.
set -euo pipefail
shopt -s nullglob

find_sensor() {
    local name=$1 address=$2 path
    for path in /sys/bus/i2c/devices/*-"$address"/hwmon/hwmon*; do
        if [[ $(<"$path/name") == "$name" ]]; then
            printf '%s\n' "$path"
            return 0
        fi
    done
    echo "Missing sensor: $name at $address" >&2
    return 1
}

temperature() {
    local value
    read -r value < "$1"
    # Do not send a fabricated zero or wrap an invalid reading into a byte.
    if [[ ! $value =~ ^[0-9]+$ ]] || (( value > 127000 )); then
        echo "Invalid temperature in $1: $value" >&2
        return 1
    fi
    printf '%d\n' "$(( (value + 500) / 1000 ))"
}

while true; do
    channel=$(readlink -e /sys/bus/i2c/devices/0-0071/channel-1)
    bus=${channel##*/i2c-}
    [[ $bus =~ ^[0-9]+$ ]]
    lm75=$(find_sensor lm75 0048)
    tmp401=$(find_sensor tmp401 0018)
    board=$(temperature "$lm75/temp1_input")
    local_temp=$(temperature "$tmp401/temp1_input")
    remote_temp=$(temperature "$tmp401/temp2_input")
    maximum=$((local_temp > remote_temp ? local_temp : remote_temp))
    cpld="/sys/bus/i2c/devices/$bus-0040"
    if [[ -L "$cpld/driver" ]]; then
        # Do not bypass an owning driver, even if its attributes are missing.
        [[ -w "$cpld/board_temperature" && -w "$cpld/soc_temperature" ]]
        printf '%s\n' "$((board * 1000))" > "$cpld/board_temperature"
        printf '%s\n' "$((maximum * 1000))" > "$cpld/soc_temperature"
    else
        i2cset -y "$bus" 0x40 0x18 "$board"
        i2cset -y "$bus" 0x40 0x19 "$maximum"
    fi
    echo "CPLD temperatures: board=$board, maximum=$maximum, bus=$bus"
    sleep 5
done
