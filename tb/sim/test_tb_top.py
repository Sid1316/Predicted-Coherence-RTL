"""Checks for the Verilator harness sim/tb_top.cpp (docs/exec.md M3.4, docs/spec.md §2.2, §9.2, §11).

Usage: test_tb_top.py <path to Vrv_soc_sim>      (make sim-test builds it and runs this)

Runs the simulator binary as a user would and checks what it reports:
  - every rv_soc_sim scenario from tb/unit/sim_scenarios.py: exit code, cycle
    count, the retire log line for line, the console bytes on stdout and the
    tohost value, all against the Python model (rv_model.CoreModel). The run
    must end at the edge where tohost is written or the core stops (§11);
  - harness errors (exit 5): missing or unreadable files, bad or unknown
    plusargs, a malformed hex image;
  - timeout (exit 2) with +max_cycles= and with the default of 1,000,000;
  - +waves writes a wave file and does not change the result;
  - +signature= (§11): the words in [sig_begin, sig_end) match the model's
    memory at the end of the run, also after an error stop; bad ranges are
    harness errors;
  - random reset (§2.2): a register read before it is written gives a value
    that depends on +verilator+seed+, is the same for the same seed, and is 0
    with +verilator+rand+reset+0.

Exit code: 0 if every check passed, 1 otherwise.
"""

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tb" / "unit"))

import sim_scenarios  # noqa: E402
from rv_model import STOP_CAUSES, write_hex  # noqa: E402

sys.path.insert(0, str(ROOT / "tb" / "sim"))
from harness_model import model_run  # noqa: E402
from rv_progs import Prog  # noqa: E402

OUT = ROOT / "build" / "sim" / "test"
CAUSE_NAMES = {v: k for k, v in STOP_CAUSES.items()}
SUMMARY = re.compile(r"^tb_top: (?P<result>\S+)(?P<details>.*?)(?: cycles=(?P<cycles>\d+))? exit=(?P<exit>\d+)$")
DEFAULT_MAX_CYCLES = 1_000_000

EXE: Path
failures: list[str] = []
checks = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class Result:
    def __init__(self, proc: subprocess.CompletedProcess, seconds: float):
        self.code = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr.decode(errors="replace")
        self.seconds = seconds
        last = self.stderr.strip().splitlines()[-1] if self.stderr.strip() else ""
        self.summary = SUMMARY.match(last)
        self.last_line = last

    @property
    def result(self):
        return self.summary["result"] if self.summary else None

    @property
    def cycles(self):
        return int(self.summary["cycles"]) if self.summary and self.summary["cycles"] else None


def run(args: list[str], cwd: Path | None = None, timeout: float = 120) -> Result:
    t0 = time.monotonic()
    proc = subprocess.run([str(EXE), *args], capture_output=True, cwd=cwd, timeout=timeout)
    return Result(proc, time.monotonic() - t0)


def check(name: str, cond: bool, msg: str = ""):
    global checks
    checks += 1
    if not cond:
        failures.append(f"{name}: {msg}")
        print(f"  FAIL  {name}: {msg}")


def write_image(name: str, image: dict[int, int]) -> Path:
    path = OUT / f"{name}.hex"
    write_hex(image, path)
    return path


