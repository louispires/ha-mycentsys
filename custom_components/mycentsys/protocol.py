"""Centurion activation packet protocol (XOR-secured, little-endian, Pack=1).

Port of the app's ActivationService / AppPhoneNumberStorageFw logic.
"""

from __future__ import annotations

import struct
from enum import IntEnum

# ActivationService.BLE_REMOTE_ENCRYPTION_KEY_BASE
_KEY_BASE = bytes((56, 152, 63, 186, 77, 191, 171, 156))


class PacketType(IntEnum):
    NACK = 0
    AUTH_REQUEST = 1
    AUTH_RESPONSE = 2
    ACTIVATION_REQUEST = 3
    ACTIVATION_RESPONSE = 4
    SET_TIME_REQUEST = 5
    SET_TIME_RESPONSE = 6


class ProtocolError(Exception):
    """A response could not be parsed or was not the packet we asked for."""


def mac_to_bytes(mac: str) -> bytes:
    """ "AA:BB:CC:DD:EE:FF" -> the first four octets, as the app does."""
    return bytes(int(part, 16) for part in mac.split(":")[:4])


def derive_key(mac: bytes) -> bytes:
    key = bytearray(_KEY_BASE)
    for i in range(min(len(mac), len(key))):
        key[i] = _KEY_BASE[i] ^ mac[i]
    return bytes(key)


def xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def build_packet(packet_type: PacketType, payload: bytes, key: bytes) -> bytes:
    """[algoVer=1, keyVer=1, packetId, 0] + XOR(payload)."""
    return bytes((1, 1, int(packet_type), 0)) + xor(payload, key)


def parse_packet(response: bytes, key: bytes) -> tuple[PacketType, bytes]:
    if len(response) < 4:
        raise ProtocolError(f"response too short ({len(response)} bytes)")
    return PacketType(response[2]), xor(response[4:], key)


def phone_parts(phone: str) -> tuple[int, int, int]:
    """Pack the digits into three 32-bit BCD words, as AppPhoneNumberStorageFw does."""
    digits = phone.replace("+", "")
    lower = mid = upper = 0
    if not digits:
        return (0, 0, 0)
    length = len(digits)
    num = length - 1
    while 16 <= num < 24:
        lower |= (ord(digits[length - num - 1]) - 48) << ((23 - num) * 4)
        num -= 1
    while 8 <= num < 16:
        mid |= (ord(digits[length - num - 1]) - 48) << ((15 - num) * 4)
        num -= 1
    while 0 <= num < 8:
        upper |= (ord(digits[length - num - 1]) - 48) << ((7 - num) * 4)
        num -= 1
    mask = 0xFFFFFFFF
    return (lower & mask, mid & mask, upper & mask)


def build_auth_payload(phone: str) -> bytes:
    """AuthenticationRequestStruct { uint Lower, Mid, Upper }."""
    return struct.pack("<III", *phone_parts(phone))


def parse_auth_response(payload: bytes) -> tuple[int, int]:
    """AuthenticationResponseStruct { byte AuthResponse, Pad1, short Pad2, uint SessionKey }."""
    if len(payload) < 8:
        raise ProtocolError("auth response too short")
    auth_response, _pad1, _pad2, session_key = struct.unpack_from("<BBHI", payload, 0)
    return auth_response, session_key


def build_activation_payload(
    config_version: int, activation_id: int, session_key: int
) -> bytes:
    """ActivationRequestStruct { byte ConfigVersion, byte Padding, short ActivationId, uint SessionKey }."""
    return struct.pack("<BBhI", config_version & 0xFF, 0, activation_id, session_key)


def parse_activation_response(payload: bytes) -> tuple[int, int]:
    """ActivationResponseStruct { byte ConfigVersion, byte ActivationResponse, short Padding }."""
    if len(payload) < 2:
        raise ProtocolError("activation response too short")
    return payload[0], payload[1]
