# Serial output format

The ESP32 firmware emits line-oriented records at 115200 baud.

- `NEXUS case=...` is one executed fuzz case. `kind` maps to `ResponseKind` (0 ACK, 1 NACK, 2 device error, 3 timeout, 4 generic data, 5 bus error).
- `timing_candidate=1` means the sample exceeded the configured statistical threshold for its response class. It is not a confirmed side-channel.
- `STATE,id,fingerprint,kind,visits` describes an observed response-fingerprint state.
- `EDGE,from,to,command_tag,outcome,traversals` describes a transition observed after a tagged corpus command.
- `TIMING,kind,count,mean_us,min_us,max_us` gives calibration statistics for one response class.

The state graph and timing summaries are bounded in RAM. The firmware does not currently persist them to flash or an SD card; capture the serial output on the host for archival.

- `HEALTH case=...` reports the liveness result after the configured consecutive-error threshold: 0 Unknown, 1 Alive, 2 Suspect, 3 Degraded, 4 Unresponsive, 5 LinkFault.
- `CRASH_SUSPECTED,...,trigger=<hex>` preserves the input frame associated with the first unresponsive-heartbeat event in the current ring-buffer slot. It is a suspected crash/unresponsive event, not proof of an MCU crash.
- `HEALTH_SUMMARY,...` reports final health, crash-suspected count, and link-fault count.
- `SAFE_OPCODE,...` reports a physical survey observation from the reviewed read-only manifest: 0 Accepted, 1 Rejected, 2 DeviceError, 3 NoResponse, 4 TransportFault, 5 Invalid.
- `SIM_OPCODE,...` is emitted only by `nexus_sim --opcode-sweep-sim`; it enumerates all 256 opcode bytes against a fictional in-process model and never accesses a physical bus.

- `DIAG_REQUIRED` indicates that NEXUS detected loss of liveness and needs target-side panic/debug output, reset cause, and matching ELF for exact localization.
- `TARGET_DIAG_UART enabled ...` announces the optional independent bidirectional target diagnostic/coverage sideband.
- `TARGET_LOG ...` relays a newline-terminated line received from the target's separate debug UART. These lines can be combined with the NEXUS run log and passed to `tools/nexus_triage.py`.
- `CRASH_SUSPECTED,case=...,tag=...,latency_us=...,failed_heartbeats=...,trigger=<hex>` includes the reproduction input. It still does not imply the PC/source line is known.


## Response classification extension (v0.6.0)

`ResponseKind::OversizedResponse` means the transport returned more than the
fixed 128-byte frame capacity. The transport layer preserves only the bounded
prefix and marks the event as oversized; downstream code must not interpret it
as a valid complete protocol response. This differs from `BusError` and
`Timeout`.

## Session JSONL schema

`tools/nexus_session.py` emits one JSON object per non-empty source line:

- `schema`: `nexus.session.v1`
- `sequence`: one-based event sequence
- `source_line`: original log line number
- `event_type`: normalized event classification
- `fields`: key/value fields parsed without changing their textual values
- `raw`: the original line, retained for auditability

The companion session summary counts event classes, unique case IDs, crash
suspicions, coverage records and observed build IDs. It does not infer a crash
root cause from a missing line or timeout.
