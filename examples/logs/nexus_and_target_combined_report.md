# NEXUS-HW Crash Triage Report

- **Input:** `examples/logs/nexus_and_target_combined.log`
- **Platform:** ESP-IDF / Xtensa-like panic log
- **Classification:** `invalid_memory_access`
- **Confidence:** **MEDIUM**

## Evidence
- Correlated NEXUS crash-suspected event: case=41, tag=0010, latency_us=20001, failed_heartbeats=2, trigger=10AA0000
- ESP panic reason: LoadProhibited
- Backtrace contains 2 PC:SP frame(s)
- Xtensa read from/to a prohibited address is reported
- EXCVADDR is near zero; null / near-null pointer access is plausible
- 2 code address(es) extracted for symbolication

## Registers

| Register | Value |
|---|---|
| `PANIC_REASON` | `LoadProhibited` |
| `PC` | `0x42001234` |
| `EXCCAUSE` | `0x0000001c` |
| `EXCVADDR` | `0x00000004` |

## Extracted code addresses
- `0x42001234`
- `0x42004567`

## NEXUS trigger correlation

- **case:** `41`
- **tag:** `0010`
- **latency_us:** `20001`
- **failed_heartbeats:** `2`
- **trigger:** `10AA0000`

## Recommended mitigations
1. Symbolicate the panic PC and every backtrace PC with the exact ELF from this firmware build.
2. At the faulting source line, validate pointers, buffer lengths, index bounds, and integer conversions before dereference.
3. Check whether parser state can reference a stale object after timeout, retry, or asynchronous callback completion.
4. Add malformed-length, zero-length, maximum-length, and truncated-frame regression tests.

## Diagnostic limitations
- A source location is only trustworthy when symbolicated against the exact ELF matching the flashed firmware.

> NEXUS-HW does not claim a confirmed crash site from transport timeout alone. Exact source location requires target-generated fault evidence and matching firmware symbols.
