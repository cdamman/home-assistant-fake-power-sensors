"""Fake Power Sensors integration for Home Assistant.

Creates fake power and energy sensors, either attached to a device already
known to Home Assistant, or carried by a brand new device created from
scratch.
"""

from __future__ import annotations

import logging

from homeassistant.components.recorder import DOMAIN as RECORDER_DOMAIN
from homeassistant.components.recorder import get_instance
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import (
    DeviceInfo,
    EventDeviceRegistryUpdatedData,
)
from homeassistant.helpers.event import async_track_device_registry_updated_event

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


@callback
def async_watch_target_device(
    hass: HomeAssistant, entry: ConfigEntry, device_id: str
) -> None:
    """Remove the entry if the device it was grafted onto disappears.

    Only "existing device" mode needs this. The entry deliberately stays out
    of the target device's config entries, so Home Assistant does not
    consider our sensors part of that device when it is deleted: instead of
    removing them, it keeps them in the entity registry with no device at all
    (see the "remove" branch of entity_registry._handle_device_registry_event).
    They then survive as entities nothing provides a state for, and the entry
    itself can no longer be set up.

    Nothing here can replace the target device — it is fixed at creation time
    and the options flow does not offer it — so the entry has lost its
    purpose and goes away with the device. This mirrors what switch_as_x does
    when the entity it wraps is removed.
    """

    async def _async_device_updated(
        event: Event[EventDeviceRegistryUpdatedData],
    ) -> None:
        """Drop the entry once the target device is really gone."""
        if event.data["action"] != "remove":
            return

        _LOGGER.info(
            "Device %s was removed, removing the fake meter %s that rode on it",
            device_id,
            entry.title,
        )
        await hass.config_entries.async_remove(entry.entry_id)

    entry.async_on_unload(
        async_track_device_registry_updated_event(
            hass, device_id, _async_device_updated
        )
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    device_info, device_entry = async_resolve_device(hass, entry)
    if device_info is None and device_entry is None:
        raise ConfigEntryError(
            f"Device {entry.data.get(CONF_DEVICE_ID)} could not be found in the "
            "device registry. It was most likely deleted."
        )

    if device_entry is not None:
        async_watch_target_device(hass, entry, device_entry.id)

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


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the long-term statistics recorded for the sensors.

    Nothing in core does this. The recorder only follows entity renames, so
    the statistics of a removed entity stay in the database and show up under
    Developer tools > Statistics as "No state is available for this entity".
    For real measurements that is the right call, since the history outlives
    the hardware; these readings are invented, so they leave with the entry
    that invented them.

    Core calls this before it clears the entity registry for the entry, which
    is what makes the entity ids -- the statistic ids of an entity-backed
    sensor -- still readable here.
    """
    if RECORDER_DOMAIN not in hass.config.components:
        return

    statistic_ids = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
    ]
    if not statistic_ids:
        return

    _LOGGER.debug("Clearing the statistics of %s", ", ".join(statistic_ids))
    get_instance(hass).async_clear_statistics(statistic_ids)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Delete the entry along with the device it created.

    Reached in "new device" mode only, the sole mode where the device belongs
    to this entry. Accepting the removal without also removing the entry would
    leave an entry with nothing to show, recreating the device on the next
    restart. Core tolerates the entry vanishing under it here, see
    `homeassistant.components.config.device_registry`.
    """
    if entry.data[CONF_MODE] != MODE_NEW_DEVICE:
        # Defensive: in existing device mode the entry is not part of the
        # target device's config entries, so core has no reason to ask us
        # about it. Deleting the entry over somebody else's device would be
        # the wrong answer if that ever changes.
        return True

    await hass.config_entries.async_remove(entry.entry_id)
    return True
