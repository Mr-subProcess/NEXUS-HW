# NEXUS-HW Crash Triage Report

- **Input:** `examples/logs/cortexm_precise_busfault.log`
- **Platform:** ARM Cortex-M fault snapshot
- **Classification:** `cortex_m_fault`
- **Confidence:** **HIGH**

## Evidence
- BusFault: precise data bus error (PRECISERR)
- BFAR contains a valid fault address (BFARVALID)
- Valid BFAR fault address: 0x2000FFF0
- 1 code address(es) extracted for symbolication

## Registers

| Register | Value |
|---|---|
| `PC` | `0x08001234` |
| `SP` | `0x20001000` |
| `LR` | `0x08004567` |
| `CFSR` | `0x00008200` |
| `HFSR` | `0x40000000` |
| `BFAR` | `0x2000FFF0` |

## Extracted code addresses
- `0x08001234`

## Recommended mitigations
1. Use valid CFSR/HFSR/MMFAR/BFAR bits to distinguish precise memory access faults from imprecise bus faults.
2. For PRECISERR or DACCVIOL, inspect the stacked PC and the valid BFAR/MMFAR address, then trace the load/store operand.
3. For stacking/unstacking faults, inspect stack bounds, interrupt nesting, and task stack sizing.
4. Add bounds checks, integer-overflow checks, and boundary-focused parser tests at the reported access site.

## Diagnostic limitations
- A source location is only trustworthy when symbolicated against the exact ELF matching the flashed firmware.

> NEXUS-HW does not claim a confirmed crash site from transport timeout alone. Exact source location requires target-generated fault evidence and matching firmware symbols.
