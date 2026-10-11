"""One-shot MQTT activation session against a Wi-Fi operator.

The app opens a mutual-TLS MQTT connection with a per-user client certificate,
authenticates with the phone number, then sends the activation. This module does
the same thing synchronously; call it from an executor thread.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import os
import ssl
import tempfile
import threading
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from .api import MyCentsysError
from .protocol import (
    PacketType,
    build_activation_payload,
    build_auth_payload,
    build_packet,
    parse_activation_response,
    parse_auth_response,
    parse_packet,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 15.0
SUBSCRIBE_TIMEOUT = 10.0
CONNECTION_REQUEST_TIMEOUT = 2.0
AUTH_TIMEOUT = 6.0
ACTIVATION_TIMEOUT = 12.0


class CertificateRejected(MyCentsysError):
    """The TLS handshake failed, so the client certificate is worth re-fetching."""


@dataclass(slots=True)
class ActivationOutcome:
    """What the operator said about the activation."""

    result_code: int
    config_version: int


class ActivationSession:
    """Connect, authenticate, send one activation, disconnect."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        client_id: str,
        serial: str,
        phone: str,
        key: bytes,
        pfx_base64: str,
        pfx_password: str,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._serial = serial
        self._phone = phone
        self._key = key
        self._pfx_base64 = pfx_base64
        self._pfx_password = pfx_password

        self._client: mqtt.Client | None = None
        self._connected = threading.Event()
        self._subscribed = threading.Event()
        self._connect_ack = threading.Event()
        self._trigger_reply = threading.Event()
        self._trigger_payload: bytes | None = None
        self._connect_reason: str | None = None

    # -- public -----------------------------------------------------------

    def run(self, trigger_id: int, config_version: int) -> ActivationOutcome:
        """Perform the whole handshake and return the operator's response."""
        cert_file, key_file = _write_client_cert(self._pfx_base64, self._pfx_password)
        try:
            self._connect(cert_file, key_file)
            self._subscribe()
            self._connection_request()
            session_key = self._authenticate()
            return self._activate(trigger_id, config_version, session_key)
        finally:
            self._disconnect()
            for path in (cert_file, key_file):
                with contextlib.suppress(OSError):
                    os.unlink(path)

    # -- steps ------------------------------------------------------------

    def _connect(self, cert_file: str, key_file: str) -> None:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._client_id,
            protocol=mqtt.MQTTv5,
            clean_session=None,
        )
        client.on_connect = self._on_connect
        client.on_subscribe = self._on_subscribe
        client.on_message = self._on_message

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        # The app accepts any server certificate here; the operators present
        # self-signed certs that no public root will chain to.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            context.set_ciphers("DEFAULT:@SECLEVEL=1")
        except ssl.SSLError:  # pragma: no cover - depends on the OpenSSL build
            _LOGGER.debug("Could not lower the cipher security level")
        context.load_cert_chain(cert_file, key_file)
        client.tls_set_context(context)

        self._client = client
        try:
            client.connect(self._host, self._port, keepalive=30, clean_start=True)
        except ssl.SSLError as err:
            raise CertificateRejected(
                f"TLS handshake with the broker failed: {err}"
            ) from err
        except OSError as err:
            raise MyCentsysError(
                f"cannot reach the broker {self._host}: {err}"
            ) from err
        client.loop_start()
        if not self._connected.wait(CONNECT_TIMEOUT):
            raise MyCentsysError(
                self._connect_reason or "timed out connecting to the broker"
            )

    def _subscribe(self) -> None:
        topics = [
            (f"{self._serial}/userRemoteTriggerResponse", 1),
            (f"{self._serial}/connectionRequestResponse", 1),
            (f"{self._serial}/response", 1),
        ]
        assert self._client is not None
        self._client.subscribe(topics)
        if not self._subscribed.wait(SUBSCRIBE_TIMEOUT):
            raise MyCentsysError("the broker never acknowledged the subscriptions")

    def _connection_request(self) -> None:
        """Nudge the operator into a session. A missing ack is not fatal."""
        self._publish(
            f"{self._serial}/connectionRequest",
            b"",
            qos=2,
            response_topic=f"{self._serial}/connectionRequestResponse",
        )
        if not self._connect_ack.wait(CONNECTION_REQUEST_TIMEOUT):
            _LOGGER.debug("%s: no connection request ack, continuing", self._serial)

    def _authenticate(self) -> int:
        payload = self._exchange(
            PacketType.AUTH_REQUEST, build_auth_payload(self._phone), AUTH_TIMEOUT
        )
        if payload is None:
            raise MyCentsysError(
                "no authentication response; the operator is offline or out of reach"
            )
        packet_type, plain = parse_packet(payload, self._key)
        if packet_type is not PacketType.AUTH_RESPONSE:
            raise MyCentsysError(f"expected an auth response, got {packet_type.name}")
        auth_code, session_key = parse_auth_response(plain)
        if auth_code != 1:
            raise MyCentsysError(
                f"the operator rejected authentication (code {auth_code})"
            )
        return session_key

    def _activate(
        self, trigger_id: int, config_version: int, session_key: int
    ) -> ActivationOutcome:
        payload = self._exchange(
            PacketType.ACTIVATION_REQUEST,
            build_activation_payload(config_version, trigger_id, session_key),
            ACTIVATION_TIMEOUT,
        )
        if payload is None:
            raise MyCentsysError("no activation response from the operator")
        packet_type, plain = parse_packet(payload, self._key)
        if packet_type is not PacketType.ACTIVATION_RESPONSE:
            raise MyCentsysError(
                f"expected an activation response, got {packet_type.name}"
            )
        device_config_version, result_code = parse_activation_response(plain)
        return ActivationOutcome(
            result_code=result_code, config_version=device_config_version
        )

    def _exchange(
        self, packet_type: PacketType, payload: bytes, timeout: float
    ) -> bytes | None:
        self._trigger_reply.clear()
        self._trigger_payload = None
        self._publish(
            f"{self._serial}/userRemoteTrigger",
            build_packet(packet_type, payload, self._key),
            qos=0,
            response_topic=f"{self._serial}/userRemoteTriggerResponse",
        )
        if not self._trigger_reply.wait(timeout):
            return None
        return self._trigger_payload

    def _publish(
        self, topic: str, payload: bytes, *, qos: int, response_topic: str
    ) -> None:
        properties = Properties(PacketTypes.PUBLISH)
        properties.UserProperty = ("ClientId", self._client_id)
        properties.ResponseTopic = response_topic
        assert self._client is not None
        info = self._client.publish(topic, payload, qos=qos, properties=properties)
        if qos > 0:
            info.wait_for_publish(timeout=5)

    def _disconnect(self) -> None:
        if self._client is None:
            return
        try:
            self._client.disconnect()
            self._client.loop_stop()
        except Exception:  # pragma: no cover - teardown must not mask the result
            _LOGGER.debug("Error while disconnecting from the broker", exc_info=True)

    # -- paho callbacks ---------------------------------------------------

    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code == 0:
            self._connected.set()
        else:
            self._connect_reason = f"broker refused the connection: {reason_code}"
            self._connected.set()

    def _on_subscribe(
        self, _client, _userdata, _mid, _reason_codes, _properties
    ) -> None:
        self._subscribed.set()

    def _on_message(self, _client, _userdata, message) -> None:
        if message.topic.endswith("userRemoteTriggerResponse"):
            self._trigger_payload = bytes(message.payload)
            self._trigger_reply.set()
        elif message.topic.endswith("connectionRequestResponse"):
            self._connect_ack.set()


def _write_client_cert(pfx_base64: str, password: str) -> tuple[str, str]:
    """Split the PKCS#12 bundle into PEM files, because ssl cannot load it in memory."""
    try:
        private_key, certificate, extra = pkcs12.load_key_and_certificates(
            base64.b64decode(pfx_base64), password.encode() or None
        )
    except Exception as err:
        raise MyCentsysError(f"could not read the client certificate: {err}") from err
    if private_key is None or certificate is None:
        raise MyCentsysError("the client certificate is missing its key or body")

    chain = certificate.public_bytes(serialization.Encoding.PEM)
    for extra_cert in extra or []:
        chain += extra_cert.public_bytes(serialization.Encoding.PEM)
    key_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return _temp_file(chain, ".crt"), _temp_file(key_bytes, ".key")


def _temp_file(content: bytes, suffix: str) -> str:
    handle, path = tempfile.mkstemp(prefix="mycentsys-", suffix=suffix)
    with os.fdopen(handle, "wb") as fh:
        fh.write(content)
    os.chmod(path, 0o600)
    return path
