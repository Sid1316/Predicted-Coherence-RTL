"""Run riscv-arch-test rv32i_m/I through RISCOF and check the result (docs/exec.md M5.3-M5.4).

Usage: run_riscof.py [--jobs-dir <work dir>]

Runs `riscof run` from tests/riscof/ (config.ini: DUT = rv_core on the
Verilator harness, reference = the Python model, exec.md §8), then checks
every test in the work directory itself rather than trusting the exit code:
  - DUT.signature exists, is not empty, and equals Reference.signature;
  - the harness ended the run with exit 0 (RVMODEL_HALT writes tohost = 1),
    so a test cannot pass by matching signatures after a stop;
  - the suite has EXPECTED_TESTS tests (spec §15.1: 39 at the pinned 3.10.0),
    so a test that silently drops out of the selection is reported.
RISCOF's own HTML report is in the work directory (report.html).

Exit code: 0 if every check passed, 1 otherwise.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RISCOF_DIR = ROOT / "tests" / "riscof"
SUITE = ROOT / "tests" / "riscv-arch-test" / "riscv-test-suite"
EXPECTED_TESTS = 39
EXIT = re.compile(r"^tb_top: .* exit=(\d+)$", re.M)


def riscof_exe() -> str:
    for cand in (Path(sys.executable).parent / "riscof.exe", Path(sys.executable).parent / "riscof"):
        if cand.exists():
            return str(cand)
    exe = shutil.which("riscof")
    if exe is None:
        raise SystemExit("run_riscof: riscof not found (pip install -r setup_require.txt in the venv)")
    return exe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work-dir", type=Path, default=ROOT / "build" / "riscof")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = args.work_dir.resolve()
    if work.exists():
        shutil.rmtree(work)      # RISCOF refuses to reuse test directories

    log = work.with_name(work.name + ".log")
    cmd = [riscof_exe(), "run", "--config=config.ini", f"--suite={SUITE.as_posix()}",
           f"--env={(SUITE / 'env').as_posix()}", f"--work-dir={work.as_posix()}", "--no-browser"]
    print("run_riscof: " + " ".join(cmd))
    with open(log, "wb") as f:
        p = subprocess.run(cmd, cwd=RISCOF_DIR, stdout=f, stderr=subprocess.STDOUT)
    if p.returncode not in (0, 1):    # riscof exits 1 when a signature differs; checked below
        print(f"run_riscof: riscof failed (exit {p.returncode}), see {log}")
        return 1

    tests = sorted(d for d in work.glob("**/src/*.S") if d.is_dir())
    failed = 0
    def signature(d: Path) -> Path:
        """RISCOF names the file <DUT|Reference>-<plugin>.signature."""
        found = sorted(d.glob("*.signature"))
        return found[0] if len(found) == 1 else d / "(missing).signature"

    for t in tests:
        dut, ref = signature(t / "dut"), signature(t / "ref")
        problems = []
        if not dut.exists() or dut.stat().st_size == 0:
            problems.append("no DUT signature")
        elif not ref.exists():
            problems.append("no reference signature")
        elif dut.read_bytes() != ref.read_bytes():
            d, r = dut.read_text().splitlines(), ref.read_text().splitlines()
            first = next((i for i, (a, b) in enumerate(zip(d, r)) if a != b), min(len(d), len(r)))
            problems.append(f"signature differs at word {first} (of {len(r)})")
        run_log = t / "dut" / "run.log"
        m = EXIT.findall(run_log.read_text(errors="replace")) if run_log.exists() else []
        if not m or m[-1] != "0":
            problems.append(f"harness exit {m[-1] if m else '?'} (see {run_log})")
        rel = t.relative_to(work).as_posix()
        if problems:
            failed += 1
            print(f"  FAIL  {rel}: {'; '.join(problems)}")
        else:
            n = len(ref.read_text().splitlines())
            print(f"  PASS  {rel}  ({n} signature words)")

    print()
    if len(tests) != EXPECTED_TESTS:
        print(f"run_riscof: {len(tests)} tests ran, expected {EXPECTED_TESTS} (spec §15.1)")
        failed += 1
    print(f"run_riscof: {len(tests) - min(failed, len(tests))}/{len(tests)} passed; "
          f"RISCOF report: {work / 'report.html'}, log: {log}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
