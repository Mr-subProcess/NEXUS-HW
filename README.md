# NEXUS-HW

**Autonomous Embedded Protocol & State Fuzzer — advanced research release v0.7.0**

NEXUS-HW is a bounded, allocation-free C++20 greybox protocol fuzzer for an **explicitly authorized, electrically isolated lab target**. The current prototype learns response fingerprints and state transitions from a user-supplied safe corpus, then mutates only the payload bytes of those approved frames. It records response classes and timing outliers as *anomaly candidates*; it does not claim that a timing deviation proves a side-channel leak.

## Implemented in this package

- Fixed-capacity frames, corpus, state graph, edge table and SPSC work queue; no heap allocation in NEXUS core algorithms or its work queue. Board framework / peripheral drivers may allocate internally.
- Payload-only mutation: bit flip, ±1 arithmetic, interesting byte substitution and bounded block fill.
- Immutable command prefix and unchanged frame length for payload mutation.
- Liveness watchdog: after a configured error streak, send a known-safe read-only heartbeat and classify Alive / Degraded / Unresponsive / LinkFault.
- Crash-suspected journal with a fixed-size reproduction frame and triggering case metadata.
- Physical safe-opcode survey for operator-reviewed, documented read-only frames only.
- Local simulator-only exhaustive 0x00–0xFF opcode census against a fictional target model.
- Response classification: ACK, NACK, device error, timeout, generic data and bus error.
- Greybox response-fingerprint state graph with transition counters.
- Per-response-class online timing baseline and configurable sigma threshold. Results are marked as candidates for manual investigation.
- Hard run budget, default 10 target transactions/second on firmware, and fail-closed halt when the liveness heartbeat also fails.
- ESP32-S3 Arduino firmware with static FreeRTOS task storage: mutation producer pinned to core 1, I/O consumer pinned to core 0.
- Raspberry Pi Pico / RP2040 Arduino firmware target (`rpipico`) with UART/SPI/I²C adapters and a bounded cooperative runner.
- UART, SPI and I²C transport adapters (select one at build time).
- Host-native simulator with deterministic boundary-value exploration and response-state corpus minimization; exports an optimized candidate `SeedSet` header.
- Offline binary-analysis crash triage: complete register extraction, PC/backtrace, ELF build-ID matching, section/load metadata, addr2line symbolication, objdump disassembly, linker-map cross-reference, coverage attachment and mitigation report; emits a self-contained HTML analysis dashboard.
- Instrumented target code coverage via fixed-size 2048-edge bitmap hooks and `NXCOV1` export; per-case new-edge reporting on the host.
- Crash-inducing input minimization via delta-debugging with an operator-supplied replay oracle and immutable command-prefix support.
- Protocol checksum engine: XOR8, SUM8, CRC-8/MAXIM, CRC-16/CCITT-FALSE, CRC-16/MODBUS, CRC-32/IEEE and configurable custom CRC-8/16/32; mutator can recompute a configured checksum field at a protocol-defined offset.
- Optional RP2040 Cortex-M0+ HardFault snapshot hook for target firmware, preserving the stacked register frame in `.noinit` RAM.
- Optional bidirectional ESP32-S3 target diagnostic sideband, separate from the fuzz bus, for per-case target coverage correlation and panic/debug capture.

- GDB/OpenOCD capture helper for a live GDB server or offline core file; captures general/all registers, all thread backtraces, frame arguments/locals, PC disassembly and stack memory, then feeds the transcript into the HTML triage dashboard.
- Explicit debug-symbol PlatformIO build environments for ESP32-S3 and RP2040 (`esp32s3-debug`, `rpipico-debug`).
- Protocol checksum repair in crash minimization (XOR8, SUM8, CRC-8/MAXIM, CRC-16/CCITT-FALSE, CRC-16/MODBUS, CRC-32/IEEE and parameterized custom CRCs), preserving frame length when checksum layout is configured.
- Repeated-oracle quorum for crash minimization to reduce flaky false positives.
- Release + ASan/UBSan validation matrix and warnings-as-errors native build option.

## Safety and scope

Use only devices you own or are explicitly authorized to assess, on a bench fixture that is isolated from production networks and safety-critical equipment. Confirm the target's logic voltage, pinout, ground reference, bus mode, clock polarity/phase, address and electrical limits before wiring. ESP32-S3 GPIO is **not** 5 V tolerant. Do not connect directly to mains, live industrial control wiring, vehicle networks, deployed smart meters or production routers. Use current limiting, level shifting and a hardware disconnect where appropriate.

The firmware ships **disarmed**. To run it on your lab fixture, edit the two build flags in `platformio.ini`:

