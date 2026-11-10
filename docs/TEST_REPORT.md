# NEXUS-HW v0.7.0 — validation report

Validation performed in the build container on 2026-11-10. This report records
host-native builds, unit/integration tests and synthetic fixtures only. It does
not claim a successful physical ESP32-S3 or RP2040 build, upload, debug session,
or electrical bus test.

## Environment

- OS: Linux x86_64
- CMake: 3.31.6
- Compiler: GCC 14.2.0
- Python: 3.13.5
- Native language mode: ISO C++20 (`CMAKE_CXX_EXTENSIONS=OFF`)

## Native validation matrix

| Matrix | Result |
|---|---:|
| Release build with warnings-as-errors | PASS |
| Release CTest | 17/17 PASS |
| Debug ASan + UBSan build | PASS |
| ASan/UBSan CTest | 17/17 PASS |
| Python `compileall` for tools/tests | PASS |
| 1,500-case host campaign fixture | PASS |
| Offline campaign dashboard generation | PASS |
| Read-only protocol manifest validation/header generation | PASS |
| Clean source staging copy Release configure/build + CTest | 17/17 PASS |
| ZIP CRC + per-file SHA-256 manifest | PASS |

The 17 CTest entries cover the C++ core, crash triage, minimization, coverage,
debugger capture, checksum engine, session normalization, evidence bundle,
campaign dashboard, protocol manifest compiler, dependency preflight, CLI help
and version, simulator smoke, coverage-guided campaign smoke, local fictional
opcode sweep and host corpus optimization.

## v0.7.0-specific functional checks

- Fixed-memory campaign scheduler supports a maximum of 16 corpus seeds and
a 3072-bit feedback namespace. Target instrumentation occupies IDs 0–2047;
protocol-transition feedback occupies IDs 2048–3071.
- Campaign scheduling is deterministic for a fixed seed and host fixture.
It tracks outcome novelty independently from bit coverage and does not treat a
32-bit response fingerprint as a collision-free identity.
- NXCOV1 parser requires canonical field order, exact case ID, exactly 2048
bits and exactly 512 hexadecimal bitmap characters. Malformed numeric fields,
wrong case IDs and malformed bitmap data are rejected.
- Target-sideband session test accepts `NXCOV_BEGIN,<id>`, resets the bitmap,
replies `NXCOV_READY,<id>` and emits a matching NXCOV1 record after dispatch.
Oversized/malformed control lines are rejected.
- ESP32-S3 source uses a single-case producer/consumer feedback handshake. If
coverage synchronization is enabled but the target does not acknowledge the
case ID, the campaign stops before the bus transaction. Missing coverage after
a successful READY acknowledgement falls back to protocol-transition feedback.
- RP2040 runner uses the same fixed-memory scheduler for observed protocol
transitions and response classes. It explicitly reports target binary coverage
as not instrumented in this release.
- Host campaign fixture executed 1,500 cases and generated an offline HTML
campaign dashboard. These data belong to the fictional `DemoTransport`; they
are not coverage claims for a physical or commercial firmware image.
- Protocol manifest compiler accepted the bundled two-command read-only lab
manifest and generated a C++ header. Its safety policy rejects commands not
explicitly classified as `documented_read_only`.

## Hardware-specific items not validated in this environment

The `nexus doctor` preflight found host CMake/C++/Python available. PlatformIO,
OpenOCD and ESP32-S3/RP2040 cross-debug toolchains were not installed.
Consequently:

- ESP32-S3 and RP2040 PlatformIO firmware builds/uploads were not run.
- ESP32-S3 JTAG and the optional bidirectional target coverage sideband were not
  tested on a physical board.
- RP2040/Pico SWD, CMSIS-DAP and the Cortex-M0+ HardFault hook were not compiled
  or tested on physical hardware.
- UART/SPI/I²C voltage levels, pin assignments, bus timing, electrical isolation
  and reset behavior were not tested.
- No customer target firmware ELF, matching MAP file or source tree was
  supplied. Target-specific symbolication and source-line claims depend on the
  exact target build artifacts.

## Diagnostic accuracy boundary

A heartbeat failure proves only that the configured health request did not
receive an acceptable response. It cannot by itself distinguish a firmware
exception from brownout, disconnected wiring, a stuck bus, deadlock, reset or a
powered-off target. Exact instruction/source attribution requires target-side
panic/fault or debugger evidence and the exact matching ELF/MAP/source revision.
The device-reported build identity is kept separate from the supplied ELF build
identity; an ELF's own Build ID is not proof that it matches the running image.

Code coverage is true target coverage only when the target firmware is built
with NEXUS coverage hooks (or a supported target coverage runtime) and reports
its edge data. ESP32-S3 per-case correlation uses the bidirectional diagnostic
sideband: NEXUS sends `NXCOV_BEGIN`, target acknowledges with `NXCOV_READY`, and
the target emits `NXCOV1` after request dispatch. The current RP2040 runner does
not yet implement this sideband. Host response novelty and protocol-transition
coverage are not represented as firmware binary coverage. Hardware timing
measurements are observed transaction latencies, not guaranteed cycle-accurate
side-channel measurements.
