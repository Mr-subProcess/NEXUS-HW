# NEXUS-HW v0.7.0 release notes

## Major additions

- Coverage-guided fixed-memory campaign scheduling for ESP32-S3, RP2040 and
  native host fixtures.
- Separate 2048-bit target instrumentation map and 1024-bit protocol transition
  map; response novelty tracked separately.
- ESP32-S3 single-case producer/consumer feedback handshake.
- Bidirectional target coverage sideband with `NXCOV_BEGIN` / `NXCOV_READY` /
  `NXCOV1` so coverage is tied to the exact fuzz case rather than inferred by
  timing.
- Offline JSONL campaign capture and interactive HTML campaign dashboard.
- JSON protocol manifest compiler that emits C++ corpus/profile source and
  rejects commands not explicitly marked documented read-only.
- Strict NXCOV record parser and target sideband unit tests.

## Engineering hardening

- NXCOV parser validates canonical field ordering, decimal fields, run identity,
  bit count, bitmap width and hexadecimal alphabet.
- Malformed or unacknowledged target coverage synchronization fails closed
  before bus dispatch when the optional sideband mode is enabled.
- Host tests validate the target-sideband handshake without requiring Arduino
  hardware using a mock stream.

## Compatibility and limitations

- ESP32-S3 has optional bidirectional target-coverage sideband support.
- RP2040 uses protocol-transition feedback only in this version and explicitly
  reports that target binary coverage is not instrumented.
- Host simulator campaign results are synthetic and must not be described as
  coverage of a real target firmware.
- Physical firmware builds and electrical tests require PlatformIO, target
  toolchains and the actual boards; they were not run in the release container.
