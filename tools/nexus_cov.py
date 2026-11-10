#!/usr/bin/env python3
"""Merge NEXUS fixed-bitmap target coverage records and report new edges."""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

RECORD = re.compile(r"NXCOV1,run=(\d+),bits=(\d+),bitmap=([0-9A-Fa-f]+)")


def parse_records(text: str) -> list[dict]:
    records = []
    for line_no, line in enumerate(text.splitlines(), 1):
        match = RECORD.search(line)
        if not match:
            continue
        run_id, bits, bitmap_hex = int(match.group(1)), int(match.group(2)), match.group(3)
        expected_hex = ((bits + 31) // 32) * 8
        if bits < 32 or bits > 8192 or len(bitmap_hex) != expected_hex:
            raise ValueError(f"invalid coverage bitmap at line {line_no}")
        raw = bytes.fromhex(bitmap_hex)
        # Firmware serializes each uint32 word in big-endian hexadecimal text.
        bitset = 0
        for word_index in range((bits + 31) // 32):
            word = int.from_bytes(raw[word_index * 4:(word_index + 1) * 4], "big")
            bitset |= word << (word_index * 32)
        bitset &= (1 << bits) - 1
        records.append({"run_id": run_id, "bits": bits, "bitmap": bitset, "line": line_no})
    return records


def summarize(records: list[dict], total_edges: int | None = None) -> dict:
    if not records:
        raise ValueError("no NXCOV1 coverage records found")
    capacities = {r["bits"] for r in records}
    if len(capacities) != 1:
        raise ValueError("coverage records use different bitmap sizes")
    merged = 0
    per_run = []
    for record in records:
        bits = record["bits"]
        current = record["bitmap"]
        new_bits = current & ~merged
        new_count = new_bits.bit_count()
        merged |= current
        per_run.append({"run_id": record["run_id"], "edges_in_run": current.bit_count(),
                        "new_edges": new_count, "line": record["line"]})
    found = merged.bit_count()
    result = {"format": "NEXUS-HW coverage report", "bitmap_capacity": next(iter(capacities)),
              "records": len(records), "unique_edges_found": found, "runs": per_run,
              "new_edge_ids": [i for i in range(next(iter(capacities))) if (merged >> i) & 1]}
    if total_edges is not None:
        if total_edges <= 0:
            raise ValueError("total_edges must be positive")
        if total_edges > next(iter(capacities)):
            raise ValueError("total_edges exceeds bitmap capacity; increase target coverage bitmap size")
        result["total_instrumented_edges"] = total_edges
        result["coverage_percent"] = round(100.0 * found / total_edges, 2)
        if found > total_edges:
            result["warning"] = "Unique bitmap IDs exceed declared total_edges; reconcile instrumentation map."
    else:
        result["coverage_percent"] = None
        result["coverage_note"] = "Percentage unavailable: pass --total-edges from the target instrumentation map."
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge NEXUS instrumented-target coverage records")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", type=Path, default=Path("coverage-report.json"))
    ap.add_argument("--total-edges", type=int, default=None,
                    help="number of edge IDs assigned by the target instrumentation map")
    args = ap.parse_args()
    try:
        records = parse_records(args.input.read_text(encoding="utf-8", errors="replace"))
        report = summarize(records, args.total_edges)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"nexus_cov: error: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
