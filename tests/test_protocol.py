"""Protocol tests. These need no Home Assistant and no network.

Run from the repository root:  python -m pytest tests -q
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# Loaded straight from the file: importing the package would pull in Home Assistant.
_SPEC = importlib.util.spec_from_file_location(
    "mycentsys_protocol",
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "mycentsys"
    / "protocol.py",
)
protocol = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(protocol)

PacketType = protocol.PacketType
build_activation_payload = protocol.build_activation_payload
build_auth_payload = protocol.build_auth_payload
build_packet = protocol.build_packet
derive_key = protocol.derive_key
mac_to_bytes = protocol.mac_to_bytes
parse_activation_response = protocol.parse_activation_response
parse_auth_response = protocol.parse_auth_response
parse_packet = protocol.parse_packet
phone_parts = protocol.phone_parts
xor = protocol.xor

KEY_BASE = bytes((56, 152, 63, 186, 77, 191, 171, 156))


def test_phone_parts_packs_bcd_the_way_the_app_does():
    # +27831234567: the last eight digits land in `upper`, nibble-reversed, and
    # the three before them in the top nibbles of `mid`.
    assert phone_parts("+27831234567") == (0x00000000, 0x87200000, 0x76543213)


def test_phone_parts_ignores_the_plus():
    assert phone_parts("27831234567") == phone_parts("+27831234567")


def test_empty_phone_is_all_zero():
    assert phone_parts("") == (0, 0, 0)


def test_mac_to_bytes_takes_four_octets():
    assert mac_to_bytes("AA:BB:CC:DD:EE:FF") == bytes((0xAA, 0xBB, 0xCC, 0xDD))


def test_derive_key_xors_only_the_mac_bytes():
    key = derive_key(bytes((0xAA, 0xBB, 0xCC, 0xDD)))
    assert key[:4] == bytes(
        KEY_BASE[i] ^ b for i, b in enumerate((0xAA, 0xBB, 0xCC, 0xDD))
    )
    assert key[4:] == KEY_BASE[4:]


def test_xor_is_its_own_inverse():
    key = derive_key(mac_to_bytes("01:02:03:04"))
    data = bytes(range(32))
    assert xor(xor(data, key), key) == data


def test_packet_header_and_round_trip():
    key = derive_key(mac_to_bytes("AA:BB:CC:DD"))
    payload = build_auth_payload("+27831234567")
    packet = build_packet(PacketType.AUTH_REQUEST, payload, key)

    assert packet[:4] == bytes((1, 1, PacketType.AUTH_REQUEST, 0))
    # A response is framed the same way, so parsing our own packet must give it back.
    packet_type, plain = parse_packet(packet, key)
    assert packet_type is PacketType.AUTH_REQUEST
    assert plain == payload


def test_auth_payload_is_three_little_endian_words():
    payload = build_auth_payload("+27831234567")
    assert payload.hex() == "00000000" + "00002087" + "13325476"


def test_parse_auth_response_reads_the_session_key():
    # AuthResponse=1, pad, pad, SessionKey=0xDEADBEEF
    payload = bytes((1, 0, 0, 0)) + (0xDEADBEEF).to_bytes(4, "little")
    assert parse_auth_response(payload) == (1, 0xDEADBEEF)


def test_activation_payload_layout():
    payload = build_activation_payload(3, 34, 0x11223344)
    assert payload == bytes((3, 0, 34, 0)) + (0x11223344).to_bytes(4, "little")


def test_parse_activation_response_reads_config_and_code():
    assert parse_activation_response(bytes((7, 1, 0, 0))) == (7, 1)
