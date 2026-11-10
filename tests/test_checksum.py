import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nexus_checksum", ROOT / "tools" / "nexus_checksum.py")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class ProtocolChecksumTests(unittest.TestCase):
    def test_standard_vectors(self):
        data = b"123456789"
        self.assertEqual(module.compute(data, {"algorithm": "xor8"}), 0x31)
        self.assertEqual(module.compute(data, {"algorithm": "sum8"}), 0xDD)
        self.assertEqual(module.compute(data, {"algorithm": "crc8_maxim"}), 0xA1)
        self.assertEqual(module.compute(data, {"algorithm": "crc16_ccitt_false"}), 0x29B1)
        self.assertEqual(module.compute(data, {"algorithm": "crc16_modbus"}), 0x4B37)
        self.assertEqual(module.compute(data, {"algorithm": "crc32_ieee"}), 0xCBF43926)

    def test_custom_crc8_and_endian_write(self):
        spec = {"algorithm": "crc8_custom", "polynomial": 0x07, "initial": 0,
                "xor_out": 0, "reflect_input": False, "reflect_output": False,
                "data_offset": 0, "data_length": 2, "checksum_offset": 2,
                "byte_order": "big"}
        result = module.apply_checksum(b"\x01\x02\x00", spec)
        self.assertEqual(result[:2], b"\x01\x02")
        self.assertEqual(result[2], module.compute(b"\x01\x02", spec))

    def test_crc16_little_endian(self):
        spec = {"algorithm": "crc16_modbus", "data_offset": 0, "data_length": 2,
                "checksum_offset": 2, "byte_order": "little"}
        result = module.apply_checksum(b"\x01\x02\x00\x00", spec)
        self.assertEqual(int.from_bytes(result[2:4], "little"), module.compute(b"\x01\x02", spec))

    def test_rejects_custom_crc_polynomial_outside_width(self):
        with self.assertRaises(ValueError):
            module.compute(b"abc", {"algorithm": "crc8_custom", "polynomial": 0x107})

    def test_rejects_overlap_and_out_of_bounds(self):
        with self.assertRaises(ValueError):
            module.apply_checksum(b"\x01\x02", {"algorithm": "xor8", "data_offset": 0,
                "data_length": 2, "checksum_offset": 1})
        with self.assertRaises(ValueError):
            module.apply_checksum(b"\x01", {"algorithm": "crc16_modbus", "data_offset": 0,
                "data_length": 1, "checksum_offset": 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
