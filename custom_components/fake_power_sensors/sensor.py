"""Fake power and energy sensors."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.sensor import (
    ATTR_LAST_RESET,
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    KEY_ENERGY,
    KEY_POWER,
    UPDATE_INTERVAL,
)
from .entity import FakePowerBaseEntity
from .runtime import FakePowerRuntime

_LOGGER = logging.getLogger(__name__)

# Watt-seconds to kilowatt-hours
WS_TO_KWH = 3_600_000.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the power and energy sensors."""
    runtime: FakePowerRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            FakePowerSensor(runtime),
            FakeDailyEnergySensor(runtime),
        ]
    )


class FakePowerSensor(FakePowerBaseEntity, SensorEntity):
    """Expose the fake instantaneous consumption, in watts."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 1

    def __init__(self, runtime: FakePowerRuntime) -> None:
        """Initialise the power sensor."""
        super().__init__(runtime, KEY_POWER)

    async def async_added_to_hass(self) -> None:
        """Subscribe to power changes."""
        await super().async_added_to_hass()
        self.async_on_remove(self._runtime.async_add_listener(self._handle_update))

    @property
    def native_value(self) -> float:
        """Return the current power."""
        return round(self._runtime.effective_power, 2)

    @callback
    def _handle_update(self) -> None:
        """Refresh the entity."""
        self.async_write_ha_state()


class FakeDailyEnergySensor(FakePowerBaseEntity, RestoreSensor):
    """Integrate the fake power and reset the total every night."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, runtime: FakePowerRuntime) -> None:
        """Initialise the daily counter."""
        super().__init__(runtime, KEY_ENERGY)
        self._energy: float = 0.0
        self._last_power: float = 0.0
        self._last_update: datetime = dt_util.utcnow()
        self._attr_last_reset: datetime = dt_util.start_of_local_day()

    async def async_added_to_hass(self) -> None:
        """Restore today's total, then start integrating."""
        await super().async_added_to_hass()

        await self._async_restore_state()

        self._last_update = dt_util.utcnow()
        self._last_power = self._runtime.effective_power

        self.async_on_remove(self._runtime.async_add_listener(self._handle_update))
        self.async_on_remove(
            async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL)
        )
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_midnight, hour=0, minute=0, second=0
            )
        )

    @property
    def native_value(self) -> float:
        """Return the energy consumed since midnight."""
        return round(self._energy, 6)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _async_restore_state(self) -> None:
        """Pick up the previous total, but only if it dates from today."""
        last_state = await self.async_get_last_state()
        if last_state is None:
            return

        if last_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        stored_reset = last_state.attributes.get(ATTR_LAST_RESET)
        if isinstance(stored_reset, str):
            stored_reset = dt_util.parse_datetime(stored_reset)

        if stored_reset is None:
            return

        if dt_util.as_local(stored_reset).date() != dt_util.now().date():
            # The day rolled over while Home Assistant was down: start again.
            return

        try:
            self._energy = float(last_state.state)
        except (TypeError, ValueError):
            _LOGGER.debug("Previous total could not be read, starting from zero")
            return

        self._attr_last_reset = stored_reset

    @callback
    def _accumulate(self) -> None:
        """Add the energy consumed since the last measurement point."""
        now = dt_util.utcnow()
        elapsed = (now - self._last_update).total_seconds()

        if elapsed > 0:
            self._energy += self._last_power * elapsed / WS_TO_KWH

        self._last_update = now
        self._last_power = self._runtime.effective_power

    @callback
    def _handle_update(self) -> None:
        """Accumulate with the previous power before applying the new one."""
        self._accumulate()
        self.async_write_ha_state()

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        """Periodically refresh the displayed total."""
        self._accumulate()
        self.async_write_ha_state()

    @callback
    def _handle_midnight(self, _now: datetime) -> None:
        """Reset the counter when midnight passes."""
        self._accumulate()
        self._energy = 0.0
        self._attr_last_reset = dt_util.start_of_local_day()
        self.async_write_ha_state()
