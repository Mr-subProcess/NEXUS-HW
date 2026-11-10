# NEXUS-HW campaign engine (v0.7.0)

NEXUS-HW v0.7 introduces a fixed-memory, feedback-guided seed scheduler. The
campaign engine combines three feedback sources without conflating them:

1. **Target binary coverage** — the 2048-bit `NXCOV1` map emitted by an
   instrumented target firmware build.
2. **Protocol transition coverage** — observed `state_before -> state_after`
   transitions in the NEXUS response-state graph. These occupy IDs 2048–3071.
3. **Response novelty** — a per-command-tag response-class table (ACK, NACK,
   device error, timeout, data, bus error, oversized response).

The scheduler uses a deterministic weighted power schedule, a fixed-size seed
corpus, and no heap allocation. Seed admissions require new target/protocol
coverage, a new command response class, or a confirmed crash event supplied by
a caller. A 32-bit response fingerprint is never used as a collision-free key.

## Host fixture campaign

```bash
./scripts/build_native.sh
python3 tools/nexus.py campaign 5000 1337 reports/campaign.jsonl
python3 tools/nexus.py dashboard --input reports/campaign.jsonl \
  --output reports/campaign.html
```

The bundled `DemoTransport` is a fictional deterministic model. Its feedback
edges demonstrate scheduler behavior only; they are not coverage of a physical
or commercial firmware image. The campaign JSONL stores each case's input,
response, response class, latency, feedback edge set, novelty, and corpus size.

## ESP32-S3 live feedback loop

The ESP32-S3 producer and consumer tasks use a single-case handshake:

1. Core 1 selects a seed from the current scheduler corpus and generates one
   payload mutation.
2. When `NEXUS_TARGET_COV_SYNC_ENABLED=1`, Core 0 sends
   `NXCOV_BEGIN,<case_id>` over the independent sideband UART.
3. The target's `TargetCoverageSession::poll_begin()` resets its per-case
   bitmap, stores the ID and replies `NXCOV_READY,<case_id>`. If coverage sync
   is enabled but this exact acknowledgement is not received inside the
   configured sync window, NEXUS stops before sending the fuzz frame.
4. Core 0 executes the frame through the configured bus transport.
5. When coverage sync is enabled, the target emits `NXCOV1` after dispatch.
   NEXUS accepts it only when its `run` field matches the current case ID,
   `bits` is exactly 2048 and the bitmap is exactly 512 valid hexadecimal
   characters. With sync disabled, the diagnostic UART can remain a
   non-blocking log tap and protocol-transition feedback is used.
6. The merged target + protocol feedback is returned to Core 1. Only then is
   the next seed selected.

The target instrumentation map occupies IDs 0–2047. The transition graph is
mapped to IDs 2048–3071. This namespace split prevents a protocol transition
from being reported as a target firmware basic block.

The optional target diagnostic UART is independent of the fuzz bus. Set
`NEXUS_TARGET_DIAG_UART_ENABLED=1` to capture logs. Set the separate
`NEXUS_TARGET_COV_SYNC_ENABLED=1` flag to require the bidirectional per-case
coverage handshake; leave it disabled for a non-blocking panic/debug log tap. NEXUS sends `NXCOV_BEGIN,<case_id>` before the bus transaction. The target
firmware's `TargetCoverageSession::poll_begin()` accepts that command, resets the
per-case bitmap, stores the ID, and replies `NXCOV_READY,<case_id>`. NEXUS
requires that exact acknowledgement before dispatching the fuzz frame; a missing
READY stops the campaign before bus I/O. After the target parser/dispatcher
finishes processing the request, `emit_after_case()` sends one `NXCOV1` line
with the same ID. The NEXUS receiver accepts only an exact case ID, 2048-bit
map and 512-hex-character bitmap. Wire NEXUS TX -> target RX and target TX ->
NEXUS RX through voltage-compatible interfaces; do not connect push-pull TX
pins together. If READY succeeds but the coverage record is missing/late, the
case remains valid and the scheduler falls back to protocol-transition feedback
with `target_cov=0`. The target must be modified and instrumented; a receive-only
panic log alone cannot create this correlation.

## RP2040/Pico feedback

The RP2040 uses the same scheduler in its cooperative single-core loop. It
currently feeds observed protocol-transition IDs and response classes into
the scheduler. The provided Pico runner does not claim target binary coverage;
that remains unavailable unless a target-specific diagnostic channel or host
coverage importer is connected.

## Scheduling and limits

- Maximum embedded corpus size: 16 entries (same bound as `SeedSet`).
- Feedback map: 3072 bits (2048 target instrumentation IDs + 1024 protocol
  transition IDs).
- Fixed-memory scheduler and deterministic xorshift selection.
- Existing frame size, immutable-prefix, checksum and operator-approved corpus
  constraints are retained.
- Default physical target transaction interval remains 100 ms (10/s), with a
  fixed case budget and heartbeat-based fail-closed stopping.
- No automatic target reset, power cycling, firmware flashing or destructive
  opcode discovery is performed by the campaign scheduler.

The scheduler's `crash_confirmed` input is a hook for a trusted external crash
oracle. An ordinary timeout or heartbeat failure must remain `Crash Suspected`
unless independent panic/fault evidence confirms the crash.
