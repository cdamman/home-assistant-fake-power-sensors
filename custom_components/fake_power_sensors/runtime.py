"""Shared state between the entities of a single config entry."""

from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_STANDBY,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_POWER,
    CONF_SOURCE_ENTITY,
    CONF_STANDBY_POWER,
    DEFAULT_POWER,
    DEFAULT_STANDBY_POWER,
)

_LOGGER = logging.getLogger(__name__)

# States treated as "off" for the optional control entity
OFF_STATES = {
    STATE_OFF,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    STATE_NOT_HOME,
    STATE_STANDBY,
}


class FakePowerRuntime:
    """Own the power calculation and notify the entities.

    One instance is created per config entry. It is the single source of
    truth for the current power, which spares the energy sensor from having
    to watch the power sensor through the state bus.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ) -> None:
        """Initialise the runtime from the config entry."""
        self.hass = hass
        self.entry = entry
        self.device_info = device_info

        self._listeners: list[Callable[[], None]] = []
        self._unsub_source: Callable[[], None] | None = None

        self._configured_power: float = DEFAULT_POWER
        self._standby_power: float = DEFAULT_STANDBY_POWER
        self._source_entity: str | None = None
        self._effective_power: float = DEFAULT_POWER

        self._read_options()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        """Start watching the optional control entity."""
        self._async_subscribe_source()
        self._effective_power = self._compute_power()

    @callback
    def async_shutdown(self) -> None:
        """Release every subscription."""
        if self._unsub_source is not None:
            self._unsub_source()
            self._unsub_source = None
        self._listeners.clear()

    @callback
    def async_update_options(self) -> None:
        """Apply updated options in place, without reloading the entry."""
        previous_source = self._source_entity
        self._read_options()

        if self._source_entity != previous_source:
            self._async_subscribe_source()

        self._effective_power = self._compute_power()
        self._async_notify()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def configured_power(self) -> float:
        """Configured power in watts, device considered on."""
        return self._configured_power

    @property
    def standby_power(self) -> float:
        """Standby power in watts."""
        return self._standby_power

    @property
    def source_entity(self) -> str | None:
        """Optional control entity driving the on/off state."""
        return self._source_entity

    @property
    def effective_power(self) -> float:
        """Power actually applied right now, in watts."""
        return self._effective_power

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    @callback
    def async_add_listener(
        self, update_callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback fired on every power change."""
        self._listeners.append(update_callback)

        @callback
        def _remove_listener() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return _remove_listener

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_options(self) -> None:
        """Re-read the current configuration of the entry."""
        options = {**self.entry.data, **self.entry.options}

        try:
            self._configured_power = float(options.get(CONF_POWER, DEFAULT_POWER))
        except (TypeError, ValueError):
            _LOGGER.warning("Invalid power value, falling back to the default")
            self._configured_power = DEFAULT_POWER

        try:
            self._standby_power = float(
                options.get(CONF_STANDBY_POWER, DEFAULT_STANDBY_POWER)
            )
        except (TypeError, ValueError):
            self._standby_power = DEFAULT_STANDBY_POWER

        self._source_entity = options.get(CONF_SOURCE_ENTITY) or None

    def _compute_power(self) -> float:
        """Work out the power to apply based on the control entity."""
        if self._source_entity is None:
            return self._configured_power

        state = self.hass.states.get(self._source_entity)
        if state is None or state.state in OFF_STATES:
            return self._standby_power

        return self._configured_power

    @callback
    def _async_subscribe_source(self) -> None:
        """(Re)subscribe to the control entity state changes."""
        if self._unsub_source is not None:
            self._unsub_source()
            self._unsub_source = None

        if self._source_entity is None:
            return

        self._unsub_source = async_track_state_change_event(
            self.hass, [self._source_entity], self._async_source_changed
        )

    @callback
    def _async_source_changed(self, event: Event[EventStateChangedData]) -> None:
        """React to a state change of the control entity."""
        power = self._compute_power()
        if power == self._effective_power:
            return

        self._effective_power = power
        self._async_notify()

    @callback
    def _async_notify(self) -> None:
        """Notify every subscribed entity."""
        for update_callback in list(self._listeners):
            update_callback()
