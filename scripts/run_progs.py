"""Build and run programs on the RTL: the directed tests in sw/asm/, the C programs in sw/c/ and
the riscv-tests rv32ui suite (docs/exec.md M3.5, M4, M5.1-M5.2; docs/spec.md §11, §12, §15).

Usage: run_progs.py --exe <Vrv_soc_sim> [-v] [program ...]
  program: a suite (asm, c, rv32ui, or the directory sw/asm, sw/c), a path to
  a .S/.c file or a C program directory, or a name / name prefix (t00, e01,
  hello, rv32ui-p-add).
  Default: every program in all three suites.

Programs:
  - sw/asm/<name>.S: a directed test (sw/asm/test.h), linked alone.
  - sw/c/<name>.c, or a directory sw/c/<name>/ with .c/.S files: a C program,
    linked with sw/common/crt0.S, the rvlib sources in sw/common/lib/ and
    libgcc (software multiply/divide).
  - tests/riscv-tests/isa/rv32ui/<test>.S, named rv32ui-p-<test>: built with
    the custom env sw/common/env/p/riscv_test.h (spec §12). Upstream files
    have no header: each must pass (exit 0), except the tests listed in
    tests/riscv-tests-waivers.txt, which must end with the result recorded
    there.
  Both use sw/common/link.ld and the spec §12 flags. Output goes to
  build/<suite>/<name>.{elf,hex,dis,map,retire.log}.

Each program declares what it expects in comments at the top of its main
source (the .S/.c file, or main.c in a directory):
  // expect: <exit code> [<stop cause>]    required (spec §11)
  // console: <text>                       console output, Python escapes (\\n)
  // tohost: <hex>                         the value stored to tohost
  // max_cycles: <n>                       default 100000

For each program: build, convert (scripts/elf2hex.py), run the harness, check
the expectations, and replay the same image on the Python model
(tb/sim/harness_model.py): the exit code, console bytes and every line of
the retire log must match. The model comparison catches a wrong result that
the program's own checks would compute the same wrong way.

Exit code: 0 if every program passed, 1 otherwise.
"""

import argparse
import codecs
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASM_DIR = ROOT / "sw" / "asm"
C_DIR = ROOT / "sw" / "c"
RV32UI_DIR = ROOT / "tests" / "riscv-tests" / "isa" / "rv32ui"
RV_MACROS = ROOT / "tests" / "riscv-tests" / "isa" / "macros" / "scalar"
RV_ENV = ROOT / "sw" / "common" / "env" / "p"
WAIVERS = ROOT / "tests" / "riscv-tests-waivers.txt"
COMMON = ROOT / "sw" / "common"
LINK_LD = COMMON / "link.ld"
BUILD = ROOT / "build"
DEFAULT_MAX_CYCLES = 100_000

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tb" / "sim"))
sys.path.insert(0, str(ROOT / "tb" / "unit"))
from elf2hex import Elf2HexError, elf2hex, tool  # noqa: E402
from harness_model import model_run  # noqa: E402
from rv_model import read_hex  # noqa: E402

# spec §12. -fno-tree-loop-distribute-patterns: without it GCC turns the
# loops in memset/memcpy into calls to memset/memcpy.
COMMON_FLAGS = ["-march=rv32i", "-mabi=ilp32", "-static", "-nostdlib", "-nostartfiles",
                "-mcmodel=medany", "-T", str(LINK_LD), "-Wl,--no-warn-rwx-segments"]
C_FLAGS = ["-O2", "-g", "-ffreestanding", "-fno-tree-loop-distribute-patterns", "-Wall", "-Wextra",
           "-I", str(COMMON / "include")]

HEADER = re.compile(r"^\s*(?://|#)\s*(expect|console|tohost|max_cycles):\s?(.*?)\s*$")
EXPECT = re.compile(r"(\d+)(?:\s+(STOP_[A-Z_]+))?")
RESULT = re.compile(r"^tb_top: .* exit=\d+$")


class ProgError(Exception):
    pass


@dataclass
class Prog:
    name: str
    suite: str                 # "asm", "c" or "rv32ui"
    main: Path                 # source holding the header
    sources: list[Path]
    expect: dict | None = None # instead of the header (upstream tests)
    note: str = ""             # shown after the result (e.g. the waiver reason)

    @property
    def out(self) -> Path:
        return BUILD / self.suite / self.name


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def c_prog(path: Path) -> Prog:
    if path.is_dir():
        srcs = sorted([*path.glob("*.c"), *path.glob("*.S")])
        if not srcs:
            raise SystemExit(f"run_progs: {path} holds no .c/.S files")
        main = path / "main.c" if (path / "main.c").exists() else srcs[0]
        return Prog(path.name, "c", main, srcs)
    return Prog(path.stem, "c", path, [path])


