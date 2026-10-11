"""Constants, endpoints and the activation catalogue for MyCentsys Remote.

Values reverse-engineered from MyCentsys Remote 2.1.0.39; see PROTOCOL.md in the
mcr-cli project for how the protocol was derived.
"""

from __future__ import annotations

import re
from typing import Final, NamedTuple

DOMAIN: Final = "mycentsys"

CONF_PHONE: Final = "phone"
CONF_REGION: Final = "region"
CONF_OTP: Final = "otp"
CONF_OTP_CHANNEL: Final = "otp_channel"
CONF_SERVICE_TOKEN: Final = "service_token"
CONF_USER_TOKEN: Final = "user_token"
CONF_EXTRA_ACTIVATIONS: Final = "extra_activations"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_ENABLE_GWEB: Final = "enable_gweb"

REGION_ZA: Final = "za"
REGION_AU: Final = "au"

GATEWAY_URL: Final = {
    REGION_ZA: "https://centsys.southafricanorth.cloudapp.azure.com:4445",
    REGION_AU: "https://centsys.australiaeast.cloudapp.azure.com:4445",
}
MQTT_HOST: Final = {REGION_ZA: "20.87.192.195", REGION_AU: "20.213.185.54"}
MQTT_PORT: Final = 8880
GWEB_URL: Final = {
    REGION_ZA: "https://www.gweb.co.za",
    REGION_AU: "https://www.g-web.com.au",
}

# OtpPlatform in the app's SendOtp body.
OTP_WHATSAPP: Final = 1
OTP_SMS: Final = 2

DEFAULT_SCAN_INTERVAL: Final = 30
MANUFACTURER: Final = "Centurion Systems"
# Marks a GSM device in entity ids and device-registry identifiers.
GWEB_PREFIX: Final = "gweb-"

# ---------------------------------------------------------------------------
# Product families (ProductsEnum -> which activation set the operator accepts)
# ---------------------------------------------------------------------------

FAMILY_SLIDER: Final = "slider"
FAMILY_SWING: Final = "swing"
FAMILY_GARAGE: Final = "garage"
FAMILY_SIREN: Final = "siren"

_SWING_PRODUCTS: Final = {30, 31, 32, 33, 34, 45, 46, 47}
_GARAGE_PRODUCTS: Final = {2, 50}
_SIREN_PRODUCTS: Final = {53}

PRODUCT_NAMES: Final = {
    0: "MyCentsys Pro",
    1: "D5 Smart",
    2: "SDO4 Smart",
    3: "D5 Motor Control",
    10: "G-Ultra GSM",
    11: "D5 4G",
    12: "D10 Smart",
    13: "D3 Smart",
    14: "Photon Smart",
    15: "D5 Smart V2",
    16: "D10 Turbo Smart",
    19: "D20 Smart",
    30: "V Series",
    31: "Vantage",
    32: "VertX",
    33: "Vector",
    35: "D Series",
    36: "D5 Evo Smart",
    39: "D6 Smart",
    40: "D10 Smart Plus",
    41: "D3 Smart Plus",
    42: "D5 Smart V2 Plus",
    43: "D10 Turbo Smart Plus",
    44: "D20 Smart Plus",
    45: "Vantage Plus",
    46: "VertX Plus",
    47: "Vector Plus",
    48: "D5 Evo Smart Plus",
    49: "D6 Smart Plus",
    50: "SDO5 Smart Plus",
    52: "D4 Smart Plus",
    53: "Wireless Siren",
}


def family_for_product(product_type: int) -> str:
    """Map the API's ProductType to the activation set the operator understands."""
    if product_type in _GARAGE_PRODUCTS:
        return FAMILY_GARAGE
    if product_type in _SWING_PRODUCTS:
        return FAMILY_SWING
    if product_type in _SIREN_PRODUCTS:
        return FAMILY_SIREN
    return FAMILY_SLIDER


# ---------------------------------------------------------------------------
# Activation ids
# ---------------------------------------------------------------------------

# SliderActivationsEnum / SwingActivationsEnum
TRG: Final = 34
PED: Final = 35
HOLIDAY_LOCK: Final = 1
KEEP_OPEN: Final = 4
COURTESY_LIGHT: Final = 16
COURTESY_LIGHT_TIMER: Final = 17
ARM_ALARM: Final = 25
DISARM_ALARM: Final = 26
CLEAR_ALARMS: Final = 27
CANCEL_AUTO_CLOSE: Final = 31
CANCEL_PIRAC: Final = 32
CANCEL_AUTO_CLOSE_AND_PIRAC: Final = 33
CUSTOM_1: Final = 37
CUSTOM_2: Final = 38
CUSTOM_3: Final = 39
AUX: Final = 70

# SdoActivationsEnum (ordinal values)
SDO_RUN: Final = 1
SDO_LIGHT: Final = 2
SDO_VACATION: Final = 3
SDO_KEEP_OPEN: Final = 4
SDO_OPEN_ONLY: Final = 5
SDO_CLOSE_ONLY: Final = 6
SDO_ARM: Final = 7
SDO_DISARM: Final = 8
SDO_CLEAR_ALARMS: Final = 9
SDO_AUTOCLOSE_OVERRIDE: Final = 10


