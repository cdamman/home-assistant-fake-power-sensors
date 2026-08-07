"""Fake Power Sensors integration for Home Assistant.

Creates fake power and energy sensors, either attached to a device already
known to Home Assistant, or carried by a brand new device created from
scratch.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_DEVICE_ID,
    CONF_MODE,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    MODE_NEW_DEVICE,
)
from .runtime import FakePowerRuntime

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


@callback
def async_resolve_device(
    hass: HomeAssistant, entry: ConfigEntry
) -> tuple[DeviceInfo | None, dr.DeviceEntry | None]:
    """Resolve how the entities of an entry attach to a device.

    In "new device" mode a dedicated device is declared through a device
    info, which this entry owns.

    In "existing device" mode the target device is returned as a registry
    entry instead, to be set on the entity as its `device_entry`. Handing a
    device info carrying somebody else's identifiers would implicitly add
    this entry to that device, which has two consequences we do not want:
    Home Assistant closes the config flow on the "name and assign" screen
    offering to rename and reassign a device we do not own, and the pattern
    is deprecated in core since it cannot be represented for a device that
    belongs to a single config entry.
    """
    if entry.data[CONF_MODE] == MODE_NEW_DEVICE:
        return (
            DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                name=entry.data[CONF_NAME],
                manufacturer=DEVICE_MANUFACTURER,
                model=DEVICE_MODEL,
            ),
            None,
        )

    return None, dr.async_get(hass).async_get(entry.data[CONF_DEVICE_ID])


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    device_info, device_entry = async_resolve_device(hass, entry)
    if device_info is None and device_entry is None:
        raise ConfigEntryError(
            f"Device {entry.data.get(CONF_DEVICE_ID)} could not be found in the "
            "device registry. It was most likely deleted."
        )

    runtime = FakePowerRuntime(hass, entry, device_info, device_entry)
    runtime.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply the new options without reloading the entry."""
    runtime: FakePowerRuntime | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is not None:
        runtime.async_update_options()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        runtime: FakePowerRuntime | None = hass.data[DOMAIN].pop(entry.entry_id, None)
        if runtime is not None:
            runtime.async_shutdown()

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow the device to be removed manually from the UI."""
    return True
