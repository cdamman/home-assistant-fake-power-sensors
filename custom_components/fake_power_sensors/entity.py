"""Base entity shared by the platforms of this integration."""

from __future__ import annotations

from homeassistant.const import CONF_NAME
from homeassistant.helpers.entity import Entity

from .const import CONF_MODE, MODE_EXISTING_DEVICE
from .runtime import FakePowerRuntime


class FakePowerBaseEntity(Entity):
    """Handle device attachment and the naming convention."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: FakePowerRuntime, key: str) -> None:
        """Initialise the entity for a given config entry."""
        self._runtime = runtime
        self._entry = runtime.entry
        self._attr_unique_id = f"{runtime.entry.entry_id}_{key}"
        self._attr_device_info = runtime.device_info
        self._attr_translation_key = key
        self._attr_translation_placeholders = {"prefix": self._name_prefix()}

    def _name_prefix(self) -> str:
        """Return the optional prefix inserted before the translated name.

        The prefix allows several fake meters to coexist on a single
        existing device without their names colliding. It is empty in the
        common case, and carries its own trailing space otherwise.
        """
        if self._entry.data[CONF_MODE] != MODE_EXISTING_DEVICE:
            return ""

        prefix = (self._entry.data.get(CONF_NAME) or "").strip()
        return f"{prefix} " if prefix else ""
