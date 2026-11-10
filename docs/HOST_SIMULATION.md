# Host simulation and corpus optimization

The native host build runs the same bounded mutator, response classifier, fingerprinting and state graph as the embedded core against an in-process **fictional protocol model**. It is intended to validate NEXUS logic, quickly explore a model, and reduce duplicate response classes before moving an explicitly reviewed seed set to a lab fixture.

Build and run the normal host simulation:

```bash
./scripts/build_native.sh
./build/nexus_sim
```

Run host-side corpus exploration and response-fingerprint minimization:

```bash
./build/nexus_sim --host-optimize 4096 optimized_corpus.hpp
```

The tool:

- begins with the example's documented read-only seed requests;
- generates deterministic, bounded payload mutations (the command prefix and frame length stay fixed);
- executes each case against the local model, never a physical interface;
- computes a model-specific normalized state fingerprint (response class, length and stable status byte in the included example) so echoed payload bytes do not create a false new state for every input;
- records the first input for each new normalized response state;
- writes a C++ `SeedSet` factory and prints each novelty event.

The output header is a **model-optimized candidate corpus**, not proof that a real target behaves the same way. The included normalization intentionally ignores the demo model's echoed payload byte; a real device model must define which response bytes are stable state indicators and which are counters, echoes, timestamps or checksums. Review each frame against the actual target protocol documentation, response profile, checksum rules, electrical setup and written authorization before using it on hardware. The host runner deliberately does not export hidden/unreviewed opcodes or service-unlock sequences.

To use an approved generated corpus in firmware, copy the header under `examples/` (or another include directory), include it in the firmware project, and replace `make_lab_corpus()` with `nexus::generated::make_optimized_corpus()` only after validating it. Keep the liveness request separately configured as an explicit, documented, read-only status query.

## What the host simulator cannot do

It cannot emulate the unknown firmware, silicon errata, real bus timing, electrical faults, analog behavior, internal RAM, watchdog behavior, or real memory corruption of an arbitrary target. A host-side response-state novelty is not a target code-coverage edge. Use a target-specific simulator / virtual board / instrumented firmware when those properties matter. To capture a hardware run from the PlatformIO monitor, use `pio device monitor -b 115200 | tee nexus-run.log`; include the target debug UART stream relayed as `TARGET_LOG` lines.
