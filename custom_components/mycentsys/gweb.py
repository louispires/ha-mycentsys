"""G-Web client for GSM/4G (G-Ultra) devices.

These never appear in the Gateway API device list. They live on gweb.co.za and
are driven by plain HTTP, authorised by a cached access token rather than a
bearer header. Every data parameter is base64-encoded and joined with '|'.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .api import MyCentsysError
from .const import GWEB_URL

_LOGGER = logging.getLogger(__name__)

APP_NAME = "MyCentsys Remote"
APP_BUILD = "2.1.0.39"
APP_TYPE = "production"
CLIENT_NAME = "HomeAssistant"

_TIMEOUT = aiohttp.ClientTimeout(total=25)
_ACTIVATION_OK = "Activation Queued Successfully"


@dataclass(slots=True)
class GwebIo:
    """One switchable output on a GSM device."""

    number: int
    name: str
    direction: int


@dataclass(slots=True)
class GwebDevice:
    device_id: int
    name: str
    imei: str
    online: bool
    ios: list[GwebIo] = field(default_factory=list)


def _enc(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


class GwebApi:
    """Device listing and activation for GSM operators."""

    def __init__(self, session: aiohttp.ClientSession, region: str, phone: str) -> None:
        self._session = session
        self._base = GWEB_URL[region]
        self._phone = phone
        self.access_token: str | None = None

    async def login(self, gweb_otp_token: str) -> str:
        """Exchange the Gateway API's G-Web token for a G-Web access token."""
        user_info = f"{APP_NAME}|{self._phone}|{CLIENT_NAME}"
        bearer = base64.b64encode(
            f"{user_info}:{gweb_otp_token}".encode("ascii")
        ).decode()
        try:
            async with self._session.post(
                f"{self._base}/api/MCROTPNumb",
                headers={"Authorization": f"Bearer {bearer}"},
                data={"Part1": APP_NAME, "Part2": APP_BUILD},
                timeout=_TIMEOUT,
            ) as resp:
                body = (await resp.text()).replace('"', "").strip()
                if resp.status >= 400 or not body:
                    raise MyCentsysError(f"G-Web sign-in failed (HTTP {resp.status})")
        except aiohttp.ClientError as err:
            raise MyCentsysError(f"G-Web sign-in failed: {err}") from err
        try:
            self.access_token = base64.b64decode(body).decode("latin-1")
        except ValueError as err:
            raise MyCentsysError("G-Web returned an unreadable token") from err
        return self.access_token

    async def get_devices(self) -> list[GwebDevice]:
        if not self.access_token:
            raise MyCentsysError("not signed in to G-Web")
        payload = "|".join(
            (_enc("-1"), _enc(self.access_token), _enc("Unavailable"), _enc(APP_TYPE))
        )
        text = await self._request("POST", "/api/MCRConfEnV3", data=payload)
        if "No Buttons for this number" in text:
            return []
        try:
            root = json.loads(text.replace("\\", "").strip('"'))
        except ValueError as err:
            raise MyCentsysError("G-Web device list was not valid JSON") from err

        devices: list[GwebDevice] = []
        for raw in root.get("DeviceConfigs") or []:
            devices.append(
                GwebDevice(
                    device_id=int(raw.get("DeviceId", 0)),
                    name=str(raw.get("DeviceName") or f"G-Web {raw.get('DeviceId')}"),
                    imei=str(raw.get("DeviceImei") or ""),
                    online=bool(raw.get("DeviceOnline")),
                    ios=[
                        GwebIo(
                            number=int(io.get("IONumber", 0)),
                            name=str(
                                io.get("IOName") or f"Output {io.get('IONumber')}"
                            ),
                            direction=int(io.get("IODirection", 0)),
                        )
                        for io in raw.get("IOConfigs") or []
                    ],
                )
            )
        return devices

    async def activate(self, device_id: int, io_number: int) -> bool:
        if not self.access_token:
            raise MyCentsysError("not signed in to G-Web")
        data = "|".join(
            (_enc(str(device_id)), _enc(self.access_token), _enc(str(io_number)))
        )
        text = await self._request("GET", f"/api/MCRActEn?data={data}")
        result = text.replace("\\", "").strip('"')
        if result != _ACTIVATION_OK:
            raise MyCentsysError(
                f"G-Web refused the activation: {result or 'no reply'}"
            )
        return True

    async def _request(self, method: str, path: str, **kwargs: Any) -> str:
        try:
            async with self._session.request(
                method, f"{self._base}{path}", timeout=_TIMEOUT, **kwargs
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise MyCentsysError(
                        f"HTTP {resp.status} from {path}: {text[:200]}"
                    )
                return text
        except aiohttp.ClientError as err:
            raise MyCentsysError(f"{path} failed: {err}") from err
        except TimeoutError as err:
            raise MyCentsysError(f"{path} timed out") from err
