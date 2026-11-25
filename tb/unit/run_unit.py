"""Run the cocotb unit tests for the RTL blocks (docs/exec.md M2).

Usage (from the repo root; normally through make):
    python tb/unit/run_unit.py                # every block
    python tb/unit/run_unit.py rv_alu         # one or more blocks
    python tb/unit/run_unit.py rv_alu --waves # also write an FST waveform

Simulator: Icarus Verilog. cocotb's Windows package ships an Icarus plugin but
none for Verilator, and Icarus is 4-state, so the tests also catch X/Z on
outputs (docs/spec.md §13). Verilator is still used for lint.

Blocks that read plusargs at time 0 (the simulation models in sim/, M3.3)
are run once per entry in sim_scenarios.RUNS, each run with its own +hex=,
+tohost= and +retire_log=; their counts add up under the block's name.

Exit code: 0 if every test passed, 1 otherwise.
"""

import argparse
import sys
from pathlib import Path

from cocotb_tools.check_results import get_results
from cocotb_tools.runner import get_runner

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_scenarios  # noqa: E402  (needs the path above)

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / "rtl"
SIM = ROOT / "sim"
TEST_DIR = Path(__file__).resolve().parent
BUILD = ROOT / "build" / "unit"

# Block -> RTL files it needs, in compile order (rv_pkg.sv first, spec §14.1).
# Add one entry per block as M2 progresses.
BLOCKS = {
    "rv_alu": ["rv_pkg.sv", "rv_alu.sv"],
    "rv_imm_gen": ["rv_pkg.sv", "rv_imm_gen.sv"],
    "rv_regfile": ["rv_regfile.sv"],
    "rv_branch_unit": ["rv_pkg.sv", "rv_branch_unit.sv"],
    "rv_lsu": ["rv_pkg.sv", "rv_lsu.sv"],
    "rv_decoder": ["rv_pkg.sv", "rv_decoder.sv"],
    "rv_pc": ["rv_pc.sv"],
    "rv_core": ["rv_pkg.sv", "rv_pc.sv", "rv_decoder.sv", "rv_imm_gen.sv", "rv_regfile.sv",
                "rv_alu.sv", "rv_branch_unit.sv", "rv_lsu.sv", "rv_core.sv"],
}
# Simulation models (sim/): RTL files as above plus files from sim/.
SIM_BLOCKS = {
    "rv_mem_model": (["rv_pkg.sv"], ["rv_mem_model.sv"]),
    "rv_soc_sim": (BLOCKS["rv_core"], ["rv_mem_model.sv", "rv_soc_sim.sv"]),
}


def sources(block: str) -> list[Path]:
    if block in SIM_BLOCKS:
        rtl, sim = SIM_BLOCKS[block]
        return [RTL / f for f in rtl] + [SIM / f for f in sim]
    return [RTL / f for f in BLOCKS[block]]


def run_block(block: str, waves: bool) -> tuple[int, int]:
    """Build and run one block's tests. Returns (tests, failures)."""
    build_dir = BUILD / block
    runner = get_runner("icarus")
    runner.build(
        sources=sources(block),
        hdl_toplevel=block,
        build_dir=build_dir,
        always=True,
        timescale=("1ns", "1ps"),
        waves=waves,
    )
    runs = sim_scenarios.RUNS.get(block)
    if runs is None:
        results = runner.test(
            test_module=f"test_{block}",
            hdl_toplevel=block,
            build_dir=build_dir,
            test_dir=TEST_DIR,
            waves=waves,
        )
        return get_results(results)

    tests = failed = 0
    for run in runs:
        plusargs, env = run.plusargs(build_dir)
        results = runner.test(
            test_module=f"test_{block}",
            hdl_toplevel=block,
            build_dir=build_dir,
            test_dir=TEST_DIR,
            plusargs=plusargs,
            extra_env=env,
            results_xml=str(build_dir / f"results_{run.name}.xml"),
            waves=waves,
        )
        t, f = get_results(results)
        tests, failed = tests + t, failed + f
        if f:
            print(f"run_unit: {block} run '{run.name}' failed ({f}/{t})")
    return tests, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("blocks", nargs="*", help=f"blocks to test (default: all of {', '.join([*BLOCKS, *SIM_BLOCKS])})")
    parser.add_argument("--waves", action="store_true", help="write FST waveforms in build/unit/<block>/")
    args = parser.parse_args()

    blocks = args.blocks or list(BLOCKS) + list(SIM_BLOCKS)
    unknown = [b for b in blocks if b not in BLOCKS and b not in SIM_BLOCKS]
    if unknown:
        parser.error(f"unknown block(s): {', '.join(unknown)}; known: {', '.join([*BLOCKS, *SIM_BLOCKS])}")

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
