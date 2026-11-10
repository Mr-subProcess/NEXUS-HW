import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLER = ROOT / "tools" / "nexus_bundle.py"


class EvidenceBundleTests(unittest.TestCase):
    def test_creates_hash_manifested_offline_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture = root / "capture.log"
            capture.write_text(
                "NEXUS case=7 tag=0001 state=0>1 kind=4 us=100 input=AA\n"
                "CRASH_SUSPECTED,case=7,tag=0001,latency_us=100,failed_heartbeats=2,trigger=AA\n"
                "Guru Meditation Error: Core  0 panic'ed (LoadProhibited)\n"
                "PC: 0x40001000\nEXCVADDR: 0x00000004\n",
                encoding="utf-8",
            )
            trigger = root / "trigger.bin"
            trigger.write_bytes(b"\xAA\x00\x01")
            output = root / "bundle.zip"
            run = subprocess.run([sys.executable, str(BUNDLER), "--capture", str(capture),
                                  "--minimized-input", str(trigger), "--output", str(output)],
                                 capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(output.is_file())
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("analysis/triage.json", names)
                self.assertIn("analysis/triage.html", names)
                self.assertIn("artifacts/capture.log", names)
                self.assertIn("artifacts/minimized-trigger.bin", names)
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["schema"], "nexus.evidence-bundle.v1")
                self.assertEqual(manifest["artifacts"][0]["sha256"].__len__(), 64)

    def test_rejects_symlink_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            real = root / "real.log"
            real.write_text("capture", encoding="utf-8")
            link = root / "link.log"
            link.symlink_to(real)
            output = root / "bundle.zip"
            run = subprocess.run([sys.executable, str(BUNDLER), "--capture", str(link),
                                  "--output", str(output)], capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 2)
            self.assertIn("non-symlink", run.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
