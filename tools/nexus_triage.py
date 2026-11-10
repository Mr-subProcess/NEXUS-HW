#!/usr/bin/env python3
"""NEXUS-HW offline crash-log triage and optional ELF symbolication.

This tool only parses an operator-supplied diagnostic log. It does not connect to,
reset, or execute code on a target. Exact source locations require a matching ELF.
"""
from __future__ import annotations

import argparse
import json
import html
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Triage:
    platform: str = "unknown"
    fault_class: str = "unclassified"
    confidence: str = "low"
    evidence: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    registers: dict[str, str] = field(default_factory=dict)
    addresses: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    direct_locations: list[str] = field(default_factory=list)
    nexus_event: dict[str, str] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    elf_metadata: list[str] = field(default_factory=list)
    disassembly: list[str] = field(default_factory=list)
    map_evidence: list[str] = field(default_factory=list)
    coverage_summary: dict = field(default_factory=dict)
    stack_dump: list[str] = field(default_factory=list)
    source_context: list[str] = field(default_factory=list)
    execution_context: list[str] = field(default_factory=list)
    build_id: str = ""
    elf_build_id: str = ""
    build_id_match: Optional[bool] = None
    debugger_metadata: list[str] = field(default_factory=list)
    debugger_frames: list[str] = field(default_factory=list)


