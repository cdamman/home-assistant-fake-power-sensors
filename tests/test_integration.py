"""Functional tests for the Fake Power Sensors integration."""

from datetime import timedelta
from functools import partial

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
    do_adhoc_statistics,
)

from homeassistant.components.recorder.statistics import get_metadata
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.fake_power_sensors import async_remove_config_entry_device
from custom_components.fake_power_sensors.const import (
    CONF_DEVICE_ID,
    CONF_MODE,
    CONF_NOTES,
    CONF_POWER,
    CONF_SHOW_ALL_ENTITIES,
    CONF_SOURCE_ENTITY,
    CONF_STANDBY_POWER,
    DOMAIN,
    MODE_EXISTING_DEVICE,
    MODE_NEW_DEVICE,
)

NOTES = (
    "Fridge in the garage.\n"
    "Measured 80 W with a plug meter on 2026-01-04.\n"
    "\n"
    "  Recheck once the seal is replaced."
)

# Statistics compile on 5-minute boundaries, so pin a clean one.
STATISTICS_START = "2026-01-15 10:00:00+00:00"

POWER_ENTITY = "sensor.box_internet_current_consumption"
ENERGY_ENTITY = "sensor.box_internet_today_s_consumption"


def _new_device_entry(**options) -> MockConfigEntry:
    """Build a config entry in new-device mode."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Box internet",
        data={CONF_MODE: MODE_NEW_DEVICE, CONF_NAME: "Box internet"},
        options={CONF_POWER: 12.0, CONF_STANDBY_POWER: 0.0, **options},
    )


async def test_new_device_creates_device_and_entities(hass: HomeAssistant) -> None:
    """A fake device carries both sensors."""
    entry = _new_device_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    )
    assert device is not None
    assert device.name == "Box internet"
    # This mode does create the device, so the entry owns it.
    assert device.config_entries == {entry.entry_id}

    entities = er.async_entries_for_config_entry(
        er.async_get(hass), entry.entry_id
    )
    assert {e.entity_id for e in entities} == {POWER_ENTITY, ENERGY_ENTITY}
    assert all(e.device_id == device.id for e in entities)

    power = hass.states.get(POWER_ENTITY)
    assert power.state == "12.0"
    assert power.attributes["unit_of_measurement"] == "W"
    assert power.attributes["device_class"] == "power"
    assert power.attributes["state_class"] == "measurement"

    energy = hass.states.get(ENERGY_ENTITY)
    assert float(energy.state) == 0.0
    assert energy.attributes["unit_of_measurement"] == "kWh"
    assert energy.attributes["state_class"] == "total"
    assert energy.attributes["last_reset"] is not None

    # The daily total is filed as diagnostic, the live power is not.
    by_id = {entity.entity_id: entity for entity in entities}
    assert by_id[POWER_ENTITY].entity_category is None
    assert by_id[ENERGY_ENTITY].entity_category is EntityCategory.DIAGNOSTIC


async def test_energy_accumulates_over_time(hass: HomeAssistant, freezer) -> None:
    """The daily counter integrates the power correctly."""
    freezer.move_to("2026-01-15 10:00:00+00:00")

    entry = _new_device_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(hours=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # 12 W for one hour = 0.012 kWh
    assert float(hass.states.get(ENERGY_ENTITY).state) == pytest.approx(0.012, abs=1e-5)

    freezer.tick(timedelta(minutes=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert float(hass.states.get(ENERGY_ENTITY).state) == pytest.approx(0.018, abs=1e-5)


async def test_energy_resets_at_midnight(hass: HomeAssistant, freezer) -> None:
    """The total is reset when midnight passes."""
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-01-15 23:00:00+00:00")

    entry = _new_device_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(minutes=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert float(hass.states.get(ENERGY_ENTITY).state) > 0
    previous_reset = hass.states.get(ENERGY_ENTITY).attributes["last_reset"]

    freezer.tick(timedelta(hours=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENERGY_ENTITY)
    assert float(state.state) < 0.001
    assert state.attributes["last_reset"] != previous_reset


async def test_options_flow_updates_power(hass: HomeAssistant) -> None:
    """A power change made in the options is applied without a reload."""
    entry = _new_device_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_POWER: 45.5, CONF_STANDBY_POWER: 0.0},
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert entry.options[CONF_POWER] == 45.5
    assert hass.states.get(POWER_ENTITY).state == "45.5"


async def test_notes_are_stored_by_the_config_flow(hass: HomeAssistant) -> None:
    """The notepad is filled in at creation time and kept verbatim."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": MODE_NEW_DEVICE}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Box internet",
            CONF_POWER: 12.0,
            CONF_STANDBY_POWER: 0.0,
            CONF_NOTES: NOTES,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    # Blank lines and indentation are part of what was typed.
    assert result["options"][CONF_NOTES] == NOTES