WAIVER = re.compile(r"(\S+)\s+(\d+)(?:\s+(STOP_[A-Z_]+))?\s+--\s+(.+)")


def waivers() -> dict[str, tuple[int, str | None, str]]:
    out = {}
    for line in WAIVERS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = WAIVER.fullmatch(line)
        if not m:
            raise SystemExit(f"run_progs: bad line in {WAIVERS.name}: {line}")
        out[m[1]] = (int(m[2]), m[3], m[4])
    return out


def suite(name: str) -> list[Prog]:
    if name == "asm":
        return [Prog(p.stem, "asm", p, [p]) for p in sorted(ASM_DIR.glob("*.S"))]
    if name == "rv32ui":
        w = waivers()
        unknown = set(w) - {p.stem for p in RV32UI_DIR.glob("*.S")}
        if unknown:
            raise SystemExit(f"run_progs: {WAIVERS.name} names unknown tests: {', '.join(sorted(unknown))}")
        progs = []
        for p in sorted(RV32UI_DIR.glob("*.S")):
            code, cause, reason = w.get(p.stem, (0, None, ""))
            exp = {"code": code, "cause": cause, "max_cycles": DEFAULT_MAX_CYCLES}
            progs.append(Prog(f"rv32ui-p-{p.stem}", "rv32ui", p, [p], exp,
                              f"(waived: {reason})" if reason else ""))
        return progs
    progs = [c_prog(p) for p in sorted(C_DIR.glob("*.c"))]
    progs += [c_prog(p) for p in sorted(C_DIR.iterdir())
              if p.is_dir() and any(p.glob("*.c"))]
    return sorted(progs, key=lambda p: p.name)


SUITES = ("asm", "c", "rv32ui")


def select(args: list[str]) -> list[Prog]:
    every = [g for s in SUITES for g in suite(s)]
    if not args:
        return every
    out: list[Prog] = []
    for a in args:
        if a in SUITES:
            out += suite(a)
            continue
        p = Path(a).resolve() if Path(a).exists() else None
        if p is None and Path(a).with_suffix(".S").exists():
            p = Path(a).with_suffix(".S").resolve()
        if p is None and Path(a).with_suffix(".c").exists():
            p = Path(a).with_suffix(".c").resolve()
        if p == ASM_DIR:
            out += suite("asm")
        elif p == C_DIR:
            out += suite("c")
        elif p == RV32UI_DIR:
            out += suite("rv32ui")
        elif p is not None and p.suffix == ".S" and p.parent == RV32UI_DIR:
            out += [g for g in suite("rv32ui") if g.main == p]
        elif p is not None and p.suffix == ".S" and p.parent == ASM_DIR:
            out.append(Prog(p.stem, "asm", p, [p]))
        elif p is not None and (p.suffix == ".c" or p.is_dir()):
            out.append(c_prog(p))
        elif p is not None:
            raise SystemExit(f"run_progs: don't know how to build {a}")
        else:
            hits = [g for g in every if g.name == a or g.name.startswith(a)]
            if not hits:
                raise SystemExit(f"run_progs: no program matches '{a}'")
            out += hits
    seen, uniq = set(), []
    for g in out:
        if (g.suite, g.name) not in seen:
            seen.add((g.suite, g.name))
            uniq.append(g)
    return uniq


# ---------------------------------------------------------------------------
# Build, run, check
# ---------------------------------------------------------------------------

def header(src: Path) -> dict:
    h = {"max_cycles": DEFAULT_MAX_CYCLES}
    for line in src.read_text(encoding="utf-8").splitlines()[:15]:
        m = HEADER.match(line)
        if not m:
            continue
        key, val = m[1], m[2]
        if key == "expect":
            e = EXPECT.fullmatch(val)
            if not e:
                raise ProgError(f"bad header 'expect: {val}'")
            h["code"], h["cause"] = int(e[1]), e[2]
        elif key == "console":
            h["console"] = codecs.decode(val, "unicode_escape").encode("latin-1")
        elif key == "tohost":
            h["tohost"] = int(val, 16)
        elif key == "max_cycles":
            h["max_cycles"] = int(val)
    if "code" not in h:
        raise ProgError(f"{src.name}: no '// expect: <code> [<cause>]' header in the first 15 lines")
    return h


