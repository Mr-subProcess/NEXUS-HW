# Crash localization, triage and remediation

## What NEXUS can prove from the bus

The external NEXUS node can reliably record the last stimulus, response class, latency, repeated timeouts, and whether a separate read-only heartbeat still responds. This proves **loss of protocol liveness**, not the exact instruction or source line where a target faulted. A disconnected cable, stuck bus, brownout, watchdog reset, deadlock and MCU exception can look identical from a single UART/SPI/I2C observer.

For an exact code location, collect target-side evidence through a separate diagnostic channel:

1. Panic / exception console output with PC, LR, SP and backtrace (where supported).
2. Reset cause or watchdog reason.
3. Fault-status registers and fault address (architecture dependent).
4. The exact ELF and linker map from the firmware image that was flashed. Keep its build ID / source revision with the test run.
5. When supported, a core dump and the platform's decoder output.

NEXUS prints `CRASH_SUSPECTED` with the case ID, command tag, latency, heartbeat failures and exact trigger bytes. The ESP32-S3 firmware also has an optional bidirectional target diagnostic UART separate from the fuzz bus. Enable `NEXUS_TARGET_DIAG_UART_ENABLED=1` in `platformio.ini`, select board-safe `NEXUS_TARGET_DIAG_RX_PIN` and `NEXUS_TARGET_DIAG_TX_PIN`, and wire NEXUS TX -> target RX plus target TX -> NEXUS RX through voltage-compatible interfaces. Do not connect push-pull TX outputs together. For per-case coverage synchronization, additionally enable `NEXUS_TARGET_COV_SYNC_ENABLED=1`; NEXUS then sends `NXCOV_BEGIN,<case_id>` and requires `NXCOV_READY,<case_id>` before each bus operation. An instrumented target can use `TargetCoverageSession::poll_begin()` and `emit_after_case()` to return matching per-case coverage. Leave coverage sync disabled when only a passive panic/debug log tap is needed. Panic/debug output on the same target diagnostic channel is also relayed to USB serial with a `TARGET_LOG` prefix. A separate receive-only console can still be captured externally, but it cannot provide NEXUS case-ID synchronization by itself.

## Offline log triage

The bundled parser recognizes common ESP-IDF / Xtensa panic signatures, generic Cortex-M fault snapshots, AddressSanitizer memory errors, and UndefinedBehaviorSanitizer diagnostics. It classifies the evidence, extracts registers and backtrace PCs, optionally resolves source locations against an ELF, and emits mitigation advice. ASan/UBSan logs can identify an exact source line directly when the instrumented build includes symbols; embedded panic logs normally need ELF symbolication.

```bash
pio device monitor -b 115200 | tee nexus-run.log
python3 tools/nexus_triage.py \
  --input nexus-run.log \
  --elf /path/to/exact-target-firmware.elf \
  --addr2line xtensa-esp32s3-elf-addr2line \
  --output crash-report.md
```

For a Cortex-M build use the matching `arm-none-eabi-addr2line` (or supply its full path). A generic ARM `addr2line` binary will not necessarily decode Xtensa addresses, and vice versa. If no ELF / matching symbols are supplied, the report will list raw addresses but cannot produce trustworthy file:line locations.

Extract the build identity and SHA-256 for the exact ELF with:

```bash
python3 tools/nexus_build_info.py --elf /path/to/exact-target.elf --output build-info.json
```

Record the printed `BUILD_ID=<id>` in the panic/capture log. The HTML debugger-style report includes task/core context, CPU register file, PC/backtrace, stack dump, ELF sections/load segments, symbolication, source excerpts (with `--source-root`), disassembly, linker-map references, coverage and remediation. A missing build ID means symbolication is provisional; a mismatch suppresses symbolication/disassembly.

