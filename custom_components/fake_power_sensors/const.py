"""Constants for the Fake Power Sensors integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "fake_power_sensors"

# Configuration modes
CONF_MODE = "mode"
MODE_EXISTING_DEVICE = "existing_device"
MODE_NEW_DEVICE = "new_device"

# Configuration keys
CONF_DEVICE_ID = "device_id"
CONF_POWER = "power"
CONF_STANDBY_POWER = "standby_power"
CONF_SOURCE_ENTITY = "source_entity"
CONF_NOTES = "notes"
CONF_SHOW_ALL_ENTITIES = "show_all_entities"

# Defaults
DEFAULT_POWER = 10.0
DEFAULT_STANDBY_POWER = 0.0

MAX_POWER = 30000.0

# Identity of the devices created in "new device" mode
DEVICE_MANUFACTURER = "Fake Power Sensors"
DEVICE_MODEL = "Fake device"

# Translation keys of the entities. The displayed names are resolved from
# translations/<lang>.json and prefixed with the device name through
# has_entity_name.
KEY_POWER = "power"
KEY_ENERGY = "energy"

# How often the energy counter refreshes its displayed total
UPDATE_INTERVAL = timedelta(seconds=30)
