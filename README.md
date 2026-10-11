# MyCentsys Remote for Home Assistant

[![Validate](https://github.com/louispires/ha-mycentsys/actions/workflows/validate.yml/badge.svg)](https://github.com/louispires/ha-mycentsys/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)

Control Centurion gates and garage doors (MyCentsys Remote) from Home Assistant.
Sign in once with your mobile number and a one-time pin; every operator on your
account then appears as a cover entity you can open, close and automate.

This is a **custom integration**, not a Supervisor add-on. Add-ons run as isolated
containers and cannot create entities; an integration can, which is what you want
here. It works on any Home Assistant install (OS, Container, Core, Supervised).

> Unofficial and unaffiliated with Centurion Systems. The protocol was worked out
> by reading the app, so Centurion can change it and break this at any time. Use
> it on your own gates, at your own risk.

## What you get, per operator

| Entity | Notes |
|---|---|
| `cover.<gate>` | Open / close / stop, with real state from Centurion's cloud |
| `binary_sensor.<gate>_connectivity` | Whether the operator is reachable |
| `sensor.<gate>_status` | open, closed, opening, closing, partly_open, … |
| `sensor.<gate>_power_supply` | normal / low / off |
| `sensor.<gate>_theft_alarm` | activated / cleared / disabled |
| `sensor.<gate>_wi_fi_signal` | dBm, disabled by default |
| `button.<gate>_pedestrian` | Plus any extra activations you switch on in Options |
| `mycentsys.activate` service | Any raw activation id, for automations |

GSM / 4G (G-Ultra) devices are picked up too, as one button per output.

## Install

### With HACS (recommended)

Click the button, which opens the "add custom repository" dialog in your own
Home Assistant with this repository already filled in:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=louispires&repository=ha-mycentsys&category=integration)

Then **Download**, and restart Home Assistant.

If the button does nothing, your browser has not been told which Home Assistant
to open. Set that up once at [my.home-assistant.io](https://my.home-assistant.io/),
or add the repository by hand: **HACS → ⋮ → Custom repositories**, URL
`https://github.com/louispires/ha-mycentsys`, type **Integration**.

### By hand

Copy `custom_components/mycentsys` into your Home Assistant
`config/custom_components/` and restart.

### Then, either way

1. Install the service token (see below).
2. Restart Home Assistant if you have not already.
3. [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=mycentsys)
   or **Settings → Devices & services → Add integration → MyCentsys Remote**.
4. Enter your mobile number, pick SMS or WhatsApp, then type the pin you receive.

### The service token

Requesting a one-time pin needs the bearer token that the MyCentsys Remote app
itself carries. It belongs to Centurion, not to you, so it is deliberately **not
in this repository** and you have to supply your own copy.

You have two ways to give it to the integration:

- **Paste it in.** Leave the file out, and the config flow shows a "App service
  token" field. Paste the token there once; it is then stored in the config entry.
- **Install it as a file.** Put it in `service_token.json` next to the
  integration, as `{"ServiceLevelJwt": "<token>"}`, and the field disappears.
  If you have the companion `mcr-cli` checkout, this script copies it across:

  ```powershell
  .\tools\import-service-token.ps1 `
      -Source <path-to>\mcr-cli\appsettings.local.json `
      -Destination <path-to>\config\custom_components\mycentsys
  ```

The file is listed in `.gitignore`, so it will not follow the repository around.

## How triggering works

Opening a gate is not a REST call. The integration fetches a per-user client
certificate, opens a mutual-TLS MQTT session to Centurion's broker, authenticates
with your number, then sends an XOR-encrypted activation packet. A press takes
roughly two to four seconds. See `mcr-cli/PROTOCOL.md` for the full write-up.

Sliders and swing gates only have one open/close trigger, so the integration
drops an "open" sent to an already-open gate rather than closing it. Garage doors
(SDO) have genuine open-only and close-only triggers and use those.

## Automation example

```yaml
automation:
  - alias: Close the gate at night
    triggers:
      - trigger: time
        at: "22:00:00"
    conditions:
      - condition: state
        entity_id: cover.driveway_gate
        state: open
    actions:
      - action: cover.close_cover
        target:
          entity_id: cover.driveway_gate
```

For an activation with no button, use the service:

```yaml
      - action: mycentsys.activate
        target:
          device_id: 1a2b3c…
        data:
          trigger_id: 16   # courtesy light
```

## Testing

```
python tests/run_tests.py
```

The protocol and product-mapping tests need nothing installed. The certificate
and cover-logic tests need `homeassistant`, `paho-mqtt` and `cryptography`; they
are skipped with a message if those are missing. No broker, no network, no gate.

## Risks and limits

- **This is reverse-engineered.** Centurion can change the API or broker at any
  time and break it. Nothing here is endorsed by Centurion Systems.
- **Keep `service_token.json` out of public git.** It is the app's own credential,
  shared by every install, and the `.gitignore` here excludes it.
- **Client id clash.** The session identifies itself the same way the phone app
  does. Triggering from Home Assistant while the app is open may briefly
  disconnect the app; it reconnects on its own.
- **Only Wi-Fi operators can be triggered remotely.** Bluetooth-only operators
  need a phone in range and are out of scope.
- **Status is cloud-polled**, every 30 seconds by default. A gate moved by a
  physical remote shows up on the next poll, not instantly.
- Your Home Assistant can now open your gate. Treat its access accordingly.

## Troubleshooting

Turn on debug logging:

```yaml
logger:
  logs:
    custom_components.mycentsys: debug
```

| Symptom | Likely cause |
|---|---|
| `no authentication response` | Operator offline, or the wrong region was chosen |
| `user_not_authenticated` | Your number is not an authorised user on that gate |
| `time_barred` | Your access on that gate is time-restricted right now |
| `configuration_mismatch` twice | Operator config changed; press again |
| Reauth prompt | The stored token expired; enter a fresh pin |
