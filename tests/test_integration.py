"""Functional tests for the Fake Power Sensors integration."""

from datetime import timedelta

import pytest

from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.fake_power_sensors.const import (
    CONF_DEVICE_ID,
    CONF_MODE,
    CONF_POWER,
    CONF_SOURCE_ENTITY,
    CONF_STANDBY_POWER,
    DOMAIN,
    MODE_EXISTING_DEVICE,
    MODE_NEW_DEVICE,
)

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


async def test_unload_entry(hass: HomeAssistant) -> None:
    """Unloading releases the resources cleanly."""
    entry = _new_device_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]
