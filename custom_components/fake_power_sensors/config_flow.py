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
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_ID,
    CONF_MODE,
    CONF_NOTES,
    CONF_POWER,
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


def _common_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return the fields shared by both modes."""
    return {
        vol.Required(
            CONF_POWER, default=defaults.get(CONF_POWER, DEFAULT_POWER)
        ): _power_selector(),
        vol.Optional(
            CONF_STANDBY_POWER,
            default=defaults.get(CONF_STANDBY_POWER, DEFAULT_STANDBY_POWER),
        ): _power_selector(),
        vol.Optional(
            CONF_SOURCE_ENTITY,
            description={"suggested_value": defaults.get(CONF_SOURCE_ENTITY)},
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=CONTROL_ENTITY_DOMAINS)
        ),
        # Last on purpose: the text area is the tallest field of the form.
        vol.Optional(
            CONF_NOTES,
            description={"suggested_value": defaults.get(CONF_NOTES)},
        ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
    }


EXISTING_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): selector.DeviceSelector(),
        vol.Optional(CONF_NAME): selector.TextSelector(),
        **_common_schema({}),
    }
)

NEW_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
        **_common_schema({}),
    }
)


class FakePowerSensorsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Walk the user through the creation of a fake meter."""

    VERSION = 1

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
        """Attach the fake sensors to a device that already exists."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device = dr.async_get(self.hass).async_get(user_input[CONF_DEVICE_ID])
            if device is None:
                errors["base"] = "device_not_found"
            else:
                prefix = (user_input.get(CONF_NAME) or "").strip()
                device_name = device.name_by_user or device.name or "Device"
                title = f"{device_name} — {prefix}" if prefix else device_name

                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_MODE: MODE_EXISTING_DEVICE,
                        CONF_DEVICE_ID: user_input[CONF_DEVICE_ID],
                        CONF_NAME: prefix,
                    },
                    options=_extract_options(user_input),
                )

        return self.async_show_form(
            step_id=MODE_EXISTING_DEVICE,
            data_schema=EXISTING_DEVICE_SCHEMA,
            errors=errors,
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

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the options."""
        if user_input is not None:
            return self.async_create_entry(data=_extract_options(user_input))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(_common_schema(dict(self.config_entry.options))),
        )


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
