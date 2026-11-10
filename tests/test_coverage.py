import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nexus_cov", ROOT / "tools" / "nexus_cov.py")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class CoverageTests(unittest.TestCase):
    def test_merge_and_new_edge_counts(self):
        text = """NXCOV1,run=1,bits=32,bitmap=00000009
NXCOV1,run=2,bits=32,bitmap=0000000B
"""
        records = module.parse_records(text)
        report = module.summarize(records, total_edges=10)
        self.assertEqual(report["unique_edges_found"], 3)
        self.assertEqual(report["coverage_percent"], 30.0)
        self.assertEqual(report["runs"][0]["new_edges"], 2)
        self.assertEqual(report["runs"][1]["new_edges"], 1)
        self.assertEqual(report["new_edge_ids"], [0, 1, 3])

    def test_rejects_invalid_bitmap(self):
        with self.assertRaises(ValueError):
            module.parse_records("NXCOV1,run=1,bits=32,bitmap=00")

    def test_rejects_total_edges_beyond_bitmap_capacity(self):
        records = module.parse_records("NXCOV1,run=1,bits=32,bitmap=00000001")
        with self.assertRaises(ValueError):
            module.summarize(records, total_edges=33)


if __name__ == "__main__":
    unittest.main(verbosity=2)
