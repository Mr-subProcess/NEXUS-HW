#!/usr/bin/env python3
"""Local-only sample oracle: reports a fake crash if the bytes CRASH_TAG remain."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True, type=Path)
args = parser.parse_args()
data = args.input.read_bytes()
if b"CRASH_TAG" in data:
    print("CRASH_CONFIRMED: demo-only synthetic fault signature")
else:
    print("NO_CRASH")
