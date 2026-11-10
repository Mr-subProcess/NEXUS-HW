# NEXUS-HW v0.6.0 release notes

## Core correctness and resilience

- Validate engine configuration before opening a transport.
- Validate the full seed corpus before any calibration transmission.
- Compare full response bytes when identifying protocol states; fingerprints are not treated as collision-free identifiers.
- Clamp and classify oversized transport responses so malformed lengths cannot cause out-of-bounds processing.
- Use RP2040 `time_us_64()` for long-running monotonic timing.
- Validate custom CRC polynomial/initial/xor values against the selected width.
- Reject coverage edge IDs before narrowing conversion and reject impossible coverage denominators.

## Operator workflow

- `nexus doctor`: dependency and toolchain preflight; no hardware contact.
- `nexus session`: deterministic JSONL normalization of NEXUS, panic, GDB and coverage log lines.
- `nexus bundle`: portable evidence ZIP with SHA-256 artifact manifest and generated JSON/HTML triage output.
- Live GDB capture requires an explicit `--halt` flag; `--dry-run` remains offline.

## Verification

Host-native Release and ASan/UBSan test matrices are run in the build environment. Physical ESP32-S3/RP2040 firmware builds, debug-probe connections and electrical bus tests are not claimed unless separately performed on the corresponding hardware.

## Final validation snapshot (2026-11-10)

- GCC 14.2 / CMake 3.31.6 native C++20 Release build: PASS.
- Release CTest: 14/14 PASS.
- Separate ASan/UBSan Debug CTest: 14/14 PASS.
- Python tool/test syntax compilation: PASS.
- Physical ESP32-S3/RP2040 toolchains and boards were unavailable; see
  `docs/TEST_REPORT.md` for the exact boundary of validation.