def _control_candidates(result, field: str = CONF_SOURCE_ENTITY) -> set[str] | None:
    """Return the entities a form offers for the control entity.

    None means the picker carries no explicit list, i.e. it still offers every
    entity of the control domains. An empty set is a real answer: a device with
    nothing controllable on it offers nothing.
    """
    schema = result["data_schema"].schema
    key = next(candidate for candidate in schema if candidate == field)
    candidates = schema[key].config.get("include_entities")
    return None if candidates is None else set(candidates)


async def _device_with_entities(hass: HomeAssistant) -> dr.DeviceEntry:
    """Build a host device carrying controllable and unrelated entities."""
    host_device = _host_device(hass, "frigo", "Frigo")
    entity_registry = er.async_get(hass)

    for domain, unique_id in (
        ("switch", "plug"),
        ("binary_sensor", "door"),
        ("sensor", "temperature"),  # not a control domain
    ):
        entity_registry.async_get_or_create(
            domain,
            "demo",
            unique_id,
            device_id=host_device.id,
            suggested_object_id=unique_id,
        )

    # An entity on another device must not leak into the list.
    other_device = _host_device(hass, "four", "Four")
    entity_registry.async_get_or_create(
        "switch", "demo", "oven", device_id=other_device.id, suggested_object_id="oven"
    )

    return host_device


async def test_existing_device_flow_offers_only_that_device_entities(
    hass: HomeAssistant,
) -> None:
    """The control entity is picked among the entities of the chosen device."""
    host_device = await _device_with_entities(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": MODE_EXISTING_DEVICE}
    )

    # Choosing the device comes first: the list below depends on it.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE_ID: host_device.id, CONF_POWER: 80.0, CONF_STANDBY_POWER: 1.0},
    )
    assert result["type"] == "form"
    assert result["step_id"] == "existing_device_settings"
    assert result["description_placeholders"] == {"device": "Frigo"}

    # Controllable entities of that device only: not its sensor, which is no
    # control domain, and not the switch of the other device.
    assert _control_candidates(result) == {"switch.plug", "binary_sensor.door"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SOURCE_ENTITY: "switch.plug"}
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert result["title"] == "Frigo"
    # Both screens land in the same entry.
    assert result["options"][CONF_POWER] == 80.0
    assert result["options"][CONF_STANDBY_POWER] == 1.0
    assert result["data"] == {
        CONF_MODE: MODE_EXISTING_DEVICE,
        CONF_DEVICE_ID: host_device.id,
        CONF_NAME: "",
    }
    assert result["options"][CONF_SOURCE_ENTITY] == "switch.plug"


async def test_existing_device_flow_keeps_the_prefix_in_the_title(
    hass: HomeAssistant,
) -> None:
    """The prefix asked with the device still reaches the entry title."""
    host_device = await _device_with_entities(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": MODE_EXISTING_DEVICE}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE_ID: host_device.id, CONF_POWER: 80.0, CONF_STANDBY_POWER: 0.0},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "  Compresseur "}
    )
    await hass.async_block_till_done()

    assert result["title"] == "Frigo — Compresseur"
    assert result["data"][CONF_NAME] == "Compresseur"