```ini
-DNEXUS_AUTHORIZED_LAB_TARGET=1
-DNEXUS_ACTIVE_FUZZ_ENABLED=1
```

These flags are an operator acknowledgement, not a technical authorization mechanism. Review the corpus and verify each command is read-only / safe to repeat before enabling. The example corpus is fictional and must not be assumed to match any real device.

Physical firmware does not brute-force undocumented commands or attempt hidden backdoor/service-mode unlock sequences. Its opcode survey is restricted to an operator-reviewed read-only manifest. Exhaustive opcode-byte enumeration is available only against the fictional in-process host simulator (`nexus_sim --opcode-sweep-sim`), never against a physical bus. Do not add privileged, destructive, irreversible or safety-relevant commands to the corpus.

## Repository layout

```text
include/nexus/       portable C++20 core interfaces and algorithms
src/engine.cpp      calibration, transaction, state and timing analysis
src/esp32s3_main.cpp ESP32-S3 Arduino firmware; UART/SPI/I2C selectable
src/rp2040_main.cpp RP2040/Pico Arduino firmware; UART/SPI/I2C selectable
host/native_simulator.cpp host-side fictional target demonstration
examples/           fictional safe corpus and response profile
host/               native-only simulator (not included in firmware build)
tests/              native unit tests
docs/               architecture, wiring, coverage, minimization and result interpretation
tools/              offline crash analyzer, coverage merger and crash minimizer
CMakeLists.txt      native build
platformio.ini      ESP32-S3 firmware build
```

## Build and test on Linux

