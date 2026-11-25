"""Instruction-mix and dependency statistics from retire logs (docs/exec.md M7.2).

Usage: stats.py [--markdown] <name>=<prog.elf>:<prog.retire.log> ...
       stats.py [--markdown] --bench          (every program in build/bench/)

For each program (one complete run, CPI 1, so instructions = cycles):
  - instruction mix by class: ALU (OP, OP-IMM), load, store, branch, jump
    (JAL/JALR), upper-immediate (LUI/AUIPC), other (FENCE/ECALL/EBREAK)
  - branches: taken / not taken, and forward / backward by the sign of the
    offset (taken = the next retired PC is not pc + 4)
  - load-use pairs: a load directly followed by an instruction that reads
    the loaded register (the stall a 5-stage pipeline would need)
  - RAW dependencies at distance 1, 2, 3: instructions whose nearest
    producer of a source register (x1-x31) retired 1, 2 or 3 instructions
    earlier (what forwarding paths of each depth would have to cover)
  - time in libgcc multiply/divide: instructions retired inside __mulsi3,
    __divsi3, __udivsi3, __modsi3, __umodsi3, __muldi3, __divdi3, __udivdi3,
    __moddi3, __umoddi3 (address ranges from the ELF symbol table)
  - code size (.text.init + .text), data (.rodata/.data/.sdata/.bss, from the
    section headers) and stack depth (lowest value written to sp below
    _stack_top)
Percentages are of all retired instructions unless stated.
"""

import argparse
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tb" / "unit"))
from elf2hex import tool  # noqa: E402
from rv_model import FORMATS, decode_ref  # noqa: E402

MEM_BASE = 0x8000_0000
LIBGCC_MULDIV = {"__mulsi3", "__divsi3", "__udivsi3", "__modsi3", "__umodsi3",
                 "__muldi3", "__divdi3", "__udivdi3", "__moddi3", "__umoddi3"}
CLASSES = ["ALU", "load", "store", "branch", "jump", "upper-imm", "other"]
LOADS = {"LB", "LH", "LW", "LBU", "LHU"}
STORES = {"SB", "SH", "SW"}
BRANCHES = {"BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU"}
NO_SOURCES = {"LUI", "AUIPC", "JAL", "FENCE", "ECALL", "EBREAK", "illegal"}
LINE = re.compile(r"^[0-9a-f]{8} ([0-9a-f]{8}) ([0-9a-f]{8})(?: x(\d+) ([0-9a-f]{8}))?")


def klass(name: str) -> str:
    if name in LOADS:
        return "load"
    if name in STORES:
        return "store"
    if name in BRANCHES:
        return "branch"
    if name in ("JAL", "JALR"):
        return "jump"
    if name in ("LUI", "AUIPC"):
        return "upper-imm"
    if name in ("FENCE", "ECALL", "EBREAK", "illegal"):
        return "other"
    return "ALU"


def sources(name: str, insn: int) -> list[int]:
    """Registers (x1-x31) the instruction reads."""
    if name in NO_SOURCES:
        return []
    rs1, rs2 = insn >> 15 & 31, insn >> 20 & 31
    regs = [rs1, rs2] if FORMATS.get(name) in ("R", "S", "B") else [rs1]
    return [r for r in regs if r != 0]


@dataclass
class Stats:
    name: str
    insns: int = 0
    classes: Counter = field(default_factory=Counter)
    br_taken: int = 0
    br_not: int = 0
    br_fwd: int = 0
    br_bwd: int = 0
    br_bwd_taken: int = 0
    br_fwd_taken: int = 0
    load_use: int = 0
    raw: Counter = field(default_factory=Counter)      # nearest producer distance 1, 2, 3
    in_muldiv: int = 0
    text: int = 0
    data: int = 0
    stack: int = 0

    def pct(self, n: int, of: int | None = None) -> float:
        of = self.insns if of is None else of
        return 100.0 * n / of if of else 0.0


def elf_info(elf: Path) -> tuple[list[tuple[int, int]], int, int, int]:
    """(libgcc mul/div address ranges, text bytes, data bytes, _stack_top)."""
    ranges, stack_top = [], 0
    for line in subprocess.run([tool("nm"), "-S", str(elf)], capture_output=True).stdout.decode().splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[3] in LIBGCC_MULDIV:
            a, s = int(parts[0], 16), int(parts[1], 16)
            ranges.append((a, a + s))
        elif len(parts) >= 3 and parts[-1] == "_stack_top":
            stack_top = int(parts[0], 16)
    text = data = 0
    out = subprocess.run([tool("readelf"), "-S", "-W", str(elf)], capture_output=True).stdout.decode()
    for line in out.splitlines():
        m = re.match(r"\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+[0-9a-f]+\s+[0-9a-f]+\s+([0-9a-f]+)", line)
        if not m:
            continue
        name, size = m[1], int(m[3], 16)
        if name in (".text.init", ".text"):
            text += size
        elif name.startswith((".rodata", ".srodata", ".data", ".sdata", ".bss", ".sbss")):
            data += size
    return ranges, text, data, stack_top


