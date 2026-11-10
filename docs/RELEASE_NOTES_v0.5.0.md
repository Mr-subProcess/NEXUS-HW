# NEXUS-HW v0.5.0 release notes

## Debugger / forensic reporting

- Added `tools/nexus_debug.py` to create bounded GDB scripts for an already-running OpenOCD/GDB server or an offline GDB-readable core file.
- Added explicit ESP32-S3 JTAG and RP2040 SWD/CMSIS-DAP profiles. ESP32-S3 is not an SWD target.
- Captures all available target registers, threads, full backtraces, frame arguments/locals, PC disassembly and a bounded stack window.
- Optional `--halt` requests a halt. No flash/program/erase/reset or memory-write command is generated. Disconnect run-state behavior remains OpenOCD/adapter dependent.
- Added HTML/JSON report fields for debugger metadata, frame list, task/thread context, registers, source excerpts, ELF sections, symbolication, disassembly, linker map, coverage and remediation guidance.
- Corrected build identity handling: `NEXUS_ELF_BUILD_ID` (host-supplied ELF identity) is separate from device-reported `BUILD_ID`. Only the latter is used for positive target/ELF identity comparison.
- Added signal-aware diagnosis: SIGSEGV, SIGBUS, SIGILL, SIGABRT and SIGFPE receive distinct hypotheses; SIGTRAP and SIGINT are not automatically called crashes.
- Explicit architecture-specific `addr2line` / `objdump` tool requests no longer silently fall back to a host/wrong-architecture tool.

## Fuzzing and analysis workflow

- Checksum-aware crash minimization preserves fixed frame length and recalculates the selected checksum for every candidate.
- Repeated oracle quorum reduces flaky crash classification; the exact crash signature remains the operator's oracle contract.
- Added a unified launcher: `python3 tools/nexus.py {sim,triage,debug,minimize,coverage,build-info,test,version}`.
- Added a reproducible synthetic native-ELF debugger workbench example. It is explicitly not a real target capture.
- Added full test matrix: Release + warnings-as-errors, then separate ASan/UBSan build and CTest.

## Validation boundary

The host-native software is validated by the bundled matrix. The build environment did not include PlatformIO, OpenOCD, architecture-specific embedded GDB toolchains or physical ESP32-S3/Pico boards. Therefore no physical board firmware build/upload or live hardware debug connection is claimed.