Requirements: CMake 3.20+, a C++20 compiler.

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
./build/nexus_sim
```

The simulator uses a fictional in-process target. It does not connect to a physical device.

## Build ESP32-S3 firmware

Install PlatformIO Core, then from the repository root:

```bash
pio run -e esp32s3
```

To flash after checking the exact board and port:

```bash
pio run -e esp32s3 -t upload
pio device monitor -b 115200
```

The firmware defaults to UART mode and is disarmed. The ESP32-S3 task stacks and task control blocks are statically reserved; the mutation task is pinned to core 1 and the I/O task to core 0. Configure pins and link mode only after checking the actual ESP32-S3 board schematic and target datasheet.

## Build Raspberry Pi Pico / RP2040 firmware

The `rpipico` environment uses PlatformIO's Pico board target and the Arduino-Pico (Earle Philhower) core:

```bash
pio run -e rpipico
pio run -e rpipico -t upload
pio device monitor -b 115200
```

The Pico runner is cooperative and bounded; it does not claim ESP32's FreeRTOS dual-task model. Review `docs/RP2040.md` for the exact pin map and Cortex-M0+ fault-capture hook. Firmware remains disarmed by default.

### Select bus

In `platformio.ini`, add exactly one build flag:

- UART: `-DNEXUS_LINK_MODE=1` (default)
- SPI: `-DNEXUS_LINK_MODE=2`
- I²C: `-DNEXUS_LINK_MODE=3`

Pin defaults are examples and must be checked for the exact board. I²C uses the fixed `NEXUS_I2C_ADDRESS` (default `0x42`) and configurable fixed read length (`NEXUS_I2C_READ_LENGTH`, default 16); the firmware does not scan the bus. SPI defaults to mode 0, 100 kHz, MSB first. Adjust the adapter for the documented target protocol, never by blind bus probing.

## Corpus format

Each `CorpusEntry` contains:

- `frame`: a known-safe, repeatable request captured from documentation or an approved lab exchange.
- `immutable_prefix`: byte count protected from mutation. Keep opcode, address, length and command selector bytes immutable.
- `minimum_mutable_bytes`: minimum payload length.
- `command_tag`: local label for reports.
- optional `checksum`: protocol checksum range, algorithm, field offset and byte order.

Mutation preserves frame size and immutable command prefix. When `checksum.enabled` is set, the mutator changes only payload bytes and recomputes the configured checksum field. Supported presets include XOR8, SUM8, CRC-8/MAXIM, CRC-16/CCITT-FALSE, CRC-16/MODBUS and CRC-32/IEEE; Custom CRC-8/16/32 accepts explicit polynomial, initial value, xor-out and reflection settings. See the Turkish quick start for configuration.

## Liveness and crash-suspected detection

Configure `EngineConfig::liveness` with a documented read-only status/identity request and its expected response signature. After `max_consecutive_io_errors`, NEXUS-HW runs the heartbeat for the configured number of retries:

- matching response: `Alive`; the preceding fuzz request may simply have been rejected, ignored, or timed out at the protocol layer;
- unexpected non-empty response: `Degraded`; the target still responds;
- all heartbeat attempts time out: `Unresponsive`, emit `CRASH_SUSPECTED`, and halt;
- bus errors during heartbeat: `LinkFault` and halt.

The fixed-size crash journal preserves the triggering frame, case ID, command tag, latency, and failed-heartbeat count. `CRASH_SUSPECTED` is not proof of an MCU crash: a disconnected cable, wedged bus, power loss, or hung target can produce the same observation. Use an independent reset/status pin, current measurement, boot log, or physical observation to confirm. NEXUS-HW does not automatically reset or power-cycle a target.

## Opcode survey scope

The physical `SafeOpcodeSurvey` accepts only manifest entries marked `documented_read_only=true`; it reports Accepted / Rejected / DeviceError / NoResponse / TransportFault and response fingerprints. It refuses unreviewed candidates. The optional firmware build flag is `NEXUS_ENABLE_SAFE_OPCODE_SURVEY=1`.

For offline experimentation, enumerate all 256 opcode-byte values against a fictional local target:

```bash
./build/nexus_sim --opcode-sweep-sim
```

This mode reports the fictional read-only diagnostic/status opcode at `0xD3` and cannot initialize or access a physical UART/SPI/I2C adapter. Physical discovery of undocumented privileged commands or hidden backdoor unlock sequences is intentionally not implemented.

## Interpreting timing results

Calibration repeats the supplied corpus and builds per-response-class online mean and standard deviation. Fuzz cases beyond `anomaly_sigma * (stddev + 1 us)` from the matching response-class baseline are flagged. This is a heuristic alert, not proof of secret-dependent execution or a cryptographic timing leak. Repeat experiments, control temperature / bus load / scheduling jitter, compare identical inputs, and validate with independent instrumentation before drawing conclusions. Microsecond counters do not imply microsecond accuracy on every board or transport.

## Current limitations

- ESP32-S3 and RP2040/Pico firmware source targets are included. PlatformIO toolchains and physical boards are not available in every build environment; compile and validate each board target on the actual toolchain before wiring hardware.
- UART response framing currently uses a 1.5 ms inter-byte idle gap. Change this for the target's documented framing.
- SPI is a fixed-length full-duplex transaction. I²C writes one request and then requests up to 128 response bytes at the configured address. Real devices often require protocol-specific framing; validate and adapt before connecting.
- State identity is response-fingerprint based. It is a greybox approximation, not formal recovery of the target's internal FSM.
- No automatic firmware extraction, JTAG/SWD control, voltage glitching, fault injection, physical unknown-opcode brute-force, persistence testing or exploit chaining is included.
- A heartbeat can identify an unresponsive target but cannot independently prove whether the cause is an MCU crash or a physical/link fault.

## License

MIT License. See `LICENSE`.


## v0.4.0: binary analysis, target coverage, minimization, checksum and RP2040

### Debugger / reverse-engineering style crash report

```bash
python3 tools/nexus_triage.py \
  --input combined-target-log.txt \
  --elf exact-target.elf \
  --map exact-target.map \
  --coverage coverage-report.json \
  --source-root ./target-firmware \
  --format html \
  --output reports/crash-analysis.html
```

Get the build identity from that exact ELF and add its ID to the target capture (where your debug logging permits):

```bash
python3 tools/nexus_build_info.py --elf exact-target.elf --output build-info.json
```

The self-contained HTML report shows registers, fault PC/backtrace, ELF Build ID, architecture and section information, symbolication, disassembly around each code address, linker-map matches, NEXUS trigger frame, coverage summary, evidence limits and remediation suggestions. Use architecture-matched `xtensa-esp32s3-elf-*` or `arm-none-eabi-*` tools. If the target log includes `BUILD_ID=...` and it differs from the ELF Build ID, symbolication/disassembly is suppressed rather than showing potentially false source locations.

### Instrumented target code coverage

`include/nexus/coverage.hpp` provides a fixed-size bitmap. Add `NEXUS_COV_HIT(edge_id)` to stable parser/state-machine basic blocks in a test build of the target firmware, then export the `NXCOV1` line over a debug channel. Merge captures:

```bash
python3 tools/nexus_cov.py --input combined-run.log --total-edges 128 --output coverage-report.json
```

This is actual coverage of instrumented target code, not host-side response diversity. It does not magically recover basic-block coverage from an arbitrary closed firmware. See `docs/CODE_COVERAGE.md`.

### Crash input minimization

```bash
python3 tools/nexus_minimize.py \
  --input crashes/original.bin --output crashes/minimized.bin \
  --immutable-prefix 1 \
  --oracle-command 'python3 my_lab_replay.py --input {input}' \
  --crash-regex 'Guru Meditation|HardFault|AddressSanitizer|CRASH_CONFIRMED' \
  --report crashes/minimized.json
