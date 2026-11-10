# NEXUS-HW Crash Triage Report

- **Input:** `examples/logs/esp32s3_stack_canary.log`
- **Platform:** ESP-IDF / Xtensa-like panic log
- **Classification:** `stack_overflow_or_stack_buffer_overwrite`
- **Confidence:** **HIGH**

## Evidence
- ESP panic reason: Unhandled debug exception
- Backtrace contains 3 PC:SP frame(s)
- Stack guard / canary diagnostic is present
- 3 code address(es) extracted for symbolication

## Registers

| Register | Value |
|---|---|
| `PANIC_REASON` | `Unhandled debug exception` |
| `PC` | `0x42001234` |
| `A0` | `0x8200456a` |
| `A1` | `0x3fcebd20` |
| `EXCCAUSE` | `0x00000001` |
| `EXCVADDR` | `0x00000000` |

## Extracted code addresses
- `0x42001234`
- `0x42004567`
- `0x40378abc`

## Recommended mitigations
1. Identify the faulting task and inspect its worst-case call depth and local array sizes.
2. Replace unbounded stack buffers with fixed, length-checked buffers; reject oversized protocol lengths before copying.
3. Measure task stack high-water marks under the same test workload and increase the stack only after fixing unbounded use.
4. Keep stack-protector/canary checks enabled in diagnostic builds and add boundary tests for every parser length field.

## Diagnostic limitations
- A source location is only trustworthy when symbolicated against the exact ELF matching the flashed firmware.

> NEXUS-HW does not claim a confirmed crash site from transport timeout alone. Exact source location requires target-generated fault evidence and matching firmware symbols.