async def _at_the_control_entity_screen(hass: HomeAssistant, device_id: str):
    """Walk the existing-device flow up to its second screen."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": MODE_EXISTING_DEVICE}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE_ID: device_id, CONF_POWER: 80.0, CONF_STANDBY_POWER: 0.0},
    )


def _field(result, field: str):
    """Return the schema marker of a field, defaults and all."""
    return next(key for key in result["data_schema"].schema if key == field)


async def test_show_all_entities_widens_the_picker(hass: HomeAssistant) -> None:
    """The escape hatch reaches an entity carried by another device."""
    host_device = await _device_with_entities(hass)
    result = await _at_the_control_entity_screen(hass, host_device.id)

    assert _control_candidates(result) == {"switch.plug", "binary_sensor.door"}

    # Ticking the box takes effect on submit, the form being static.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SHOW_ALL_ENTITIES: True, CONF_NAME: "Compresseur"},
    )

    assert result["type"] == "form"
    assert result["step_id"] == "existing_device_settings"
    assert _control_candidates(result) is None
    # Neither the box nor what was already typed is lost on the way.
    assert _field(result, CONF_SHOW_ALL_ENTITIES).default() is True
    assert _field(result, CONF_NAME).description["suggested_value"] == "Compresseur"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SOURCE_ENTITY: "switch.oven",
            CONF_SHOW_ALL_ENTITIES: True,
            CONF_NAME: "Compresseur",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert result["title"] == "Frigo — Compresseur"
    assert result["options"][CONF_SOURCE_ENTITY] == "switch.oven"
    # The box drives the form, it is no setting of the meter.
    assert CONF_SHOW_ALL_ENTITIES not in result["options"]


async def test_unticking_show_all_entities_narrows_again(
    hass: HomeAssistant,
) -> None:
    """The escape hatch closes as easily as it opens."""
    host_device = await _device_with_entities(hass)
    result = await _at_the_control_entity_screen(hass, host_device.id)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SHOW_ALL_ENTITIES: True}
    )
    assert _control_candidates(result) is None

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SHOW_ALL_ENTITIES: False}
    )

    assert result["type"] == "form"
    assert _control_candidates(result) == {"switch.plug", "binary_sensor.door"}


async def test_a_device_with_nothing_controllable_offers_nothing(
    hass: HomeAssistant,
) -> None:
    """An empty list stays empty rather than falling back to every entity."""
    host_device = _host_device(hass, "mur", "Mur")
    er.async_get(hass).async_get_or_create(
        "sensor", "demo", "humidity", device_id=host_device.id
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": MODE_EXISTING_DEVICE}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE_ID: host_device.id, CONF_POWER: 10.0, CONF_STANDBY_POWER: 0.0},
    )

    assert _control_candidates(result) == set()


async def test_new_device_flow_still_offers_every_entity(hass: HomeAssistant) -> None:
    """A brand new device carries nothing, so nothing is narrowed there."""
    await _device_with_entities(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": MODE_NEW_DEVICE}
    )

    assert _control_candidates(result) is None


async def test_options_of_a_grafted_meter_are_narrowed_too(
    hass: HomeAssistant,
) -> None:
    """Reconfiguring keeps offering the host device's entities."""
    host_device = await _device_with_entities(hass)

    entry = _existing_device_entry(host_device.id)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert _control_candidates(result) == {"switch.plug", "binary_sensor.door"}


async def test_options_keep_a_control_entity_from_another_device(
    hass: HomeAssistant,
) -> None:
    """A meter set up before the narrowing keeps its own control entity.

    Reopening the options must not quietly drop a working setting just because
    the entity driving it lives on another device.
    """
    host_device = await _device_with_entities(hass)

    entry = _existing_device_entry(host_device.id)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SOURCE_ENTITY: "switch.oven"}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert _control_candidates(result) == {
        "switch.plug",
        "binary_sensor.door",
        "switch.oven",
    }