The parser is an offline assistant, not a debugger. It does not infer a definite buffer overflow merely from a `LoadProhibited` or `StoreProhibited` exception. Those exceptions mean an invalid memory access; a bad pointer, out-of-range index, use-after-free, corrupted pointer, or unrelated bus fault may be responsible. Confirm the cause at the symbolicated source line and with a reproducible test.

## ESP32-S3 target firmware (ESP-IDF)

For a target whose firmware is built with ESP-IDF:

- Keep the panic handler configured to print a register dump and backtrace to a dedicated console.
- Use the same build directory / `build/*.elf` that generated the flashed binary.
- Decode an ESP-IDF core dump with the `esp-coredump` tool from the matching ESP-IDF version if core-dump support was enabled in that firmware.
- Preserve the complete serial log from reboot through the panic. The first panic line and the complete backtrace are important.
- Enable heap integrity / poisoning and stack canaries in a diagnostic build. More instrumentation improves detection but changes timing and memory layout; compare against a production-like build too.

For Arduino-ESP32 targets, capture the serial panic/backtrace and use the matching Xtensa toolchain shipped with the exact Arduino-ESP32 platform package. A random ELF or a different firmware build can resolve to wrong lines.

## Cortex-M target firmware

Where the core implements them, preserve the stacked PC/LR/SP plus CFSR, HFSR, MMFAR and BFAR. Decode only valid address registers: MMFAR is valid when `CFSR.MMARVALID` is set; BFAR is valid when `CFSR.BFARVALID` is set. Some cores (for example Cortex-M0+) do not implement the full CFSR fault model; do not report unsupported registers as zero-valued evidence.

A precise bus fault / data access violation can often identify the access address. An imprecise bus fault may identify the exception context but not the exact offending instruction. Exact source mapping still requires the matching ELF.

## Remediation playbook

| Evidence | Likely area to inspect | Defensive controls |
|---|---|---|
| Stack canary / stack smashing | Oversized local arrays, recursion, task stack exhaustion, writes beyond local buffers | Bound lengths before copy, move large buffers to bounded static storage, measure stack high-water marks, retain stack protector / canaries |
| Heap integrity / heap canary | Out-of-bounds write, integer-overflow allocation size, use-after-free, double free | Checked size arithmetic, ownership discipline, heap poisoning in test builds, canaries around parser buffers, reduce dynamic allocation |
| LoadProhibited / StoreProhibited | Null/stale pointer, out-of-range index, malformed length, use-after-free | Validate pointer and every length/index at trust boundaries, checked arithmetic, parser state invariants, boundary regression tests |
| InstrFetchProhibited / IllegalInstruction | Corrupted return address, invalid function pointer, stack overwrite, invalid branch target | Validate dispatch tables, bound writes, audit callback lifetime, retain memory protection and control-flow checks where supported |
| Cortex-M PRECISERR / DACCVIOL | Specific invalid load/store; BFAR/MMFAR may locate address | Inspect the operand at stacked PC, validate region/length/alignment, guard peripheral access and parser-derived offsets |
| Watchdog reset / liveness loss only | Deadlock, long critical section, starvation, power/bus fault, or crash | Capture reset cause, independent heartbeat, task watchdog data, power/current trace, separate bus analyzer |
| Timing anomaly only | Scheduling jitter, bus contention, interrupt load, data-dependent path | Repeat under controlled clock/load, gather distributions, isolate transport timing, do not label as a leak until statistically reproduced |

## Reproduction discipline

1. Stop immediately after a suspected crash; do not continue fuzzing a possibly unstable target.
2. Save the run log, generated corpus, trigger frame, random seed, interface settings, firmware build ID, ELF and map file.
3. Restore the target to a known lab state using the vendor-approved recovery procedure.
4. Replay only the minimized trigger in a current-limited, isolated fixture.
5. Add the trigger as a regression test after the defect is fixed and verify the corrected firmware under the same checks.

NEXUS does not automatically power-cycle, reset, unlock, erase, or reconfigure a target as part of triage.
