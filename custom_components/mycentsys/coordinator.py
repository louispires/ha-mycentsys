"""Polling and activation for all MyCentsys devices on one account."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GatewayApi, MyCentsysAuthError, MyCentsysError
from .const import (
    ACTIVATION_RESULT,
    CONF_PHONE,
    CONF_REGION,
    DOMAIN,
    MQTT_HOST,
    MQTT_PORT,
    PRODUCT_NAMES,
    RESULT_CONFIG_MISMATCH,
    RESULT_OK,
    family_for_product,
)
from .gweb import GwebApi, GwebDevice
from .mqtt_trigger import ActivationOutcome, ActivationSession, CertificateRejected
from .protocol import derive_key, mac_to_bytes

_LOGGER = logging.getLogger(__name__)

# The device list changes rarely; the status overview is what needs polling.
DEVICE_LIST_INTERVAL = 300.0
CERTIFICATE_TTL = 12 * 3600.0


@dataclass(slots=True)
class MyCentsysDevice:
    """A Wi-Fi operator on the account, plus its last known status."""

    serial: str
    name: str
    product_type: int
    product_code: int
    mac: str | None
    is_wifi: bool
    family: str
    online: bool | None = None
    rssi: int | None = None
    status: dict = field(default_factory=dict)

    @property
    def model(self) -> str:
        return PRODUCT_NAMES.get(self.product_type, f"Product {self.product_type}")


@dataclass(slots=True)
class MyCentsysData:
    """Everything the entities read."""

    devices: dict[str, MyCentsysDevice] = field(default_factory=dict)
    gweb_devices: dict[int, GwebDevice] = field(default_factory=dict)


class MyCentsysCoordinator(DataUpdateCoordinator[MyCentsysData]):
    """Keeps device state fresh and serialises activations per operator."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, scan_interval: int
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
            config_entry=entry,
        )
        session = async_get_clientsession(hass)
        self.phone: str = entry.data[CONF_PHONE]
        self.region: str = entry.data[CONF_REGION]
        self.api = GatewayApi(session, self.region, user_token=entry.data["user_token"])
        self.gweb: GwebApi | None = None
        self._gweb_session = session

        self._locks: dict[str, asyncio.Lock] = {}
        self._config_versions: dict[str, int] = {}
        self._certificate: tuple[str, str] | None = None
        self._certificate_at = 0.0
        self._devices_at = 0.0
        self._known: dict[str, MyCentsysDevice] = {}
        self._gweb_devices: dict[int, GwebDevice] = {}

    # -- polling ----------------------------------------------------------

    async def _async_update_data(self) -> MyCentsysData:
        try:
            if (
                not self._known
                or time.monotonic() - self._devices_at > DEVICE_LIST_INTERVAL
            ):
                await self._async_refresh_devices()
                await self._async_refresh_gweb()
            try:
                await self._async_refresh_status()
            except MyCentsysAuthError:
                raise
            except MyCentsysError as err:
                # Status is a nicety; triggering still works without it.
                _LOGGER.debug("Operator overview unavailable: %s", err)
        except MyCentsysAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MyCentsysError as err:
            raise UpdateFailed(str(err)) from err
        return MyCentsysData(
            devices=dict(self._known), gweb_devices=dict(self._gweb_devices)
        )

    async def _async_refresh_devices(self) -> None:
        raw_devices = await self.api.get_devices(self.phone)
        devices: dict[str, MyCentsysDevice] = {}
        for raw in raw_devices:
            serial = str(raw.get("SerialNumber") or "")
            if not serial:
                continue
            wifi_status = raw.get("DeviceWiFiStatus") or {}
            product_type = int(raw.get("ProductType") or 0)
            devices[serial] = MyCentsysDevice(
                serial=serial,
                name=str(raw.get("DeviceName") or f"Operator {serial}"),
                product_type=product_type,
                product_code=int(raw.get("ProductCode") or 0),
                mac=raw.get("MacAddress"),
                is_wifi=bool(raw.get("IsWifiDevice")),
                family=family_for_product(product_type),
                online=wifi_status.get("IsOnline"),
                rssi=wifi_status.get("WifiRssi"),
                status=self._known[serial].status if serial in self._known else {},
            )
        self._known = devices
        self._devices_at = time.monotonic()

    async def _async_refresh_status(self) -> None:
        serials = [d.serial for d in self._known.values() if d.is_wifi]
        if not serials:
            return
        for entry in await self.api.get_operator_overview(serials):
            device = self._known.get(str(entry.get("OperatorSerialNumber") or ""))
            if device is not None:
                device.status = entry

    # -- G-Web ------------------------------------------------------------

    async def async_setup_gweb(self) -> None:
        """Sign in to G-Web. Call before the first refresh; failure is not fatal."""
        try:
            otp_token = await self.api.get_gweb_token(self.phone)
            if not otp_token:
                return
            gweb = GwebApi(self._gweb_session, self.region, self.phone)
            await gweb.login(otp_token)
        except MyCentsysError as err:
            _LOGGER.debug("Skipping G-Web devices: %s", err)
            return
        self.gweb = gweb

    async def _async_refresh_gweb(self) -> None:
        """Re-read the GSM device list for its online flags."""
        if self.gweb is None:
            return
        try:
            devices = await self.gweb.get_devices()
        except MyCentsysError as err:
            _LOGGER.debug("G-Web refresh failed: %s", err)
            return
        self._gweb_devices = {device.device_id: device for device in devices}

    # -- activation -------------------------------------------------------

    async def async_activate(self, serial: str, trigger_id: int) -> None:
        """Send one activation to a Wi-Fi operator and raise if it is refused."""
        device = self._known.get(serial)
        if device is None:
            raise HomeAssistantError(f"{serial} is not on this account")
        if not device.is_wifi:
            raise HomeAssistantError(
                f"{device.name} is not a Wi-Fi operator, so it cannot be triggered remotely"
            )
        if not device.mac:
            raise HomeAssistantError(
                f"{device.name} has no MAC address to derive its key from"
            )

        lock = self._locks.setdefault(serial, asyncio.Lock())
        async with lock:
            outcome = await self._async_send(device, trigger_id)

        if outcome.result_code != RESULT_OK:
            reason = ACTIVATION_RESULT.get(
                outcome.result_code, f"code {outcome.result_code}"
            )
            raise HomeAssistantError(f"{device.name} refused the activation: {reason}")
        await self.async_request_refresh()

    async def _async_send(
        self, device: MyCentsysDevice, trigger_id: int
    ) -> ActivationOutcome:
        key = derive_key(mac_to_bytes(device.mac or ""))
        config_version = self._config_versions.get(device.serial, 0)
        outcome = None

        for attempt in range(2):
            pfx, password = await self._async_certificate()
            session = ActivationSession(
                host=MQTT_HOST[self.region],
                port=MQTT_PORT,
                client_id=f"mcr:{self.phone}",
                serial=device.serial,
                phone=self.phone,
                key=key,
                pfx_base64=pfx,
                pfx_password=password,
            )
            try:
                outcome = await self.hass.async_add_executor_job(
                    session.run, trigger_id, config_version
                )
            except CertificateRejected as err:
                if attempt == 0:
                    _LOGGER.debug(
                        "%s: %s, fetching a new certificate", device.serial, err
                    )
                    self._certificate = None
                    continue
                raise HomeAssistantError(f"{device.name}: {err}") from err
            except MyCentsysError as err:
                raise HomeAssistantError(f"{device.name}: {err}") from err

            # The operator reports its own config version when ours is stale.
            if outcome.result_code == RESULT_CONFIG_MISMATCH and attempt == 0:
                config_version = outcome.config_version
                _LOGGER.debug(
                    "%s: retrying with config version %s", device.serial, config_version
                )
                continue
            break

        self._config_versions[device.serial] = config_version
        if outcome is None:
            raise HomeAssistantError(f"{device.name} gave no response")
        return outcome

    async def async_activate_gweb(self, device_id: int, io_number: int) -> None:
        if self.gweb is None:
            raise HomeAssistantError("not signed in to G-Web")
        try:
            await self.gweb.activate(device_id, io_number)
        except MyCentsysError as err:
            raise HomeAssistantError(str(err)) from err

    # -- helpers ----------------------------------------------------------

    async def _async_certificate(self, *, refresh: bool = False) -> tuple[str, str]:
        expired = time.monotonic() - self._certificate_at > CERTIFICATE_TTL
        if self._certificate is None or refresh or expired:
            try:
                self._certificate = await self.api.get_certificate()
            except MyCentsysAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            self._certificate_at = time.monotonic()
        return self._certificate
