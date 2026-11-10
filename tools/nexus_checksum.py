#!/usr/bin/env python3
"""Protocol checksum helpers shared by corpus/minimization tooling."""
from __future__ import annotations

from typing import Any

WIDTHS = {
    "xor8": 1, "sum8": 1, "crc8_maxim": 1,
    "crc16_ccitt_false": 2, "crc16_modbus": 2, "crc32_ieee": 4,
    "crc8_custom": 1, "crc16_custom": 2, "crc32_custom": 4,
}


def reflect_bits(value: int, width: int) -> int:
    result = 0
    for _ in range(width):
        result = (result << 1) | (value & 1)
        value >>= 1
    return result


def compute(data: bytes, spec: dict[str, Any]) -> int:
    algorithm = str(spec.get("algorithm", "")).lower()
    if algorithm not in WIDTHS:
        raise ValueError(f"unsupported checksum algorithm: {algorithm}")
    if algorithm == "xor8":
        value = 0
        for byte in data:
            value ^= byte
        return value
    if algorithm == "sum8":
        return sum(data) & 0xFF
    if algorithm == "crc8_maxim":
        crc = 0
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = ((crc >> 1) ^ 0x8C) if (crc & 1) else (crc >> 1)
        return crc & 0xFF
    if algorithm == "crc16_ccitt_false":
        crc = 0xFFFF
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                crc = (((crc << 1) ^ 0x1021) & 0xFFFF) if (crc & 0x8000) else ((crc << 1) & 0xFFFF)
        return crc
    if algorithm == "crc16_modbus":
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = ((crc >> 1) ^ 0xA001) if (crc & 1) else (crc >> 1)
        return crc & 0xFFFF
    if algorithm == "crc32_ieee":
        crc = 0xFFFFFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = ((crc >> 1) ^ 0xEDB88320) if (crc & 1) else (crc >> 1)
        return crc ^ 0xFFFFFFFF

    width = WIDTHS[algorithm] * 8
    mask = (1 << width) - 1
    top = 1 << (width - 1)
    polynomial = int(spec.get("polynomial", 0))
    initial = int(spec.get("initial", 0))
    xor_out = int(spec.get("xor_out", 0))
    reflect_input = bool(spec.get("reflect_input", False))
    reflect_output = bool(spec.get("reflect_output", False))
    if polynomial <= 0 or polynomial > mask:
        raise ValueError("custom CRC polynomial must fit the selected width and be non-zero")
    crc = initial & mask
    reflected_poly = reflect_bits(polynomial, width) if reflect_input else polynomial
    for byte in data:
        if reflect_input:
            crc ^= byte
            for _ in range(8):
                crc = ((crc >> 1) ^ reflected_poly) & mask if (crc & 1) else (crc >> 1)
        else:
            crc ^= byte << (width - 8)
            for _ in range(8):
                crc = (((crc << 1) ^ polynomial) & mask) if (crc & top) else ((crc << 1) & mask)
    if reflect_input != reflect_output:
        crc = reflect_bits(crc, width)
    return (crc ^ xor_out) & mask


def apply_checksum(frame: bytes, spec: dict[str, Any]) -> bytes:
    algorithm = str(spec.get("algorithm", "")).lower()
    if algorithm not in WIDTHS:
        raise ValueError(f"unsupported checksum algorithm: {algorithm}")
    data_offset = int(spec.get("data_offset", 0))
    data_length = int(spec.get("data_length", -1))
    checksum_offset = int(spec.get("checksum_offset", -1))
    byte_order = str(spec.get("byte_order", "big")).lower()
    width = WIDTHS[algorithm]
    if byte_order not in ("big", "little"):
        raise ValueError("byte_order must be 'big' or 'little'")
    if data_offset < 0 or data_length <= 0 or checksum_offset < 0:
        raise ValueError("data_offset/checksum_offset must be non-negative and data_length positive")
    data_end = data_offset + data_length
    checksum_end = checksum_offset + width
    if data_end > len(frame) or checksum_end > len(frame):
        raise ValueError("checksum data or output field lies outside the frame")
    if not (data_end <= checksum_offset or checksum_end <= data_offset):
        raise ValueError("checksum field must not overlap checksum input bytes")
    value = compute(frame[data_offset:data_end], spec)
    output = bytearray(frame)
    output[checksum_offset:checksum_end] = value.to_bytes(width, byte_order)
    return bytes(output)
