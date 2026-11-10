# NEXUS-HW Crash Triage Report

- **Input:** `examples/logs/esp32s3_watchdog.log`
- **Platform:** ESP-IDF / Xtensa-like panic log
- **Classification:** `watchdog_timeout_or_task_starvation`
- **Confidence:** **HIGH**

## Evidence
- Backtrace contains 2 PC:SP frame(s)
- Watchdog diagnostic is present
- 2 code address(es) extracted for symbolication

## Registers

| Register | Value |
|---|---|
| `PC` | `0x42005555` |
| `A1` | `0x3fcebd20` |

## Extracted code addresses
- `0x42005555`
- `0x42006666`

## Recommended mitigations
1. Identify the task/core named by the watchdog log and inspect its backtrace and last scheduling points.
2. Bound critical sections and blocking waits; avoid holding locks across peripheral I/O or parser loops.
3. Check task priorities, queue backpressure, interrupt latency and worst-case processing time.
4. Do not merely lengthen the watchdog timeout before determining why progress stopped.

## Diagnostic limitations
- No architecture fault-status register was present; root-cause classification is based on log text only.
- A source location is only trustworthy when symbolicated against the exact ELF matching the flashed firmware.

> NEXUS-HW does not claim a confirmed crash site from transport timeout alone. Exact source location requires target-generated fault evidence and matching firmware symbols.
