# GDB / OpenOCD / SWD-JTAG debugger integration

NEXUS-HW v0.5.0 can capture target debug state from either a live GDB server or
an offline core dump. This integration is intentionally diagnostic-only:
NEXUS does not flash, erase, program, reset, or write target memory. A live
capture may halt the MCU only when `--halt` is explicitly supplied.

## Hardware interface distinction

- **ESP32-S3:** JTAG. The chip does not support SWD. With its built-in USB-JTAG,
  Espressif documents `openocd -f board/esp32s3-builtin.cfg` and the
  `xtensa-esp32s3-elf-gdb` debugger. External adapter profiles must match the
  actual adapter/board wiring.
- **RP2040 / Pico:** SWD. The Raspberry Pi Debug Probe is CMSIS-DAP compatible
  and works with OpenOCD. A typical OpenOCD server command is
  `openocd -f interface/cmsis-dap.cfg -f target/rp2040.cfg`; use
  `arm-none-eabi-gdb` or `gdb-multiarch`.

Check the official references before choosing adapter configurations:

- Espressif ESP32-S3 JTAG guide:
  https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/jtag-debugging/
- Raspberry Pi Debug Probe:
  https://www.raspberrypi.com/documentation/microcontrollers/debug-probe.html
- OpenOCD GDB remote connection:
  https://openocd.org/doc-release/html/GDB-and-OpenOCD.html

## 1. Build a debug-symbol firmware

```bash
pio run -e esp32s3-debug
# or
pio run -e rpipico-debug
```

Keep the generated `.elf`, `.map`, build ID and source revision associated
with the exact image flashed to the test target. The debug environment does
not enable active fuzzing; the two authorization flags remain `0` by default.

## 2. Start OpenOCD separately

ESP32-S3 built-in USB-JTAG:

```bash
openocd -f board/esp32s3-builtin.cfg
```

RP2040 with Raspberry Pi Debug Probe / CMSIS-DAP:

```bash
openocd -f interface/cmsis-dap.cfg -f target/rp2040.cfg
```

The server normally exposes its GDB endpoint on TCP port 3333. Adapter-specific
commands and port settings are installation-dependent. Do not run OpenOCD as
root unless your OS permissions require it; prefer the correct udev/device
permissions.

## 3. Capture a live debugger snapshot

ESP32-S3:

```bash
python3 tools/nexus_debug.py \\
  --profile esp32s3 \\
  --elf .pio/build/esp32s3-debug/firmware.elf \\
  --gdb xtensa-esp32s3-elf-gdb \\
  --remote localhost:3333 --halt \\
  --capture captures/esp32s3-gdb.log \\
  --report reports/esp32s3-debug.html \\
  --map .pio/build/esp32s3-debug/firmware.map \\
  --source-root ./target-firmware
```

RP2040:

```bash
python3 tools/nexus_debug.py \\
  --profile rp2040 \\
  --elf .pio/build/rpipico-debug/firmware.elf \\
  --gdb arm-none-eabi-gdb \\
  --remote localhost:3333 --halt \\
  --capture captures/rp2040-gdb.log \\
  --report reports/rp2040-debug.html \\
  --map .pio/build/rpipico-debug/firmware.map \\
  --source-root ./target-firmware
```

`--halt` is explicit because the GDB capture requires a stable register/memory
snapshot and stopping a live MCU changes its execution state. The helper does
not issue flash/program/erase/reset or memory-write commands; it does not issue
an explicit GDB continue either. The effect of disconnect/detach on the target's
run state remains adapter/OpenOCD-configuration dependent and must be verified.
Only use this on
your authorized, isolated lab target. Omitting `--halt` avoids the explicit
OpenOCD `monitor halt` request, but connecting GDB may itself stop a target
according to the server/target configuration; verify your adapter's behavior.

`--dry-run` prints the exact GDB/OpenOCD command profile and writes the GDB
script without contacting hardware:

```bash
python3 tools/nexus_debug.py --profile rp2040 \\
  --elf build/firmware.elf --remote localhost:3333 --dry-run
```

## 4. Offline core dump analysis

No debug probe is needed when a target runtime has produced a core file that
GDB can read:

```bash
python3 tools/nexus_debug.py \\
  --profile rp2040 --elf build/firmware.elf --core captures/core.dump \\
  --gdb arm-none-eabi-gdb --capture captures/core-gdb.log \\
  --report reports/core-analysis.html --source-root ./target-firmware
```

The core format must be supported by the selected GDB target toolchain. A
textual panic log is not a core dump; use `tools/nexus_triage.py` for text logs.

## 5. Forensic report contents

The capture transcript and HTML report include, when the target/debug server
provides them:

- General-purpose and architecture-specific CPU register files.
- Current PC, stack pointer, link/return address and fault registers.
- All available threads/tasks and `thread apply all bt full` stack traces.
- Frame arguments and local variables when debug info and frame state allow.
- Instructions at the current PC and a bounded stack-memory window.
- ELF sections, loadable segments, GNU Build ID, symbols, source line context
  and linker-map matches.
- NEXUS case ID / command tag / trigger frame correlation when the serial log
  is combined with target panic output, plus optional merged target coverage.

A register may be unavailable on a given core or GDB target description. The
report records missing evidence rather than synthesizing values. Optimized
firmware can omit locals or make stack unwinding incomplete; use `-Og -g3`,
frame pointers and the exact same ELF/source revision for diagnostic builds.

## 6. Combine debugger, target and NEXUS logs

Capture NEXUS serial output and the target debug UART on the same host session
where possible. Merge them into a timestamped text file without removing
`BUILD_ID`, `CRASH_SUSPECTED`, `TARGET_LOG`, or `NXCOV1` records, then run:

The capture header stores the supplied ELF's identity as `NEXUS_ELF_BUILD_ID`.
A separate target-reported `BUILD_ID` is required to prove that the analyzed ELF
matches the firmware actually running on the device. If the target build ID is
absent, the report marks identity as unverified; it never substitutes the
host-supplied ELF's own ID for target evidence.

```bash
python3 tools/nexus_triage.py \\
  --input captures/combined.log \\
  --elf build/firmware.elf --map build/firmware.map \\
  --coverage reports/coverage-report.json \\
  --source-root ./target-firmware \\
  --format html --output reports/full-crash-analysis.html
```

The GDB transcript is also accepted as input directly. An externally captured
panic snapshot is often preferable after a crash because a JTAG attach can be
impossible if the MCU, clock tree, power rail or debug port is no longer alive.

## Limitations

- This is a GDB/OpenOCD *client integration*, not a bundled debugger or probe.
  Install the vendor-supported OpenOCD and architecture-matched GDB toolchain.
- NEXUS cannot recover register state from a powered-off or physically damaged
  target. Use retained fault snapshots, panic UART, reset-cause logging or a
  core dump where available.
- ESP32-S3 uses JTAG, while RP2040 uses SWD. They are not interchangeable.
- The target must be built with usable debug information. Source mapping is
  only as trustworthy as the ELF/build ID/source revision match.
- The script does not issue flash/program/erase/reset commands. OpenOCD itself
  has powerful commands; use only reviewed configuration files and commands.
