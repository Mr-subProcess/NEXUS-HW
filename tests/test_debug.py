import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nexus_debug", ROOT / "tools" / "nexus_debug.py")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
TRIAGE_SPEC = importlib.util.spec_from_file_location("nexus_triage_debug", ROOT / "tools" / "nexus_triage.py")
triage = importlib.util.module_from_spec(TRIAGE_SPEC)
sys.modules[TRIAGE_SPEC.name] = triage
TRIAGE_SPEC.loader.exec_module(triage)


class DebugIntegrationTests(unittest.TestCase):
    def test_profile_configs_are_documented_and_safe(self):
        self.assertEqual(module.PROFILES["esp32s3"]["interface"], "JTAG (ESP32-S3 does not support SWD)")
        self.assertIn("board/esp32s3-builtin.cfg", module.PROFILES["esp32s3"]["openocd"])
        self.assertIn("interface/cmsis-dap.cfg", module.PROFILES["rp2040"]["openocd"])
        self.assertIn("target/rp2040.cfg", module.PROFILES["rp2040"]["openocd"])

    def test_live_script_does_not_flash_or_reset(self):
        script = module.build_gdb_script("esp32s3", "localhost:3333", None, True, 64, 32)
        self.assertIn("target extended-remote localhost:3333", script)
        self.assertIn("monitor halt", script)
        self.assertIn("info all-registers", script)
        self.assertIn("thread apply all bt full", script)
        self.assertNotIn("program_esp", script)
        self.assertNotIn("monitor reset", script)
        self.assertNotIn("load", script)

    def test_offline_core_script(self):
        with tempfile.TemporaryDirectory() as temp:
            core = Path(temp) / "core.dump"
            core.write_bytes(b"dummy")
            script = module.build_gdb_script("rp2040", None, core, False, 48, 24)
            self.assertIn("core-file", script)
            self.assertNotIn("target extended-remote", script)
            self.assertIn("x/48wx $sp", script)

    def test_rejects_bad_remote_and_bounds(self):
        with self.assertRaises(ValueError):
            module.validate_remote("localhost:3333\nmonitor reset")
        with self.assertRaises(ValueError):
            module.validate_remote("localhost:99999")
        with self.assertRaises(ValueError):
            module.build_gdb_script("rp2040", "localhost:3333", None, False, 2, 16)

    def test_live_capture_requires_explicit_halt_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            elf = root / "target.elf"
            elf.write_bytes(b"fixture")
            result = subprocess.run([sys.executable, str(ROOT / "tools" / "nexus_debug.py"),
                                     "--profile", "rp2040", "--elf", str(elf),
                                     "--remote", "localhost:3333", "--script", str(root / "x.gdb"),
                                     "--capture", str(root / "x.log")],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires explicit --halt", result.stderr)

    def test_profile_metadata_identifies_platform(self):
        rp = triage.parse_log("NEXUS_DEBUG_CAPTURE,profile=rp2040,arch=Arm Cortex-M0+,mode=remote\n")
        esp = triage.parse_log("NEXUS_DEBUG_CAPTURE,profile=esp32s3,arch=Xtensa LX7,mode=remote\n")
        generic = triage.parse_log("NEXUS_DEBUG_CAPTURE,profile=synthetic,arch=x86_64 fixture,mode=offline-core\n")
        self.assertIn("RP2040", rp.platform)
        self.assertIn("ESP32-S3", esp.platform)
        self.assertIn("x86_64 fixture", generic.platform)

    def test_supplied_elf_identity_is_not_mistaken_for_target_identity(self):
        sample = "NEXUS_ELF_BUILD_ID=0123456789abcdef\nNEXUS_ELF_SHA256=deadbeef\n"
        result = triage.parse_log(sample)
        self.assertEqual(result.build_id, "")
        self.assertTrue(any("supplied_elf_build_id=0123456789abcdef" == item
                            for item in result.debugger_metadata))

    def test_extract_build_metadata_from_native_elf(self):
        compiler = shutil.which("c++") or shutil.which("g++")
        readelf = shutil.which("readelf")
        if not compiler or not readelf:
            self.skipTest("native compiler/readelf unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "fixture.cpp"
            elf = root / "fixture.elf"
            source.write_text("int main(){return 0;}\n", encoding="utf-8")
            subprocess.run([compiler, "-g", "-Wl,--build-id=sha1", str(source), "-o", str(elf)],
                           check=True, capture_output=True)
            build_id, digest = module.extract_build_metadata("rp2040", elf)
            self.assertIsNotNone(build_id)
            self.assertRegex(build_id, r"^[0-9a-f]{40}$")
            self.assertEqual(len(digest), 64)

    def test_gdb_output_parser_extracts_registers_frames_and_stack(self):
        sample = """NEXUS_DEBUG_CAPTURE,profile=rp2040,arch=Arm Cortex-M0+ / RP2040,mode=remote,remote=localhost:3333,halt=1
NEXUS_CAPTURE_MODE=live-remote
NEXUS_TARGET_ACTION=halt-requested; no reset/flash/write requested
r0             0x1                 1
r1             0x20001000          536875008
sp             0x20002000          0x20002000
lr             0x10000121          0x10000121
pc             0x10000234          0x10000234
xpsr           0x61000000          0x61000000
* 1 Thread 1 (Thread 0x20001f00)
#0  0x10000234 in parse_request (buf=0x0) at /work/target/parser.c:77
#1  0x10000120 in main_loop () at /work/target/main.c:120
0x20002000: 0x00000000 0x10000121 0x10000234 0x61000000
Program received signal SIGTRAP, Trace/breakpoint trap.
"""
        result = triage.parse_log(sample)
        self.assertEqual(result.registers.get("PC"), "0x10000234")
        self.assertEqual(result.registers.get("SP"), "0x20002000")
        self.assertTrue(any("parse_request" in frame for frame in result.debugger_frames))
        self.assertTrue(any("parser.c:77" in location for location in result.direct_locations))
        self.assertTrue(result.stack_dump)
        self.assertTrue(result.debugger_metadata)

    def test_fake_gdb_capture_pipeline(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            elf = temp_path / "fixture.elf"
            elf.write_bytes(b"dummy elf placeholder")
            fake_gdb = temp_path / "fake-gdb"
            fake_gdb.write_text(
                "#!/usr/bin/env python3\n"
                "print('pc 0x10000100 0x10000100')\n"
                "print('sp 0x20001000 0x20001000')\n"
                "print('#0 0x10000100 in parse_frame() at /tmp/target.c:42')\n"
                "print('0x20001000: 0x00000000 0x10000010 0x10000100 0x61000000')\n",
                encoding="utf-8",
            )
            fake_gdb.chmod(fake_gdb.stat().st_mode | stat.S_IXUSR)
            script = temp_path / "capture.gdb"
            capture = temp_path / "capture.log"
            generated = module.build_gdb_script("rp2040", "localhost:3333", None, False, 64, 32)
            script.write_text(generated, encoding="utf-8")
            completed = module.run_capture(str(fake_gdb), elf, script, 5.0)
            self.assertEqual(completed.returncode, 0)
            transcript = completed.stdout
            parsed = triage.parse_log(transcript)
            self.assertEqual(parsed.registers.get("PC"), "0x10000100")
            self.assertEqual(parsed.registers.get("SP"), "0x20001000")
            self.assertTrue(parsed.debugger_frames)


if __name__ == "__main__":
    unittest.main(verbosity=2)