class Activation(NamedTuple):
    """One optional push-button activation offered for a product family."""

    key: str
    name: str
    trigger_id: int
    icon: str


# Buttons the user can switch on per config entry. Open/close and stop are not
# listed: they are the cover entity.
OPTIONAL_ACTIVATIONS: Final[dict[str, tuple[Activation, ...]]] = {
    FAMILY_SLIDER: (
        Activation("pedestrian", "Pedestrian", PED, "mdi:walk"),
        Activation("holiday_lock", "Holiday lock", HOLIDAY_LOCK, "mdi:lock"),
        Activation("keep_open", "Keep open", KEEP_OPEN, "mdi:gate-open"),
        Activation("courtesy_light", "Courtesy light", COURTESY_LIGHT, "mdi:lightbulb"),
        Activation(
            "courtesy_light_timer",
            "Courtesy light timer",
            COURTESY_LIGHT_TIMER,
            "mdi:timer-outline",
        ),
        Activation("arm_alarm", "Arm alarm", ARM_ALARM, "mdi:shield-lock"),
        Activation("disarm_alarm", "Disarm alarm", DISARM_ALARM, "mdi:shield-off"),
        Activation("clear_alarms", "Clear alarms", CLEAR_ALARMS, "mdi:bell-off"),
        Activation(
            "cancel_auto_close", "Cancel auto-close", CANCEL_AUTO_CLOSE, "mdi:timer-off"
        ),
        Activation(
            "cancel_pirac", "Cancel PIRAC", CANCEL_PIRAC, "mdi:motion-sensor-off"
        ),
        Activation(
            "cancel_auto_close_pirac",
            "Cancel auto-close and PIRAC",
            CANCEL_AUTO_CLOSE_AND_PIRAC,
            "mdi:timer-off-outline",
        ),
        Activation("custom_1", "Custom 1", CUSTOM_1, "mdi:numeric-1-box"),
        Activation("custom_2", "Custom 2", CUSTOM_2, "mdi:numeric-2-box"),
        Activation("custom_3", "Custom 3", CUSTOM_3, "mdi:numeric-3-box"),
        Activation("aux", "Aux output", AUX, "mdi:electric-switch"),
    ),
    FAMILY_GARAGE: (
        Activation("light", "Courtesy light", SDO_LIGHT, "mdi:lightbulb"),
        Activation("vacation_mode", "Vacation mode", SDO_VACATION, "mdi:airplane"),
        Activation("keep_open", "Keep open", SDO_KEEP_OPEN, "mdi:garage-open"),
        Activation("arm_alarm", "Arm alarm", SDO_ARM, "mdi:shield-lock"),
        Activation("disarm_alarm", "Disarm alarm", SDO_DISARM, "mdi:shield-off"),
        Activation("clear_alarms", "Clear alarms", SDO_CLEAR_ALARMS, "mdi:bell-off"),
        Activation(
            "autoclose_override",
            "Override auto-close",
            SDO_AUTOCLOSE_OVERRIDE,
            "mdi:timer-off",
        ),
    ),
    FAMILY_SIREN: (
        Activation("trigger_alarm", "Trigger alarm", 1, "mdi:bullhorn"),
        Activation("clear_alarm", "Clear alarm", 2, "mdi:bullhorn-outline"),
        Activation("mute_alarm", "Mute alarm", 3, "mdi:volume-off"),
        Activation("unmute_alarm", "Unmute alarm", 4, "mdi:volume-high"),
    ),
}
OPTIONAL_ACTIVATIONS[FAMILY_SWING] = tuple(
    a
    for a in OPTIONAL_ACTIVATIONS[FAMILY_SLIDER]
    # Swing operators have no theft-alarm activations.
    if a.key not in ("arm_alarm", "disarm_alarm", "clear_alarms")
)

# Switched on for a new config entry, because they are what people actually press.
DEFAULT_ACTIVATIONS: Final = ("pedestrian",)

# ---------------------------------------------------------------------------
# Status enums from the Gateway API overview response
# ---------------------------------------------------------------------------

OPERATOR_STATUS: Final = {
    0: "unknown",
    1: "open",
    2: "closed",
    3: "partly_open",
    4: "partly_closed",
    5: "opening",
    6: "closing",
}
POWER_STATUS: Final = {0: "normal", 1: "low", 2: "off", 3: "unknown"}
THEFT_ALARM_STATUS: Final = {0: "activated", 1: "cleared", 2: "disabled"}

# ActivationResponseEnum
ACTIVATION_RESULT: Final = {
    1: "ok",
    2: "session_key_mismatch",
    3: "unknown",
    4: "timeout",
    5: "failed",
    6: "user_not_authenticated",
    7: "configuration_mismatch",
    8: "time_barred",
    9: "cancellation_requested",
    10: "device_offline",
    11: "no_internet",
    12: "in_progress",
    13: "access_share_expired",
    14: "device_already_connected",
}
RESULT_OK: Final = 1
RESULT_CONFIG_MISMATCH: Final = 7


def status_name(value: object, mapping: dict[int, str]) -> str | None:
    """Normalise an enum the API may send as a number or as its C# name."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return mapping.get(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return mapping.get(int(text))
    return re.sub(r"(?<!^)(?=[A-Z])", "_", text).lower()
