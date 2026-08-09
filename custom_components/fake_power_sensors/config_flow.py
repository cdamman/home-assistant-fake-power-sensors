"""Config flow for the Fake Power Sensors integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_ID,
    CONF_MODE,
    CONF_NOTES,
    CONF_POWER,
    CONF_SHOW_ALL_ENTITIES,
    CONF_SOURCE_ENTITY,
    CONF_STANDBY_POWER,
    DEFAULT_POWER,
    DEFAULT_STANDBY_POWER,
    DOMAIN,
    MAX_POWER,
    MODE_EXISTING_DEVICE,
    MODE_NEW_DEVICE,
)

# Domains offered for the optional control entity
CONTROL_ENTITY_DOMAINS = [
    "binary_sensor",
    "device_tracker",
    "fan",
    "input_boolean",
    "light",
    "media_player",
    "switch",
]


def _power_selector() -> selector.NumberSelector:
    """Return a numeric selector expressed in watts."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=MAX_POWER,
            step=0.1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="W",
        )
    )


def _control_entity_selector(
    hass: HomeAssistant | None = None,
    device_id: str | None = None,
    keep: str | None = None,
) -> selector.EntitySelector:
    """Return the picker for the optional control entity.

    Given a device, the picker is narrowed to the entities that device
    carries, since a fake meter grafted onto it is normally driven by one of
    them. The entity selector has no device filter of its own, so the list is
    resolved here and passed as include_entities.

    Without a device -- new device mode, whose fake device carries nothing but
    our own sensors -- every entity of the control domains is offered.

    `keep` is the entity already configured. It is offered whatever device it
    belongs to: a meter set up before the list was narrowed, or against an
    entity that has since moved elsewhere, must not lose a working setting
    just because its options were reopened.
    """
    if hass is None or device_id is None:
        return selector.EntitySelector(
            selector.EntitySelectorConfig(domain=CONTROL_ENTITY_DOMAINS)
        )

    candidates = [
        entity.entity_id
        for entity in er.async_entries_for_device(er.async_get(hass), device_id)
        if entity.domain in CONTROL_ENTITY_DOMAINS
    ]
    if keep and keep not in candidates:
        candidates.append(keep)

    return selector.EntitySelector(
        selector.EntitySelectorConfig(include_entities=candidates)
    )


def _consumption_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return the two power figures a fake meter applies."""
    return {
        vol.Required(
            CONF_POWER, default=defaults.get(CONF_POWER, DEFAULT_POWER)
        ): _power_selector(),
        vol.Optional(
            CONF_STANDBY_POWER,
            default=defaults.get(CONF_STANDBY_POWER, DEFAULT_STANDBY_POWER),
        ): _power_selector(),
    }


def _control_entity_schema(
    defaults: dict[str, Any],
    hass: HomeAssistant | None = None,
    device_id: str | None = None,
) -> dict[Any, Any]:
    """Return the optional control entity field."""
    return {
        vol.Optional(
            CONF_SOURCE_ENTITY,
            description={"suggested_value": defaults.get(CONF_SOURCE_ENTITY)},
        ): _control_entity_selector(
            hass, device_id, defaults.get(CONF_SOURCE_ENTITY)
        ),
    }


def _show_all_entities_schema(default: bool) -> dict[Any, Any]:
    """Return the escape hatch from the per-device entity list.

    A config flow cannot refresh a form as it is filled in, so ticking this
    box takes effect on submit: the step is shown again, this time offering
    every control entity of the instance.
    """
    return {
        vol.Optional(
            CONF_SHOW_ALL_ENTITIES, default=default
        ): selector.BooleanSelector()
    }


def _prefix_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return the optional prefix inserted before the sensor names."""
    return {
        vol.Optional(
            CONF_NAME, description={"suggested_value": defaults.get(CONF_NAME)}
        ): selector.TextSelector()
    }


