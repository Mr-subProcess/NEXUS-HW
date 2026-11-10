# NEXUS-HW Crash Triage Report

- **Input:** `examples/logs/esp32s3_brownout.log`
- **Platform:** unknown
- **Classification:** `brownout_or_power_integrity_reset`
- **Confidence:** **HIGH**

## Evidence
- ESP reset reason: BROWNOUT_RST (0x15)
- Power/brownout reset evidence is present; this is not a source-code crash location

## Registers

| Register | Value |
|---|---|
| `RESET_CODE` | `0x15` |
| `RESET_REASON` | `BROWNOUT_RST` |

## Recommended mitigations
1. Measure target supply voltage at the device pins during the exact fuzz transaction, not only at the bench supply.
2. Check peak current, regulator transient response, cable drop, ground reference, decoupling and reset supervision.
3. Use a current-limited supply and correlate reset timestamps with bus activity; do not classify a brownout as a buffer overflow.

## Diagnostic limitations
- No PC/backtrace address or sanitizer source line was found; source file and line cannot be determined from this log.
- No architecture fault-status register was present; root-cause classification is based on log text only.
- A source location is only trustworthy when symbolicated against the exact ELF matching the flashed firmware.

> NEXUS-HW does not claim a confirmed crash site from transport timeout alone. Exact source location requires target-generated fault evidence and matching firmware symbols.
