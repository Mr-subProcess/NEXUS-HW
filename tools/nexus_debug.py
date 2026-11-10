#!/usr/bin/env python3
"""NEXUS-HW GDB/OpenOCD capture helper.

Connects to an already-running GDB server or analyzes a local core file. It
never flashes, erases, resets, resumes, or writes target memory. Live register
capture may halt the target only when --halt is explicitly supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import re
import shlex
import subprocess
import sys
from pathlib import Path

PROFILES = {
    "esp32s3": {
        "gdb": "xtensa-esp32s3-elf-gdb",
        "arch": "Xtensa LX7 / ESP32-S3",
        "interface": "JTAG (ESP32-S3 does not support SWD)",
        "openocd": ["openocd", "-f", "board/esp32s3-builtin.cfg"],
        "readelf": "xtensa-esp32s3-elf-readelf",
        "addr2line": "xtensa-esp32s3-elf-addr2line",
        "objdump": "xtensa-esp32s3-elf-objdump",
    },
    "rp2040": {
        "gdb": "arm-none-eabi-gdb",
        "arch": "Arm Cortex-M0+ / RP2040",
        "interface": "SWD",
        "openocd": ["openocd", "-f", "interface/cmsis-dap.cfg", "-f", "target/rp2040.cfg"],
        "readelf": "arm-none-eabi-readelf",
        "addr2line": "arm-none-eabi-addr2line",
        "objdump": "arm-none-eabi-objdump",
    },
}


def _gdb_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def validate_remote(remote: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.:\-\[\]]+:[0-9]{1,5}", remote):
        raise ValueError("remote must be a host:port endpoint, e.g. localhost:3333")
    host, port_text = remote.rsplit(":", 1)
    port = int(port_text)
    if not host or not (1 <= port <= 65535):
        raise ValueError("invalid GDB remote host or port")
    return remote


def build_gdb_script(profile: str, remote: str | None, core: Path | None,
                     halt: bool, stack_words: int, disasm_instructions: int) -> str:
    if profile not in PROFILES:
        raise ValueError(f"unsupported profile: {profile}")
    if (remote is None) == (core is None):
        raise ValueError("select exactly one of --remote or --core")
    if remote:
        validate_remote(remote)
    if not (8 <= stack_words <= 256):
        raise ValueError("stack words must be in range 8..256")
    if not (4 <= disasm_instructions <= 128):
        raise ValueError("disassembly instructions must be in range 4..128")
    if halt and core is not None:
        raise ValueError("--halt applies only to a live remote target")

    lines = [
        "set pagination off",
        "set confirm off",
        "set print pretty on",
        "set print elements 0",
        "set backtrace past-main on",
        "set backtrace limit 128",
    ]
    if core is not None:
        lines.append(f"core-file {_gdb_quote(str(core.resolve()))}")
        lines.append('printf "\\nNEXUS_CAPTURE_MODE=offline-core\\n"')
    else:
        lines.append(f"target extended-remote {remote}")
        lines.append('printf "\\nNEXUS_CAPTURE_MODE=live-remote\\n"')
        if halt:
            lines.append("monitor halt")
            lines.append('printf "NEXUS_TARGET_ACTION=halt-requested; no reset/flash/write requested\\n"')
        else:
            lines.append('printf "NEXUS_TARGET_ACTION=no-explicit-monitor-halt\\n"')
    lines += [
        'printf "\\n========== NEXUS GDB CAPTURE BEGIN ==========\\n"',
        "info registers",
        "info all-registers",
        "info threads",
        "thread apply all bt full",
        "bt full",
        "frame 0",
        "info frame",
        "info args",
        "info locals",
        "info symbol $pc",
        f"x/{disasm_instructions}i $pc",
        f"x/{stack_words}wx $sp",
        "info files",
        "maintenance info sections ALLOBJ",
        'printf "========== NEXUS GDB CAPTURE END ==========\\n"',
    ]
    if remote:
        lines.append("detach")
    lines.append("quit")
    return "\n".join(lines) + "\n"


def run_capture(gdb: str, elf: Path, script: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    command = [gdb, "--batch", "--nx", "--quiet", "--command", str(script), str(elf)]
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def extract_build_metadata(profile: str, elf: Path) -> tuple[str | None, str]:
    digest = hashlib.sha256(elf.read_bytes()).hexdigest()
    candidates = [PROFILES[profile].get("readelf"), "llvm-readelf", "readelf"]
    tool = next((shutil.which(item) for item in candidates if item and shutil.which(item)), None)
    if not tool:
        return None, digest
    completed = subprocess.run([tool, "-n", str(elf)], text=True, capture_output=True, check=False)
    match = re.search(r"Build ID:\s*([0-9a-fA-F]+)", (completed.stdout or "") + (completed.stderr or ""))
    return (match.group(1).lower() if match else None), digest


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture GDB/OpenOCD debugger context for NEXUS-HW triage")
    ap.add_argument("--profile", choices=sorted(PROFILES), required=True)
    ap.add_argument("--elf", required=True, type=Path, help="exact ELF matching the target firmware")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--remote", help="already-running GDB server host:port (e.g. localhost:3333)")
    mode.add_argument("--core", type=Path, help="offline core dump / core file")
    ap.add_argument("--gdb", help="architecture-matched GDB executable; defaults to profile toolchain")
    ap.add_argument("--halt", action="store_true", help="request monitor halt on live target before capture")
    ap.add_argument("--stack-words", type=int, default=64)
    ap.add_argument("--disasm-instructions", type=int, default=32)
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--script", type=Path, default=Path("nexus-capture.gdb"), help="generated GDB command file")
    ap.add_argument("--capture", type=Path, default=Path("nexus-gdb-capture.log"), help="raw GDB transcript")
    ap.add_argument("--report", type=Path, help="optional HTML report path; invokes nexus_triage.py")
    ap.add_argument("--map", type=Path)
    ap.add_argument("--coverage", type=Path, help="optional JSON coverage report to include in HTML report")
    ap.add_argument("--addr2line", help="override architecture-matched addr2line executable")
    ap.add_argument("--objdump", help="override architecture-matched objdump executable")
    ap.add_argument("--source-root", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true", help="write GDB script and print command without connecting")
    args = ap.parse_args()

    try:
        if not args.elf.is_file():
            raise ValueError(f"ELF not found: {args.elf}")
        if args.core and not args.core.is_file():
            raise ValueError(f"core file not found: {args.core}")
        if args.timeout <= 0:
            raise ValueError("timeout must be positive")
        if args.remote:
            validate_remote(args.remote)
            if not args.halt and not args.dry_run:
                raise ValueError("live GDB capture requires explicit --halt; attaching may stop the target")
        gdb = args.gdb or PROFILES[args.profile]["gdb"]
        script_text = build_gdb_script(args.profile, args.remote, args.core, args.halt,
                                       args.stack_words, args.disasm_instructions)
        args.script.parent.mkdir(parents=True, exist_ok=True)
        args.script.write_text(script_text, encoding="utf-8")
        command = [gdb, "--batch", "--nx", "--quiet", "--command", str(args.script), str(args.elf)]
        if args.dry_run:
            print(f"PROFILE={args.profile} ARCH={PROFILES[args.profile]['arch']}")
            print(f"DEBUG_INTERFACE={PROFILES[args.profile]['interface']}")
            print("OPENOCD_SERVER_COMMAND=" + shlex.join(PROFILES[args.profile]["openocd"]))
            print("GDB_COMMAND=" + shlex.join(command))
            print(f"GDB_SCRIPT={args.script}")
            return 0
        completed = run_capture(gdb, args.elf, args.script, args.timeout)
        build_id, elf_sha256 = extract_build_metadata(args.profile, args.elf)
        build_line = f"NEXUS_ELF_BUILD_ID={build_id}\n" if build_id else "NEXUS_ELF_BUILD_ID_UNAVAILABLE=1\n"
        header = (
            f"NEXUS_DEBUG_CAPTURE,profile={args.profile},arch={PROFILES[args.profile]['arch']},"
            f"mode={'core' if args.core else 'remote'},remote={args.remote or ''},halt={int(args.halt)}\n"
            f"NEXUS_ELF={args.elf.resolve()}\n{build_line}NEXUS_ELF_SHA256={elf_sha256}\n"
        )
        transcript = header + (completed.stdout or "") + "\n--- GDB STDERR ---\n" + (completed.stderr or "")
        args.capture.parent.mkdir(parents=True, exist_ok=True)
        args.capture.write_text(transcript, encoding="utf-8", errors="replace")
        print(f"GDB_EXIT={completed.returncode}")
        print(f"CAPTURE={args.capture}")
        if args.report:
            triage = Path(__file__).with_name("nexus_triage.py")
            triage_cmd = [sys.executable, str(triage), "--input", str(args.capture),
                          "--elf", str(args.elf), "--format", "html", "--output", str(args.report),
                          "--addr2line", args.addr2line or PROFILES[args.profile]["addr2line"],
                          "--objdump", args.objdump or PROFILES[args.profile]["objdump"]]
            if args.coverage:
                triage_cmd += ["--coverage", str(args.coverage)]
            if args.map:
                triage_cmd += ["--map", str(args.map)]
            for root in args.source_root:
                triage_cmd += ["--source-root", root]
            triage_result = subprocess.run(triage_cmd, text=True, capture_output=True, check=False)
            if triage_result.returncode != 0:
                sys.stderr.write(triage_result.stderr)
                return triage_result.returncode
            print(f"HTML_REPORT={args.report}")
        if completed.returncode != 0:
            sys.stderr.write(completed.stderr or "GDB returned a non-zero exit status.\n")
            return 3
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"nexus_debug: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
