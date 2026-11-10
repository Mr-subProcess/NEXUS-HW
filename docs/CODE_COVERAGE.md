# Instrumented target code coverage

NEXUS-HW's coverage runtime is a fixed-size bitmap intended to be compiled into a test build of the target firmware (the device under test), not merely into the attacker board.

## Instrumentation contract

1. Assign a stable integer edge ID to each basic block or branch edge you want measured.
2. Insert `NEXUS_COV_HIT(id)` in the corresponding target code path.
3. At a safe snapshot point, serialize with `g_nexus_coverage.format_record(buffer, sizeof(buffer), case_id)`.
4. Capture `NXCOV1` records from the target diagnostic channel and merge them with `tools/nexus_cov.py`.
5. Pass `--total-edges` only when you have an authoritative instrumentation map. The tool will not guess a denominator.

The default bitmap has 2048 IDs. It is fixed-size and uses atomic bit operations, so it does not allocate heap memory in a hot protocol path. IDs outside the configured bitmap are rejected. The coverage snapshot is cumulative until `reset()` is called; call `reset()` between test cases only if you need per-case coverage rather than cumulative coverage.

## What this does and does not measure

- It measures execution of the instrumented firmware blocks/edges.
- It can merge edge sets across fuzz cases and show which case introduced new edges.
- It does not recover coverage from arbitrary closed firmware or from passive UART responses.
- Host simulator novelty is not target firmware coverage.
- For full automatic compiler-level instrumentation, use a target-supported SanitizerCoverage/gcov/trace runtime and export an equivalent edge bitmap; those compiler integrations are not silently assumed by this portable manual-hook implementation.

## Record format

`NXCOV1,run=<case-id>,bits=2048,bitmap=<fixed-width-hex>`

Each 32-bit bitmap word is printed as eight uppercase hexadecimal digits, most-significant nibble first. Word 0 carries IDs 0-31, word 1 carries IDs 32-63, and so on.
