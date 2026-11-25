"""Run the cocotb unit tests for the RTL blocks (docs/exec.md M2).

Usage (from the repo root; normally through make):
    python tb/unit/run_unit.py                # every block
    python tb/unit/run_unit.py rv_alu         # one or more blocks
    python tb/unit/run_unit.py rv_alu --waves # also write an FST waveform

Simulator: Icarus Verilog. cocotb's Windows package ships an Icarus plugin but
none for Verilator, and Icarus is 4-state, so the tests also catch X/Z on
outputs (docs/spec.md §13). Verilator is still used for lint.

Exit code: 0 if every test passed, 1 otherwise.
"""

import argparse
import sys
from pathlib import Path

from cocotb_tools.check_results import get_results
from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / "rtl"
TEST_DIR = Path(__file__).resolve().parent
BUILD = ROOT / "build" / "unit"

# Block -> RTL files it needs, in compile order (rv_pkg.sv first, spec §14.1).
# Add one entry per block as M2 progresses.
BLOCKS = {
    "rv_alu": ["rv_pkg.sv", "rv_alu.sv"],
}


def run_block(block: str, waves: bool) -> tuple[int, int]:
    """Build and run one block's tests. Returns (tests, failures)."""
    build_dir = BUILD / block
    runner = get_runner("icarus")
    runner.build(
        sources=[RTL / f for f in BLOCKS[block]],
        hdl_toplevel=block,
        build_dir=build_dir,
        always=True,
        timescale=("1ns", "1ps"),
        waves=waves,
    )
    results = runner.test(
        test_module=f"test_{block}",
        hdl_toplevel=block,
        build_dir=build_dir,
        test_dir=TEST_DIR,
        waves=waves,
    )
    return get_results(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("blocks", nargs="*", help=f"blocks to test (default: all of {', '.join(BLOCKS)})")
    parser.add_argument("--waves", action="store_true", help="write FST waveforms in build/unit/<block>/")
    args = parser.parse_args()

    blocks = args.blocks or list(BLOCKS)
    unknown = [b for b in blocks if b not in BLOCKS]
    if unknown:
        parser.error(f"unknown block(s): {', '.join(unknown)}; known: {', '.join(BLOCKS)}")

    summary = []
    for block in blocks:
        tests, failed = run_block(block, args.waves)
        summary.append((block, tests, failed))

    print("\nunit test summary")
    for block, tests, failed in summary:
        status = "PASS" if failed == 0 and tests > 0 else "FAIL"
        print(f"  {status}  {block:<16} {tests - failed}/{tests} passed")
    total_failed = sum(f for _, _, f in summary) + sum(1 for _, t, _ in summary if t == 0)
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