def build(g: Prog) -> tuple[Path, int, str]:
    """Return (hex image, tohost address, compiler warnings)."""
    g.out.parent.mkdir(parents=True, exist_ok=True)
    elf = g.out.with_suffix(".elf")
    if g.suite == "asm":
        cmd = [tool("gcc"), *COMMON_FLAGS, "-I", str(ASM_DIR), *map(str, g.sources)]
    elif g.suite == "rv32ui":
        # _zifencei only lets the assembler accept fence.i, so the waived
        # fence_i test builds and can be shown to stop with STOP_ILLEGAL: the
        # core itself has no Zifencei (spec §4.2 rule 3).
        flags = [f if f != "-march=rv32i" else "-march=rv32i_zifencei" for f in COMMON_FLAGS]
        cmd = [tool("gcc"), *flags, "-I", str(RV_ENV), "-I", str(RV_MACROS), *map(str, g.sources)]
    else:
        lib = sorted((COMMON / "lib").glob("*.c"))
        cmd = [tool("gcc"), *COMMON_FLAGS, *C_FLAGS, str(COMMON / "crt0.S"), *map(str, g.sources),
               *map(str, lib), "-lgcc", f"-Wl,-Map={g.out.with_suffix('.map')}"]
    p = subprocess.run([*cmd, "-o", str(elf)], capture_output=True)
    warnings = p.stderr.decode(errors="replace").strip()
    if p.returncode != 0:
        raise ProgError(f"build failed:\n{warnings}")
    dis = subprocess.run([tool("objdump"), "-d", "-S" if g.suite == "c" else "-d", str(elf)],
                         capture_output=True)
    g.out.with_suffix(".dis").write_bytes(dis.stdout)
    hexf = g.out.with_suffix(".hex")
    try:
        tohost = elf2hex(elf, hexf)
    except Elf2HexError as e:
        raise ProgError(str(e)) from None
    return hexf, tohost, warnings


def run_prog(g: Prog, exe: Path, verbose: bool, extra: list[str]) -> str:
    """Return the harness result line; raise ProgError on any failed check."""
    h = g.expect if g.expect is not None else header(g.main)
    hexf, tohost, warnings = build(g)
    if warnings:
        print(f"  ----  {g.name}: compiler output:\n{warnings}")
    log = g.out.with_suffix(".retire.log")
    p = subprocess.run([str(exe), f"+hex={hexf.as_posix()}", f"+tohost={tohost:08x}",
                        f"+retire_log={log.as_posix()}", f"+max_cycles={h['max_cycles']}", *extra],
                       capture_output=True, timeout=600)
    err = p.stderr.decode(errors="replace").strip().splitlines()
    result = next((l for l in reversed(err) if RESULT.match(l)), "(no result line)")
    if verbose:
        sys.stdout.write(p.stdout.decode(errors="replace"))
        print(result)

    problems = []
    if p.returncode != h["code"]:
        problems.append(f"exit {p.returncode}, expected {h['code']}")
    if h["cause"] and h["cause"] not in result:
        problems.append(f"expected {h['cause']}")
    if "console" in h and p.stdout != h["console"]:
        problems.append(f"console {p.stdout!r}, expected {h['console']!r}")
    if "tohost" in h and f"tohost={h['tohost']:08x}" not in result:
        problems.append(f"expected tohost={h['tohost']:08x}")

    exp = model_run(read_hex(hexf), tohost, h["max_cycles"])
    got = log.read_text(encoding="ascii").splitlines()
    if exp.code != p.returncode:
        problems.append(f"model exits {exp.code}")
    if p.stdout != exp.console:
        problems.append(f"model console {exp.console!r}")
    for n, (gl, el) in enumerate(zip(got, exp.lines)):
        if gl != el:
            problems.append(f"retire log differs from the model at line {n} (see {g.out.with_suffix('.dis')}):"
                            f"\n      rtl   {gl}\n      model {el}")
            break
    else:
        if len(got) != len(exp.lines):
            problems.append(f"retire log has {len(got)} lines, model {len(exp.lines)}")
    if problems:
        raise ProgError(f"{result}\n    " + "\n    ".join(problems))
    return result.removeprefix("tb_top: ") + (f"  {g.note}" if g.note else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", required=True, type=Path, help="the Verilator simulator (make sim-build)")
    ap.add_argument("-v", "--verbose", action="store_true", help="show console output and the result line")
    ap.add_argument("--waves", type=Path, help="write a wave file (one program only)")
    ap.add_argument("--seed", type=int, help="+verilator+seed+ for the random register reset")
    ap.add_argument("programs", nargs="*")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    extra = []
    if args.seed is not None:
        extra.append(f"+verilator+seed+{args.seed}")
    if not args.exe.exists():
        raise SystemExit(f"run_progs: {args.exe} not found (run make sim-build)")

    progs = select(args.programs)
    if args.waves is not None:
        if len(progs) != 1:
            raise SystemExit("run_progs: --waves needs exactly one program")
        extra.append(f"+waves={args.waves.as_posix()}")
    failed = 0
    for g in progs:
        label = f"{g.suite}/{g.name}"
        try:
            print(f"  PASS  {label:28s} {run_prog(g, args.exe, args.verbose, extra)}")
        except (ProgError, Elf2HexError, subprocess.TimeoutExpired) as e:
            failed += 1
            print(f"  FAIL  {label:28s} {e}")
    print(f"\nrun_progs: {len(progs) - failed}/{len(progs)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
