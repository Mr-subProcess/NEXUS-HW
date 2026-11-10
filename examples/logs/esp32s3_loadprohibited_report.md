# NEXUS-HW Crash Triage Report

- **Input:** `examples/logs/esp32s3_loadprohibited.log`
- **Platform:** ESP-IDF / Xtensa-like panic log
- **Classification:** `invalid_memory_access`
- **Confidence:** **MEDIUM**

## Evidence
- ESP panic reason: LoadProhibited
- Backtrace contains 3 PC:SP frame(s)
- Xtensa read from/to a prohibited address is reported
- EXCVADDR is near zero; null / near-null pointer access is plausible
- 3 code address(es) extracted for symbolication

## Registers

| Register | Value |
|---|---|
| `PANIC_REASON` | `LoadProhibited` |
| `PC` | `0x42001010` |
| `A0` | `0x82002023` |
| `A1` | `0x3fcebc00` |
| `EXCCAUSE` | `0x0000001c` |
| `EXCVADDR` | `0x00000004` |

## Extracted code addresses
- `0x42001010`
- `0x42002020`
- `0x40378abc`

## Recommended mitigations
1. Symbolicate the panic PC and every backtrace PC with the exact ELF from this firmware build.
2. At the faulting source line, validate pointers, buffer lengths, index bounds, and integer conversions before dereference.
3. Check whether parser state can reference a stale object after timeout, retry, or asynchronous callback completion.
4. Add malformed-length, zero-length, maximum-length, and truncated-frame regression tests.

## Diagnostic limitations
- A source location is only trustworthy when symbolicated against the exact ELF matching the flashed firmware.

> NEXUS-HW does not claim a confirmed crash site from transport timeout alone. Exact source location requires target-generated fault evidence and matching firmware symbols.
