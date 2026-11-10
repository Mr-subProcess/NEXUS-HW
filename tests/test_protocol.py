#!/usr/bin/env python3
from __future__ import annotations
import json
import subprocess
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "nexus_protocol.py"
FIXTURE = ROOT / "examples" / "protocols" / "lab-demo-v1.json"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nexus_protocol_test_") as temp:
        base = Path(temp)
        header = base / "generated_protocol.hpp"
        good = subprocess.run([sys.executable, str(TOOL), "--input", str(FIXTURE), "--output", str(header)], capture_output=True, text=True)
        assert good.returncode == 0, good.stderr
        generated = header.read_text(encoding="utf-8")
        assert "make_protocol_corpus" in generated
        assert "0x0010" in generated
        compiler = shutil.which("c++") or shutil.which("g++")
        assert compiler is not None
        translation_unit = base / "generated_check.cpp"
        translation_unit.write_text(
            '#include "nexus/types.hpp"\n#include "generated_protocol.hpp"\n'
            'int main(){ auto c=nexus::generated::make_protocol_corpus(); '
            'auto p=nexus::generated::make_protocol_profile(); '
            'return (c.count == 2 && p.ack.size == 1) ? 0 : 1; }\n',
            encoding="utf-8")
        compile_result = subprocess.run(
            [compiler, "-std=c++20", "-fsyntax-only", "-I", str(ROOT / "include"),
             "-I", str(base), str(translation_unit)], capture_output=True, text=True)
        assert compile_result.returncode == 0, compile_result.stderr
        bad_manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bad_manifest["commands"][0]["classification"] = "unknown_or_hidden"
        bad_path = base / "unsafe.json"
        bad_path.write_text(json.dumps(bad_manifest), encoding="utf-8")
        bad = subprocess.run([sys.executable, str(TOOL), "--input", str(bad_path), "--output", str(base / "bad.hpp")], capture_output=True, text=True)
        assert bad.returncode == 2
        assert "documented_read_only" in bad.stderr
        bad_manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bad_manifest["commands"][0]["minimum_mutable_bytes"] = 99
        bad_path.write_text(json.dumps(bad_manifest), encoding="utf-8")
        bad_range = subprocess.run([sys.executable, str(TOOL), "--input", str(bad_path)], capture_output=True, text=True)
        assert bad_range.returncode == 2
        assert "minimum_mutable_bytes" in bad_range.stderr
    print("NEXUS protocol compiler tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
