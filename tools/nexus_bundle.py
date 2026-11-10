#!/usr/bin/env python3
"""Build a portable, hash-manifested NEXUS-HW offline evidence bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_input(path: Path | None, label: str) -> Path | None:
    if path is None:
        return None
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    return resolved


def main() -> int:
    ap = argparse.ArgumentParser(description="Package logs, target ELF/MAP, minimized input and generated triage views")
    ap.add_argument("--capture", required=True, type=Path, help="combined target/NEXUS/GDB text capture")
    ap.add_argument("--elf", type=Path, help="exact target ELF (optional but strongly recommended)")
    ap.add_argument("--map", type=Path, help="matching linker map")
    ap.add_argument("--coverage", type=Path, help="merged coverage JSON")
    ap.add_argument("--minimized-input", type=Path, help="reproducing minimized binary trigger")
    ap.add_argument("--source-root", action="append", default=[], help="source root for DWARF source excerpts")
    ap.add_argument("--output", required=True, type=Path, help="output .zip evidence bundle")
    args = ap.parse_args()

    try:
        supplied = [
            ("capture.log", safe_input(args.capture, "capture")),
            ("target.elf", safe_input(args.elf, "ELF")),
            ("target.map", safe_input(args.map, "map")),
            ("coverage.json", safe_input(args.coverage, "coverage")),
            ("minimized-trigger.bin", safe_input(args.minimized_input, "minimized input")),
        ]
        if supplied[0][1] is None:
            raise ValueError("capture is required")
        for root in args.source_root:
            if not Path(root).is_dir():
                raise ValueError(f"source root does not exist or is not a directory: {root}")

        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        triage_tool = ROOT / "tools" / "nexus_triage.py"
        with tempfile.TemporaryDirectory(prefix="nexus_bundle_") as temp_name:
            temp = Path(temp_name)
            artifact_dir = temp / "artifacts"
            artifact_dir.mkdir()
            copied: list[dict] = []
            for archive_name, source in supplied:
                if source is None:
                    continue
                destination = artifact_dir / archive_name
                destination.write_bytes(source.read_bytes())
                copied.append({"archive_path": f"artifacts/{archive_name}",
                               "source_name": source.name, "size_bytes": destination.stat().st_size,
                               "sha256": sha256(destination)})

            triage_json = temp / "triage.json"
            triage_html = temp / "triage.html"
            command = [sys.executable, str(triage_tool), "--input", str(supplied[0][1]),
                       "--format", "json", "--output", str(triage_json)]
            if supplied[1][1]: command += ["--elf", str(supplied[1][1])]
            if supplied[2][1]: command += ["--map", str(supplied[2][1])]
            if supplied[3][1]: command += ["--coverage", str(supplied[3][1])]
            for root in args.source_root: command += ["--source-root", str(Path(root).resolve())]
            run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=90, check=False)
            if run.returncode != 0:
                raise RuntimeError("triage JSON generation failed: " + (run.stderr or run.stdout)[-2000:])
            html_command = [sys.executable, str(triage_tool), "--input", str(supplied[0][1]),
                            "--format", "html", "--output", str(triage_html)]
            if supplied[1][1]: html_command += ["--elf", str(supplied[1][1])]
            if supplied[2][1]: html_command += ["--map", str(supplied[2][1])]
            if supplied[3][1]: html_command += ["--coverage", str(supplied[3][1])]
            for root in args.source_root: html_command += ["--source-root", str(Path(root).resolve())]
            html_run = subprocess.run(html_command, cwd=ROOT, capture_output=True, text=True, timeout=90, check=False)
            if html_run.returncode != 0:
                raise RuntimeError("triage HTML generation failed: " + (html_run.stderr or html_run.stdout)[-2000:])

            triage_data = json.loads(triage_json.read_text(encoding="utf-8"))
            manifest = {
                "schema": "nexus.evidence-bundle.v1",
                "tool": "NEXUS-HW",
                "tool_version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "artifacts": copied,
                "analysis": {
                    "platform": triage_data.get("platform"),
                    "fault_class": triage_data.get("fault_class"),
                    "confidence": triage_data.get("confidence"),
                    "target_build_id": triage_data.get("build_id"),
                    "elf_build_id": triage_data.get("elf_build_id"),
                    "build_id_match": triage_data.get("build_id_match"),
                    "address_count": len(triage_data.get("addresses", [])),
                    "symbol_count": len(triage_data.get("symbols", [])),
                },
                "generated_analysis": [
                    {"archive_path": "analysis/triage.json", "size_bytes": triage_json.stat().st_size,
                     "sha256": sha256(triage_json)},
                    {"archive_path": "analysis/triage.html", "size_bytes": triage_html.stat().st_size,
                     "sha256": sha256(triage_html)},
                ],
                "limitations": triage_data.get("limitations", []),
                "bundle_note": "Evidence is copied without modifying source artifacts. Review build identity and diagnostic limitations before assigning root cause.",
            }
            (temp / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.write(temp / "manifest.json", "manifest.json")
                archive.write(triage_json, "analysis/triage.json")
                archive.write(triage_html, "analysis/triage.html")
                for item in copied:
                    archive.write(artifact_dir / Path(item["archive_path"]).name, item["archive_path"])

        print(json.dumps({"output": str(output), "size_bytes": output.stat().st_size,
                          "artifact_count": len(copied), "fault_class": manifest["analysis"]["fault_class"],
                          "build_id_match": manifest["analysis"]["build_id_match"]}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"nexus_bundle: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
