import importlib.util
import json
import unittest
import subprocess
import tempfile
import shutil
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nexus_triage", ROOT / "tools" / "nexus_triage.py")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class TriageTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / "examples" / "logs" / name).read_text(encoding="utf-8")

    def test_stack_canary(self):
        report = module.parse_log(self.read("esp32s3_stack_canary.log"))
        self.assertEqual(report.fault_class, "stack_overflow_or_stack_buffer_overwrite")
        self.assertEqual(report.confidence, "high")
        self.assertEqual(report.addresses[0], "0x42001234")
        self.assertTrue(any("stack" in x.lower() for x in report.recommendations))

    def test_load_prohibited(self):
        report = module.parse_log(self.read("esp32s3_loadprohibited.log"))
        self.assertEqual(report.fault_class, "invalid_memory_access")
        self.assertIn("EXCVADDR", report.registers)
        self.assertTrue(report.addresses)

    def test_cortexm_cfsr(self):
        report = module.parse_log(self.read("cortexm_precise_busfault.log"))
        self.assertEqual(report.platform, "ARM Cortex-M fault snapshot")
        self.assertIn("BFAR contains a valid fault address (BFARVALID)", report.evidence)
        self.assertTrue(any("precise data bus error" in x.lower() for x in report.evidence))
        self.assertEqual(report.fault_class, "cortex_m_fault")
        self.assertEqual(report.confidence, "high")

    def test_timeout_is_not_exact_crash(self):
        report = module.parse_log("CRASH_SUSPECTED,case=17,health=4,trigger=10AABBCC")
        self.assertEqual(report.fault_class, "target_unresponsive_without_fault_dump")
        self.assertEqual(report.confidence, "low")
        self.assertFalse(report.addresses)
        self.assertEqual(report.nexus_event.get("case"), "17")
        self.assertEqual(report.nexus_event.get("trigger"), "10AABBCC")

    def test_asan_buffer_overflow_direct_location(self):
        log = """==99==ERROR: AddressSanitizer: stack-buffer-overflow on address 0x1234
WRITE of size 4 at 0x1234 thread T0
    #0 0x123456 in parse_frame /tmp/parser.cpp:42
SUMMARY: AddressSanitizer: stack-buffer-overflow /tmp/parser.cpp:42 in parse_frame
"""
        report = module.parse_log(log)
        self.assertEqual(report.fault_class, "memory_safety_violation:stack-buffer-overflow")
        self.assertEqual(report.confidence, "high")
        self.assertTrue(any("parser.cpp:42" in item for item in report.direct_locations))

    def test_ubsan(self):
        report = module.parse_log("/tmp/parser.cpp:31:9: runtime error: index 8 out of bounds for type char [4]")
        self.assertEqual(report.fault_class, "undefined_behavior")
        self.assertTrue(any("parser.cpp" in item for item in report.direct_locations))

    def test_gdb_sigsegv_gets_memory_access_remediation(self):
        report = module.parse_log("Program received signal SIGSEGV, Segmentation fault.\npc 0x401234\n")
        self.assertEqual(report.fault_class, "invalid_memory_access")
        self.assertTrue(any("faulting instruction" in item for item in report.recommendations))

    def test_gdb_sigtrap_is_not_misreported_as_a_crash(self):
        report = module.parse_log("Program received signal SIGTRAP, Trace/breakpoint trap.\npc 0x401234\n")
        self.assertEqual(report.fault_class, "debugger_breakpoint_or_trap")
        self.assertEqual(report.confidence, "low")
        self.assertTrue(any("not by itself proof of a crash" in item for item in report.recommendations))

    def test_elf_identity_does_not_substitute_for_target_identity(self):
        report = module.parse_log("NEXUS_ELF_BUILD_ID=0123456789abcdef\nBUILD_ID=abcdef0123456789\n")
        self.assertEqual(report.build_id, "abcdef0123456789")
        self.assertIn("supplied_elf_build_id=0123456789abcdef", report.debugger_metadata)

    def test_brownout_is_not_memory_crash(self):
        log = (ROOT / "examples" / "logs" / "esp32s3_brownout.log").read_text()
        report = module.parse_log(log)
        self.assertEqual(report.fault_class, "brownout_or_power_integrity_reset")
        self.assertEqual(report.registers.get("RESET_REASON"), "BROWNOUT_RST")

    def test_watchdog(self):
        log = (ROOT / "examples" / "logs" / "esp32s3_watchdog.log").read_text()
        report = module.parse_log(log)
        self.assertEqual(report.fault_class, "watchdog_timeout_or_task_starvation")

    def test_correlates_nexus_trigger_with_target_panic(self):
        log = """CRASH_SUSPECTED,case=41,tag=0010,latency_us=20001,failed_heartbeats=2,trigger=10AA0000
TARGET_LOG Guru Meditation Error: Core 0 panic'ed (LoadProhibited). Exception was unhandled.
TARGET_LOG Backtrace: 0x42001234:0x3fcebd20
TARGET_LOG PC: 0x42001234 EXCVADDR: 0x00000004
"""
        report = module.parse_log(log)
        self.assertEqual(report.fault_class, "invalid_memory_access")
        self.assertEqual(report.nexus_event.get("case"), "41")
        self.assertEqual(report.nexus_event.get("trigger"), "10AA0000")
        self.assertEqual(report.addresses[0], "0x42001234")


    def test_elf_build_id_symbolication_and_disassembly_pipeline(self):
        required = ["g++", "readelf", "nm", "addr2line", "objdump"]
        if any(shutil.which(tool) is None for tool in required):
            self.skipTest("host ELF toolchain is unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "fixture.cpp"
            elf = root / "fixture.elf"
            map_file = root / "fixture.map"
            source.write_text("#include <cstdint>\n__attribute__((noinline)) int packet_parse(const std::uint8_t* p, unsigned n) { volatile int x=n?p[0]:0; return x; }\nint main(){ std::uint8_t p[1]={1}; return packet_parse(p,1); }\n")
            subprocess.run(["g++", "-g3", "-O0", "-Wl,--build-id=sha1", f"-Wl,-Map={map_file}", str(source), "-o", str(elf)], check=True)
            build_info_path = root / "build-info.json"
            subprocess.run([sys.executable, str(ROOT / "tools" / "nexus_build_info.py"),
                            "--elf", str(elf), "--output", str(build_info_path)],
                           check=True, capture_output=True, text=True)
            build_info = json.loads(build_info_path.read_text(encoding="utf-8"))
            self.assertIn("X86-64", build_info["machine"])
            note = subprocess.check_output(["readelf", "-n", str(elf)], text=True)
            build_id = re.search(r"Build ID:\s*([0-9a-f]+)", note).group(1)
            symbols = subprocess.check_output(["nm", "-n", "-C", str(elf)], text=True)
            pc = re.search(r"^([0-9a-f]+) T packet_parse\(", symbols, re.M).group(1)
            report = module.parse_log(f"BUILD_ID={build_id}\nHardFault\nPC=0x{pc}\nLR=0x{pc}\n")
            module.inspect_elf(report, elf, map_path=map_file)
            self.assertTrue(report.build_id_match)
            self.assertTrue(any("packet_parse" in item for item in report.symbols))
            self.assertTrue(report.disassembly)
            self.assertTrue(report.elf_metadata)
            self.assertTrue(report.source_context)
            self.assertTrue(any("packet_parse" in item for item in report.source_context))

    def test_debugger_style_html_and_full_register_file(self):
        text = """Guru Meditation Error: Core 0 panic'ed (LoadProhibited).
PC : 0x42001234  A0 : 0x42001000  A1 : 0x3fcebd20
R0=0x00000001 R1=0x00000002 SP=0x3fcebd20 LR=0x42001000
EXCVADDR: 0x00000004
CRASH_SUSPECTED,case=41,tag=0010,trigger=10AA0000
"""
        report = module.parse_log(text)
        self.assertIn("R0", report.registers)
        self.assertIn("SP", report.registers)
        self.assertEqual(report.nexus_event.get("case"), "41")
        page = module.render_html(report, "fixture.log", None)
        self.assertIn("CRASH & BINARY ANALYSIS", page)
        self.assertIn("CPU register file", page)
        self.assertIn("Stack memory dump", page)
        self.assertIn("Crash remediation", page)
        self.assertIn("Source view", page)
        self.assertIn("Thread / task / core context", page)
        self.assertIn("Stack memory dump", page)
        self.assertIn("0x42001234", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