def _hex_register(text: str, name: str) -> Optional[str]:
    # Accept panic-dump forms (PC: 0x...), compact custom forms (R0=0x...),
    # and GDB `info registers` rows (pc 0x... flags...).
    m = re.search(rf"\b{name}\s*[:=]\s*(0x[0-9a-fA-F]+)", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(rf"(?im)^\s*{name}\s+(0x[0-9a-fA-F]+)(?:\s|$)", text)
    return m.group(1) if m else None


def _decode_cfsr(value: int) -> list[str]:
    bits = [
        (0, "MemManage: instruction access violation (IACCVIOL)"),
        (1, "MemManage: data access violation (DACCVIOL)"),
        (3, "MemManage: fault while unstacking exception frame (MUNSTKERR)"),
        (4, "MemManage: fault while stacking exception frame (MSTKERR)"),
        (7, "MMFAR contains a valid fault address (MMARVALID)"),
        (8, "BusFault: instruction bus error (IBUSERR)"),
        (9, "BusFault: precise data bus error (PRECISERR)"),
        (10, "BusFault: imprecise data bus error (IMPRECISERR)"),
        (11, "BusFault: fault while unstacking (UNSTKERR)"),
        (12, "BusFault: fault while stacking (STKERR)"),
        (15, "BFAR contains a valid fault address (BFARVALID)"),
        (16, "UsageFault: undefined instruction (UNDEFINSTR)"),
        (17, "UsageFault: invalid state (INVSTATE)"),
        (18, "UsageFault: invalid exception return (INVPC)"),
        (19, "UsageFault: coprocessor disabled (NOCP)"),
        (24, "UsageFault: unaligned access (UNALIGNED)"),
        (25, "UsageFault: divide by zero (DIVBYZERO)"),
    ]
    return [label for bit, label in bits if value & (1 << bit)]


def parse_log(text: str) -> Triage:
    result = Triage()
    lower = text.lower()

    # Keep the device-reported identity separate from the ELF supplied to the
    # analyzer. An ELF's own metadata must never be mistaken for proof that it
    # matches the image currently running on the target.
    target_build_id = re.search(
        r"(?im)^\s*(?:(?:TARGET_LOG_PREFIX|TARGET_LOG)\s*:\s*)?"
        r"(?:TARGET[_ -]?BUILD[_ -]?ID|BUILD[_ -]?ID)\s*[:=]\s*([0-9a-fA-F]{8,64})\s*$",
        text,
    )
    if target_build_id:
        result.build_id = target_build_id.group(1).lower()
        result.evidence.append(f"Target-reported firmware build ID: {result.build_id}")
    supplied_elf_build_id = re.search(
        r"(?im)^\s*(?:NEXUS[_ -]ELF[_ -]?BUILD[_ -]?ID|ELF[_ -]?BUILD[_ -]?ID)\s*[:=]\s*([0-9a-fA-F]{8,64})\s*$",
        text,
    )
    if supplied_elf_build_id:
        result.debugger_metadata.append("supplied_elf_build_id=" + supplied_elf_build_id.group(1).lower())

    debug_meta = re.search(r"NEXUS_DEBUG_CAPTURE,([^\r\n]+)", text, re.IGNORECASE)
    if debug_meta:
        result.debugger_metadata.extend(part.strip() for part in debug_meta.group(1).split(","))
        result.evidence.append("GDB/OpenOCD debugger transcript metadata is present")
        profile = re.search(r"(?:^|,)profile=([^,]+)", debug_meta.group(1))
        if profile and profile.group(1).lower() == "rp2040":
            result.platform = "RP2040 / ARM Cortex-M0+ debugger capture"
        elif profile and profile.group(1).lower() == "esp32s3":
            result.platform = "ESP32-S3 / Xtensa LX7 debugger capture"
        else:
            architecture = re.search(r"(?:^|,)arch=([^,]+)", debug_meta.group(1))
            result.platform = "Generic GDB capture" + (f" ({architecture.group(1)})" if architecture else "")
    capture_mode = re.search(r"NEXUS_CAPTURE_MODE=([^\s]+)", text)
    if capture_mode:
        result.debugger_metadata.append("capture_mode=" + capture_mode.group(1))
    target_action = re.search(r"NEXUS_TARGET_ACTION=([^\r\n]+)", text)
    if target_action:
        result.debugger_metadata.append("target_action=" + target_action.group(1))

    for line in text.splitlines():
        if re.search(r"\b(?:core\s*[0-9]+|task(?: name)?\s*[:=]|thread(?: id)?\s*[:=]|cpu\s*[0-9]+)\b", line, re.IGNORECASE):
            result.execution_context.append(line.strip())
    for line in text.splitlines():
        if re.match(r"^\s*\*?\s*\d+\s+Thread\s+", line, re.IGNORECASE):
            result.execution_context.append(line.strip())
    result.execution_context = list(dict.fromkeys(result.execution_context))[:32]

    # ESP reset cause can distinguish a reboot/brownout from a live bus timeout.
    reset = re.search(r"rst\s*:\s*(0x[0-9a-fA-F]+)\s*\(([^)]+)\)", text, re.IGNORECASE)
    if reset:
        result.registers["RESET_CODE"] = reset.group(1)
        result.registers["RESET_REASON"] = reset.group(2).strip()
        result.evidence.append(f"ESP reset reason: {reset.group(2).strip()} ({reset.group(1)})")

    # NEXUS event correlation: case ID and trigger bytes are preserved by firmware.
    nexus = re.search(r"CRASH_SUSPECTED,([^\r\n]+)", text, re.IGNORECASE)
    if nexus:
        for part in nexus.group(1).split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                result.nexus_event[key.strip()] = value.strip()
        if result.nexus_event:
            result.evidence.append("Correlated NEXUS crash-suspected event: " +
                                   ", ".join(f"{k}={v}" for k, v in result.nexus_event.items()))

    # Compiler sanitizer reports can pinpoint the invalid access more precisely
    # than an external protocol observer.
    asan = re.search(r"AddressSanitizer:\s*([a-zA-Z0-9_-]+)", text, re.IGNORECASE)
    if asan:
        sanitizer_kind = asan.group(1).lower()
        result.fault_class = "memory_safety_violation:" + sanitizer_kind
        result.platform = "AddressSanitizer / instrumented host or target build"
        result.confidence = "high"
        result.evidence.append("AddressSanitizer reported " + sanitizer_kind.replace("-", " "))
        access = re.search(r"(READ|WRITE) of size (\d+)", text, re.IGNORECASE)
        if access:
            result.evidence.append(f"Invalid {access.group(1).upper()} access size: {access.group(2)} byte(s)")
        summary = re.search(r"SUMMARY: AddressSanitizer:[^\r\n]*?((?:[A-Za-z]:)?[^\r\n]*?:\d+(?::\d+)?)", text)
        if summary:
            result.direct_locations.append(summary.group(1).strip())
        for frame in re.findall(r"#\d+\s+0x[0-9a-fA-F]+\s+in\s+[^\r\n]*", text):
            result.direct_locations.append(frame.strip())
        if "stack-buffer-overflow" in sanitizer_kind or "stack-overflow" in sanitizer_kind:
            result.recommendations += [
                "Inspect the reported stack object and access offset; ensure the parser rejects lengths beyond the declared array extent.",
                "Replace unsafe copies and pointer arithmetic with bounded operations and checked length calculations.",
                "Add regression tests for exact boundary, one-byte-over-boundary, truncated and oversized frames.",
            ]
        elif "heap-use-after-free" in sanitizer_kind or "use-after-free" in sanitizer_kind:
            result.recommendations += [
                "Trace allocation/free ownership for the reported object and remove stale references after asynchronous or retry paths.",
                "Use explicit lifetime ownership and add a regression test covering the triggering sequence.",
            ]
        else:
            result.recommendations += [
                "Inspect the reported allocation/object bounds and the exact invalid access line.",
                "Check all length fields, offset arithmetic, signed/unsigned conversions and copy sizes before accessing memory.",
                "Add the triggering input as a minimized regression test and keep sanitizer instrumentation enabled in CI.",
            ]

    ubsan = re.search(r"runtime error:\s*([^\r\n]+)", text, re.IGNORECASE)
    if ubsan and result.fault_class == "unclassified":
        result.fault_class = "undefined_behavior"
        result.platform = "UndefinedBehaviorSanitizer / instrumented build"
        result.confidence = "high"
        result.evidence.append("UBSan: " + ubsan.group(1).strip())
        loc = re.search(r"([^\s:]+\.(?:c|cc|cpp|h|hpp)):(\d+)(?::(\d+))?:\s*runtime error", text, re.IGNORECASE)
        if not loc:
            loc = re.search(r"([^\s:]+\.(?:c|cc|cpp|h|hpp)):(\d+)(?::(\d+))?", ubsan.group(1))
        if loc:
            result.direct_locations.append(": ".join([loc.group(1), loc.group(2)] + ([loc.group(3)] if loc.group(3) else [])))
        result.recommendations += [
            "Correct the reported undefined operation (for example, bounds, signed overflow, alignment or nullability) at the source line.",
            "Use checked arithmetic and explicit range validation for every protocol-derived length and index.",
            "Keep UBSan in the host regression build and preserve the smallest reproducing corpus input.",
        ]

    # ESP-IDF / ESP32 panic signatures.
    panic = re.search(r"panic'ed\s*\(([^)]+)\)", text, re.IGNORECASE)
    if panic or "guru meditation error" in lower or "backtrace:" in lower:
        result.platform = "ESP-IDF / Xtensa-like panic log"
    if panic:
        reason = panic.group(1).strip()
        result.registers["PANIC_REASON"] = reason
        result.evidence.append(f"ESP panic reason: {reason}")

    register_names = ("PC", "LR", "SP", "PSP", "MSP", "XPSR", "APSR", "IPSR",
                      "EXCCAUSE", "EXCVADDR", "EXC_RETURN", "CFSR", "HFSR", "MMFAR", "BFAR", "SHCSR",
                      "ICSR", "PRIMASK", "BASEPRI", "FAULTMASK", "CONTROL", "RESET_REASON",
                      "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12", "A13", "A14", "A15",
                      "R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15",
                      "SAR", "PS", "LBEG", "LEND", "LCOUNT", "WINDOWBASE", "WINDOWSTART", "EPC1", "EPS2", "EPS3", "EPS4", "EPS5", "EPS6")
    for reg in register_names:
        value = _hex_register(text, reg)
        if value:
            result.registers[reg] = value

    for line in text.splitlines():
        if re.search(r"STACK(?:_DUMP| DUMP)\s*[:=]", line, re.IGNORECASE):
            result.stack_dump.append(line.strip())
        elif re.search(r"^\s*0x[0-9a-fA-F]{6,16}\s*:\s*(?:(?:0x)?[0-9a-fA-F]{2,16}\s+){2,}", line):
            result.stack_dump.append(line.strip())
        # Capture GDB frame lines, including source file/line when DWARF exists.
        elif re.match(r"^\s*#\d+\s+(?:0x[0-9a-fA-F]+|<signal handler)", line):
            result.debugger_frames.append(line.strip())
            frame_addr = re.search(r"#\d+\s+(0x[0-9a-fA-F]+)", line)
            if frame_addr and frame_addr.group(1) not in result.addresses:
                result.addresses.append(frame_addr.group(1))
            source_loc = re.search(r"((?:[A-Za-z]:)?[^\s:]+\.(?:c|cc|cpp|h|hpp|S)):(\d+)(?::(\d+))?", line)
            if source_loc:
                loc = ":".join(x for x in source_loc.groups() if x)
                if loc not in result.direct_locations:
                    result.direct_locations.append(loc)
        elif re.match(r"^\s*\*?\s*\d+\s+Thread\s+", line, re.IGNORECASE):
            result.debugger_frames.append(line.strip())

    gdb_signal = re.search(r"Program received signal ([A-Z0-9_]+)(?:,([^\r\n]+))?", text)
    if gdb_signal:
        signal_name = gdb_signal.group(1).upper()
        signal_detail = gdb_signal.group(2).strip() if gdb_signal.group(2) else ""
        result.evidence.append("GDB stop reason: " + signal_name + (" — " + signal_detail if signal_detail else ""))
        if result.fault_class == "unclassified":
            signal_profiles = {
                "SIGSEGV": ("invalid_memory_access", "medium", [
                    "Inspect the faulting instruction and effective address; classify null, out-of-range, stale-pointer and use-after-free hypotheses separately.",
                    "Check every protocol-derived length, index, pointer and integer conversion before dereference or copy.",
                    "Use the matching ELF plus DWARF, then preserve the minimized trigger as a regression test."]),
                "SIGBUS": ("bus_or_alignment_fault", "medium", [
                    "Inspect the faulting load/store width, alignment and mapped memory region; verify peripheral and DMA alignment requirements.",
                    "Check bus electrical integrity separately from CPU address faults and correlate with the target's bus/power logs.",
                    "Add malformed-length and alignment-boundary regression cases."]),
                "SIGILL": ("invalid_instruction_or_control_flow", "medium", [
                    "Disassemble the fault PC and inspect the caller/return path for overwritten control data or an invalid function pointer.",
                    "Validate dispatch-table indices and callback lifetimes; do not treat every illegal instruction as proof of exploitation.",
                    "Preserve the exact ELF and add a regression test for the trigger."]),
                "SIGABRT": ("assertion_or_explicit_abort", "medium", [
                    "Resolve the abort/assert call site and inspect the failed invariant and caller using the matching ELF.",
                    "Validate untrusted protocol fields before they reach internal assertions; return a controlled parser error where appropriate.",
                    "Add the minimized trigger to the regression corpus."]),
                "SIGFPE": ("arithmetic_exception", "medium", [
                    "Inspect the faulting arithmetic operation for division by zero, invalid conversion or architecture-specific arithmetic traps.",
                    "Check input-controlled divisors, signed overflow assumptions and fixed-point scaling boundaries.",
                    "Add boundary tests and enable UBSan in the host/test firmware build."]),
                "SIGTRAP": ("debugger_breakpoint_or_trap", "low", [
                    "A SIGTRAP may be a debugger breakpoint, explicit trap instruction or requested halt; it is not by itself proof of a crash.",
                    "Compare the PC with configured breakpoints and platform panic records before classifying this as a product defect."]),
                "SIGINT": ("debugger_interrupt", "low", [
                    "SIGINT commonly indicates an operator interrupt; inspect target state and logs before treating it as a firmware fault."]),
            }
            mapped = signal_profiles.get(signal_name)
            if mapped:
                result.fault_class, result.confidence, advice = mapped
                result.recommendations.extend(advice)
            else:
                result.fault_class = "debugger_stop_or_target_exception"
                result.confidence = "low"
                result.recommendations += [
                    "Inspect the GDB stop reason, faulting PC, thread backtrace and target panic/reset logs before assigning a root cause.",
                    "Compare the target-reported build ID with the exact ELF; a debugger stop alone does not prove memory corruption."]

    hfsr = result.registers.get("HFSR")
    if hfsr:
        value = int(hfsr, 16)
        if value & (1 << 30): result.evidence.append("HFSR.FORCED: configurable fault escalated to HardFault")
        if value & (1 << 1): result.evidence.append("HFSR.VECTTBL: fault occurred during exception vector table read")

    # IDF backtrace entries are generally PC:SP pairs. Keep the PC-like value.
    bt = re.search(r"Backtrace\s*:\s*([^\r\n]+)", text, re.IGNORECASE)
    if bt:
        pairs = re.findall(r"(0x[0-9a-fA-F]+)\s*:\s*0x[0-9a-fA-F]+", bt.group(1))
        if pairs:
            result.addresses.extend(pairs)
            result.evidence.append(f"Backtrace contains {len(pairs)} PC:SP frame(s)")

    # Cortex-M fault logs / hand-written fault snapshots.
    cfsr = result.registers.get("CFSR")
    if cfsr:
        result.platform = "ARM Cortex-M fault snapshot"
        decoded = _decode_cfsr(int(cfsr, 16))
        result.evidence.extend(decoded or ["CFSR was present but no recognized status bits were set"])
        if "MMFAR" in result.registers and (int(cfsr, 16) & (1 << 7)):
            result.evidence.append(f"Valid MMFAR fault address: {result.registers['MMFAR']}")
        if "BFAR" in result.registers and (int(cfsr, 16) & (1 << 15)):
            result.evidence.append(f"Valid BFAR fault address: {result.registers['BFAR']}")

    pc = result.registers.get("PC")
    if pc and pc not in result.addresses:
        result.addresses.insert(0, pc)
    for caller_reg in ("LR", "A0"):
        caller = result.registers.get(caller_reg)
        if caller and caller not in result.addresses:
            result.addresses.append(caller)
    # Remove duplicate addresses while preserving order.
    result.addresses = list(dict.fromkeys(result.addresses))[:32]

    if result.fault_class != "unclassified":
        pass
    elif any(s in lower for s in ("stack canary watchpoint triggered", "stack smashing detected",
                                 "stack overflow", "stack-protector")):
        result.fault_class = "stack_overflow_or_stack_buffer_overwrite"
        result.confidence = "high" if "canary" in lower or "stack smashing" in lower else "medium"
        result.evidence.append("Stack guard / canary diagnostic is present")
        result.recommendations += [
            "Identify the faulting task and inspect its worst-case call depth and local array sizes.",
            "Replace unbounded stack buffers with fixed, length-checked buffers; reject oversized protocol lengths before copying.",
            "Measure task stack high-water marks under the same test workload and increase the stack only after fixing unbounded use.",
            "Keep stack-protector/canary checks enabled in diagnostic builds and add boundary tests for every parser length field.",
        ]
    elif any(s in lower for s in ("corrupt heap", "heap corruption", "multi_heap", "heap canary")):
        result.fault_class = "heap_corruption"
        result.confidence = "high"
        result.evidence.append("Heap allocator integrity diagnostic is present")
        result.recommendations += [
            "Enable the platform heap poisoning / integrity checks in a diagnostic build and capture the first corruption point.",
            "Audit allocation size arithmetic for integer overflow and verify every allocation is at least the amount subsequently written.",
            "Audit ownership, lifetime, double-free, and use-after-free paths; prefer static or bounded buffers in protocol hot paths.",
            "Add canary bytes around parser buffers and validate them immediately after each parse stage.",
        ]
    elif "loadprohibited" in lower or "storeprohibited" in lower:
        result.fault_class = "invalid_memory_access"
        result.confidence = "medium"
        access = "read" if "loadprohibited" in lower else "write"
        result.evidence.append(f"Xtensa {access} from/to a prohibited address is reported")
        excv = result.registers.get("EXCVADDR")
        if excv:
            addr = int(excv, 16)
            if addr < 0x1000:
                result.evidence.append("EXCVADDR is near zero; null / near-null pointer access is plausible")
        result.recommendations += [
            "Symbolicate the panic PC and every backtrace PC with the exact ELF from this firmware build.",
            "At the faulting source line, validate pointers, buffer lengths, index bounds, and integer conversions before dereference.",
            "Check whether parser state can reference a stale object after timeout, retry, or asynchronous callback completion.",
            "Add malformed-length, zero-length, maximum-length, and truncated-frame regression tests.",
        ]
    elif "instrfetchprohibited" in lower or "illegalinstruction" in lower or "invalid pc" in lower:
        result.fault_class = "invalid_control_flow_or_instruction"
        result.confidence = "medium"
        result.evidence.append("Invalid instruction fetch / illegal instruction diagnostic is present")
        result.recommendations += [
            "Symbolicate PC and backtrace using the exact ELF; inspect the caller immediately before the invalid PC.",
            "Audit function-pointer tables, callback lifetimes, return-address corruption, and writes near stack frames.",
            "Validate indirect-call targets and keep executable memory protections enabled where supported.",
        ]
    elif "CFSR" in result.registers or any(s in lower for s in ("hardfault", "hard fault", "preciserr", "daccviol", "iaccviol")):
        result.fault_class = "cortex_m_fault"
        result.confidence = "high" if any(x in result.evidence for x in (
            "BusFault: precise data bus error (PRECISERR)",
            "MemManage: data access violation (DACCVIOL)",
            "MemManage: instruction access violation (IACCVIOL)")) else "medium"
        result.recommendations += [
            "Use valid CFSR/HFSR/MMFAR/BFAR bits to distinguish precise memory access faults from imprecise bus faults.",
            "For PRECISERR or DACCVIOL, inspect the stacked PC and the valid BFAR/MMFAR address, then trace the load/store operand.",
            "For stacking/unstacking faults, inspect stack bounds, interrupt nesting, and task stack sizing.",
            "Add bounds checks, integer-overflow checks, and boundary-focused parser tests at the reported access site.",
        ]
    elif "abort()" in lower or "assert failed" in lower or "assertion failed" in lower:
        result.fault_class = "assertion_or_explicit_abort"
        result.confidence = "high"
        result.evidence.append("Explicit abort/assert diagnostic is present; this is not by itself a memory-corruption proof")
        result.recommendations += [
            "Resolve the assertion expression and caller using the matching ELF and source revision.",
            "Determine whether malformed input reaches an invariant that should be validated at the protocol boundary.",
            "Add a regression test for the triggering input and return a controlled protocol error for invalid external data.",
        ]
    elif "brownout" in lower or "brown-out" in lower or "brownout" in result.registers.get("RESET_REASON", "").lower():
        result.fault_class = "brownout_or_power_integrity_reset"
        result.confidence = "high"
        result.evidence.append("Power/brownout reset evidence is present; this is not a source-code crash location")
        result.recommendations += [
            "Measure target supply voltage at the device pins during the exact fuzz transaction, not only at the bench supply.",
            "Check peak current, regulator transient response, cable drop, ground reference, decoupling and reset supervision.",
            "Use a current-limited supply and correlate reset timestamps with bus activity; do not classify a brownout as a buffer overflow.",
        ]
    elif "task watchdog" in lower or "interrupt wdt" in lower or "watchdog timeout" in lower or "watchdog got triggered" in lower:
        result.fault_class = "watchdog_timeout_or_task_starvation"
        result.confidence = "high"
        result.evidence.append("Watchdog diagnostic is present")
        result.recommendations += [
            "Identify the task/core named by the watchdog log and inspect its backtrace and last scheduling points.",
            "Bound critical sections and blocking waits; avoid holding locks across peripheral I/O or parser loops.",
            "Check task priorities, queue backpressure, interrupt latency and worst-case processing time.",
            "Do not merely lengthen the watchdog timeout before determining why progress stopped.",
        ]
    elif "crash_suspected" in lower or "unresponsive" in lower or "health=4" in lower:
        result.fault_class = "target_unresponsive_without_fault_dump"
        result.confidence = "low"
        result.evidence.append("NEXUS observed lost liveness; this does not prove an MCU crash or identify an instruction")
        result.recommendations += [
            "Collect the target's independent debug UART / panic console output; do not infer a source line from a bus timeout.",
            "Record reset-cause GPIO or an independent power/current monitor to separate reset, brownout, bus lock, and firmware hang.",
            "Repeat only after restoring the lab fixture and confirm the same seed reproduces the event.",
            "If the target supports it, enable a firmware crash dump and retain the exact ELF, map, and build ID.",
        ]
    else:
        result.fault_class = "unclassified_or_no_fault_dump"
        result.confidence = "low"
        result.recommendations += [
            "Capture the complete target panic/debug log and a reset-cause indication; a bus timeout alone cannot locate a crash.",
            "Retain the exact target ELF/map file and enable the platform's panic / fault register dump.",
            "Reproduce from the saved case ID and trigger frame in an isolated fixture before changing firmware.",
        ]

    if result.direct_locations:
        result.evidence.append(f"{len(result.direct_locations)} direct sanitizer source location(s) extracted")
    if result.addresses:
        result.evidence.append(f"{len(result.addresses)} code address(es) extracted for symbolication")
    elif not result.direct_locations:
        result.limitations.append("No PC/backtrace address or sanitizer source line was found; source file and line cannot be determined from this log.")
    if not any(k in result.registers for k in ("CFSR", "EXCCAUSE")):
        result.limitations.append("No architecture fault-status register was present; root-cause classification is based on log text only.")
    result.limitations.append("A source location is only trustworthy when symbolicated against the exact ELF matching the flashed firmware.")
    return result


def _find_tool(explicit: Optional[str], candidates: list[str]) -> Optional[str]:
    # An explicitly requested cross-tool must never silently fall back to a
    # host or wrong-architecture utility (e.g. Xtensa addr2line for Cortex-M).
    if explicit:
        return shutil.which(explicit)
    return next((shutil.which(x) for x in candidates if shutil.which(x)), None)


def _run_capture(command: list[str], timeout: float = 15.0) -> str:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"[tool invocation failed: {exc}]"


def _read_source_context(report: Triage, source_roots: Optional[list[Path]] = None,
                         radius: int = 5) -> None:
    roots = source_roots or []
    seen: set[str] = set()
    location_sources = list(report.symbols) + list(report.direct_locations)
    for location_text in location_sources:
        matches = re.findall(r"\bat\s+(.+?\.(?:c|cc|cpp|h|hpp|S|s)):(\d+)", location_text)
        if not matches:
            matches = re.findall(r"((?:[A-Za-z]:)?[/\\][^\s:]+?\.(?:c|cc|cpp|h|hpp|S|s)):(\d+)", location_text)
        if not matches:
            matches = re.findall(r"([^\s:]+\.(?:c|cc|cpp|h|hpp|S|s)):(\d+)", location_text)
        for filename, line_text in matches:
            line_number = int(line_text)
            candidates = [Path(filename)]
            candidates.extend(root / filename for root in roots)
            candidates.extend(root / Path(filename).name for root in roots)
            source_file = next((candidate for candidate in candidates if candidate.is_file()), None)
            if source_file is None:
                continue
            identity = f"{source_file}:{line_number}"
            if identity in seen:
                continue
            seen.add(identity)
            try:
                source_lines = source_file.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            if line_number < 1 or line_number > len(source_lines):
                continue
            start = max(1, line_number - radius)
            end = min(len(source_lines), line_number + radius)
            excerpt = [f"{source_file}:{line_number} (lines {start}-{end})"]
            for number in range(start, end + 1):
                marker = ">" if number == line_number else " "
                excerpt.append(f"{marker} {number:5d} | {source_lines[number - 1]}")
            report.source_context.append("\n".join(excerpt))


def inspect_elf(report: Triage, elf: Path, addr2line_tool: Optional[str] = None,
                objdump_tool: Optional[str] = None, readelf_tool: Optional[str] = None,
                map_path: Optional[Path] = None, coverage_path: Optional[Path] = None,
                disassembly_context: int = 24, source_roots: Optional[list[Path]] = None) -> None:
    # Extract architecture/sections, symbols and nearby disassembly.
    readelf = _find_tool(readelf_tool, ["xtensa-esp32s3-elf-readelf", "arm-none-eabi-readelf", "llvm-readelf", "readelf"])
    objdump = _find_tool(objdump_tool, ["xtensa-esp32s3-elf-objdump", "arm-none-eabi-objdump", "llvm-objdump", "objdump"])
    a2l = _find_tool(addr2line_tool, ["xtensa-esp32s3-elf-addr2line", "arm-none-eabi-addr2line", "llvm-addr2line", "addr2line"])

    if readelf:
        header = _run_capture([readelf, "-h", str(elf)])
        for line in header.splitlines():
            if any(token in line for token in ("Class:", "Data:", "Machine:", "Entry point address:")):
                report.elf_metadata.append(line.strip())
        notes = _run_capture([readelf, "-n", str(elf)])
        match = re.search(r"Build ID:\s*([0-9a-fA-F]+)", notes)
        if match:
            report.elf_build_id = match.group(1).lower()
            report.elf_metadata.append(f"ELF Build ID: {report.elf_build_id}")
            if report.build_id:
                report.build_id_match = report.build_id == report.elf_build_id
                report.evidence.append("Target log and ELF build IDs " + ("match" if report.build_id_match else "DO NOT MATCH"))
                if not report.build_id_match:
                    report.limitations.append("Build-ID mismatch: symbol/disassembly mappings may refer to a different firmware image. Rebuild/reflash or supply the exact ELF.")
        elif report.build_id:
            report.limitations.append("ELF has no GNU build ID note; binary identity could not be independently matched.")

        sections = _run_capture([readelf, "-SW", str(elf)])
        interesting = (".text", ".rodata", ".data", ".bss", ".iram", ".dram", ".flash", ".vectors", ".init")
        for line in sections.splitlines():
            if any(name in line for name in interesting) and re.search(r"\[\s*\d+\]", line):
                report.elf_metadata.append("SECTION " + line.strip())
        segments = _run_capture([readelf, "-lW", str(elf)])
        for line in segments.splitlines():
            if re.match(r"\s*LOAD\s", line):
                report.elf_metadata.append("SEGMENT " + line.strip())
    else:
        report.limitations.append("readelf/llvm-readelf not found; ELF architecture and section metadata were not extracted.")

    symbols_are_trustworthy = report.build_id_match is not False
    if report.addresses and a2l and symbols_are_trustworthy:
        for addr in report.addresses:
            output = _run_capture([a2l, "-pfiaC", "-e", str(elf), addr]).strip()
            report.symbols.append(f"{addr}: {output or 'no symbol information'}")
    elif report.addresses and not symbols_are_trustworthy:
        report.limitations.append("Symbolication and disassembly were suppressed because the target log build ID does not match the supplied ELF.")
    elif report.addresses:
        report.limitations.append("Matching addr2line executable not found; install the architecture-specific toolchain to map PCs to functions/source lines.")
    if report.elf_build_id and not report.build_id:
        report.limitations.append("The capture has no target BUILD_ID field. ELF identity cannot be proven from the log; symbolication is provisional until the flashed-image build ID is recorded.")
    _read_source_context(report, source_roots)

    if report.addresses and objdump and symbols_are_trustworthy:
        for addr in report.addresses[:8]:
            try:
                pc = int(addr, 16)
            except ValueError:
                continue
            begin = max(0, pc - max(4, disassembly_context))
            end = pc + max(16, disassembly_context)
            disasm = _run_capture([objdump, "-d", "-C", "-l", f"--start-address=0x{begin:x}",
                                   f"--stop-address=0x{end:x}", str(elf)])
            useful = [line.rstrip() for line in disasm.splitlines()
                      if line.strip() and (re.search(r"^[0-9a-fA-F]+\s+<", line.strip())
                                           or re.match(r"^[0-9a-fA-F]+:", line.strip())
                                           or line.lstrip().startswith("/")
                                           or "file format" in line)]
            if useful:
                report.disassembly.append(f"===== Disassembly around {addr} =====\n" + "\n".join(useful[:100]))
    elif report.addresses and not symbols_are_trustworthy:
        pass
    elif report.addresses:
        report.limitations.append("objdump not found; nearby machine instructions were not decoded.")

    if map_path and not map_path.is_file():
        report.limitations.append(f"Linker map file not found: {map_path}")
    if map_path and map_path.is_file():
        try:
            map_lines = map_path.read_text(encoding="utf-8", errors="replace").splitlines()
            needles = set()
            for addr in report.addresses:
                needles.add(addr.lower())
                needles.add(addr.lower().replace("0x", ""))
            hits = []
            for index, line in enumerate(map_lines):
                low = line.lower()
                if any(n in low for n in needles):
                    lo, hi = max(0, index - 1), min(len(map_lines), index + 2)
                    hits.extend(f"L{j + 1}: {map_lines[j]}" for j in range(lo, hi))
            report.map_evidence = list(dict.fromkeys(hits))[:60]
        except OSError as exc:
            report.limitations.append(f"Could not read linker map file: {exc}")

    if coverage_path and not coverage_path.is_file():
        report.limitations.append(f"Coverage report not found: {coverage_path}")
    if coverage_path and coverage_path.is_file():
        try:
            report.coverage_summary = json.loads(coverage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report.limitations.append(f"Coverage report could not be parsed: {exc}")


def render_markdown(report: Triage, source: str, elf: Optional[Path]) -> str:
    lines = [
        "# NEXUS-HW Crash Triage & Binary Analysis Report", "",
        f"- **Capture:** `{source}`", f"- **Platform:** {report.platform}",
        f"- **Classification:** `{report.fault_class}`", f"- **Confidence:** **{report.confidence.upper()}**",
    ]
    if elf:
        lines.append(f"- **ELF:** `{elf}`")
    if report.build_id:
        lines.append(f"- **Target Build ID:** `{report.build_id}`")
    if report.elf_build_id:
        lines.append(f"- **ELF Build ID:** `{report.elf_build_id}` (match={report.build_id_match})")
    lines += ["", "## Executive finding"]
    lines += [f"- {x}" for x in report.evidence] or ["- No direct fault evidence extracted."]
    if report.registers:
        lines += ["", "## CPU register context", "", "| Register | Value |", "|---|---|"]
        lines += [f"| `{k}` | `{v}` |" for k, v in report.registers.items()]
    if report.debugger_metadata:
        lines += ["", "## Debugger capture metadata"] + [f"- `{x}`" for x in report.debugger_metadata]
    if report.execution_context:
        lines += ["", "## Thread / task / core context"] + [f"- `{x}`" for x in report.execution_context]
    if report.debugger_frames:
        lines += ["", "## GDB backtrace / thread frames", "", "```text"] + report.debugger_frames + ["```"]
    if report.stack_dump:
        lines += ["", "## Stack memory dump", "", "```text"] + report.stack_dump + ["```"]
    if report.source_context:
        lines += ["", "## Source view"]
        for item in report.source_context:
            lines += ["", "```cpp", item, "```"]
    if report.addresses:
        lines += ["", "## Program-counter / backtrace addresses"] + [f"- `{x}`" for x in report.addresses]
    if report.direct_locations:
        lines += ["", "## Direct sanitizer source locations"] + [f"- `{x}`" for x in report.direct_locations]
    if report.symbols:
        lines += ["", "## ELF symbolication"] + [f"- `{x}`" for x in report.symbols]
    if report.disassembly:
        lines += ["", "## Nearby disassembly"]
        for item in report.disassembly:
            lines += ["", "```asm", item, "```"]
    if report.elf_metadata:
        lines += ["", "## ELF architecture / section / load-segment metadata", ""]
        lines += [f"- `{x}`" for x in report.elf_metadata]
    if report.map_evidence:
        lines += ["", "## Linker-map matches", "", "```text"] + report.map_evidence + ["```"]
    if report.coverage_summary:
        lines += ["", "## Instrumented target code coverage", "", "```json",
                  json.dumps(report.coverage_summary, indent=2), "```"]
    if report.nexus_event:
        lines += ["", "## NEXUS reproduction event", ""]
        lines += [f"- **{k}:** `{v}`" for k, v in report.nexus_event.items()]
    lines += ["", "## Recommended remediation"]
    lines += [f"{i}. {x}" for i, x in enumerate(report.recommendations, 1)]
    lines += ["", "## Evidence limitations"]
    lines += [f"- {x}" for x in report.limitations]
    lines += ["", "> A transport timeout is not a faulting PC. Exact source mapping requires target-generated registers/panic output and the exact matching ELF/map. Instrumented code coverage requires target firmware built with NEXUS coverage hooks or an equivalent coverage runtime.", ""]
    return "\n".join(lines)


def render_html(report: Triage, source: str, elf: Optional[Path]) -> str:
    esc = html.escape
    def panel(title: str, body: str) -> str:
        return f'<section class="panel"><h2>{esc(title)}</h2>{body}</section>'
    def list_html(items: list[str]) -> str:
        return "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>" if items else "<p class='muted'>No data captured.</p>"
    reg_rows = "".join(f"<tr><th>{esc(k)}</th><td><code>{esc(v)}</code></td></tr>" for k, v in report.registers.items())
    address_rows = "".join(f"<tr><td>{i}</td><td><code>{esc(v)}</code></td><td>{'FAULT PC' if i == 0 else 'BACKTRACE'}</td></tr>" for i, v in enumerate(report.addresses))
    disasm = "".join(f"<h3>{esc(item.splitlines()[0])}</h3><pre class='asm'>{esc(chr(10).join(item.splitlines()[1:]))}</pre>" for item in report.disassembly)
    meta = "".join(f"<li><code>{esc(x)}</code></li>" for x in report.elf_metadata)
    symbols = "".join(f"<li><code>{esc(x)}</code></li>" for x in report.symbols)
    map_body = "<pre>" + esc("\n".join(report.map_evidence)) + "</pre>" if report.map_evidence else "<p class='muted'>No map-file address match.</p>"
    coverage = esc(json.dumps(report.coverage_summary, indent=2)) if report.coverage_summary else "No coverage JSON attached."
    nexus_rows = "".join(f"<tr><th>{esc(k)}</th><td><code>{esc(v)}</code></td></tr>" for k, v in report.nexus_event.items())
    source_view = "".join(f"<h3>{esc(item.splitlines()[0])}</h3><pre>{esc(chr(10).join(item.splitlines()[1:]))}</pre>" for item in report.source_context)
    build_match = "NOT CHECKED" if report.build_id_match is None else ("MATCH" if report.build_id_match else "MISMATCH")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NEXUS-HW Binary Crash Analysis</title>
<style>
:root{{--bg:#0b1020;--panel:#131c31;--panel2:#0f172a;--line:#26334d;--text:#e5edf8;--muted:#91a0b8;--cyan:#5eead4;--red:#fb7185;--amber:#fbbf24;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 Inter,ui-sans-serif,system-ui,Segoe UI,Arial}}
header{{padding:28px 34px;background:linear-gradient(115deg,#111d36,#142a3d);border-bottom:1px solid var(--line)}}h1{{margin:0;font-size:25px;letter-spacing:.03em}}.sub{{color:var(--muted);margin-top:6px}}main{{max-width:1400px;margin:24px auto;padding:0 22px;display:grid;grid-template-columns:repeat(12,1fr);gap:16px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;min-width:0;grid-column:span 6;overflow:hidden}}.wide{{grid-column:span 12}}h2{{font-size:15px;margin:0 0 13px;color:var(--cyan);text-transform:uppercase;letter-spacing:.08em}}h3{{font-size:13px;color:var(--amber);margin:14px 0 5px}}.hero{{grid-column:span 12;display:flex;gap:14px;flex-wrap:wrap}}.metric{{flex:1;min-width:180px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:14px}}.metric b{{display:block;font-size:17px;margin-bottom:4px}}.muted,small{{color:var(--muted)}}code,pre{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}}code{{color:#a5f3fc}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#090f1d;border:1px solid var(--line);border-radius:8px;padding:12px;color:#cbd5e1;max-height:560px;overflow:auto}}.asm{{color:#d5e4ff}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--muted);font-weight:600;width:32%}}.pill{{display:inline-block;padding:4px 9px;border-radius:999px;background:#25334d;color:var(--cyan);font-size:11px;margin:4px 4px 0 0}}.critical{{color:var(--red)}}li{{margin:7px 0}}footer{{max-width:1400px;margin:0 auto;padding:8px 22px 30px;color:var(--muted)}}@media(max-width:900px){{.panel{{grid-column:span 12}}}}
</style></head><body>
<header><h1>NEXUS-HW / CRASH & BINARY ANALYSIS</h1><div class="sub">Offline reverse-engineering style report · Capture: {esc(source)} · ELF: {esc(str(elf) if elf else 'not supplied')}</div>
<span class="pill">{esc(report.platform)}</span><span class="pill">CONFIDENCE: {esc(report.confidence.upper())}</span><span class="pill">ELF BUILD ID: {esc(build_match)}</span></header>
<main>
<div class="hero"><div class="metric"><small>FAULT CLASS</small><b class="critical">{esc(report.fault_class)}</b></div><div class="metric"><small>FAULT / BACKTRACE ADDRESSES</small><b>{len(report.addresses)}</b></div><div class="metric"><small>CPU REGISTERS</small><b>{len(report.registers)}</b></div><div class="metric"><small>RECOMMENDATIONS</small><b>{len(report.recommendations)}</b></div></div>
{panel('Executive evidence', list_html(report.evidence))}
{panel('NEXUS trigger correlation', '<table>'+nexus_rows+'</table>' if nexus_rows else "<p class='muted'>No NEXUS event found in the capture.</p>")}
{panel('Debugger capture metadata', list_html(report.debugger_metadata))}
{panel('Thread / task / core context', list_html(report.execution_context))}
{panel('GDB backtrace / thread frames', '<pre>'+esc(chr(10).join(report.debugger_frames))+'</pre>' if report.debugger_frames else "<p class='muted'>No GDB frame transcript found.</p>")}
{panel('CPU register file', '<table>'+reg_rows+'</table>' if reg_rows else "<p class='muted'>No register dump found.</p>")}
{panel('Program counter & backtrace', '<table><tr><th>#</th><th>Address</th><th>Role</th></tr>'+address_rows+'</table>' if address_rows else "<p class='muted'>No PC/backtrace address found.</p>")}
{panel('Stack memory dump', '<pre>'+esc(chr(10).join(report.stack_dump))+'</pre>' if report.stack_dump else "<p class='muted'>No raw stack words were included in the target log.</p>")}
{panel('ELF symbolication', '<ul>'+symbols+'</ul>' if symbols else "<p class='muted'>No symbolication; provide the exact ELF and matching cross-toolchain.</p>")}
{panel('ELF architecture, sections & segments', '<ul>'+meta+'</ul>' if meta else "<p class='muted'>ELF metadata unavailable.</p>")}
{panel('Linker map cross-reference', map_body)}
{panel('Instrumented code coverage', '<pre>'+coverage+'</pre>')}
{panel('Crash remediation', list_html(report.recommendations))}
{panel('Evidence limitations', list_html(report.limitations))}
<div class="panel wide"><h2>Source view</h2>{source_view if source_view else "<p class='muted'>No source context resolved. Supply a matching ELF with DWARF information and --source-root pointing to the matching source revision.</p>"}</div>
<div class="panel wide"><h2>Instruction view / disassembly around fault addresses</h2>{disasm if disasm else "<p class='muted'>No disassembly. Supply an architecture-matched objdump and ELF.</p>"}</div>
</main><footer>NEXUS-HW does not infer a source-level crash site from transport timeouts. A source line is reliable only when target fault evidence is symbolicated using the exact ELF matching the flashed image.</footer>
</body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline NEXUS-HW crash triage and reverse-engineering report")
    parser.add_argument("--input", required=True, help="Target panic/debug log or NEXUS capture file")
    parser.add_argument("--elf", help="Exact ELF used to build the flashed target firmware")
    parser.add_argument("--map", help="Optional linker .map file from the same build")
    parser.add_argument("--coverage", help="Optional JSON report produced by tools/nexus_cov.py")
    parser.add_argument("--addr2line", help="Path to matching architecture addr2line executable")
    parser.add_argument("--objdump", help="Path to matching architecture objdump executable")
    parser.add_argument("--readelf", help="Path to matching architecture readelf executable")
    parser.add_argument("--source-root", action="append", default=[], help="Source checkout root; may be specified multiple times")
    parser.add_argument("--disassembly-context", type=int, default=24, help="bytes around each PC to disassemble")
    parser.add_argument("--format", choices=("md", "html", "json"), default=None)
    parser.add_argument("--output", help="Output report path; extension selects md/html/json when --format is omitted")
    parser.add_argument("--json", action="store_true", help="Compatibility alias for --format json")
    args = parser.parse_args()

    input_path = Path(args.input)
    try:
        text = input_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"nexus_triage: cannot read {input_path}: {exc}", file=sys.stderr)
        return 2
    report = parse_log(text)
    elf_path = Path(args.elf) if args.elf else None
    if elf_path:
        if not elf_path.is_file():
            print(f"nexus_triage: ELF not found: {elf_path}", file=sys.stderr)
            return 2
        inspect_elf(report, elf_path, args.addr2line, args.objdump, args.readelf,
                    Path(args.map) if args.map else None,
                    Path(args.coverage) if args.coverage else None,
                    args.disassembly_context, [Path(root) for root in args.source_root])
    elif args.coverage:
        try:
            report.coverage_summary = json.loads(Path(args.coverage).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"nexus_triage: cannot read coverage JSON: {exc}", file=sys.stderr)
            return 2
    selected_format = "json" if args.json else args.format
    if selected_format is None:
        selected_format = Path(args.output).suffix.lower().lstrip(".") if args.output else "md"
        if selected_format not in ("md", "markdown", "html", "json"):
            selected_format = "md"
        if selected_format == "markdown": selected_format = "md"
    if selected_format == "json":
        output = json.dumps(asdict(report), indent=2)
    elif selected_format == "html":
        output = render_html(report, str(input_path), elf_path)
    else:
        output = render_markdown(report, str(input_path), elf_path)
    if args.output:
        try:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(output + ("\n" if not output.endswith("\n") else ""), encoding="utf-8")
        except OSError as exc:
            print(f"nexus_triage: cannot write report: {exc}", file=sys.stderr)
            return 2
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
