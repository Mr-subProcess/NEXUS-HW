#!/usr/bin/env python3
"""Delta-debug a binary test case while preserving a caller-defined crash signature.

The oracle is an operator-supplied replay command. Arguments are tokenized with
shlex and executed without a shell; use {input} as the temporary input filename.
This tool is intentionally offline from target-control APIs: the supplied oracle
owns the replay policy, isolation, rate limit and reset procedure.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nexus_checksum import apply_checksum

DEFAULT_CRASH_PATTERN = (
    r"(?i)(Guru Meditation|HardFault|Hard Fault|AddressSanitizer|"
    r"UndefinedBehaviorSanitizer|runtime error:|CRASH_CONFIRMED)"
)


@dataclass
class OracleResult:
    reproduced: bool
    returncode: int
    output: str


def ddmin(data: bytes, oracle: Callable[[bytes], bool], immutable_prefix: int = 0,
          max_trials: int = 10000) -> tuple[bytes, int]:
    """Classic chunk-removal delta debugging. Prefix bytes are never removed."""
    if immutable_prefix < 0 or immutable_prefix > len(data):
        raise ValueError("immutable_prefix must be within the input length")
    if not oracle(data):
        raise ValueError("baseline input does not reproduce the requested crash signature")
    prefix = data[:immutable_prefix]
    current = data[immutable_prefix:]
    granularity = 2
    trials = 1
    while current and trials < max_trials:
        chunk_size = max(1, (len(current) + granularity - 1) // granularity)
        reduced = False
        starts = list(range(0, len(current), chunk_size))
        for start in starts:
            candidate = current[:start] + current[min(len(current), start + chunk_size):]
            trials += 1
            if oracle(prefix + candidate):
                current = candidate
                granularity = max(2, granularity - 1)
                reduced = True
                break
            if trials >= max_trials:
                break
        if not reduced:
            if granularity >= len(current):
                break
            granularity = min(len(current), granularity * 2)
    return prefix + current, trials


def simplify_bytes(data: bytes, oracle: Callable[[bytes], bool], immutable_prefix: int = 0,
                   max_trials: int = 10000, already_used: int = 0) -> tuple[bytes, int]:
    """Try common boundary values at each mutable byte while retaining the crash."""
    current = bytearray(data)
    trials = already_used
    interesting = (0x00, 0x01, 0x7F, 0x80, 0xFF)
    changed = True
    while changed and trials < max_trials:
        changed = False
        for offset in range(immutable_prefix, len(current)):
            original = current[offset]
            for value in interesting:
                if value == original:
                    continue
                candidate = bytearray(current)
                candidate[offset] = value
                trials += 1
                if oracle(bytes(candidate)):
                    current = candidate
                    changed = True
                    break
                if trials >= max_trials:
                    break
            if trials >= max_trials:
                break
    return bytes(current), trials


def command_oracle(command_template: list[str], pattern: re.Pattern[str], timeout: float,
                   cwd: Path | None = None, repetitions: int = 1,
                   required_reproductions: int = 1,
                   checksum_spec: dict | None = None) -> Callable[[bytes], bool]:
    """Replay a candidate repeatedly; optionally repair its protocol checksum first."""
    if repetitions < 1 or required_reproductions < 1 or required_reproductions > repetitions:
        raise ValueError("required reproductions must be between 1 and repetitions")

    def run(data: bytes) -> bool:
        try:
            candidate = apply_checksum(data, checksum_spec) if checksum_spec else data
        except (ValueError, OverflowError):
            return False
        successes = 0
        for _ in range(repetitions):
            with tempfile.NamedTemporaryFile(prefix="nexus_case_", suffix=".bin", delete=True) as tmp:
                tmp.write(candidate)
                tmp.flush()
                command = [part.replace("{input}", tmp.name) for part in command_template]
                if not any("{input}" in part for part in command_template):
                    command.append(tmp.name)
                try:
                    completed = subprocess.run(command, cwd=str(cwd) if cwd else None,
                                               capture_output=True, text=True, timeout=timeout,
                                               check=False)
                except (OSError, subprocess.TimeoutExpired):
                    continue
                combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
                if pattern.search(combined):
                    successes += 1
                if successes >= required_reproductions:
                    return True
                # Early exit when the remaining attempts cannot reach quorum.
                remaining = repetitions - (_ + 1)
                if successes + remaining < required_reproductions:
                    return False
        return successes >= required_reproductions
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimize a crash-inducing NEXUS-HW input")
    parser.add_argument("--input", required=True, type=Path, help="original binary input")
    parser.add_argument("--output", required=True, type=Path, help="minimized binary output")
    parser.add_argument("--oracle-command", required=True,
                        help="replay command; quote as one string and include {input}")
    parser.add_argument("--crash-regex", default=DEFAULT_CRASH_PATTERN,
                        help="signature proving the same crash class was reproduced")
    parser.add_argument("--immutable-prefix", type=int, default=0,
                        help="number of leading bytes that must not be removed")
    parser.add_argument("--timeout", type=float, default=10.0, help="timeout per oracle trial")
    parser.add_argument("--max-trials", type=int, default=10000)
    parser.add_argument("--repetitions", type=int, default=1,
                        help="oracle replays per candidate (increase for flaky hardware targets)")
    parser.add_argument("--required-reproductions", type=int, default=1,
                        help="minimum matching replays required; use e.g. 2 with --repetitions 3")
    parser.add_argument("--checksum-spec", type=Path, default=None,
                        help="JSON checksum layout; recalculates checksum for every candidate and preserves frame length")
    parser.add_argument("--no-byte-simplify", action="store_true",
                        help="skip replacement of retained bytes with common boundary values")
    parser.add_argument("--cwd", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None, help="optional JSON summary")
    args = parser.parse_args()

    try:
        original = args.input.read_bytes()
        if not original:
            raise ValueError("input file is empty")
        if args.timeout <= 0 or args.max_trials < 1:
            raise ValueError("timeout and max-trials must be positive")
        if args.repetitions < 1 or args.required_reproductions < 1 or args.required_reproductions > args.repetitions:
            raise ValueError("required-reproductions must be between 1 and repetitions")
        checksum_spec = None
        if args.checksum_spec:
            checksum_spec = json.loads(args.checksum_spec.read_text(encoding="utf-8"))
            if not isinstance(checksum_spec, dict):
                raise ValueError("checksum spec must be a JSON object")
            # Validate the checksum layout against the original frame before any minimization.
            apply_checksum(original, checksum_spec)
        pattern = re.compile(args.crash_regex)
        command = shlex.split(args.oracle_command)
        if not command:
            raise ValueError("oracle command is empty")
        oracle = command_oracle(command, pattern, args.timeout, args.cwd,
                                args.repetitions, args.required_reproductions, checksum_spec)
        if checksum_spec:
            # Checksummed protocols generally encode fixed offsets/lengths. Preserve total
            # frame length and simplify payload bytes while recomputing the checksum each try.
            minimized, trials = original, 0
            if not args.no_byte_simplify:
                minimized, trials = simplify_bytes(minimized, oracle, args.immutable_prefix,
                                                   args.max_trials, trials)
            final_bytes = apply_checksum(minimized, checksum_spec)
        else:
            minimized, trials = ddmin(original, oracle, args.immutable_prefix, args.max_trials)
            if not args.no_byte_simplify and trials < args.max_trials:
                minimized, trials = simplify_bytes(minimized, oracle, args.immutable_prefix,
                                                   args.max_trials, trials)
            final_bytes = minimized
        reproduced = bool(oracle(minimized))
        if not reproduced:
            raise RuntimeError("minimized input failed final reproduction check")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(final_bytes)
        summary = {
            "input": str(args.input), "output": str(args.output),
            "original_size": len(original), "minimized_size": len(final_bytes),
            "bytes_removed": len(original) - len(final_bytes),
            "immutable_prefix": args.immutable_prefix, "oracle_trials": trials,
            "oracle_repetitions": args.repetitions,
            "required_reproductions": args.required_reproductions,
            "checksum_spec": checksum_spec,
            "length_preserved_for_checksum": bool(checksum_spec),
            "crash_regex": args.crash_regex,
            "minimized_hex": final_bytes.hex().upper(),
            "reproduced_after_minimization": reproduced,
            "note": "A matching textual signature is an oracle contract, not proof of identical root cause. Review the target log and fault class. Hardware replays should use a fixture-specific timeout, stable signature, and reset/re-arm policy."
        }
        if not summary["reproduced_after_minimization"]:
            raise RuntimeError("minimized input failed final reproduction check")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0
    except (OSError, ValueError, re.error, RuntimeError) as exc:
        print(f"nexus_minimize: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