async def test_options_can_swap_for_another_foreign_control_entity(
    hass: HomeAssistant,
) -> None:
    """The box reaches a second foreign entity, not just the one in place.

    The appliance is driven by a plug that is its own device; it later moves to
    a second plug. Without the box the new one would be unreachable, and the
    entry would have to be deleted and recreated -- losing its statistics.
    """
    host_device = await _device_with_entities(hass)
    other_device = _host_device(hass, "prise", "Prise cellier")
    er.async_get(hass).async_get_or_create(
        "switch",
        "demo",
        "cellier",
        device_id=other_device.id,
        suggested_object_id="prise_cellier",
    )

    entry = _existing_device_entry(host_device.id)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SOURCE_ENTITY: "switch.oven"}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    # The entity in place is offered, the second plug is not.
    assert _control_candidates(result) == {
        "switch.plug",
        "binary_sensor.door",
        "switch.oven",
    }
    assert _field(result, CONF_SHOW_ALL_ENTITIES).default() is False

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_POWER: 80.0,
            CONF_STANDBY_POWER: 0.0,
            CONF_SOURCE_ENTITY: "switch.oven",
            CONF_SHOW_ALL_ENTITIES: True,
        },
    )

    assert result["type"] == "form"
    assert _control_candidates(result) is None

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_POWER: 80.0,
            CONF_STANDBY_POWER: 0.0,
            CONF_SOURCE_ENTITY: "switch.prise_cellier",
            CONF_SHOW_ALL_ENTITIES: True,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert entry.options[CONF_SOURCE_ENTITY] == "switch.prise_cellier"
    assert CONF_SHOW_ALL_ENTITIES not in entry.options
    # The new control entity drives the meter straight away.
    assert hass.states.get("sensor.frigo_current_consumption").state == "0.0"


async def test_options_of_a_fake_device_have_no_box(hass: HomeAssistant) -> None:
    """Nothing to widen when the entry targets no device."""
    entry = _new_device_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    fields = {str(key.schema) for key in result["data_schema"].schema}
    assert CONF_SHOW_ALL_ENTITIES not in fields


async def test_options_of_a_fake_device_are_not_narrowed(hass: HomeAssistant) -> None:
    """A fake device has no entities of its own to drive it."""
    await _device_with_entities(hass)

    entry = _new_device_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert _control_candidates(result) is None


async def test_notes_round_trip_through_the_options(hass: HomeAssistant) -> None:
    """Notes are editable afterwards, and offered back for editing."""
    entry = _new_device_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_POWER: 12.0, CONF_STANDBY_POWER: 0.0, CONF_NOTES: NOTES},
    )
    await hass.async_block_till_done()

    assert entry.options[CONF_NOTES] == NOTES
    # Notes carry no measurement, so the metering is untouched.
    assert hass.states.get(POWER_ENTITY).state == "12.0"

    # Reopening the dialog shows what was written rather than an empty box.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    notes_field = next(key for key in result["data_schema"].schema if key == CONF_NOTES)
    assert notes_field.description["suggested_value"] == NOTES


async def test_blank_notes_clear_the_notepad(hass: HomeAssistant) -> None:
    """Emptying the box removes the notes instead of storing whitespace."""
    entry = _new_device_entry(**{CONF_NOTES: NOTES})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_POWER: 12.0, CONF_STANDBY_POWER: 0.0, CONF_NOTES: "  \n\n "},
    )
    await hass.async_block_till_done()

    assert CONF_NOTES not in entry.options


