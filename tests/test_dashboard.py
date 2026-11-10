#!/usr/bin/env python3
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "nexus_dashboard.py"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nexus_dashboard_test_") as temp:
        base = Path(temp)
        source = base / "campaign.jsonl"
        output = base / "dashboard.html"
        records = [
            {"schema":"nexus.campaign.v1","type":"case","case_id":1,"mutation":"bit_flip","input_hex":"1001","response_hex":"06","response_kind":"ack","latency_us":42,"feedback_edges":[0,1],"novel_edges":2,"new_outcome":True,"admitted":True,"corpus_size":3},
            {"schema":"nexus.campaign.v1","type":"summary","target":"fictional_host_model","requested_cases":1,"executed_cases":1,"novel_cases":1,"coverage_events":1,"new_response_classes":1,"unique_edges":2,"corpus_size":3,"dropped_candidates":0,"outcomes":{"ack":1}}
        ]
        source.write_text("".join(json.dumps(x) + "\n" for x in records), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(TOOL), "--input", str(source), "--output", str(output)], capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stderr, file=sys.stderr)
            return 1
        html = output.read_text(encoding="utf-8")
        assert "NEXUS-HW" in html
        assert "1001" in html
        assert "Case explorer" in html
    print("NEXUS dashboard tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
