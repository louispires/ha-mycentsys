"""Diagnostic sensors from the operator overview."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MyCentsysConfigEntry
from .const import (
    FAMILY_SIREN,
    OPERATOR_STATUS,
    POWER_STATUS,
    THEFT_ALARM_STATUS,
    status_name,
)
from .coordinator import MyCentsysCoordinator, MyCentsysDevice
from .entity import MyCentsysEntity


@dataclass(frozen=True, kw_only=True)
class MyCentsysSensorDescription(SensorEntityDescription):
    """A sensor fed from the device record or its overview."""

    value: Callable[[MyCentsysDevice], str | int | None]


SENSORS: tuple[MyCentsysSensorDescription, ...] = (
    MyCentsysSensorDescription(
        key="operator_status",
        name="Status",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(set(OPERATOR_STATUS.values())),
        value=lambda d: status_name(d.status.get("OperatorStatus"), OPERATOR_STATUS),
    ),
    MyCentsysSensorDescription(
        key="power_supply",
        name="Power supply",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(set(POWER_STATUS.values())),
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda d: status_name(d.status.get("PowerSupplyStatus"), POWER_STATUS),
    ),
    MyCentsysSensorDescription(
        key="theft_alarm",
        name="Theft alarm",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(set(THEFT_ALARM_STATUS.values())),
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda d: status_name(
            d.status.get("TheftAlarmState"), THEFT_ALARM_STATUS
        ),
    ),
    MyCentsysSensorDescription(
        key="wifi_rssi",
        name="Wi-Fi signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda d: d.rssi,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyCentsysConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        MyCentsysSensor(coordinator, serial, description)
        for serial, device in coordinator.data.devices.items()
        if device.is_wifi and device.family != FAMILY_SIREN
        for description in SENSORS
    )


class MyCentsysSensor(MyCentsysEntity, SensorEntity):
    """Reads one field out of the cached device record."""

    entity_description: MyCentsysSensorDescription

    def __init__(
        self,
        coordinator: MyCentsysCoordinator,
        serial: str,
        description: MyCentsysSensorDescription,
    ) -> None:
        super().__init__(coordinator, serial)
        self.entity_description = description
        self._attr_unique_id = f"{serial}-{description.key}"

    @property
    def native_value(self) -> str | int | None:
        device = self.device
        if device is None:
            return None
        value = self.entity_description.value(device)
        options = self.entity_description.options
        # An enum sensor must never report a state outside its declared options.
        if options is not None and value is not None and value not in options:
            return None
        return value
