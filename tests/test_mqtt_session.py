"""Checks the parts of the MQTT session that fail silently if they are wrong.

Needs homeassistant, paho-mqtt and cryptography installed. No broker is used.
"""

from __future__ import annotations

import base64
import datetime
import importlib
import os
import ssl
import sys
from pathlib import Path

import paho.mqtt.client as mqtt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

# Imported as a package member: this module uses relative imports.
trigger = importlib.import_module("mycentsys.mqtt_trigger")


def _self_signed_pfx(password: str) -> str:
    """A throwaway PKCS#12 bundle shaped like the one the API hands out."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mcr-test")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    blob = pkcs12.serialize_key_and_certificates(
        b"mcr",
        key,
        cert,
        None,
        serialization.BestAvailableEncryption(password.encode()),
    )
    return base64.b64encode(blob).decode()


def test_pfx_is_split_into_loadable_pem_files():
    # The failure this guards against: PEM files that openssl will not accept,
    # which only shows up as a TLS error at the broker.
    password = "s3cret"
    cert_file, key_file = trigger._write_client_cert(
        _self_signed_pfx(password), password
    )
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.load_cert_chain(cert_file, key_file)
        assert os.path.getsize(cert_file) > 0
        assert os.path.getsize(key_file) > 0
    finally:
        os.unlink(cert_file)
        os.unlink(key_file)


def test_a_bad_pfx_is_reported_not_crashed():
    try:
        trigger._write_client_cert("bm90IGEgcGZ4", "")
    except Exception as err:
        assert "certificate" in str(err)
    else:
        raise AssertionError("expected a MyCentsysError")


def test_paho_accepts_the_client_options_we_use():
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="mcr:+27831234567",
        protocol=mqtt.MQTTv5,
        clean_session=None,
    )
    assert client is not None


def test_publish_properties_carry_the_client_id():
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.properties import Properties

    properties = Properties(PacketTypes.PUBLISH)
    properties.UserProperty = ("ClientId", "mcr:+27831234567")
    properties.ResponseTopic = "1234/userRemoteTriggerResponse"
    assert properties.pack()