def tohost_end(p: Prog, value_reg: int) -> Prog:
    """Store register value_reg to tohost (x9 holds the address)."""
    return p.li(9, sim_scenarios.TOHOST)("SW", rs1=9, rs2=value_reg, imm=0)("ECALL")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_scenarios():
    """Every rv_soc_sim scenario, against the model."""
    for sc in sim_scenarios.SOC_RUNS:
        name = f"scenario {sc.name}"
        args, env = sc.plusargs(OUT)
        if sc.image() is None:   # no program: the harness requires +hex=
            r = run(args)
            check(name, r.code == 5 and "missing +hex" in r.stderr, f"exit {r.code}: {r.last_line}")
            continue
        args.append(f"+max_cycles={sc.max_cycles}")
        r = run(args)
        exp = model_run(sc.image(), sc.tohost, sc.max_cycles)
        code, cycles, lines, console, tohost = exp.code, exp.cycles, exp.lines, exp.console, exp.tohost
        check(name, r.summary is not None, f"no result line in stderr: {r.stderr!r}")
        check(name, r.code == code, f"exit {r.code}, expected {code} ({r.last_line})")
        check(name, r.cycles == cycles, f"cycles={r.cycles}, expected {cycles}")
        check(name, r.stdout == console, f"console {r.stdout!r}, expected {console!r}")
        if tohost is not None:
            check(name, f"tohost={tohost:08x}" in r.last_line, f"tohost {tohost:08x} not in {r.last_line!r}")
        got = Path(env["SIM_LOG"]).read_text(encoding="ascii")
        got_lines = got.splitlines()
        first_bad = next((i for i, (g, e) in enumerate(zip(got_lines, lines)) if g != e), None)
        check(name, first_bad is None,
              f"retire log line {first_bad}:\n    got      {got_lines[first_bad]}\n    expected {lines[first_bad]}"
              if first_bad is not None else "")
        check(name, len(got_lines) == len(lines), f"retire log has {len(got_lines)} lines, expected {len(lines)}")
        check(name, got == "" or got.endswith("\n"), "retire log does not end with a newline")
        print(f"  ok    {sc.name:22s} exit={r.code} cycles={r.cycles} ({r.seconds:.2f}s)")


def check_stop_causes_named():
    """The result line names the stop cause and the stopping PC."""
    for sc in sim_scenarios.SOC_RUNS:
        x = sc.expect
        if "cause" not in x or sc.image() is None or x.get("done"):
            continue
        args, _ = sc.plusargs(OUT)
        r = run(args + [f"+max_cycles={sc.max_cycles}"])
        check(f"cause {sc.name}", x["cause"] in r.last_line, f"{x['cause']} not in {r.last_line!r}")
        check(f"cause {sc.name}", re.search(r"pc=[0-9a-f]{8}", r.last_line) is not None,
              f"no pc= in {r.last_line!r}")


def check_harness_errors():
    ok_hex = write_image("ok", tohost_end(Prog().init_regs()("ADDI", rd=10, rs1=0, imm=1), 10).image())
    words = sim_scenarios.MEM_SIZE_BYTES // 4
    bad_images = {
        "hex with Z digits": "@00000000\nZZZZZZZZ\n",
        "hex with x digits": "@00000000\n0000x093\n",
        "hex word too long": "@00000000\n000000093\n",
        "hex @address outside RAM": f"@{words:08X}\n00000013\n",
        "hex data past end of RAM": f"@{words - 1:08X}\n00000013 00000013\n",
        "hex single slash": "@00000000\n00000013 / comment\n",
        "hex empty": "// nothing here\n",
    }
    paths = {}
    for name, text in bad_images.items():
        paths[name] = OUT / f"bad_{len(paths)}.hex"
        paths[name].write_text(text, encoding="ascii")
    missing = OUT / "does_not_exist.hex"
    no_dir_log = OUT / "no_such_dir" / "x.log"
    cases = [(name, [f"+hex={path.as_posix()}"]) for name, path in paths.items()] + [
        ("no arguments", []),
        ("missing hex file", [f"+hex={missing.as_posix()}"]),
        ("tohost with 0x", [f"+hex={ok_hex.as_posix()}", "+tohost=0x8000f000"]),
        ("tohost not hex", [f"+hex={ok_hex.as_posix()}", "+tohost=zz"]),
        ("tohost too wide", [f"+hex={ok_hex.as_posix()}", "+tohost=18000f000"]),
        ("tohost empty", [f"+hex={ok_hex.as_posix()}", "+tohost="]),
        ("max_cycles 0", [f"+hex={ok_hex.as_posix()}", "+max_cycles=0"]),
        ("max_cycles text", [f"+hex={ok_hex.as_posix()}", "+max_cycles=abc"]),
        ("max_cycles negative", [f"+hex={ok_hex.as_posix()}", "+max_cycles=-5"]),
        ("max_cycles hex", [f"+hex={ok_hex.as_posix()}", "+max_cycles=0x10"]),
        ("unknown plusarg", [f"+hex={ok_hex.as_posix()}", "+bogus=1"]),
        ("positional argument", [f"+hex={ok_hex.as_posix()}", "extra"]),
        ("retire log not writable", [f"+hex={ok_hex.as_posix()}", f"+retire_log={no_dir_log.as_posix()}"]),
        ("waves not writable", [f"+hex={ok_hex.as_posix()}", f"+waves={(OUT / 'no_such_dir' / 'w').as_posix()}"]),
    ]
    for name, args in cases:
        r = run(args)
        check(f"harness error: {name}", r.code == 5 and r.result == "harness", f"exit {r.code}: {r.last_line!r}")
    print(f"  ok    {len(cases)} harness-error cases")

    # Sanity: the same image with good arguments passes (so the cases above
    # failed for the argument, not the image).
    r = run([f"+hex={ok_hex.as_posix()}", f"+tohost={sim_scenarios.TOHOST:08x}"])
    check("harness error: control run", r.code == 0 and r.result == "PASS", f"exit {r.code}: {r.last_line!r}")
    # The same image in objcopy's layout (comments, lower case, short words,
    # last RAM word used) is accepted.
    text = ok_hex.read_text(encoding="ascii").lower().replace("00000013", "13")
    alt = OUT / "ok_alt.hex"
    alt.write_text(f"// objcopy-style\n{text}@{words - 1:x} // last word\n0\n", encoding="ascii")
    r = run([f"+hex={alt.as_posix()}", f"+tohost={sim_scenarios.TOHOST:08x}"])
    check("harness error: objcopy-style image", r.code == 0 and r.result == "PASS", f"exit {r.code}: {r.last_line!r}")


