"""Test programs shared by the core and SoC unit tests (docs/exec.md M3.2, M3.3).

Prog builds an instruction list with labels; random_program() builds a random
RV32I program (it draws from the global `random`, so seed that first for a
reproducible program).
"""

import random

from rv_model import MASK32, RESET_PC, asm, asm_li

DATA = 0x8000_8000          # data window used by the programs


# ---------------------------------------------------------------------------
# Program builder
# ---------------------------------------------------------------------------

class Prog:
    """Instruction list with labels for branches and JAL."""

    def __init__(self, base: int = RESET_PC):
        self.base = base
        self.words: list[int | tuple] = []
        self.labels: dict[str, int] = {}

    def pc(self) -> int:
        return self.base + 4 * len(self.words)

    def __call__(self, name, **kw):
        self.words.append(asm(name, **kw))
        return self

    def word(self, w):
        self.words.append(w & MASK32)
        return self

    def li(self, rd, value):
        self.words += asm_li(rd, value)
        return self

    def label(self, name):
        self.labels[name] = self.pc()
        return self

    def to(self, name, label, **kw):
        """Branch or JAL to a label (offset filled in by image())."""
        self.words.append((name, label, kw))
        return self

    def init_regs(self):
        """Write every register, so later reads are defined (the regfile is not reset)."""
        for r in range(1, 32):
            self(name="ADDI", rd=r, rs1=0, imm=0)
        return self

    def image(self) -> dict[int, int]:
        out = {}
        for i, w in enumerate(self.words):
            addr = self.base + 4 * i
            if isinstance(w, tuple):
                name, label, kw = w
                w = asm(name, imm=self.labels[label] - addr, **kw)
            out[addr] = w
        return out



CODE_REG, DATA_REG = 29, 30   # hold CODE base / DATA, never overwritten by the body
RD_CHOICES = [r for r in range(32) if r not in (CODE_REG, DATA_REG)]
EDGE_VALUES = [0, 1, 2, 0x7FF, 0x800, 0x7FFF_FFFF, 0x8000_0000, 0xFFFF_FFFF, 0xFFFF_F800]


def rand_value():
    return random.choice(EDGE_VALUES) if random.random() < 0.3 else random.getrandbits(32)


def rand_imm12():
    return random.choice([0, 1, -1, 2047, -2048]) if random.random() < 0.2 else random.randint(-2048, 2047)


def random_program(n_body=200):
    p = Prog()
    for r in range(1, 32):
        p.li(r, rand_value())
    p.li(CODE_REG, RESET_PC).li(DATA_REG, DATA)
    start = len(p.words)
    total = start + n_body + 1
    rd = lambda: random.choice(RD_CHOICES)  # noqa: E731
    rs = lambda: random.randrange(32)       # noqa: E731
    ops_r = ["ADD", "SUB", "SLL", "SLT", "SLTU", "XOR", "SRL", "SRA", "OR", "AND"]
    ops_i = ["ADDI", "SLTI", "SLTIU", "XORI", "ORI", "ANDI"]
    for _ in range(n_body):
        idx = len(p.words)
        k = random.random()
        if k < 0.20:
            p(random.choice(ops_r), rd=rd(), rs1=rs(), rs2=rs())
        elif k < 0.36:
            p(random.choice(ops_i), rd=rd(), rs1=rs(), imm=rand_imm12())
        elif k < 0.42:
            p(random.choice(["SLLI", "SRLI", "SRAI"]), rd=rd(), rs1=rs(), imm=random.randrange(32))
        elif k < 0.46:
            p(random.choice(["LUI", "AUIPC"]), rd=rd(), imm=random.getrandbits(20) << 12)
        elif k < 0.62:
            name = random.choice(["LB", "LH", "LW", "LBU", "LHU", "SB", "SH", "SW"])
            size = {"B": 1, "H": 2, "W": 4}[name[1]]
            imm = random.randint(-512, 511) * size if random.random() < 0.95 else random.randint(-2048, 2047)
            base = DATA_REG if random.random() < 0.97 else rs()
            if name[0] == "L":
                p(name, rd=rd(), rs1=base, imm=imm)
            else:
                p(name, rs1=base, rs2=rs(), imm=imm)
        elif k < 0.78:
            name = random.choice(["BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU"])
            off = 4 * random.randint(-6, 20) + (2 if random.random() < 0.03 else 0)
            # Compare a register with itself sometimes, so EQ/GE/GEU take and NE/LT/LTU don't.
            a = rs()
            p(name, rs1=a, rs2=a if random.random() < 0.2 else rs(), imm=off or 4)
        elif k < 0.84:
            off = 4 * random.randint(1, 20) + (2 if random.random() < 0.03 else 0)
            p("JAL", rd=rd(), imm=off)
        elif k < 0.90:
            if random.random() < 0.15:   # random base: usually outside RAM (fetch error)
                p("JALR", rd=rd(), rs1=rs(), imm=rand_imm12())
            else:
                dest = 4 * random.randint(idx + 1, min(idx + 20, total))
                dest += random.choice([0] * 12 + [1, 2, 3])
                p("JALR", rd=rd(), rs1=CODE_REG, imm=dest)
        elif k < 0.92:
            p.word(asm("FENCE") | (random.getrandbits(32) & ~(0x7F | 0x7 << 12)))
        elif k < 0.93:
            p(random.choice(["ECALL", "EBREAK"]))
        elif k < 0.94:
            p.word(random.getrandbits(32))   # mostly illegal; sometimes a legal surprise
        else:
            p("ADDI", rd=rd(), rs1=rs(), imm=rand_imm12())
    p("ECALL")
    return p