async def test_source_entity_gates_power(hass: HomeAssistant) -> None:
    """The control entity toggles between nominal and standby power."""
    hass.states.async_set("switch.fictif", STATE_ON)

    entry = _new_device_entry(
        **{CONF_SOURCE_ENTITY: "switch.fictif", CONF_STANDBY_POWER: 1.5}
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(POWER_ENTITY).state == "12.0"

    hass.states.async_set("switch.fictif", STATE_OFF)
    await hass.async_block_till_done()

    assert hass.states.get(POWER_ENTITY).state == "1.5"


async def test_existing_device_mode_attaches_entities(hass: HomeAssistant) -> None:
    """The sensors are grafted onto a device that already exists."""
    device_registry = dr.async_get(hass)

    host_entry = MockConfigEntry(domain="demo", title="Host")
    host_entry.add_to_hass(hass)
    host_device = device_registry.async_get_or_create(
        config_entry_id=host_entry.entry_id,
        identifiers={("demo", "frigo")},
        name="Frigo",
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frigo",
        data={
            CONF_MODE: MODE_EXISTING_DEVICE,
            CONF_DEVICE_ID: host_device.id,
            CONF_NAME: "",
        },
        options={CONF_POWER: 80.0, CONF_STANDBY_POWER: 0.0},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entities = er.async_entries_for_config_entry(
        er.async_get(hass), entry.entry_id
    )
    assert len(entities) == 2
    assert all(e.device_id == host_device.id for e in entities)

    # The sensors ride on the host device without our entry claiming it:
    # claiming it would end the config flow on the "name and assign" screen,
    # offering to rename a device owned by another integration.
    host_device = device_registry.async_get(host_device.id)
    assert entry.entry_id not in host_device.config_entries
    assert host_device.config_entries == {host_entry.entry_id}

    assert hass.states.get("sensor.frigo_current_consumption").state == "80.0"


async def test_entity_names_are_translated(hass: HomeAssistant) -> None:
    """Entity names come from the translation files, English by default."""
    entry = _new_device_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        hass.states.get(POWER_ENTITY).attributes["friendly_name"]
        == "Box internet Current consumption"
    )
    assert (
        hass.states.get(ENERGY_ENTITY).attributes["friendly_name"]
        == "Box internet Today's consumption"
    )


async def test_entity_names_follow_the_ui_language(hass: HomeAssistant) -> None:
    """Switching the instance to French yields the French names."""
    hass.config.language = "fr"

    entry = _new_device_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    names = {
        state.attributes["friendly_name"]
        for state in hass.states.async_all("sensor")
    }
    assert names == {
        "Box internet Consommation actuelle",
        "Box internet Consommation d'aujourd'hui",
    }


async def test_prefix_disambiguates_several_meters(hass: HomeAssistant) -> None:
    """The optional prefix is inserted before the translated name."""
    device_registry = dr.async_get(hass)

    host_entry = MockConfigEntry(domain="demo", title="Host")
    host_entry.add_to_hass(hass)
    host_device = device_registry.async_get_or_create(
        config_entry_id=host_entry.entry_id,
        identifiers={("demo", "rack")},
        name="Rack",
    )

    for prefix in ("Switch", "NAS"):
        entry = MockConfigEntry(
            domain=DOMAIN,
            title=f"Rack — {prefix}",
            data={
                CONF_MODE: MODE_EXISTING_DEVICE,
                CONF_DEVICE_ID: host_device.id,
                CONF_NAME: prefix,
            },
            options={CONF_POWER: 20.0, CONF_STANDBY_POWER: 0.0},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)

    await hass.async_block_till_done()

    names = {
        state.attributes["friendly_name"]
        for state in hass.states.async_all("sensor")
    }
    assert names == {
        "Rack Switch Current consumption",
        "Rack Switch Today's consumption",
        "Rack NAS Current consumption",
        "Rack NAS Today's consumption",
    }


def _host_device(hass: HomeAssistant, identifier: str, name: str) -> dr.DeviceEntry:
    """Create a device owned by another integration."""
    host_entry = MockConfigEntry(domain="demo", title="Host")
    host_entry.add_to_hass(hass)

    return dr.async_get(hass).async_get_or_create(
        config_entry_id=host_entry.entry_id,
        identifiers={("demo", identifier)},
        name=name,
    )


def _existing_device_entry(device_id: str, prefix: str = "") -> MockConfigEntry:
    """Build a config entry grafted onto an existing device."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Frigo",
        data={
            CONF_MODE: MODE_EXISTING_DEVICE,
            CONF_DEVICE_ID: device_id,
            CONF_NAME: prefix,
        },
        options={CONF_POWER: 80.0, CONF_STANDBY_POWER: 0.0},
    )


async def test_target_device_removal_removes_the_entry(hass: HomeAssistant) -> None:
    """Deleting the host device takes the fake meter with it.

    Home Assistant does not remove entities of a config entry that is not
    part of the deleted device, it merely unlinks them. Left alone they would
    stay in the registry as entities without a state, and the entry could no
    longer be set up.
    """
    host_device = _host_device(hass, "frigo", "Frigo")

    entry = _existing_device_entry(host_device.id)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.frigo_current_consumption") is not None

    dr.async_get(hass).async_remove_device(host_device.id)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.config_entries.async_entry_ids()
    assert er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id) == []
    assert hass.states.get("sensor.frigo_current_consumption") is None


async def test_own_device_removal_removes_the_entry(hass: HomeAssistant) -> None:
    """Deleting a fake device deletes its entry, so it stays deleted."""
    entry = _new_device_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})

    assert await async_remove_config_entry_device(hass, entry, device)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.config_entries.async_entry_ids()
    assert er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id) == []
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
        is None
    )
    assert hass.states.get(POWER_ENTITY) is None


async def test_removal_of_a_foreign_device_keeps_the_entry(
    hass: HomeAssistant,
) -> None:
    """A device we do not own is never a reason to delete our entry."""
    host_device = _host_device(hass, "frigo", "Frigo")

    entry = _existing_device_entry(host_device.id)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await async_remove_config_entry_device(hass, entry, host_device)
    await hass.async_block_till_done()

    assert entry.entry_id in hass.config_entries.async_entry_ids()
    assert hass.states.get("sensor.frigo_current_consumption") is not None


async def _recorded_statistics(
    hass: HomeAssistant, statistic_ids: set[str]
) -> set[str]:
    """Return which of these statistic ids the database actually holds.

    Deliberately not list_statistic_ids: that one also reports the ids a
    platform announces for its live entities, so it answers the same before
    and after a deletion and would hide the very leftovers under test.
    """
    metadata = await hass.async_add_executor_job(
        partial(get_metadata, hass, statistic_ids=statistic_ids)
    )
    return set(metadata)


async def _compile_statistics(hass: HomeAssistant, freezer) -> None:
    """Give the sensors some history and turn it into statistics."""
    await async_wait_recording_done(hass)

    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    do_adhoc_statistics(hass, start=dt_util.parse_datetime(STATISTICS_START))
    await async_wait_recording_done(hass)


async def test_statistics_are_deleted_with_the_entry(
    recorder_mock, hass: HomeAssistant, freezer
) -> None:
    """Deleting a fake device takes its long-term statistics with it.

    Core never deletes them: the recorder only follows entity renames, so the
    rows outlive the entity and Developer tools > Statistics reports them as
    having no state available.
    """
    freezer.move_to(STATISTICS_START)

    entry = _new_device_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await _compile_statistics(hass, freezer)
    assert await _recorded_statistics(hass, {POWER_ENTITY, ENERGY_ENTITY}) == {
        POWER_ENTITY,
        ENERGY_ENTITY,
    }

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert await async_remove_config_entry_device(hass, entry, device)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    assert await _recorded_statistics(hass, {POWER_ENTITY, ENERGY_ENTITY}) == set()


async def test_statistics_of_a_grafted_meter_are_deleted_too(
    recorder_mock, hass: HomeAssistant, freezer
) -> None:
    """Same when the host device goes, which removes the entry indirectly."""
    freezer.move_to(STATISTICS_START)

    host_device = _host_device(hass, "frigo", "Frigo")
    entry = _existing_device_entry(host_device.id)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    grafted = {
        "sensor.frigo_current_consumption",
        "sensor.frigo_today_s_consumption",
    }

    await _compile_statistics(hass, freezer)
    assert await _recorded_statistics(hass, grafted) == grafted

    dr.async_get(hass).async_remove_device(host_device.id)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    assert entry.entry_id not in hass.config_entries.async_entry_ids()
    assert await _recorded_statistics(hass, grafted) == set()


async def test_unload_stops_watching_the_target_device(hass: HomeAssistant) -> None:
    """The device watch goes away with the entry it belongs to."""
    host_device = _host_device(hass, "frigo", "Frigo")

    entry = _existing_device_entry(host_device.id)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    # Removing the device now must not try to remove an already unloaded entry.
    dr.async_get(hass).async_remove_device(host_device.id)
    await hass.async_block_till_done()

    assert entry.entry_id in hass.config_entries.async_entry_ids()


async def test_unload_entry(hass: HomeAssistant) -> None:
    """Unloading releases the resources cleanly."""
    entry = _new_device_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]
