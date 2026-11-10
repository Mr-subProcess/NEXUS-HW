#!/usr/bin/env python3
"""Normalize NEXUS-HW serial/debug text into a stable JSONL event stream.

This parser is intentionally offline and does not open serial devices.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PAIR = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)=(\"[^\"]*\"|'[^']*'|[^,\s]+)")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def classify_line(line: str) -> tuple[str, dict[str, str]]:
    stripped = line.strip()
    if not stripped:
        return "blank", {}
    upper = stripped.upper()
    if upper.startswith("CRASH_SUSPECTED"):
        kind = "crash_suspected"
    elif upper.startswith("HEALTH"):
        kind = "health"
    elif upper.startswith("NXCOV1"):
        kind = "coverage"
    elif upper.startswith("TARGET_LOG"):
        kind = "target_log"
    elif upper.startswith("NEXUS_DEBUG_CAPTURE"):
        kind = "debug_capture"
    elif upper.startswith("NEXUS ") or upper.startswith("NEXUS,"):
        kind = "case"
    elif upper.startswith("SAFE_OPCODE"):
        kind = "opcode_observation"
    elif upper.startswith("HOST_NOVEL"):
        kind = "host_novelty"
    elif upper.startswith("HOST_OPTIMIZE_SUMMARY"):
        kind = "host_summary"
    elif upper.startswith("STATE,"):
        kind = "state"
    elif upper.startswith("EDGE,"):
        kind = "edge"
    elif upper.startswith("TIMING,"):
        kind = "timing"
    elif upper.startswith("DONE"):
        kind = "run_complete"
    elif re.search(r"(?i)(?:TARGET[_ -]?BUILD[_ -]?ID|BUILD[_ -]?ID)\s*[:=]", stripped):
        kind = "build_identity"
    else:
        kind = "log"

    fields: dict[str, str] = {}
    for match in PAIR.finditer(stripped):
        fields[match.group(1)] = _unquote(match.group(2))
    if kind == "target_log":
        payload = re.sub(r"(?i)^TARGET_LOG\s*:?\s*", "", stripped, count=1)
        fields.setdefault("message", payload)
        build = re.search(r"(?i)(?:TARGET[_ -]?BUILD[_ -]?ID|BUILD[_ -]?ID)\s*[:=]\s*([0-9a-f]{8,64})", payload)
        if build:
            fields.setdefault("build_id", build.group(1).lower())
    if kind == "build_identity":
        build = re.search(r"(?i)(?:TARGET[_ -]?BUILD[_ -]?ID|BUILD[_ -]?ID)\s*[:=]\s*([0-9a-f]{8,64})", stripped)
        if build:
            fields["build_id"] = build.group(1).lower()
    return kind, fields


def normalize(text: str) -> tuple[list[dict], dict]:
    events: list[dict] = []
    counts: Counter[str] = Counter()
    cases: set[str] = set()
    coverage_records = 0
    for line_number, raw in enumerate(text.splitlines(), 1):
        kind, fields = classify_line(raw)
        if kind == "blank":
            continue
        event = {
            "schema": "nexus.session.v1",
            "sequence": len(events) + 1,
            "source_line": line_number,
            "event_type": kind,
            "fields": fields,
            "raw": raw,
        }
        if "case" in fields:
            cases.add(fields["case"])
        if kind == "coverage":
            coverage_records += 1
        events.append(event)
        counts[kind] += 1
    summary = {
        "schema": "nexus.session-summary.v1",
        "event_count": len(events),
        "event_types": dict(sorted(counts.items())),
        "unique_case_ids": len(cases),
        "crash_suspected_events": counts["crash_suspected"],
        "coverage_records": coverage_records,
        "build_ids": sorted({e["fields"].get("build_id") for e in events if e["fields"].get("build_id")}),
    }
    return events, summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Normalize NEXUS-HW serial/debug logs into JSONL")
    ap.add_argument("--input", required=True, type=Path, help="combined NEXUS/target/debug text log")
    ap.add_argument("--output", required=True, type=Path, help="JSONL output")
    ap.add_argument("--summary", type=Path, help="optional JSON session summary")
    args = ap.parse_args()
    try:
        text = args.input.read_text(encoding="utf-8", errors="replace")
        events, summary = normalize(text)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events), encoding="utf-8")
        if args.summary:
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0
    except OSError as exc:
        print(f"nexus_session: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
