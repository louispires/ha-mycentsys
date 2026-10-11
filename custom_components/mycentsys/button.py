"""Push-button activations: pedestrian, holiday lock, courtesy light and friends."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MyCentsysConfigEntry
from .const import (
    CONF_EXTRA_ACTIVATIONS,
    DEFAULT_ACTIVATIONS,
    GWEB_PREFIX,
    OPTIONAL_ACTIVATIONS,
    Activation,
)
from .coordinator import MyCentsysCoordinator
from .entity import MyCentsysEntity, MyCentsysGwebEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyCentsysConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    enabled = set(entry.options.get(CONF_EXTRA_ACTIVATIONS, DEFAULT_ACTIVATIONS))

    entities: list[ButtonEntity] = []
    for serial, device in coordinator.data.devices.items():
        if not device.is_wifi:
            continue
        for activation in OPTIONAL_ACTIVATIONS.get(device.family, ()):
            if activation.key in enabled:
                entities.append(
                    MyCentsysActivationButton(coordinator, serial, activation)
                )

    for device_id, gweb_device in coordinator.data.gweb_devices.items():
        for io in gweb_device.ios:
            entities.append(MyCentsysGwebButton(coordinator, device_id, io))

    async_add_entities(entities)


class MyCentsysActivationButton(MyCentsysEntity, ButtonEntity):
    """One activation id on a Wi-Fi operator."""

    def __init__(
        self, coordinator: MyCentsysCoordinator, serial: str, activation: Activation
    ) -> None:
        super().__init__(coordinator, serial)
        self._activation = activation
        self._attr_unique_id = f"{serial}-{activation.key}"
        self._attr_name = activation.name
        self._attr_icon = activation.icon

    async def async_press(self) -> None:
        await self.coordinator.async_activate(self._serial, self._activation.trigger_id)


class MyCentsysGwebButton(MyCentsysGwebEntity, ButtonEntity):
    """One output on a GSM device."""

    _attr_icon = "mdi:gesture-tap-button"

    def __init__(self, coordinator: MyCentsysCoordinator, device_id: int, io) -> None:
        super().__init__(coordinator, device_id)
        self._io = io
        self._attr_unique_id = f"{GWEB_PREFIX}{device_id}-{io.number}"
        self._attr_name = io.name

    async def async_press(self) -> None:
        await self.coordinator.async_activate_gweb(self._device_id, self._io.number)
