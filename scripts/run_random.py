"""Run random programs on the RTL and the reference model and compare them (docs/exec.md M6.4).

Usage: run_random.py --exe <Vrv_soc_sim> [--seeds N] [--start S] [-j JOBS] [--keep]

For each seed in [S, S + N), and first for every saved regression test in
tests/random/*.S:
  1. generate the program (scripts/randgen.py), build it like a directed test
     (sw/asm/test.h, sw/common/link.ld, spec §12 flags), convert it (elf2hex);
  2. run it on the Verilator harness and on the Python model (the reference,
     exec.md §8), both stepped until tohost is written, the core stops, or
     MAX_CYCLES;
  3. compare: exit code, console output, and the retire logs line for line
     (on a difference, scripts/trace_compare.py reports the first differing
     instruction with context).
A seed that fails is saved as tests/random/seed_<n>.S, so it stays a
regression test even if the generator changes. Work files of passing seeds
are deleted unless --keep.

At the end: how often each RV32I instruction retired and how the runs ended.
With 50 or more programs, every one of the 40 RV32I instructions must have
retired at least once, or the run fails (the generator lost coverage).

Exit code: 0 if every program matched the model, 1 otherwise.
"""

import argparse
import os
import shutil
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tb" / "sim"))
sys.path.insert(0, str(ROOT / "tb" / "unit"))
from elf2hex import elf2hex, tool  # noqa: E402
from harness_model import model_run  # noqa: E402
from randgen import generate  # noqa: E402
from rv_model import INSTRS, decode_ref, read_hex  # noqa: E402
from run_progs import ASM_DIR, COMMON_FLAGS  # noqa: E402
from trace_compare import compare, parse_retire  # noqa: E402

OUT = ROOT / "build" / "random"
REGRESS = ROOT / "tests" / "random"
MAX_CYCLES = 200_000
EXIT_NAMES = {0: "pass", 1: "tohost fail", 2: "timeout", 3: "error stop", 4: "ECALL/EBREAK"}


def run_one(name: str, source: str, exe: str, keep: bool) -> dict:
    """Build and run one program; return what happened. Runs in a worker process."""
    wd = OUT / name
    wd.mkdir(parents=True, exist_ok=True)
    src = wd / f"{name}.S"
    src.write_text(source, encoding="ascii", newline="\n")
    res = {"name": name, "ok": False, "problems": [], "insns": Counter(), "cause": None, "code": None}
    elf = wd / f"{name}.elf"
    p = subprocess.run([tool("gcc"), *COMMON_FLAGS, "-I", str(ASM_DIR), str(src), "-o", str(elf)],
                       capture_output=True)
    if p.returncode != 0:
        res["problems"].append("build failed:\n" + p.stderr.decode(errors="replace"))
        return res
    hexf = wd / f"{name}.hex"
    tohost = elf2hex(elf, hexf)
    log = wd / "retire.log"
    h = subprocess.run([exe, f"+hex={hexf.as_posix()}", f"+tohost={tohost:08x}", f"+max_cycles={MAX_CYCLES}",
                        f"+retire_log={log.as_posix()}"], capture_output=True, timeout=300)
    exp = model_run(read_hex(hexf), tohost, MAX_CYCLES)
    got = log.read_text(encoding="ascii").splitlines()
    res["code"], res["cause"] = h.returncode, exp.cause
    if h.returncode != exp.code:
        res["problems"].append(f"exit {h.returncode}, model {exp.code} "
                               f"({h.stderr.decode(errors='replace').strip().splitlines()[-1:]})")
    if h.stdout != exp.console:
        res["problems"].append(f"console {h.stdout!r}, model {exp.console!r}")
    if got != exp.lines:
        report = compare(parse_retire("\n".join(got)), parse_retire("\n".join(exp.lines)))
        first = next((i for i, (a, b) in enumerate(zip(got, exp.lines)) if a != b), min(len(got), len(exp.lines)))
        res["problems"].append(report or f"retire logs differ at line {first} in fields trace_compare does not "
                                         f"compare:\n  rtl   {got[first] if first < len(got) else '(end)'}\n"
                                         f"  model {exp.lines[first] if first < len(exp.lines) else '(end)'}")
    for line in got:
        res["insns"][decode_ref(int(line.split()[2], 16))[0]] += 1
    res["ok"] = not res["problems"]
    if res["ok"] and not keep:
        shutil.rmtree(wd, ignore_errors=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", required=True, type=Path)
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--keep", action="store_true", help="keep the work files of passing programs")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not args.exe.exists():
        raise SystemExit(f"run_random: {args.exe} not found (run make sim-build)")
    OUT.mkdir(parents=True, exist_ok=True)

    jobs = [(p.stem, p.read_text(encoding="ascii")) for p in sorted(REGRESS.glob("*.S"))]
    n_regress = len(jobs)
    jobs += [(f"seed_{s}", generate(s)) for s in range(args.start, args.start + args.seeds)]
    print(f"run_random: {n_regress} saved regression tests + seeds {args.start}..{args.start + args.seeds - 1}, "
          f"{args.jobs} jobs")

    results = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(run_one, name, src, str(args.exe), args.keep): name for name, src in jobs}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception as e:  # noqa: BLE001 - a crash in one program is a failure, not the end
                r = {"name": futs[f], "ok": False, "problems": [f"runner error: {e!r}"], "insns": Counter(),
                     "cause": None, "code": None}
            results.append(r)
            if not r["ok"]:
                print(f"  FAIL  {r['name']}: " + "\n    ".join(r["problems"]))
                if r["name"].startswith("seed_"):
                    REGRESS.mkdir(parents=True, exist_ok=True)
                    dest = REGRESS / f"{r['name']}.S"
                    if not dest.exists():
                        shutil.copy(OUT / r["name"] / f"{r['name']}.S", dest)
                        print(f"        saved as {dest.relative_to(ROOT).as_posix()} (regression test)")

    failed = [r for r in results if not r["ok"]]
    insns = sum((r["insns"] for r in results), Counter())
    ends = Counter(EXIT_NAMES.get(r["code"], f"exit {r['code']}") for r in results)
    causes = Counter(r["cause"] for r in results if r["cause"] and r["cause"] != "STOP_NONE")

    print(f"\nInstructions retired: {sum(insns.values())} in {len(results)} programs")
    names = [n for n in INSTRS]
    for i in range(0, len(names), 8):
        print("  " + "  ".join(f"{n:6s}{insns[n]:7d}" for n in names[i:i + 8]))
    if insns["illegal"]:
        print(f"  illegal {insns['illegal']} (deliberate error endings)")
    print("Endings: " + ", ".join(f"{k} {v}" for k, v in sorted(ends.items())))
    print("Stop causes: " + ", ".join(f"{k} {v}" for k, v in sorted(causes.items())))

    missing = [n for n in names if insns[n] == 0]
    status = 0
    if missing and len(results) >= 50:
        print(f"run_random: never retired: {', '.join(missing)}")
        status = 1
    if failed:
        print(f"run_random: {len(failed)} of {len(results)} programs differ from the model")
        status = 1
    else:
        print(f"run_random: all {len(results)} programs match the model")
    return status


if __name__ == "__main__":
    sys.exit(main())
