"""Gate and garage door covers."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MyCentsysConfigEntry
from .const import (
    FAMILY_GARAGE,
    FAMILY_SIREN,
    OPERATOR_STATUS,
    SDO_CLOSE_ONLY,
    SDO_OPEN_ONLY,
    SDO_RUN,
    TRG,
    status_name,
)
from .coordinator import MyCentsysCoordinator
from .entity import MyCentsysEntity

_LOGGER = logging.getLogger(__name__)

MOVING = ("opening", "closing")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyCentsysConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        MyCentsysCover(coordinator, serial)
        for serial, device in coordinator.data.devices.items()
        if device.is_wifi and device.family != FAMILY_SIREN
    )


class MyCentsysCover(MyCentsysEntity, CoverEntity):
    """One operator, driven by its activation ids.

    Sliders and swing gates only have a single open/close trigger, so an open
    request on an already-open gate is dropped rather than closing it.
    """

    _attr_name = None
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(self, coordinator: MyCentsysCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = serial
        family = coordinator.data.devices[serial].family
        self._is_garage = family == FAMILY_GARAGE
        self._attr_device_class = (
            CoverDeviceClass.GARAGE if self._is_garage else CoverDeviceClass.GATE
        )

    # -- state ------------------------------------------------------------

    @property
    def _status(self) -> str | None:
        device = self.device
        if device is None:
            return None
        return status_name(device.status.get("OperatorStatus"), OPERATOR_STATUS)

    @property
    def is_closed(self) -> bool | None:
        status = self._status
        if status is None or status == "unknown":
            return None
        return status == "closed"

    @property
    def is_opening(self) -> bool:
        return self._status == "opening"

    @property
    def is_closing(self) -> bool:
        return self._status == "closing"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"operator_status": self._status or "unknown"}

    # -- commands ---------------------------------------------------------

    async def async_open_cover(self, **kwargs: Any) -> None:
        if self._is_garage:
            await self._activate(SDO_OPEN_ONLY)
            return
        if self._status in ("open", "opening"):
            _LOGGER.debug("%s is already open; not sending a trigger", self._serial)
            return
        await self._activate(TRG)

    async def async_close_cover(self, **kwargs: Any) -> None:
        if self._is_garage:
            await self._activate(SDO_CLOSE_ONLY)
            return
        if self._status in ("closed", "closing"):
            _LOGGER.debug("%s is already closed; not sending a trigger", self._serial)
            return
        await self._activate(TRG)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """A trigger during travel stops the operator."""
        if self._status not in MOVING:
            return
        await self._activate(SDO_RUN if self._is_garage else TRG)

    async def _activate(self, trigger_id: int) -> None:
        await self.coordinator.async_activate(self._serial, trigger_id)
