#!/usr/bin/env python3
"""Validate a read-only protocol manifest and emit a C++ SeedSet/Profile header."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ALLOWED_CHECKSUMS = {
    "none": "None", "xor8": "Xor8", "sum8": "Sum8",
    "crc8_maxim": "Crc8Maxim", "crc16_ccitt_false": "Crc16CcittFalse",
    "crc16_modbus": "Crc16Modbus", "crc32_ieee": "Crc32Ieee",
}
HEX_RE = re.compile(r"^(?:[0-9a-fA-F]{2}){1,128}$")


def parse_hex(value: str, label: str) -> bytes:
    if not isinstance(value, str) or not HEX_RE.fullmatch(value):
        raise ValueError(f"{label}: expected 1..128 bytes as even-length hexadecimal")
    return bytes.fromhex(value)


def validate_manifest(data: dict) -> list[dict]:
    if data.get("schema") != "nexus.protocol.v1":
        raise ValueError("schema must be nexus.protocol.v1")
    link = data.get("link")
    if link not in {"uart", "spi", "i2c"}:
        raise ValueError("link must be uart, spi or i2c")
    profile = data.get("profile", {})
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    for key in ("ack", "nack", "device_error"):
        if key in profile and profile[key] is not None:
            if len(parse_hex(profile[key], f"profile.{key}")) > 8:
                raise ValueError(f"profile.{key} is limited to 8 bytes")
    commands = data.get("commands")
    if not isinstance(commands, list) or not commands:
        raise ValueError("commands must be a non-empty array")
    if len(commands) > 16:
        raise ValueError("maximum 16 seed commands per embedded manifest")
    tags: set[int] = set()
    validated = []
    for index, command in enumerate(commands):
        label = f"commands[{index}]"
        if command.get("classification") != "documented_read_only":
            raise ValueError(f"{label}: only documented_read_only commands may enter a physical corpus")
        raw_tag = command.get("tag")
        try:
            tag = int(raw_tag, 0) if isinstance(raw_tag, str) else int(raw_tag)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{label}.tag must be an integer or 0x-prefixed string") from exc
        if not 0 <= tag <= 0xFFFF or tag in tags:
            raise ValueError(f"{label}.tag must be unique and in range 0..65535")
        tags.add(tag)
        frame = parse_hex(command.get("frame_hex"), f"{label}.frame_hex")
        prefix = int(command.get("immutable_prefix", 1))
        minimum = int(command.get("minimum_mutable_bytes", 1))
        if not 0 <= prefix < len(frame):
            raise ValueError(f"{label}.immutable_prefix must leave at least one payload byte")
        if not 1 <= minimum <= len(frame) - prefix:
            raise ValueError(f"{label}.minimum_mutable_bytes must fit the mutable payload")
        checksum = command.get("checksum")
        if checksum is not None:
            if not isinstance(checksum, dict):
                raise ValueError(f"{label}.checksum must be an object")
            algorithm = checksum.get("algorithm", "none")
            if algorithm not in ALLOWED_CHECKSUMS or algorithm == "none":
                raise ValueError(f"{label}.checksum.algorithm is unsupported")
            # This generator emits common fixed CRC definitions. Custom CRCs
            # are deliberately kept in the C++ API until their full parameters
            # can be described and validated here.
            widths = {"Xor8": 1, "Sum8": 1, "Crc8Maxim": 1,
                      "Crc16CcittFalse": 2, "Crc16Modbus": 2, "Crc32Ieee": 4}
            checksum = {
                "algorithm": ALLOWED_CHECKSUMS[algorithm],
                "data_offset": int(checksum.get("data_offset", 0)),
                "data_length": int(checksum.get("data_length", 0)),
                "checksum_offset": int(checksum.get("checksum_offset", 0)),
                "big_endian": bool(checksum.get("big_endian", True)),
            }
            width = widths[checksum["algorithm"]]
            data_end = checksum["data_offset"] + checksum["data_length"]
            checksum_end = checksum["checksum_offset"] + width
            if not (0 <= checksum["data_offset"] <= 255 and 1 <= checksum["data_length"] <= 128):
                raise ValueError(f"{label}.checksum data range is invalid")
            if data_end > len(frame) or not (0 <= checksum["checksum_offset"] <= 255) or checksum_end > len(frame):
                raise ValueError(f"{label}.checksum field lies outside the frame")
            if checksum["checksum_offset"] < prefix:
                raise ValueError(f"{label}.checksum field overlaps immutable command prefix")
            if not (data_end <= checksum["checksum_offset"] or checksum_end <= checksum["data_offset"]):
                raise ValueError(f"{label}.checksum field overlaps checksum input range")
        validated.append({"tag": tag, "name": str(command.get("name", f"command_{tag:04x}")),
                          "frame": frame, "prefix": prefix, "minimum": minimum,
                          "checksum": checksum})
    return validated


def generate(data: dict, commands: list[dict]) -> str:
    profile = data.get("profile", {})
    def pattern(name: str) -> bytes:
        raw = profile.get(name)
        return parse_hex(raw, f"profile.{name}") if raw else b""
    lines = [
        "#pragma once", '#include "nexus/types.hpp"', "", "// Generated by NEXUS-HW protocol manifest compiler.",
        "// Review against the target manufacturer's protocol documentation before physical use.",
        "namespace nexus::generated {", "inline SeedSet make_protocol_corpus() noexcept {", "    SeedSet set{};",
        f"    set.count = {len(commands)};"
    ]
    for i, cmd in enumerate(commands):
        frame = ", ".join(f"0x{x:02X}" for x in cmd["frame"])
        lines += [
            f"    set.entries[{i}].frame.size = {len(cmd['frame'])};",
            f"    set.entries[{i}].frame.bytes = {{{frame}}};",
            f"    set.entries[{i}].immutable_prefix = {cmd['prefix']};",
            f"    set.entries[{i}].minimum_mutable_bytes = {cmd['minimum']};",
            f"    set.entries[{i}].command_tag = 0x{cmd['tag']:04X};",
        ]
        checksum = cmd["checksum"]
        if checksum:
            lines += [
                f"    set.entries[{i}].checksum.enabled = true;",
                f"    set.entries[{i}].checksum.algorithm = ChecksumAlgorithm::{checksum['algorithm']};",
                f"    set.entries[{i}].checksum.data_offset = {checksum['data_offset']};",
                f"    set.entries[{i}].checksum.data_length = {checksum['data_length']};",
                f"    set.entries[{i}].checksum.checksum_offset = {checksum['checksum_offset']};",
                f"    set.entries[{i}].checksum.big_endian = {'true' if checksum['big_endian'] else 'false'};",
            ]
    lines += ["    return set;", "}", "inline ProtocolProfile make_protocol_profile() noexcept {", "    ProtocolProfile profile{};"]
    for name in ("ack", "nack", "device_error"):
        raw = pattern(name)
        if raw:
            lines.append(f"    profile.{name}.size = {len(raw)};")
            lines.append(f"    profile.{name}.bytes = {{{', '.join(f'0x{x:02X}' for x in raw)}}};")
    lines += ["    return profile;", "}", "} // namespace nexus::generated", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Compile a documented read-only protocol manifest to a NEXUS C++ corpus")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", type=Path, help="generated C++ header; omit for validation only")
    args = ap.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        commands = validate_manifest(data)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(generate(data, commands), encoding="utf-8")
            print(f"NEXUS_PROTOCOL_VALID commands={len(commands)} link={data['link']} output={args.output}")
        else:
            print(f"NEXUS_PROTOCOL_VALID commands={len(commands)} link={data['link']}")
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"nexus_protocol: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
