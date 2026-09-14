#!/usr/bin/env python3
"""Reject accidental binding to ESP32-C3 ROM's incompatible miniz ABI."""

import subprocess, sys

text = subprocess.check_output([sys.argv[1], "-n", sys.argv[2]], text=True)
symbol = [
    line
    for line in text.splitlines()
    if line.split() and line.split()[-1].lstrip("_") == "pet_tinfl_decompress"
]
assert len(symbol) == 1 and symbol[0].split()[1].upper() == "T", symbol
assert not any(line.endswith(" U tinfl_decompress") for line in text.splitlines())
print("PASS: pet_tinfl_decompress is linked from the vendored implementation")
