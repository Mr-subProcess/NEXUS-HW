#!/usr/bin/env python3
"""Read-only environment preflight for host and embedded NEXUS workflows."""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

CHECKS = {
    "host": ["cmake", "c++", "python3"],
    "esp32s3": ["pio", "openocd", "xtensa-esp32s3-elf-gdb", "xtensa-esp32s3-elf-addr2line", "xtensa-esp32s3-elf-objdump"],
    "rp2040": ["pio", "openocd", "arm-none-eabi-gdb", "arm-none-eabi-addr2line", "arm-none-eabi-objdump"],
}


def probe(name: str) -> dict:
    path = shutil.which(name)
    item = {"name": name, "available": path is not None, "path": path}
    if path:
        try:
            run = subprocess.run([path, "--version"], capture_output=True, text=True,
                                 timeout=3, check=False)
            first = (run.stdout or run.stderr).splitlines()
            if first:
                item["version"] = first[0][:180]
        except (OSError, subprocess.TimeoutExpired):
            item["version"] = "version query unavailable"
    return item


def main() -> int:
    ap = argparse.ArgumentParser(description="Check NEXUS-HW build/debug prerequisites; no hardware is contacted")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--strict-hardware", action="store_true", help="return failure when embedded toolchains are missing")
    args = ap.parse_args()
    report = {
        "tool": "NEXUS-HW doctor",
        "version": (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "checks": {group: [probe(name) for name in names] for group, names in CHECKS.items()},
        "optional": [probe("gdb-multiarch"), probe("llvm-readelf"), probe("readelf")],
        "hardware_contacted": False,
    }
    host_ok = all(item["available"] for item in report["checks"]["host"])
    hardware_ok = all(item["available"] for group in ("esp32s3", "rp2040")
                       for item in report["checks"][group])
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"NEXUS-HW doctor {report['version']} | {report['platform']}")
        for group, items in report["checks"].items():
            print(f"\n[{group}]")
            for item in items:
                state = "FOUND" if item["available"] else "MISSING"
                print(f"{state:7} {item['name']:<32} {item.get('version', item.get('path') or '')}")
        print("\nNo hardware was contacted. Missing cross-toolchains do not block host simulation.")
    return 0 if host_ok and (hardware_ok or not args.strict_hardware) else 1


if __name__ == "__main__":
    raise SystemExit(main())
