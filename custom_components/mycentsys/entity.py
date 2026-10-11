"""Shared entity plumbing."""

from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, GWEB_PREFIX, MANUFACTURER
from .coordinator import MyCentsysCoordinator, MyCentsysDevice


class MyCentsysEntity(CoordinatorEntity[MyCentsysCoordinator]):
    """Base for entities belonging to one Wi-Fi operator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MyCentsysCoordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._serial = serial
        device = coordinator.data.devices[serial]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=device.model,
            serial_number=serial,
            connections=(
                {(CONNECTION_NETWORK_MAC, format_mac(device.mac))}
                if device.mac
                else set()
            ),
        )

    @property
    def device(self) -> MyCentsysDevice | None:
        return self.coordinator.data.devices.get(self._serial)

    @property
    def available(self) -> bool:
        device = self.device
        if device is None or not super().available:
            return False
        # IsOnline is absent on some product types; absence is not "offline".
        return device.online is not False


class MyCentsysGwebEntity(CoordinatorEntity[MyCentsysCoordinator]):
    """Base for entities belonging to one GSM (G-Web) device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MyCentsysCoordinator, device_id: int) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        device = coordinator.data.gweb_devices[device_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{GWEB_PREFIX}{device_id}")},
            name=device.name,
            manufacturer=MANUFACTURER,
            model="G-Ultra (GSM)",
            serial_number=device.imei or None,
        )

    @property
    def gweb_device(self):
        return self.coordinator.data.gweb_devices.get(self._device_id)

    @property
    def available(self) -> bool:
        device = self.gweb_device
        return super().available and device is not None and device.online
