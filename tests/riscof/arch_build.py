"""Build one riscv-arch-test program, shared by both RISCOF plugins (docs/exec.md M5.3).

The DUT plugin (rv_core: the Verilator harness) and the reference plugin
(pymodel: the project's Python RV32I model, the reference chosen for Phase 1
in exec.md §8) build each test with exactly this command, so the two run the
same image and only the model differs.

Two things differ from the directed-test build (scripts/run_progs.py):
  - RAM is MEM_SIZE_BYTES = 2 MiB, not 64 KiB: jal-01 needs about 1.7 MiB
    and the branch tests up to 310 KiB. The link script takes the size via
    --defsym=__ram_size, the DUT runs on a simulator built with the same
    size (make riscof builds build/sim-2097152/), and the model gets it too.
  - -mno-relax: arch_test.h's LA() macro switches on .option rvc around its
    .align padding, and with linker relaxation ld fills that padding with
    compressed c.nop, which this RV32I core rejects as illegal. Without
    relaxation the padding is made of 4-byte nops.
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = Path(__file__).resolve().parent / "env"
LINK_LD = ROOT / "sw" / "common" / "link.ld"
MAX_CYCLES = 2_000_000
MEM_SIZE_BYTES = 2 * 1024 * 1024

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tb" / "sim"))
sys.path.insert(0, str(ROOT / "tb" / "unit"))
from elf2hex import elf2hex, run, tool  # noqa: E402


@dataclass
class Built:
    hexf: Path
    tohost: int
    sig_begin: int
    sig_end: int


def symbol(elf: Path, name: str) -> int:
    for line in run([tool("nm"), str(elf)]).splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]+) \w " + re.escape(name), line.strip())
        if m:
            return int(m[1], 16)
    raise RuntimeError(f"{elf}: no symbol {name}")


def build(test: Path, work_dir: Path, isa: str, macros: list[str], archtest_env: Path) -> Built:
    """Compile test into work_dir/my.{elf,hex,dis}; return the image and its symbols."""
    elf = work_dir / "my.elf"
    cmd = [tool("gcc"), f"-march={isa.lower()}", "-mabi=ilp32", "-static", "-mcmodel=medany",
           "-fvisibility=hidden", "-nostdlib", "-nostartfiles", "-g", "-mno-relax", "-T", str(LINK_LD),
           f"-Wl,--defsym=__ram_size={MEM_SIZE_BYTES:#x}", "-Wl,-e,rvtest_entry_point",
           "-Wl,--no-warn-rwx-segments",
           "-I", str(ENV), "-I", str(archtest_env), *[f"-D{m}" for m in macros], str(test), "-o", str(elf)]
    p = subprocess.run(cmd, capture_output=True)
    (work_dir / "build.log").write_bytes(p.stdout + p.stderr)
    if p.returncode != 0:
        raise RuntimeError(f"build failed (see {work_dir / 'build.log'}):\n{p.stderr.decode(errors='replace')}")
    (work_dir / "my.dis").write_bytes(subprocess.run([tool("objdump"), "-d", str(elf)], capture_output=True).stdout)
    hexf = work_dir / "my.hex"
    tohost = elf2hex(elf, hexf, MEM_SIZE_BYTES)
    return Built(hexf, tohost, symbol(elf, "begin_signature"), symbol(elf, "end_signature"))