```

The tool uses delta-debugging and validates the final minimized input against the same operator-supplied oracle. It does not itself reset or power-cycle the physical target. See `docs/CRASH_MINIMIZATION.md`.

### RP2040 / Pico and HardFault capture

Build with `pio run -e rpipico`. The optional `examples/target_hooks/rp2040_hardfault_capture.cpp` target hook saves the Cortex-M0+ exception-stacked registers to `.noinit` memory for later reporting. The RP2040 M0+ does not expose the M3/M4 CFSR/BFAR register set, so the hook does not invent those values. See `docs/RP2040.md`.

### Checksum engine

Corpus entries may carry `ChecksumSpec`. After payload mutation, NEXUS recalculates the configured checksum field after each payload mutation; the checksum field may be placed anywhere outside its covered data range. Supported presets and custom CRC polynomial/initial/xor-out/reflection configuration are documented and covered by standard-vector unit tests.

### Optional independent target diagnostic UART

Set `-DNEXUS_TARGET_DIAG_UART_ENABLED=1` in `platformio.ini`, and set `-DNEXUS_TARGET_COV_SYNC_ENABLED=1` only when the target implements the READY handshake. With coverage sync disabled, the same UART can be used as a non-blocking log tap. Choose board-safe `NEXUS_TARGET_DIAG_RX_PIN` and `NEXUS_TARGET_DIAG_TX_PIN`, and wire NEXUS TX -> target RX plus target TX -> NEXUS RX through suitable voltage-level conversion/isolation. This bidirectional sideband is separate from the fuzz bus. NEXUS sends `NXCOV_BEGIN,<case_id>` and waits for `NXCOV_READY,<case_id>` before dispatch; the instrumented target then emits an `NXCOV1` per-case bitmap after parser dispatch. Verify exact GPIOs and voltage levels before connecting.


## GDB / OpenOCD live and offline debugging (v0.5.0)

Build a debug-symbol target image and preserve its exact ELF/MAP/source revision:

```bash
pio run -e esp32s3-debug
# or
pio run -e rpipico-debug
```

Start OpenOCD separately, using the correct debug interface:

```bash
# ESP32-S3: JTAG (not SWD), built-in USB-JTAG profile
openocd -f board/esp32s3-builtin.cfg

# RP2040: SWD through CMSIS-DAP / Raspberry Pi Debug Probe
openocd -f interface/cmsis-dap.cfg -f target/rp2040.cfg
```

Attach and produce a debugger-style HTML report (the `--halt` flag explicitly
requests a target halt; no flash, erase, reset, or memory-write command is sent):

```bash
python3 tools/nexus_debug.py --profile esp32s3 \
  --elf .pio/build/esp32s3-debug/firmware.elf \
  --gdb xtensa-esp32s3-elf-gdb --remote localhost:3333 --halt \
  --capture captures/live-gdb.log --report reports/live-debug.html \
  --map .pio/build/esp32s3-debug/firmware.map --source-root ./target-firmware \
  --coverage reports/coverage-report.json
```

For an offline core file, replace `--remote localhost:3333 --halt` with
`--core captures/core.dump`. Full workflow, adapter distinction, limitations
and RP2040/ESP32-S3 examples: `docs/DEBUGGER_INTEGRATION.md`.

## Checksum-aware crash minimization

For checksummed fixed-layout frames, give `nexus_minimize.py` a JSON checksum
layout. It recomputes the checksum for every oracle candidate and preserves
frame length; the command oracle can use a repetition quorum:

```bash
python3 tools/nexus_minimize.py \
  --input crashes/original.bin --output crashes/minimized.bin \
  --oracle-command 'python3 replay_fixture.py --input {input}' \
  --checksum-spec examples/protocols/demo-crc16.json \
  --immutable-prefix 1 --repetitions 3 --required-reproductions 2 \
  --report crashes/minimized.json
