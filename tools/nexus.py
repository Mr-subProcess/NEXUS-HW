#!/usr/bin/env python3
"""Unified NEXUS-HW command launcher (no shell interpolation)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
COMMANDS = {
    "triage": [sys.executable, str(TOOLS / "nexus_triage.py")],
    "debug": [sys.executable, str(TOOLS / "nexus_debug.py")],
    "minimize": [sys.executable, str(TOOLS / "nexus_minimize.py")],
    "coverage": [sys.executable, str(TOOLS / "nexus_cov.py")],
    "build-info": [sys.executable, str(TOOLS / "nexus_build_info.py")],
    "session": [sys.executable, str(TOOLS / "nexus_session.py")],
    "bundle": [sys.executable, str(TOOLS / "nexus_bundle.py")],
    "doctor": [sys.executable, str(TOOLS / "nexus_doctor.py")],
    "dashboard": [sys.executable, str(TOOLS / "nexus_dashboard.py")],
    "protocol": [sys.executable, str(TOOLS / "nexus_protocol.py")],
}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="nexus",
        description="NEXUS-HW unified command launcher",
        epilog=(
            "commands: sim [args...] | campaign [args...] | triage [args...] | debug [args...] | "
            "minimize [args...] | coverage [args...] | build-info [args...] | "
            "session [args...] | bundle [args...] | dashboard [args...] | protocol [args...] | doctor [args...] | test"
        ),
    )
    parser.add_argument("command", nargs="?", choices=[*COMMANDS, "sim", "campaign", "test", "version"])
    parser.add_argument("args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args()
    if not parsed.command:
        parser.print_help()
        return 0
    if parsed.command == "version":
        print((ROOT / "VERSION").read_text(encoding="utf-8").strip())
        return 0
    if parsed.command == "test":
        command = [str(ROOT / "scripts" / "test_matrix.sh")]
    elif parsed.command in ("sim", "campaign"):
        candidates = [ROOT / "build-release" / "nexus_sim", ROOT / "build" / "nexus_sim"]
        binary = next((item for item in candidates if item.is_file()), None)
        if binary is None:
            print("nexus: simulator not found; build first with ./scripts/build_native.sh", file=sys.stderr)
            return 2
        command = [str(binary)] + (["--campaign"] if parsed.command == "campaign" else [])
    else:
        command = COMMANDS[parsed.command]
    try:
        return subprocess.run(command + parsed.args, cwd=ROOT, check=False).returncode
    except OSError as exc:
        print(f"nexus: cannot execute {command[0]}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
