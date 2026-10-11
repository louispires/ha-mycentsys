"""Connectivity of each operator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MyCentsysConfigEntry
from .const import GWEB_PREFIX
from .coordinator import MyCentsysCoordinator
from .entity import MyCentsysEntity, MyCentsysGwebEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyCentsysConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        MyCentsysOnline(coordinator, serial)
        for serial, device in coordinator.data.devices.items()
        if device.is_wifi
    ]
    entities += [
        MyCentsysGwebOnline(coordinator, device_id)
        for device_id in coordinator.data.gweb_devices
    ]
    async_add_entities(entities)


class MyCentsysOnline(MyCentsysEntity, BinarySensorEntity):
    """Whether the operator is reachable through Centurion's cloud."""

    _attr_name = "Connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MyCentsysCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}-online"

    @property
    def available(self) -> bool:
        # This entity reports the offline state, so it must not go unavailable with it.
        return self.coordinator.last_update_success and self.device is not None

    @property
    def is_on(self) -> bool | None:
        device = self.device
        return None if device is None else device.online


class MyCentsysGwebOnline(MyCentsysGwebEntity, BinarySensorEntity):
    """Whether the GSM device last reported in."""

    _attr_name = "Connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MyCentsysCoordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{GWEB_PREFIX}{device_id}-online"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.gweb_device is not None

    @property
    def is_on(self) -> bool | None:
        device = self.gweb_device
        return None if device is None else device.online
