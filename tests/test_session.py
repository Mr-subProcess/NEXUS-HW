import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nexus_session", ROOT / "tools" / "nexus_session.py")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class SessionParserTests(unittest.TestCase):
    def test_parses_major_event_types_and_build_identity(self):
        sample = """NEXUS case=42 tag=00A1 state=1>2 kind=4 us=930 input=AA01
HEALTH case=42 health=3 streak=3 checked=1 crash_suspected=1
CRASH_SUSPECTED,case=42,tag=00A1,latency_us=20000,failed_heartbeats=2,trigger=AA01
TARGET_LOG Guru Meditation Error: Core  0 panic'ed (LoadProhibited)
TARGET_LOG BUILD_ID=0123456789abcdef
NXCOV1,run=42,bits=32,bitmap=00000001000000000000000000000000
DONE cases=42 states=3 edges=2 halted=1
"""
        events, summary = module.normalize(sample)
        self.assertEqual(summary["event_count"], 7)
        self.assertEqual(summary["unique_case_ids"], 1)
        self.assertEqual(summary["crash_suspected_events"], 1)
        self.assertEqual(summary["coverage_records"], 1)
        self.assertEqual(summary["build_ids"], ["0123456789abcdef"])
        self.assertEqual(events[0]["event_type"], "case")
        self.assertEqual(events[2]["fields"]["trigger"], "AA01")

    def test_empty_log_is_valid_empty_session(self):
        events, summary = module.normalize("\n\r\n")
        self.assertEqual(events, [])
        self.assertEqual(summary["event_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
