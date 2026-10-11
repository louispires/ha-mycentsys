"""Config and options flow: phone number, one OTP, done."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import GatewayApi, MyCentsysAuthError, MyCentsysError
from .const import (
    CONF_ENABLE_GWEB,
    CONF_EXTRA_ACTIVATIONS,
    CONF_OTP,
    CONF_OTP_CHANNEL,
    CONF_PHONE,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_SERVICE_TOKEN,
    CONF_USER_TOKEN,
    DEFAULT_ACTIVATIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTIONAL_ACTIVATIONS,
    OTP_SMS,
    OTP_WHATSAPP,
    REGION_AU,
    REGION_ZA,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_TOKEN_FILE = "service_token.json"
_DIALLING_CODE = {REGION_ZA: "+27", REGION_AU: "+61"}
_PHONE_RE = re.compile(r"^\+\d{8,15}$")

_REGIONS = [
    SelectOptionDict(value=REGION_ZA, label="South Africa"),
    SelectOptionDict(value=REGION_AU, label="Australia / New Zealand"),
]
_CHANNELS = [
    SelectOptionDict(value=str(OTP_SMS), label="SMS"),
    SelectOptionDict(value=str(OTP_WHATSAPP), label="WhatsApp"),
]


def load_service_token() -> str | None:
    """Read the app's service token from service_token.json, if it was installed."""
    path = Path(__file__).parent / SERVICE_TOKEN_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _LOGGER.warning("%s exists but could not be read", SERVICE_TOKEN_FILE)
        return None
    token = data.get("ServiceLevelJwt") or data.get("service_token")
    return str(token) if token else None


def normalise_phone(phone: str, region: str) -> str:
    """Turn what people actually type into the +27831234567 the API wants."""
    cleaned = re.sub(r"[\s()\-]", "", phone.strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    elif cleaned.startswith("0"):
        cleaned = _DIALLING_CODE.get(region, "+27") + cleaned[1:]
    elif not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


class MyCentsysConfigFlow(ConfigFlow, domain=DOMAIN):
    """Collect the phone number, send an OTP, store the resulting token."""

    VERSION = 1

    def __init__(self) -> None:
        self._phone: str = ""
        self._region: str = REGION_ZA
        self._service_token: str = ""
        self._reauth_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MyCentsysOptionsFlow:
        return MyCentsysOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        bundled_token = await self.hass.async_add_executor_job(load_service_token)
        if not bundled_token and self._reauth_entry is not None:
            bundled_token = self._reauth_entry.data.get(CONF_SERVICE_TOKEN)
        errors: dict[str, str] = {}

        if user_input is not None:
            region = user_input[CONF_REGION]
            phone = normalise_phone(user_input[CONF_PHONE], region)
            token = (user_input.get(CONF_SERVICE_TOKEN) or bundled_token or "").strip()

            if not _PHONE_RE.match(phone):
                errors[CONF_PHONE] = "invalid_phone"
            elif not token:
                errors[CONF_SERVICE_TOKEN] = "missing_service_token"
            else:
                await self.async_set_unique_id(phone)
                if self._reauth_entry is None:
                    self._abort_if_unique_id_configured()
                else:
                    self._abort_if_unique_id_mismatch(reason="wrong_account")

                api = GatewayApi(
                    async_get_clientsession(self.hass), region, service_token=token
                )
                try:
                    sent = await api.send_otp(phone, int(user_input[CONF_OTP_CHANNEL]))
                except MyCentsysAuthError:
                    errors["base"] = "invalid_service_token"
                except MyCentsysError as err:
                    _LOGGER.debug("SendOtp failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if not sent:
                        errors["base"] = "otp_refused"
                    else:
                        self._phone = phone
                        self._region = region
                        self._service_token = token
                        return await self.async_step_otp()

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_schema(user_input, bundled_token),
            errors=errors,
        )

    def _user_schema(
        self, user_input: dict[str, Any] | None, bundled_token: str | None
    ) -> vol.Schema:
        previous = user_input or {}
        default_phone = previous.get(CONF_PHONE) or (
            self._reauth_entry.data[CONF_PHONE] if self._reauth_entry else ""
        )
        default_region = previous.get(CONF_REGION) or (
            self._reauth_entry.data[CONF_REGION] if self._reauth_entry else REGION_ZA
        )
        schema: dict[Any, Any] = {
            vol.Required(CONF_PHONE, default=default_phone): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEL)
            ),
            vol.Required(CONF_REGION, default=default_region): SelectSelector(
                SelectSelectorConfig(options=_REGIONS, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_OTP_CHANNEL, default=str(OTP_SMS)): SelectSelector(
                SelectSelectorConfig(options=_CHANNELS, mode=SelectSelectorMode.LIST)
            ),
        }
        if not bundled_token:
            schema[vol.Required(CONF_SERVICE_TOKEN, default="")] = TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            )
        return vol.Schema(schema)

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            api = GatewayApi(
                async_get_clientsession(self.hass),
                self._region,
                service_token=self._service_token,
            )
            try:
                user_token = await api.validate_otp(
                    self._phone, str(user_input[CONF_OTP]).strip()
                )
            except MyCentsysAuthError:
                errors[CONF_OTP] = "invalid_otp"
            except MyCentsysError as err:
                _LOGGER.debug("ValidateOtp failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                data = {
                    CONF_PHONE: self._phone,
                    CONF_REGION: self._region,
                    CONF_SERVICE_TOKEN: self._service_token,
                    CONF_USER_TOKEN: user_token,
                }
                if self._reauth_entry is not None:
                    return self.async_update_reload_and_abort(
                        self._reauth_entry, data=data
                    )
                return self.async_create_entry(
                    title=f"MyCentsys {self._phone}",
                    data=data,
                    options={
                        CONF_EXTRA_ACTIVATIONS: list(DEFAULT_ACTIVATIONS),
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_ENABLE_GWEB: True,
                    },
                )

        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_OTP): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.NUMBER)
                    )
                }
            ),
            errors=errors,
            description_placeholders={"phone": self._phone},
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()


class MyCentsysOptionsFlow(OptionsFlow):
    """Which extra buttons to create, and how often to poll."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_EXTRA_ACTIVATIONS: user_input[CONF_EXTRA_ACTIVATIONS],
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_ENABLE_GWEB: user_input[CONF_ENABLE_GWEB],
                }
            )

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EXTRA_ACTIVATIONS,
                        default=list(
                            options.get(CONF_EXTRA_ACTIVATIONS, DEFAULT_ACTIVATIONS)
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=_activation_options(),
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=10,
                            max=600,
                            step=5,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_ENABLE_GWEB,
                        default=options.get(CONF_ENABLE_GWEB, True),
                    ): BooleanSelector(),
                }
            ),
        )


def _activation_options() -> list[SelectOptionDict]:
    """Every optional activation across all families, de-duplicated by key."""
    seen: dict[str, str] = {}
    for activations in OPTIONAL_ACTIVATIONS.values():
        for activation in activations:
            seen.setdefault(activation.key, activation.name)
    return [
        SelectOptionDict(value=key, label=name) for key, name in sorted(seen.items())
    ]