def check_timeout():
    loop = write_image("loop", Prog().init_regs()("JAL", rd=0, imm=0).image())
    r = run([f"+hex={loop.as_posix()}", "+max_cycles=50", f"+retire_log={(OUT / 'loop.log').as_posix()}"])
    check("timeout 50", r.code == 2 and r.result == "TIMEOUT" and r.cycles == 50, f"exit {r.code}: {r.last_line!r}")
    n = len((OUT / "loop.log").read_text(encoding="ascii").splitlines())
    check("timeout 50", n == 50, f"retire log has {n} lines, expected 50")
    r = run([f"+hex={loop.as_posix()}"], timeout=600)
    check("timeout default", r.code == 2 and r.cycles == DEFAULT_MAX_CYCLES, f"exit {r.code}: {r.last_line!r}")
    print(f"  ok    timeout (default {DEFAULT_MAX_CYCLES} cycles took {r.seconds:.1f}s)")


def check_waves():
    sc = sim_scenarios.find("pass")
    args, _ = sc.plusargs(OUT)
    base = run(args)
    wave = OUT / "pass.wave"
    wave.unlink(missing_ok=True)
    r = run(args + [f"+waves={wave.as_posix()}"])
    check("waves", r.code == base.code == 0 and r.stdout == base.stdout and r.cycles == base.cycles,
          f"result changed with +waves: {r.last_line!r} vs {base.last_line!r}")
    check("waves", wave.exists() and wave.stat().st_size > 1000, "wave file missing or tiny")
    # Bare +waves: the default file name in the working directory.
    cwd = OUT / "waves_cwd"
    cwd.mkdir(exist_ok=True)
    for f in cwd.iterdir():
        f.unlink()
    r = run([a for a in args if not a.startswith("+retire_log=")] + ["+waves"], cwd=cwd)
    made = [f.name for f in cwd.iterdir()]
    check("waves default name", r.code == 0 and len(made) == 1 and made[0] in ("waves.fst", "waves.vcd")
          and (cwd / made[0]).stat().st_size > 1000, f"exit {r.code}, files {made}")
    print(f"  ok    waves ({', '.join(made)})")


