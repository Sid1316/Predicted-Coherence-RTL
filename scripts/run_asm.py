"""Build and run the directed assembly tests in sw/asm/ (docs/exec.md M3.5, docs/spec.md §11, §15.2).

Usage: run_asm.py --exe <Vrv_soc_sim> [-v] [test ...]
  test: a name (t00_lui_addi), a name prefix (t00, e01) or a path to a .S file.
  Default: every sw/asm/*.S.

For each test:
  1. build: riscv*-gcc (spec §12 flags, sw/common/link.ld) -> .elf; objcopy
     -> .hex ($readmemh image, word-indexed from MEM_BASE); objdump -> .dis;
     nm -> the tohost address. Output in build/asm/<name>.*.
  2. run: the Verilator harness with +hex= +tohost= +retire_log=.
  3. check: the exit code (and stop cause) against the test's
     "// expect: <code> [<cause>]" header, the console output against an
     optional "// console: <text>" header (Python escapes), and the retire
     log, line for line, against the Python model running the same image
     (tb/sim/harness_model.py). The model comparison catches a wrong result
     that the test's own checks would compute the same wrong way.

Exit code: 0 if every test passed, 1 otherwise.
"""

import argparse
import codecs
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASM_DIR = ROOT / "sw" / "asm"
LINK_LD = ROOT / "sw" / "common" / "link.ld"
OUT = ROOT / "build" / "asm"
MAX_CYCLES = 100_000

sys.path.insert(0, str(ROOT / "tb" / "sim"))
sys.path.insert(0, str(ROOT / "tb" / "unit"))
from harness_model import model_run  # noqa: E402
from rv_model import MEM_BASE, read_hex  # noqa: E402

CFLAGS = ["-march=rv32i", "-mabi=ilp32", "-nostdlib", "-nostartfiles", "-ffreestanding", "-static",
          "-mcmodel=medany", "-Wl,--no-warn-rwx-segments"]
EXPECT = re.compile(r"^\s*(?://|#)\s*expect:\s*(\d+)(?:\s+(STOP_[A-Z_]+))?\s*$")
CONSOLE = re.compile(r"^\s*(?://|#)\s*console:\s?(.*)$")
RESULT = re.compile(r"^tb_top: .* exit=\d+$")


class TestError(Exception):
    pass


def tool(name: str) -> str:
    prefix = os.environ.get("RISCV_PREFIX", "riscv-none-elf-")
    exe = shutil.which(prefix + name)
    if exe is None:
        raise SystemExit(f"run_asm: {prefix}{name} not found on PATH (set RISCV_PREFIX)")
    return exe


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, **kw)
    if p.returncode != 0:
        raise TestError(f"{Path(cmd[0]).name} failed:\n{p.stderr.decode(errors='replace')}")
    return p


def header(src: Path) -> tuple[int, str | None, bytes | None]:
    code = cause = console = None
    for line in src.read_text(encoding="utf-8").splitlines()[:10]:
        if m := EXPECT.match(line):
            code, cause = int(m[1]), m[2]
        elif m := CONSOLE.match(line):
            console = codecs.decode(m[1], "unicode_escape").encode("latin-1")
    if code is None:
        raise TestError("no '// expect: <code> [<cause>]' line in the first 10 lines")
    return code, cause, console


def build(src: Path) -> tuple[Path, int]:
    name = src.stem
    elf, hexf, dis = OUT / f"{name}.elf", OUT / f"{name}.hex", OUT / f"{name}.dis"
    sh([tool("gcc"), *CFLAGS, "-T", str(LINK_LD), "-I", str(ASM_DIR), str(src), "-o", str(elf)])
    sh([tool("objcopy"), "-O", "verilog", "--verilog-data-width=4",
        f"--change-addresses=-{MEM_BASE:#x}", str(elf), str(hexf)])
    dis.write_bytes(sh([tool("objdump"), "-d", "-M", "no-aliases", str(elf)]).stdout)
    syms = sh([tool("nm"), str(elf)]).stdout.decode().splitlines()   # CRLF on Windows
    m = next((m for line in syms if (m := re.fullmatch(r"([0-9a-fA-F]+) \w tohost", line.strip()))), None)
    if m is None:
        raise TestError("no tohost symbol (TEST_DATA missing?)")
    return hexf, int(m[1], 16)


def run_test(src: Path, exe: Path, verbose: bool) -> str:
    """Return a one-line result description; raise TestError on failure."""
    code, cause, console = header(src)
    hexf, tohost = build(src)
    log = OUT / f"{src.stem}.retire.log"
    p = subprocess.run([str(exe), f"+hex={hexf.as_posix()}", f"+tohost={tohost:08x}",
                        f"+retire_log={log.as_posix()}", f"+max_cycles={MAX_CYCLES}"],
                       capture_output=True, timeout=120)
    err = p.stderr.decode(errors="replace").strip().splitlines()
    result = next((l for l in reversed(err) if RESULT.match(l)), "(no result line)")
    if verbose:
        sys.stdout.write(p.stdout.decode(errors="replace"))
        print(result)

    problems = []
    if p.returncode != code:
        problems.append(f"exit {p.returncode}, expected {code}")
    if cause and cause not in result:
        problems.append(f"expected {cause}")
    if console is not None and p.stdout != console:
        problems.append(f"console {p.stdout!r}, expected {console!r}")

    # The same image on the model.
    exp = model_run(read_hex(hexf), tohost, MAX_CYCLES)
    got = log.read_text(encoding="ascii").splitlines()
    if exp.code != p.returncode:
        problems.append(f"model exits {exp.code}")
    if p.stdout != exp.console:
        problems.append(f"model console {exp.console!r}")
    for n, (g, e) in enumerate(zip(got, exp.lines)):
        if g != e:
            problems.append(f"retire log differs from the model at line {n} "
                            f"(see build/asm/{src.stem}.dis):\n      rtl   {g}\n      model {e}")
            break
    else:
        if len(got) != len(exp.lines):
            problems.append(f"retire log has {len(got)} lines, model {len(exp.lines)}")
    if problems:
        raise TestError(f"{result}\n    " + "\n    ".join(problems))
    return result.removeprefix("tb_top: ")


def select(names: list[str]) -> list[Path]:
    every = sorted(ASM_DIR.glob("*.S"))
    if not names:
        return every
    out = []
    for n in names:
        p = Path(n)
        if p.suffix == ".S" or p.exists() or p.with_suffix(".S").exists():
            p = p if p.suffix == ".S" else p.with_suffix(".S")
            if not p.exists():
                raise SystemExit(f"run_asm: {p} not found")
            out.append(p.resolve())
            continue
        hits = [s for s in every if s.stem == n or s.stem.startswith(n)]
        if not hits:
            raise SystemExit(f"run_asm: no test matches '{n}'")
        out += hits
    return list(dict.fromkeys(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", required=True, type=Path, help="the Verilator simulator (make sim-build)")
    ap.add_argument("-v", "--verbose", action="store_true", help="show console output and the result line")
    ap.add_argument("tests", nargs="*")
    args = ap.parse_args()
    if not args.exe.exists():
        raise SystemExit(f"run_asm: {args.exe} not found (run make sim-build)")
    OUT.mkdir(parents=True, exist_ok=True)

    failed = 0
    tests = select(args.tests)
    for src in tests:
        try:
            print(f"  PASS  {src.stem:24s} {run_test(src, args.exe, args.verbose)}")
        except (TestError, subprocess.TimeoutExpired) as e:
            failed += 1
            print(f"  FAIL  {src.stem:24s} {e}")
    print(f"\nrun_asm: {len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