```

Checksum repair is only correct when the supplied offsets, range, byte order
and algorithm match the actual protocol frame. With a checksum spec, NEXUS
preserves frame length because fixed offsets may otherwise move.

## Native validation matrix

```bash
./scripts/test_matrix.sh
```

This builds with warnings-as-errors in Release mode, runs all CTest cases,
then builds and tests an ASan/UBSan configuration. Hardware firmware builds
remain separate and require the vendor toolchains / physical probes.

## Unified command launcher and debugger workbench example

A small command launcher keeps the separate analysis tools easy to invoke:

```bash
python3 tools/nexus.py version
python3 tools/nexus.py sim --host-optimize 4096 optimized_corpus.hpp
python3 tools/nexus.py triage --input captures/combined.log --elf build/firmware.elf --format html --output reports/crash.html
python3 tools/nexus.py debug --profile rp2040 --elf build/firmware.elf --remote localhost:3333 --dry-run
python3 tools/nexus.py minimize --help
python3 tools/nexus.py test
```

Open `examples/reports/debugger-workbench-demo.html` to inspect the debugger-style HTML workbench. Its source/ELF/log inputs are reproducible with `examples/debugger_fixture/build_demo.sh`; all capture events are synthetic and no target is connected or faulted.


## v0.6.0 — engineering hardening and forensic workflow

This release adds preflight validation and evidence-management tooling on top of
v0.5.0:

- Core configuration validation rejects impossible timeouts, unbounded case
  budgets, invalid timing thresholds, and incomplete liveness signatures before
  opening the transport.
- The complete seed corpus is validated before the first calibration frame is
  transmitted; invalid later entries cannot cause partial target exercise.
- State graph identity now checks the full observable response bytes in
  addition to the 32-bit fingerprint, avoiding accidental state merging on a
  hash collision.
- Oversized UART/transport responses are classified explicitly rather than
  silently truncated and parsed as valid frames.
- RP2040 uses the SDK's 64-bit monotonic `time_us_64()` clock to avoid the
  approximately 71-minute wraparound of a 32-bit microsecond counter.
- Added `nexus doctor` for host/cross-toolchain readiness, `nexus session` for
  normalization of combined serial/debug logs to JSONL, and `nexus bundle` for
  a hash-manifested offline triage evidence ZIP.
- Live GDB capture now requires explicit `--halt` acknowledgement; dry-run
  script generation remains non-contacting.
- Coverage macro rejects edge IDs before narrowing conversion; coverage
  percentage cannot exceed declared bitmap capacity. Custom CRC parameters are
  width-validated.

### Unified commands

```bash
python3 tools/nexus.py doctor
python3 tools/nexus.py sim --host-optimize 4096 optimized_corpus.hpp
python3 tools/nexus.py session --input captures/combined.log \
  --output reports/session.jsonl --summary reports/session-summary.json
python3 tools/nexus.py triage --input captures/combined.log --elf target.elf \
  --map target.map --format html --output reports/crash.html
python3 tools/nexus.py bundle --capture captures/combined.log --elf target.elf \
  --map target.map --coverage reports/coverage-report.json \
  --minimized-input crashes/minimized.bin --output reports/case-evidence.zip
python3 tools/nexus.py test
```

The evidence bundle copies only explicitly supplied artifacts, records SHA-256
hashes, and includes JSON + HTML triage views. It does not include full source
repositories; provide `--source-root` only to let the analyzer display local
source excerpts. Review sensitive ELF/log contents before sharing the ZIP.

## v0.7.0 — feedback-guided campaigns and target coverage correlation

v0.7.0 adds a fixed-memory coverage-guided campaign scheduler on top of the
reverse-engineering and forensic workbench:

- Up to 16 bounded seeds, deterministic weighted scheduling and fixed-memory
  response novelty tracking.
- A 3072-bit feedback namespace: target-instrumented binary edges occupy IDs
  0–2047; observable protocol state transitions occupy IDs 2048–3071.
- ESP32-S3 producer/consumer feedback handshake: the next seed is selected only
  after the current target response and any matching target coverage record are
  processed.
- Bidirectional target diagnostic sideband. NEXUS sends
  `NXCOV_BEGIN,<case_id>` before each case; instrumented target firmware resets
  its per-case bitmap and emits `NXCOV1` using the same case ID after dispatch.
- RP2040 uses the same bounded scheduler for protocol-transition feedback and
  response novelty; this release does not claim Pico target binary coverage.
- JSONL campaign capture, offline interactive HTML dashboard and a validated
  JSON read-only protocol manifest compiler.

Run a local fictional campaign and create its dashboard:

```bash
./scripts/build_native.sh
python3 tools/nexus.py campaign 2500 1337 examples/reports/host-campaign-demo.jsonl
python3 tools/nexus.py dashboard --input examples/reports/host-campaign-demo.jsonl \
  --output examples/reports/host-campaign-dashboard.html
```

The host fixture is fictional and its feedback is not physical firmware code
coverage. True target coverage requires instrumentation in the target firmware
and case-ID correlation through the independent diagnostic UART. See
`docs/CAMPAIGN_ENGINE.md`, `docs/PROTOCOL_MANIFESTS.md`, and
`examples/instrumented_target/coverage_example.cpp`.

