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
def async_build_device_info(
    hass: HomeAssistant, entry: ConfigEntry
) -> DeviceInfo | None:
    """Build the device info for the entities of an entry.

    In "new device" mode a dedicated device is declared. In "existing
    device" mode the identifiers of the target device are reused: the
    registry recognises them and attaches our entities to that device.
    """
    if entry.data[CONF_MODE] == MODE_NEW_DEVICE:
        return DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    device = dr.async_get(hass).async_get(entry.data[CONF_DEVICE_ID])
    if device is None:
        return None

    return DeviceInfo(
        identifiers=device.identifiers,
        connections=device.connections,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    device_info = async_build_device_info(hass, entry)
    if device_info is None:
        raise ConfigEntryError(
            f"Device {entry.data.get(CONF_DEVICE_ID)} could not be found in the "
            "device registry. It was most likely deleted."
        )

    runtime = FakePowerRuntime(hass, entry, device_info)
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
