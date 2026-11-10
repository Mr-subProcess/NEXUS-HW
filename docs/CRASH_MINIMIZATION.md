# Crash-inducing input minimization

`tools/nexus_minimize.py` implements deterministic delta-debugging over a binary frame. It removes chunks while repeatedly asking an operator-supplied oracle whether the same crash signature remains reproducible.

The oracle must:
- replay only against an owned or explicitly authorized isolated lab target;
- apply the correct safe power/reset/restore procedure between attempts;
- impose appropriate transaction-rate and attempt limits;
- emit a stable signature for the fault class being minimized;
- distinguish a confirmed panic/fault dump from a mere transport timeout.

The minimizer itself does not reset, unlock, erase, reconfigure, or power-cycle a device. It executes a command without a shell and substitutes `{input}` with a temporary file containing the candidate bytes. `--immutable-prefix` preserves opcode/address/framing bytes that must not be deleted.

After chunk deletion, it also tries common boundary substitutions (`00`, `01`, `7F`, `80`, `FF`) on retained mutable bytes. The output includes the reduced bytes, original/reduced lengths, number of oracle trials, and a final reproduction check. A regular-expression match is only as reliable as the oracle's logging contract; use a specific panic class and compare target PC/fault class if you need root-cause equivalence.
