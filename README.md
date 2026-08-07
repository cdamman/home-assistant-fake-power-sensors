# Fake Power Sensors

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

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

### Through HACS

1. HACS → ⋮ menu → **Custom repositories**
2. URL: `https://github.com/cdamman/home-assistant-fake-power-sensors`, category **Integration**
3. Install **Fake Power Sensors**, then restart Home Assistant

### Manually

Copy `custom_components/fake_power_sensors` into the Home Assistant `config`
folder, then restart.

## Configuration

**Settings → Devices & services → Add integration → Fake Power Sensors**, then
pick one of the two modes.

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

The power stays editable at any time through the **Configure** button on the
entry. The new value takes effect immediately, with no reload of the
integration and no gap in the metering.

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
pip install pytest-homeassistant-custom-component
pytest
```

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
