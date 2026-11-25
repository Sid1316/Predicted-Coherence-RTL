"""Checks for scripts/stats.py on a hand-built trace (docs/exec.md M7.2).

Usage: test_stats.py            (make sim-test runs it)

The trace below has a known answer for every metric: one load-use pair,
RAW dependencies at distance 1 (one), 2 (two) and 3 (one), counted by the
nearest producer, a taken forward branch, a not-taken backward branch, a taken
backward branch, and two instructions inside a fake __mulsi3.

Exit code: 0 if every check passed, 1 otherwise.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tb" / "unit"))
import stats  # noqa: E402
from rv_model import asm  # noqa: E402

BASE = 0x8000_0000
MULSI3 = (0x8000_1000, 0x8000_1010)

# (pc, instruction, rd, rd value): a retire log in program order.
TRACE = [
    (BASE + 0x00, asm("LW", rd=5, rs1=8, imm=0), 5, 7),        # 0 load x5
    (BASE + 0x04, asm("ADD", rd=6, rs1=5, rs2=0), 6, 7),       # 1 uses x5 right after: load-use, RAW 1
    (BASE + 0x08, asm("ADDI", rd=7, rs1=0, imm=1), 7, 1),      # 2 no sources
    (BASE + 0x0C, asm("BEQ", rs1=0, rs2=0, imm=8), 0, 0),      # 3 forward, taken (next pc +8)
    (BASE + 0x14, asm("ADD", rd=9, rs1=6, rs2=7), 9, 8),       # 4 x7 from 2 (dist 2), x6 from 1 (dist 3): nearest 2
    (BASE + 0x18, asm("BNE", rs1=0, rs2=0, imm=-8), 0, 0),     # 5 backward, not taken
    (BASE + 0x1C, asm("ADDI", rd=10, rs1=6, imm=0), 10, 7),    # 6 x6 from 1: dist 5, not counted
    (BASE + 0x20, asm("SW", rs1=8, rs2=9, imm=4), 0, 0),       # 7 x9 from 4: dist 3; x8 never written
    (BASE + 0x24, asm("BLT", rs1=0, rs2=10, imm=-0x24), 0, 0), # 8 backward, taken (to BASE); x10 from 6: dist 2
    (MULSI3[0], asm("ADDI", rd=11, rs1=0, imm=2), 11, 2),      # 9 in __mulsi3
    (MULSI3[0] + 4, asm("ADDI", rd=2, rs1=0, imm=0), 2, 0x8000_FF00),  # 10 in __mulsi3; sp write
]

failures = checks = 0


def check(name, got, exp):
    global failures, checks
    checks += 1
    if got != exp:
        failures += 1
        print(f"  FAIL  {name}: got {got}, expected {exp}")


def main() -> int:
    out = ROOT / "build" / "sim" / "test"
    out.mkdir(parents=True, exist_ok=True)
    log = out / "stats.retire.log"
    lines = []
    for i, (pc, insn, rd, val) in enumerate(TRACE):
        s = f"{i:08x} {pc:08x} {insn:08x}"
        if rd:
            s += f" x{rd} {val & 0xFFFF_FFFF:08x}"
        lines.append(s)
    log.write_text("\n".join(lines) + "\n", encoding="ascii")
    stats.elf_info = lambda elf: ([MULSI3], 1234, 567, 0x8001_0000)   # no ELF needed
    st = stats.analyse("t", Path("unused.elf"), log)

    check("instructions", st.insns, 11)
    check("classes", dict(st.classes), {"load": 1, "ALU": 6, "branch": 3, "store": 1})
    check("branches taken / not", (st.br_taken, st.br_not), (2, 1))
    check("forward / backward", (st.br_fwd, st.br_bwd), (1, 2))
    check("backward taken", st.br_bwd_taken, 1)
    check("forward taken", st.br_fwd_taken, 1)
    check("load-use", st.load_use, 1)
    check("RAW by distance", dict(st.raw), {1: 1, 2: 2, 3: 1})
    check("in mul/div", st.in_muldiv, 2)
    check("sizes", (st.text, st.data), (1234, 567))
    check("stack", st.stack, 0x100)
    print(f"test_stats: {checks - failures}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