def analyse(name: str, elf: Path, log: Path) -> Stats:
    st = Stats(name)
    ranges, st.text, st.data, stack_top = elf_info(elf)
    decoded: dict[int, str] = {}
    last_write: dict[int, int] = {}
    prev = None                       # (index, name, insn, pc, rd)
    min_sp = stack_top
    for i, line in enumerate(log.read_text(encoding="ascii").splitlines()):
        m = LINE.match(line)
        if not m:
            continue
        pc, insn = int(m[1], 16), int(m[2], 16)
        rd = int(m[3]) if m[3] else 0
        nm = decoded.get(insn)
        if nm is None:
            nm = decoded[insn] = decode_ref(insn)[0]
        st.insns += 1
        st.classes[klass(nm)] += 1
        if any(lo <= pc < hi for lo, hi in ranges):
            st.in_muldiv += 1
        srcs = sources(nm, insn)
        if prev is not None:
            p_i, p_nm, p_insn, p_pc, p_rd = prev
            if p_nm in BRANCHES:
                taken = pc != (p_pc + 4) & 0xFFFF_FFFF
                backward = bool(p_insn >> 31)
                st.br_taken += taken
                st.br_not += not taken
                if backward:
                    st.br_bwd += 1
                    st.br_bwd_taken += taken
                else:
                    st.br_fwd += 1
                    st.br_fwd_taken += taken
            if p_nm in LOADS and p_rd and p_rd in srcs:
                st.load_use += 1
        dists = [i - last_write[r] for r in srcs if r in last_write]
        if dists and min(dists) <= 3:
            st.raw[min(dists)] += 1
        if rd:
            last_write[rd] = i
            if rd == 2 and m[4] and MEM_BASE <= int(m[4], 16) <= stack_top:   # crt0 first zeroes sp
                min_sp = min(min_sp, int(m[4], 16))
        prev = (i, nm, insn, pc, rd)
    st.stack = max(0, stack_top - min_sp) if stack_top else 0
    return st


def table(rows: list[Stats], markdown: bool) -> str:
    cols = [("Instructions (= cycles)", lambda s: f"{s.insns:,}")]
    cols += [(f"{c} %", (lambda c: lambda s: f"{s.pct(s.classes[c]):.1f}")(c)) for c in CLASSES]
    cols += [
        ("branches taken %", lambda s: f"{s.pct(s.br_taken, s.br_taken + s.br_not):.1f}"),
        ("backward branches %", lambda s: f"{s.pct(s.br_bwd, s.br_bwd + s.br_fwd):.1f}"),
        ("backward taken %", lambda s: f"{s.pct(s.br_bwd_taken, s.br_bwd):.1f}"),
        ("forward taken %", lambda s: f"{s.pct(s.br_fwd_taken, s.br_fwd):.1f}"),
        ("load-use pairs %", lambda s: f"{s.pct(s.load_use):.1f}"),
        ("load-use % of loads", lambda s: f"{s.pct(s.load_use, s.classes['load']):.1f}"),
        ("RAW dist 1 %", lambda s: f"{s.pct(s.raw[1]):.1f}"),
        ("RAW dist 2 %", lambda s: f"{s.pct(s.raw[2]):.1f}"),
        ("RAW dist 3 %", lambda s: f"{s.pct(s.raw[3]):.1f}"),
        ("in libgcc mul/div %", lambda s: f"{s.pct(s.in_muldiv):.1f}"),
        ("code (.text) bytes", lambda s: f"{s.text:,}"),
        ("data bytes", lambda s: f"{s.data:,}"),
        ("stack bytes", lambda s: f"{s.stack:,}"),
    ]
    names = [s.name for s in rows]
    if markdown:
        out = ["| Metric | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
        out += [f"| {label} | " + " | ".join(f(s) for s in rows) + " |" for label, f in cols]
        return "\n".join(out)
    w = max(len(label) for label, _ in cols)
    cw = [max(len(n), 10) for n in names]
    out = [" " * w + "  " + "  ".join(n.rjust(c) for n, c in zip(names, cw))]
    out += [label.ljust(w) + "  " + "  ".join(f(s).rjust(c) for s, c in zip(rows, cw)) for label, f in cols]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--bench", action="store_true", help="every program in build/bench/ (make bench first)")
    ap.add_argument("progs", nargs="*", help="name=prog.elf:prog.retire.log")
    args = ap.parse_args()
    items = []
    if args.bench:
        for log in sorted((ROOT / "build" / "bench").glob("*.retire.log")):
            name = log.name.removesuffix(".retire.log")
            items.append((name, log.with_name(name + ".elf"), log))
    for p in args.progs:
        name, rest = p.split("=", 1)
        elf, log = rest.rsplit(":", 1) if rest.count(":") > 1 or not re.match(r"^[A-Za-z]:", rest) else (rest, "")
        items.append((name, Path(elf), Path(log)))
    if not items:
        ap.error("no programs (give name=elf:log, or --bench)")
    rows = [analyse(n, e, l) for n, e, l in items]
    print(table(rows, args.markdown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
