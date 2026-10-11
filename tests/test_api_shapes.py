"""Response-parsing rules for the Gateway API. Needs aiohttp; no network.

The gateway is ASP.NET and may answer in PascalCase or camelCase depending on
how it is configured, so every response read has to survive either.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

api = importlib.import_module("mycentsys.api")


class _StubApi(api.GatewayApi):
    """A GatewayApi whose _post returns a canned reply instead of calling out."""

    def __init__(self, reply: object) -> None:
        super().__init__(None, "za", service_token="service")
        self._reply = reply
        self.calls: list[str] = []

    async def _post(self, route, **kwargs):
        self.calls.append(route)
        # The real _post wraps every decoded reply, so the stub must too.
        return api.case_insensitive(self._reply)


def _run(coroutine):
    return asyncio.run(coroutine)


def test_case_insensitive_reads_either_casing():
    wrapped = api.case_insensitive({"SerialNumber": "123", "deviceName": "Gate"})
    assert wrapped.get("serialnumber") == "123"
    assert wrapped.get("DeviceName") == "Gate"
    assert "SERIALNUMBER" in wrapped


def test_case_insensitive_reaches_nested_objects_and_lists():
    wrapped = api.case_insensitive(
        {"deviceWiFiStatus": {"isOnline": True}, "ioConfigs": [{"ioNumber": 2}]}
    )
    assert wrapped["DeviceWiFiStatus"]["IsOnline"] is True
    assert wrapped["IOConfigs"][0]["IONumber"] == 2


def test_case_insensitive_keeps_exact_matches_first():
    wrapped = api.case_insensitive({"Response": "exact", "response": "folded"})
    assert wrapped["Response"] == "exact"


def test_missing_keys_still_raise_and_default():
    wrapped = api.case_insensitive({"Response": "x"})
    assert wrapped.get("Nope", "fallback") == "fallback"
    assert "Nope" not in wrapped


def test_validate_otp_accepts_a_camel_case_reply():
    stub = _StubApi({"response": "header.payload.signature"})
    assert _run(stub.validate_otp("+27831234567", "123456")) == (
        "header.payload.signature"
    )
    assert stub.user_token == "header.payload.signature"


def test_validate_otp_accepts_a_bare_token():
    stub = _StubApi("header.payload.signature")
    assert _run(stub.validate_otp("+27831234567", "123456")) == (
        "header.payload.signature"
    )


def test_validate_otp_rejects_an_empty_response():
    for reply in ({"Response": None}, {}, None, True):
        stub = _StubApi(reply)
        try:
            _run(stub.validate_otp("+27831234567", "123456"))
        except api.MyCentsysAuthError:
            continue
        raise AssertionError(f"{reply!r} should not have been accepted")


def test_certificate_reads_a_camel_case_reply():
    stub = _StubApi({"certificatePfxBase64": "AAA=", "certificatePassword": "pw"})
    assert _run(stub.get_certificate()) == ("AAA=", "pw")