def _notes_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return the notepad, kept last: it is the tallest field of a form."""
    return {
        vol.Optional(
            CONF_NOTES,
            description={"suggested_value": defaults.get(CONF_NOTES)},
        ): selector.TextSelector(selector.TextSelectorConfig(multiline=True))
    }


# The device comes with the consumption it is meant to fake. Only the control
# entity waits for the second screen, since the list offered there is drawn
# from the device chosen here.
EXISTING_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): selector.DeviceSelector(),
        **_consumption_schema({}),
        **_notes_schema({}),
    }
)

STEP_EXISTING_DEVICE_SETTINGS = "existing_device_settings"

NEW_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
        **_consumption_schema({}),
        **_control_entity_schema({}),
        **_notes_schema({}),
    }
)


class FakePowerSensorsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Walk the user through the creation of a fake meter."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with no device chosen."""
        self._device_id: str | None = None
        self._settings: dict[str, Any] = {}
        self._show_all_entities = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the choice between the two modes."""
        return self.async_show_menu(
            step_id="user",
            menu_options=[MODE_EXISTING_DEVICE, MODE_NEW_DEVICE],
        )

    async def async_step_existing_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the device the fake sensors will be attached to."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device = dr.async_get(self.hass).async_get(user_input[CONF_DEVICE_ID])
            if device is None:
                errors["base"] = "device_not_found"
            else:
                self._device_id = user_input[CONF_DEVICE_ID]
                self._settings = dict(user_input)
                return await self.async_step_existing_device_settings()

        return self.async_show_form(
            step_id=MODE_EXISTING_DEVICE,
            data_schema=EXISTING_DEVICE_SCHEMA,
            errors=errors,
        )

    async def async_step_existing_device_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick what drives the meter, among the entities of that device."""
        device = dr.async_get(self.hass).async_get(self._device_id or "")
        if device is None:
            # Only reachable if the device is deleted mid-flow.
            return self.async_abort(reason="device_not_found")

        device_name = device.name_by_user or device.name or "Device"

        if user_input is not None:
            asked_for_all = bool(user_input.get(CONF_SHOW_ALL_ENTITIES, False))

            if asked_for_all == self._show_all_entities:
                prefix = (user_input.get(CONF_NAME) or "").strip()
                title = f"{device_name} — {prefix}" if prefix else device_name

                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_MODE: MODE_EXISTING_DEVICE,
                        CONF_DEVICE_ID: self._device_id,
                        CONF_NAME: prefix,
                    },
                    options=_extract_options({**self._settings, **user_input}),
                )

            # The box was just toggled: widen or narrow the list and ask again,
            # keeping whatever was already filled in.
            self._show_all_entities = asked_for_all

        return self.async_show_form(
            step_id=STEP_EXISTING_DEVICE_SETTINGS,
            data_schema=vol.Schema(
                {
                    **_control_entity_schema(
                        user_input or {},
                        None if self._show_all_entities else self.hass,
                        None if self._show_all_entities else self._device_id,
                    ),
                    **_show_all_entities_schema(self._show_all_entities),
                    **_prefix_schema(user_input or {}),
                }
            ),
            description_placeholders={"device": device_name},
        )

    async def async_step_new_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a fake device carrying both sensors."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_MODE: MODE_NEW_DEVICE,
                    CONF_NAME: user_input[CONF_NAME],
                },
                options=_extract_options(user_input),
            )

        return self.async_show_form(
            step_id=MODE_NEW_DEVICE,
            data_schema=NEW_DEVICE_SCHEMA,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the matching options flow."""
        return FakePowerSensorsOptionsFlow()


class FakePowerSensorsOptionsFlow(OptionsFlow):
    """Allow the power and the control entity to be adjusted afterwards."""

    def __init__(self) -> None:
        """Start with the control entities of the target device only."""
        self._show_all_entities = False

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the options."""
        entry = self.config_entry

        # An existing-device entry keeps offering that device's entities; the
        # device cannot be changed afterwards, so the list cannot go stale.
        # A new-device entry has no device to narrow to, and therefore no box.
        device_id = (
            entry.data[CONF_DEVICE_ID]
            if entry.data[CONF_MODE] == MODE_EXISTING_DEVICE
            else None
        )

        if user_input is not None:
            asked_for_all = bool(user_input.get(CONF_SHOW_ALL_ENTITIES, False))

            if device_id is None or asked_for_all == self._show_all_entities:
                return self.async_create_entry(data=_extract_options(user_input))

            # The box was just toggled: widen or narrow the list and ask again.
            self._show_all_entities = asked_for_all

        # Everything the form last carried, or the stored options on first
        # sight. Taking user_input as it stands keeps a field the user has just
        # emptied empty, which merging over the stored options would undo.
        defaults = dict(user_input) if user_input is not None else dict(entry.options)

        schema = {
            **_consumption_schema(defaults),
            **_control_entity_schema(
                defaults,
                None if self._show_all_entities else self.hass,
                None if self._show_all_entities else device_id,
            ),
        }
        if device_id is not None:
            schema.update(_show_all_entities_schema(self._show_all_entities))
        schema.update(_notes_schema(defaults))

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))


def _extract_options(user_input: dict[str, Any]) -> dict[str, Any]:
    """Isolate the keys that belong to the mutable options."""
    options: dict[str, Any] = {
        CONF_POWER: float(user_input.get(CONF_POWER, DEFAULT_POWER)),
        CONF_STANDBY_POWER: float(
            user_input.get(CONF_STANDBY_POWER, DEFAULT_STANDBY_POWER)
        ),
    }

    source_entity = user_input.get(CONF_SOURCE_ENTITY)
    if source_entity:
        options[CONF_SOURCE_ENTITY] = source_entity

    # Stored verbatim, newlines and indentation included; only a note made of
    # nothing but whitespace counts as no note, which is how it gets cleared.
    notes = user_input.get(CONF_NOTES) or ""
    if notes.strip():
        options[CONF_NOTES] = notes

    return options
