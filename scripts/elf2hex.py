"""Convert an ELF to the rv_mem_model $readmemh image and find its tohost address (docs/exec.md M4.4).

Usage: elf2hex.py <prog.elf> <prog.hex>     prints the tohost address (hex, no 0x)

The image is what `objcopy -O verilog --verilog-data-width=4
--change-addresses=-MEM_BASE` writes: one 32-bit word per entry, `@<n>` =
word index n from MEM_BASE (the format sim/rv_mem_model.sv documents and
sim/tb_top.cpp checks). Every loadable section must lie inside RAM; a section
outside it is reported here rather than as a harness error later. The tohost
address comes from `nm` (spec §11) and is passed to the harness as +tohost=.

Tools: $RISCV_PREFIX (default riscv-none-elf-) objcopy, nm, readelf.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MEM_BASE = 0x8000_0000
MEM_SIZE_BYTES = 0x1_0000


class Elf2HexError(Exception):
    pass


def tool(name: str) -> str:
    prefix = os.environ.get("RISCV_PREFIX", "riscv-none-elf-")
    exe = shutil.which(prefix + name)
    if exe is None:
        raise Elf2HexError(f"{prefix}{name} not found on PATH (set RISCV_PREFIX)")
    return exe


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise Elf2HexError(f"{Path(cmd[0]).name} failed:\n{p.stderr.decode(errors='replace')}")
    return p.stdout.decode(errors="replace")


def check_sections(elf: Path, mem_size: int = MEM_SIZE_BYTES) -> None:
    """Every SHF_ALLOC section with contents (not NOBITS) must be inside RAM."""
    out = run([tool("readelf"), "-S", "-W", str(elf)])
    for line in out.splitlines():
        m = re.match(r"\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)\s+\S+\s+(\S*)", line)
        if not m:
            continue
        name, kind, addr, size, flags = m[1], m[2], int(m[3], 16), int(m[4], 16), m[5]
        if "A" not in flags or kind == "NOBITS" or size == 0:
            continue
        if not (MEM_BASE <= addr and addr + size <= MEM_BASE + mem_size):
            raise Elf2HexError(f"section {name} at {addr:#010x}+{size:#x} is outside RAM "
                               f"({MEM_BASE:#010x}..{MEM_BASE + mem_size:#010x})")


def tohost_address(elf: Path) -> int:
    for line in run([tool("nm"), str(elf)]).splitlines():   # CRLF on Windows: strip()
        m = re.fullmatch(r"([0-9a-fA-F]+) \w tohost", line.strip())
        if m:
            return int(m[1], 16)
    raise Elf2HexError(f"{elf.name}: no tohost symbol (spec §11: the program must define it)")


def elf2hex(elf: Path, hexf: Path, mem_size: int = MEM_SIZE_BYTES) -> int:
    """Write the image; return the tohost address. mem_size: RAM size in bytes."""
    check_sections(elf, mem_size)
    run([tool("objcopy"), "-O", "verilog", "--verilog-data-width=4",
         f"--change-addresses=-{MEM_BASE:#x}", str(elf), str(hexf)])
    return tohost_address(elf)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.splitlines()[2].strip(), file=sys.stderr)
        return 2
    try:
        print(f"{elf2hex(Path(sys.argv[1]), Path(sys.argv[2])):08x}")
    except Elf2HexError as e:
        print(f"elf2hex: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
