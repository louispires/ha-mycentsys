"""Cover state and command rules, driven with a stub coordinator.

Needs homeassistant installed; no hass instance and no network.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

const = importlib.import_module("mycentsys.const")
coordinator_mod = importlib.import_module("mycentsys.coordinator")
cover_mod = importlib.import_module("mycentsys.cover")

MyCentsysDevice = coordinator_mod.MyCentsysDevice
MyCentsysData = coordinator_mod.MyCentsysData


class StubCoordinator:
    """Just enough of the coordinator for the entity to read and command."""

    def __init__(self, device: MyCentsysDevice) -> None:
        self.data = MyCentsysData(devices={device.serial: device})
        self.sent: list[tuple[str, int]] = []
        self.last_update_success = True

    async def async_activate(self, serial: str, trigger_id: int) -> None:
        self.sent.append((serial, trigger_id))

    async def async_request_refresh(self) -> None:
        pass


def _make(family_product: int, status: int | None) -> tuple[StubCoordinator, object]:
    device = MyCentsysDevice(
        serial="123456",
        name="Driveway gate",
        product_type=family_product,
        product_code=0,
        mac="AA:BB:CC:DD:EE:FF",
        is_wifi=True,
        family=const.family_for_product(family_product),
        online=True,
        status={} if status is None else {"OperatorStatus": status},
    )
    coordinator = StubCoordinator(device)
    return coordinator, cover_mod.MyCentsysCover(coordinator, "123456")


def test_a_closed_gate_reports_closed():
    _, cover = _make(1, 2)
    assert cover.is_closed is True
    assert cover.is_opening is False


def test_an_unknown_status_is_reported_as_unknown_not_closed():
    _, cover = _make(1, 0)
    assert cover.is_closed is None


def test_a_missing_overview_is_reported_as_unknown():
    _, cover = _make(1, None)
    assert cover.is_closed is None


def test_a_moving_gate_reports_the_direction():
    _, cover = _make(1, 5)
    assert cover.is_opening is True
    assert cover.is_closing is False


def test_opening_a_closed_slider_sends_the_single_trigger():
    coordinator, cover = _make(1, 2)
    asyncio.run(cover.async_open_cover())
    assert coordinator.sent == [("123456", const.TRG)]


def test_opening_an_already_open_slider_sends_nothing():
    # The gate has only one trigger, so a second one would close it.
    coordinator, cover = _make(1, 1)
    asyncio.run(cover.async_open_cover())
    assert coordinator.sent == []


def test_closing_an_already_closed_slider_sends_nothing():
    coordinator, cover = _make(1, 2)
    asyncio.run(cover.async_close_cover())
    assert coordinator.sent == []


def test_a_slider_with_unknown_state_still_accepts_a_command():
    coordinator, cover = _make(1, None)
    asyncio.run(cover.async_open_cover())
    assert coordinator.sent == [("123456", const.TRG)]


def test_a_garage_door_uses_open_only_and_close_only():
    coordinator, cover = _make(50, 2)
    asyncio.run(cover.async_open_cover())
    asyncio.run(cover.async_close_cover())
    assert coordinator.sent == [
        ("123456", const.SDO_OPEN_ONLY),
        ("123456", const.SDO_CLOSE_ONLY),
    ]


def test_stop_only_acts_while_the_operator_is_moving():
    coordinator, cover = _make(1, 2)
    asyncio.run(cover.async_stop_cover())
    assert coordinator.sent == []

    coordinator, cover = _make(1, 6)
    asyncio.run(cover.async_stop_cover())
    assert coordinator.sent == [("123456", const.TRG)]


def test_device_classes_follow_the_product():
    _, gate = _make(1, 2)
    _, garage = _make(50, 2)
    assert gate.device_class == "gate"
    assert garage.device_class == "garage"
