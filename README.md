# Fake Power Sensors

[![HACS: custom repository](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Latest release](https://img.shields.io/github/v/release/cdamman/home-assistant-fake-power-sensors?display_name=tag&sort=semver)](https://github.com/cdamman/home-assistant-fake-power-sensors/releases/latest)
[![Validation](https://github.com/cdamman/home-assistant-fake-power-sensors/actions/workflows/validate.yml/badge.svg)](https://github.com/cdamman/home-assistant-fake-power-sensors/actions/workflows/validate.yml)

A Home Assistant custom integration that creates **fake** electricity
consumption sensors, ready to be used in the Energy dashboard.

Two modes are available:

1. **Add to an existing device** — the sensors are grafted onto a device
   Home Assistant already knows about (a plug, a lamp, a thermostat…) that
   exposes no power measurement of its own.
2. **Create a new device** — a device is created from scratch to represent a
   piece of equipment that is not connected at all: internet router, fridge,
   doorbell transformer, outdoor lighting…

Either way, two entities are created:

| Entity | Type | Purpose |
| --- | --- | --- |
| `Current consumption` | `sensor` — `power` / `measurement` (W) | Instantaneous power |
| `Today's consumption` | `sensor` — `energy` / `total` (kWh) | Daily total, reset at midnight |

Entity names follow the language of the Home Assistant instance. A French
instance shows `Consommation actuelle` and `Consommation d'aujourd'hui`.

## Installation

Home Assistant 2025.8 or newer is required: attaching the sensors to an
existing device relies on `Entity.device_entry`, which earlier releases
ignore.

### Through HACS

[![Open this repository in HACS on your Home Assistant instance.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cdamman&repository=home-assistant-fake-power-sensors&category=integration)

The button opens this repository straight inside HACS on your own instance, and
offers to add it as a custom repository. It relies on
[My Home Assistant](https://my.home-assistant.io/), which needs to have been
pointed at your instance once beforehand. Manually, the same thing:

1. HACS → ⋮ menu → **Custom repositories**
2. URL: `https://github.com/cdamman/home-assistant-fake-power-sensors`, category **Integration**
3. Install **Fake Power Sensors**, then restart Home Assistant

### Manually

Copy `custom_components/fake_power_sensors` into the Home Assistant `config`
folder, then restart.

## Configuration

[![Add the Fake Power Sensors integration to your Home Assistant instance.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=fake_power_sensors)

The button starts the configuration flow directly, once the integration is
installed. Manually: **Settings → Devices & services → Add integration → Fake
Power Sensors**. Then pick one of the two modes. The entry sits among the
integrations rather than under the **Helpers** tab, because *new device* mode
really does register a device of its own.

| Field | Description |
| --- | --- |
| Device | *(existing device mode)* device the sensors are attached to |
| Sensor prefix | *(optional)* allows several fake meters on the same device |
| Name | *(new device mode)* name of the created device |
| Power | Power applied while the device is considered on |
| Standby power | Power applied while the control entity is off |
| Control entity | *(optional)* `switch`, `light`, `binary_sensor`… driving the on/off state |

Without a control entity the power is applied permanently, which is the
intended behaviour for an appliance that is always powered.

In *existing device* mode the sensors are attached to the target device
without this integration taking ownership of it. The flow therefore ends
straight away instead of stopping on the **Name and assign** screen, which
would otherwise offer to rename and reassign a device belonging to another
integration. In *new device* mode the device really is ours, so that screen
still appears and does what it says.

The power stays editable at any time through the **Configure** button on the
entry. The new value takes effect immediately, with no reload of the
integration and no gap in the metering.

The target device, on the other hand, is fixed once the entry is created. So a
fake meter is deleted along with the device it describes: deleting a fake device
deletes its entry rather than letting it come back on the next restart, and
deleting the device a fake meter was grafted onto deletes that meter too. Either
way the sensors go with it instead of lingering in the entity registry with no
state.

## Energy dashboard

**Settings → Energy → Individual devices → Add device**, then pick the
`Today's consumption` sensor. The sensor declares `state_class: total`
along with a `last_reset` pinned to local midnight, which is the contract the
long-term statistics expect.

That sensor carries the `diagnostic` entity category, so on the device page it
sits in the **Diagnostic** block rather than among the sensors. The category is
cosmetic as far as metering goes — statistics and the Energy dashboard are
unaffected — but Home Assistant does keep categorised entities out of the
Alexa, Google Assistant and Cloud exports.

## How it works

The power is integrated over time using the left-rectangle rule: the total is
recomputed on every power change and every 30 seconds, which is exact for a
piecewise-constant signal. The total is restored on restart when it dates from
the current day, and reset when midnight passes.

## Translations

English and French are bundled. Adding a language means dropping a
`custom_components/fake_power_sensors/translations/<code>.json` file next to
the existing ones. The `{prefix}` placeholder in the entity names carries the
optional sensor prefix and must be kept.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-test.txt
pytest
```

That runs against the current Home Assistant. `requirements-test-min.txt`
installs the oldest supported one instead, which is what the minimum quoted
above means in practice. CI runs both, on Python 3.14 and 3.13 respectively —
Home Assistant dictates the interpreter, so each end of the range comes with
its own version.

The brand assets live in `custom_components/fake_power_sensors/brand/`, the
location HACS looks at for integrations that are not listed in the
[Home Assistant brands](https://github.com/home-assistant/brands) repository.
They are generated, so edit the generator rather than the PNGs:

```bash
pip install Pillow
python scripts/generate_brand_icon.py
```

## License

MIT