def check_random_reset():
    """x5 is never written: the program stores it to tohost."""
    p = Prog()("ADD", rd=10, rs1=5, rs2=0)
    img = write_image("uninit", tohost_end(p, 10).image())
    th = f"+tohost={sim_scenarios.TOHOST:08x}"

    def value(*extra):
        r = run([f"+hex={img.as_posix()}", th, *extra])
        m = re.search(r"tohost=([0-9a-f]{8})", r.last_line)
        check("random reset", r.code in (0, 1) and m is not None, f"exit {r.code}: {r.last_line!r}")
        return int(m[1], 16) if m else None

    default = value()
    seeds = {s: value(f"+verilator+seed+{s}") for s in (1, 2, 3, 4)}
    zero = value("+verilator+rand+reset+0")
    check("random reset", default == seeds[1], f"default {default!r} differs from seed 1 {seeds[1]!r}")
    check("random reset", value("+verilator+seed+2") == seeds[2], "same seed, different value")
    check("random reset", len(set(seeds.values())) == len(seeds), f"seeds give {seeds}")
    check("random reset", all(v not in (0, None) for v in seeds.values()), f"seeds give {seeds}")
    check("random reset", zero == 0, f"rand+reset+0 gives {zero!r}")
    print(f"  ok    random reset: seeds 1-4 give {', '.join(f'{v:08x}' for v in seeds.values() if v is not None)}")


def check_signature():
    data = sim_scenarios.DATA
    cases = [("pass", data - 0x40, data + 0x40), ("pass", 0x8000_0000, 0x8000_0100),
             ("bus_store_above_ram", 0x8000_0000, 0x8000_0080), ("pass", data, data),
             ("fail", sim_scenarios.TOHOST, sim_scenarios.TOHOST + 8),
             ("pass", 0x8001_0000 - 0x20, 0x8001_0000)]
    for name, lo, hi in cases:
        sc = sim_scenarios.find(name)
        args, _ = sc.plusargs(OUT)
        sig = OUT / f"{name}.sig"
        sig.unlink(missing_ok=True)
        r = run(args + [f"+max_cycles={sc.max_cycles}", f"+signature={sig.as_posix()}",
                        f"+sig_begin={lo:08x}", f"+sig_end={hi:08x}"])
        exp = model_run(sc.image(), sc.tohost, sc.max_cycles)
        tag = f"signature {name} [{lo:08x}, {hi:08x})"
        check(tag, r.code == exp.code, f"exit {r.code}, expected {exp.code}: {r.last_line!r}")
        got = sig.read_bytes().decode("ascii") if sig.exists() else None
        check(tag, got == exp.signature(lo, hi), f"got {got!r:.120}")

    sc = sim_scenarios.find("pass")
    args, _ = sc.plusargs(OUT)
    sig = (OUT / "x.sig").as_posix()
    bad = [
        ("only +signature=", [f"+signature={sig}"]),
        ("no +sig_end=", [f"+signature={sig}", "+sig_begin=80000000"]),
        ("no +signature=", ["+sig_begin=80000000", "+sig_end=80000010"]),
        ("unaligned begin", [f"+signature={sig}", "+sig_begin=80000002", "+sig_end=80000010"]),
        ("unaligned end", [f"+signature={sig}", "+sig_begin=80000000", "+sig_end=80000011"]),
        ("begin above end", [f"+signature={sig}", "+sig_begin=80000010", "+sig_end=80000000"]),
        ("below RAM", [f"+signature={sig}", "+sig_begin=7ffffffc", "+sig_end=80000010"]),
        ("above RAM", [f"+signature={sig}", "+sig_begin=8000fff0", "+sig_end=80010004"]),
        ("0x prefix", [f"+signature={sig}", "+sig_begin=0x80000000", "+sig_end=80000010"]),
        ("not writable", [f"+signature={(OUT / 'no_such_dir' / 's').as_posix()}", "+sig_begin=80000000",
                          "+sig_end=80000010"]),
    ]
    for name, extra in bad:
        r = run(args + extra)
        check(f"signature error: {name}", r.code == 5 and r.result == "harness", f"exit {r.code}: {r.last_line!r}")
    print(f"  ok    signature: {len(cases)} ranges, {len(bad)} bad-argument cases")


def main() -> int:
    global EXE
    if len(sys.argv) != 2:
        print(__doc__.splitlines()[2])
        return 1
    EXE = Path(sys.argv[1])
    if not EXE.exists():
        print(f"test_tb_top: {EXE} not found (run make sim-build)")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    for fn in (check_scenarios, check_stop_causes_named, check_harness_errors, check_timeout,
               check_waves, check_signature, check_random_reset):
        print(f"{fn.__name__}:")
        fn()

    print()
    if failures:
        print(f"test_tb_top: {len(failures)} of {checks} checks FAILED")
        return 1
    print(f"test_tb_top: all {checks} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
