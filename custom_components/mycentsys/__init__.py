"""The MyCentsys Remote integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_ENABLE_GWEB,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    GWEB_PREFIX,
)
from .coordinator import MyCentsysCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.SENSOR,
]

type MyCentsysConfigEntry = ConfigEntry[MyCentsysCoordinator]

SERVICE_ACTIVATE = "activate"
ATTR_TRIGGER_ID = "trigger_id"

SERVICE_ACTIVATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Required(ATTR_TRIGGER_ID): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: MyCentsysConfigEntry) -> bool:
    """Set up one MyCentsys account."""
    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    coordinator = MyCentsysCoordinator(hass, entry, scan_interval)

    # G-Web has to sign in before the first refresh, or its devices are missed.
    if entry.options.get(CONF_ENABLE_GWEB, True):
        await coordinator.async_setup_gweb()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MyCentsysConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: MyCentsysConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Expose mycentsys.activate for trigger ids that have no entity."""
    if hass.services.has_service(DOMAIN, SERVICE_ACTIVATE):
        return

    async def _handle_activate(call: ServiceCall) -> None:
        registry = dr.async_get(hass)
        trigger_id = call.data[ATTR_TRIGGER_ID]
        for device_id in call.data[ATTR_DEVICE_ID]:
            device = registry.async_get(device_id)
            if device is None:
                raise HomeAssistantError(f"Unknown device {device_id}")
            identifier = next(
                (ident[1] for ident in device.identifiers if ident[0] == DOMAIN), None
            )
            if identifier is None:
                raise HomeAssistantError(f"{device.name} is not a MyCentsys device")

            if identifier.startswith(GWEB_PREFIX):
                gweb_id = int(identifier.removeprefix(GWEB_PREFIX))
                coordinator = _coordinator_for(hass, gweb_id=gweb_id)
                # A GSM device has outputs rather than activation ids.
                await coordinator.async_activate_gweb(gweb_id, trigger_id)
            else:
                coordinator = _coordinator_for(hass, serial=identifier)
                await coordinator.async_activate(identifier, trigger_id)

    hass.services.async_register(
        DOMAIN, SERVICE_ACTIVATE, _handle_activate, schema=SERVICE_ACTIVATE_SCHEMA
    )


def _coordinator_for(
    hass: HomeAssistant, *, serial: str | None = None, gweb_id: int | None = None
) -> MyCentsysCoordinator:
    """Find the loaded account that owns a device.

    Asking the device registry which config entries it belongs to is deprecated,
    so the lookup goes the other way: ask each loaded account what it knows.
    """
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator: MyCentsysCoordinator = entry.runtime_data
        if serial is not None and serial in coordinator.data.devices:
            return coordinator
        if gweb_id is not None and gweb_id in coordinator.data.gweb_devices:
            return coordinator
    raise HomeAssistantError("That device has no loaded MyCentsys account")
