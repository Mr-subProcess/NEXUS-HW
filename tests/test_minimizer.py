import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nexus_minimize", ROOT / "tools" / "nexus_minimize.py")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class MinimizeTests(unittest.TestCase):
    def test_delta_debug_preserves_signature_and_immutable_prefix(self):
        original = b"\xA5\x01noise-left-CRASH_TAG-noise-right"
        def oracle(candidate: bytes) -> bool:
            return candidate.startswith(b"\xA5\x01") and b"CRASH_TAG" in candidate
        reduced, trials = module.ddmin(original, oracle, immutable_prefix=2)
        self.assertTrue(oracle(reduced))
        self.assertEqual(reduced, b"\xA5\x01CRASH_TAG")
        self.assertGreater(trials, 1)

    def test_byte_simplification_preserves_crash(self):
        def oracle(candidate: bytes) -> bool:
            return candidate.startswith(b"\xAA") and candidate[1:] == b"\x00CRASH"
        reduced, trials = module.simplify_bytes(b"\xAA\x7FCRASH", oracle, immutable_prefix=1)
        self.assertEqual(reduced, b"\xAA\x00CRASH")
        self.assertGreater(trials, 0)

    def test_repeated_oracle_quorum_and_checksum_recalculation(self):
        import re
        import tempfile
        import sys
        helper = """import pathlib, sys
data = pathlib.Path(sys.argv[1]).read_bytes()
if len(data) == 3 and data[0] == 0xA5 and data[2] == (data[0] ^ data[1]):
    print('CRASH_CONFIRMED')
else:
    print('NO_CRASH')
"""
        with tempfile.TemporaryDirectory() as temp:
            helper_path = Path(temp) / "oracle.py"
            helper_path.write_text(helper, encoding="utf-8")
            spec = {"algorithm": "xor8", "data_offset": 0, "data_length": 2,
                    "checksum_offset": 2, "byte_order": "big"}
            oracle = module.command_oracle(
                [sys.executable, str(helper_path), "{input}"], re.compile("CRASH_CONFIRMED"),
                2.0, repetitions=3, required_reproductions=2, checksum_spec=spec)
            self.assertTrue(oracle(b"\xA5\x00\x00"))
            self.assertFalse(oracle(b"\x00\x00\x00"))

    def test_baseline_must_reproduce(self):
        with self.assertRaises(ValueError):
            module.ddmin(b"no crash", lambda _: False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
