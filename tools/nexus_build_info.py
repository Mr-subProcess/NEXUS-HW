#!/usr/bin/env python3
"""Print ELF identity and architecture metadata for a target firmware build."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract build identity from an embedded target ELF")
    ap.add_argument("--elf", required=True, type=Path)
    ap.add_argument("--readelf", default=None, help="Architecture-matched readelf executable")
    ap.add_argument("--output", type=Path, default=None, help="Optional JSON metadata output")
    args = ap.parse_args()
    try:
        if not args.elf.is_file():
            raise FileNotFoundError(args.elf)
        candidates = [args.readelf] if args.readelf else []
        candidates += ["xtensa-esp32s3-elf-readelf", "arm-none-eabi-readelf", "llvm-readelf", "readelf"]
        tool = next((shutil.which(item) for item in candidates if item and shutil.which(item)), None)
        if not tool:
            raise RuntimeError("readelf not found; install the matching target toolchain")
        header = subprocess.run([tool, "-h", str(args.elf)], capture_output=True, text=True, check=False)
        notes = subprocess.run([tool, "-n", str(args.elf)], capture_output=True, text=True, check=False)
        if header.returncode != 0:
            raise RuntimeError(header.stderr.strip() or "readelf could not parse the ELF")
        build = re.search(r"Build ID:\s*([0-9a-fA-F]+)", notes.stdout + notes.stderr)
        arch = re.search(r"Machine:\s*(.+)", header.stdout)
        elf_class = re.search(r"Class:\s*(.+)", header.stdout)
        digest = hashlib.sha256(args.elf.read_bytes()).hexdigest()
        info = {"elf": str(args.elf), "build_id": build.group(1).lower() if build else None,
                "machine": arch.group(1).strip() if arch else "unknown",
                "class": elf_class.group(1).strip() if elf_class else "unknown",
                "sha256": digest}
        print(json.dumps(info, indent=2))
        if info["build_id"]:
            print(f"TARGET_LOG_PREFIX: BUILD_ID={info['build_id']}")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"nexus_build_info: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
