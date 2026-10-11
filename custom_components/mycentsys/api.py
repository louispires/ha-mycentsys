"""Async client for the Centurion Gateway API used by MyCentsys Remote.

Routes sit directly under the base URL with no /api prefix, and the generated
server expects POST with an empty JSON body even for the "Get…" routes.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from yarl import URL

from .const import GATEWAY_URL, OTP_SMS

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=20)


class MyCentsysError(Exception):
    """Any failure talking to the Gateway API."""


class MyCentsysAuthError(MyCentsysError):
    """The token was rejected; the user has to sign in again."""


class CaseInsensitiveDict(dict):
    """A response object whose keys match whatever case the server used.

    The gateway is ASP.NET, so whether it answers in PascalCase or camelCase
    depends on how the server is configured. The app's C# client is built on
    Newtonsoft, which matches either way, so the wire casing was never pinned
    down. Everything here asks for the PascalCase name from the models.
    """

    def __getitem__(self, key: Any) -> Any:
        try:
            return super().__getitem__(key)
        except KeyError:
            if isinstance(key, str):
                folded = key.casefold()
                for existing, value in self.items():
                    if isinstance(existing, str) and existing.casefold() == folded:
                        return value
            raise

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: Any) -> bool:
        try:
            self[key]
        except KeyError:
            return False
        return True


def case_insensitive(value: Any) -> Any:
    """Re-wrap decoded JSON so nested objects ignore key casing too."""
    if isinstance(value, dict):
        return CaseInsensitiveDict(
            {key: case_insensitive(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return [case_insensitive(item) for item in value]
    return value


class GatewayApi:
    """Thin wrapper over the handful of routes this integration needs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        region: str,
        *,
        service_token: str | None = None,
        user_token: str | None = None,
    ) -> None:
        self._session = session
        self._base = URL(GATEWAY_URL[region] + "/")
        self._service_token = service_token
        self.user_token = user_token

    # -- auth -------------------------------------------------------------

    async def send_otp(self, phone: str, channel: int = OTP_SMS) -> bool:
        """Ask the server to send a one-time pin. Uses the app's service token."""
        result = await self._post(
            "SendOtp",
            token=self._service_token,
            json={
                "MobileNumber": phone,
                "OtpPlatform": channel,
                "ThreeLetterIsoLanguageName": "eng",
            },
        )
        return bool(result)

    async def validate_otp(self, phone: str, otp: str) -> str:
        """Exchange the pin for this user's long-lived token."""
        result = await self._post(
            "ValidateOtp",
            token=self._service_token,
            json={"MobileNumber": phone, "Otp": otp},
        )
        if isinstance(result, dict):
            token = result.get("Response")
        elif isinstance(result, str) and result.count(".") == 2:
            # Some deployments hand the JWT back bare rather than wrapped.
            token = result
        else:
            token = None
        if not token or not isinstance(token, str):
            _LOGGER.debug(
                "ValidateOtp returned no token; response was %s",
                sorted(result) if isinstance(result, dict) else type(result).__name__,
            )
            raise MyCentsysAuthError("OTP rejected")
        self.user_token = token
        return token

    # -- devices ----------------------------------------------------------

    async def get_devices(self, phone: str) -> list[dict[str, Any]]:
        result = await self._post(
            "GetDevicesByRemoteUserNumber",
            params={"remoteUserNumber": phone},
        )
        return list(result or [])

    async def get_operator_overview(self, serials: list[str]) -> list[dict[str, Any]]:
        if not serials:
            return []
        result = await self._post(
            "GetOperatorOverview", json={"OperatorSerialNumbers": serials}
        )
        return list(result or [])

    async def get_certificate(self) -> tuple[str, str]:
        """Return the client certificate (PFX, base64) for the mTLS MQTT session."""
        result = await self._post("GetCertificate")
        if not isinstance(result, dict) or not result.get("CertificatePfxBase64"):
            raise MyCentsysError("certificate response did not contain a PFX")
        return result["CertificatePfxBase64"], result.get("CertificatePassword") or ""

    async def get_gweb_token(self, phone: str) -> str:
        """Mint the short-lived token that the G-Web (GSM) endpoints exchange."""
        text = await self._post(
            "GetGwebToken", params={"mobileNumber": phone}, raw=True
        )
        return str(text or "").strip().strip('"')

    # -- plumbing ---------------------------------------------------------

    async def _post(
        self,
        route: str,
        *,
        token: str | None = None,
        json: Any | None = None,
        params: dict[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        bearer = token or self.user_token
        if not bearer:
            raise MyCentsysAuthError("no token available")
        url = self._base.join(URL(route))
        if params:
            url = url.with_query(params)
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        # The "Get…" routes take no body but still insist on the JSON content type.
        body: dict[str, Any] = {"json": json} if json is not None else {"data": b""}
        try:
            async with self._session.post(
                url, headers=headers, timeout=_TIMEOUT, **body
            ) as resp:
                text = await resp.text()
                _LOGGER.debug("%s -> HTTP %s (%s bytes)", route, resp.status, len(text))
                if resp.status in (401, 403):
                    raise MyCentsysAuthError(f"HTTP {resp.status} from {route}")
                if resp.status >= 400:
                    raise MyCentsysError(
                        f"HTTP {resp.status} from {route}: {text[:300]}"
                    )
                if raw:
                    return text
                if not text.strip():
                    return None
                try:
                    return case_insensitive(await resp.json(content_type=None))
                except ValueError:
                    return text
        except aiohttp.ClientError as err:
            raise MyCentsysError(f"{route} failed: {err}") from err
        except TimeoutError as err:
            raise MyCentsysError(f"{route} timed out") from err
