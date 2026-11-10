# Architecture and data flow

```text
        operator-approved corpus + protocol response profile
                              |
                              v
                    fixed-size Mutator (core 1)
                  prefix preserved; payload only
                              |
                       bounded SPSC queue
                              |
                              v
                    transport + Engine (core 0)
                       UART / SPI / I2C
                              |
                  response class + fingerprint
                         /             \
                        v               v
                state/edge graph    timing baseline
                        \               /
                         v             v
                     bounded telemetry output
```

## Core invariants

1. Frame lengths are not mutated.
2. Bytes before `immutable_prefix` never change.
3. Only command frames already present in the operator corpus can be emitted.
4. The engine refuses to start unless both authorization and active-test configuration flags are true.
5. Firmware uses a bounded test budget and at most 10 exchanges per second by default.
6. Storage is fixed-capacity; a full graph increments a dropped-record counter rather than allocating memory.

## State model

The engine maps each observed `(response kind, response bytes, response length)` to a state node. A 32-bit fingerprint is retained for display/fast prefiltering, but full bytes are compared before states are merged, so a hash collision does not collapse distinct states. An edge records `(previous state, next state, corpus command tag, response kind)`. This yields an observed protocol response graph. It cannot see hidden internal states that do not change externally observable responses.

## Timing model

Calibration measures known-safe baseline corpus exchanges. Welford online statistics are held per response class. A later sample is flagged only when that response class has at least four baseline samples and the absolute deviation exceeds the configured sigma threshold. The alert is named `timing_anomaly_candidate` to avoid overclaiming.

## Liveness and failure classification

A run of transport timeouts is not automatically called a crash. At the configured threshold, the engine sends a known-safe read-only heartbeat. A matching signature means the target is alive; an unexpected non-empty response means it is degraded but responsive; repeated heartbeat timeouts yield `Unresponsive` and a `CRASH_SUSPECTED` record; bus failures yield `LinkFault`. The engine does not reset or power-cycle the target. Without an independent status/reset/power channel, a crash cannot be conclusively distinguished from a wiring or bus fault.

## Opcode discovery boundaries

The physical opcode survey accepts only an operator-reviewed manifest whose entries are explicitly marked documented read-only. It does not brute-force unknown hardware commands or hidden backdoor unlock sequences. The only exhaustive byte-range sweep is a local simulator mode (`nexus_sim --opcode-sweep-sim`) against a fictional read-only protocol model.


## Preflight and evidence lifecycle (v0.6.0)

- `Engine::begin()` validates bounds and liveness configuration before opening
  a bus transport. `Engine::calibrate()` validates every corpus entry before
  transmitting the first calibration frame.
- A target response exceeding the fixed frame capacity is reported as
  `OversizedResponse`, not silently accepted as a complete frame.
- `tools/nexus_session.py` normalizes raw serial/debug logs into JSONL events
  while preserving the source line and original text.
- `tools/nexus_bundle.py` creates a portable evidence archive with SHA-256
  hashes for explicitly supplied artifacts and generated triage outputs.
- `tools/nexus_doctor.py` checks build/debug dependencies without contacting
  hardware. Missing cross-toolchains do not prevent host-native simulation.


## Feedback-guided campaign loop (v0.7.0)

```text
bounded seed corpus -> weighted scheduler -> payload mutator
                                      |
                              NXCOV_BEGIN(case_id)
                                      |
                         NXCOV_READY(case_id) ack
                                      |
                         UART / SPI / I2C transport
                                      |
              target parser/state machine + optional hooks
                                      |
                         NXCOV1(case_id, bitmap)
                                      |
                 merge target edges + protocol transitions
                                      |
                     response novelty / seed admission
                                      +------> next seed
```

The case-ID handshake is an out-of-band diagnostic protocol and does not alter
the target's fuzz request frame. When enabled on ESP32-S3, the exact READY
acknowledgement is required before a case is dispatched. The per-case coverage
record is optional after dispatch; if absent, protocol-transition feedback is
still available and is not mislabeled as target binary coverage. RP2040 currently
uses the protocol-transition portion only.
