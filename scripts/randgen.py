"""Constrained-random RV32I program generator (docs/exec.md M6.3).

Usage: randgen.py <seed> [-o <file.S>] [--length N]

Writes an assembly test (built like sw/asm/ tests, with sw/asm/test.h) whose
result is not checked by the program itself: scripts/run_random.py runs it on
the RTL and on the reference model and compares the traces (M6.4). The same
seed always gives the same program (random.Random(seed), no other source of
randomness); GENERATOR_VERSION goes into the file so a changed generator is
visible in a saved regression test.

What a program contains:
  - every register except the reserved ones set to a random, edge-biased value;
  - straight-line code: all OP and OP-IMM instructions (shift amounts 0-31,
    12-bit immediates with their edges), LUI/AUIPC, x0 as destination
    (HINTs), FENCE / FENCE.TSO / PAUSE and FENCEs with reserved fields set;
  - loads and stores of every width at aligned offsets inside a 2 KiB data
    window of random words (s0 points at its middle);
  - control flow that always terminates: forward branches of all six kinds
    (taken or not, depending on the random values), bounded backward loops
    (counter s1, 1-6 iterations, closed by BNE/BLT/BLTU), forward JAL and
    JALR jumps (JALR sometimes with bit 0 set, which is cleared), and calls
    to generated leaf functions through JAL and JALR;
  - an ending: most programs store 1 to tohost; some stop with ECALL, EBREAK
    or one deliberate error (illegal word, misaligned load or store,
    misaligned jump target, unmapped load, fetch outside RAM), so the halt
    and error paths are covered too (spec §10, §15.1).

Reserved registers: s0 (x8, data window), s1 (x9, loop counter), t6 (x31,
jump targets); ra (x1) is not written inside functions. gp and t5 are free
until the final TEST_PASS uses them.
"""

import argparse
import random
import sys
from pathlib import Path

GENERATOR_VERSION = 1

S0, S1, T6, RA = 8, 9, 31, 1
MAIN_RD = [r for r in range(32) if r not in (S0, S1, T6)]          # x0 included (HINTs)
FUNC_RD = [r for r in MAIN_RD if r != RA]
SRC = list(range(32))
EDGES = [0, 1, 2, 0x7FF, 0x800, 0xFFF, 0x7FFF_FFFF, 0x8000_0000, 0x8000_0001, 0xFFFF_FFFF,
         0xFFFF_F800, 0x0000_FFFF, 0xFFFF_0000, 0x5555_5555, 0xAAAA_AAAA]
IMM_EDGES = [0, 1, -1, 2047, -2048, 0x7F, -0x80]
OP = ["add", "sub", "sll", "slt", "sltu", "xor", "srl", "sra", "or", "and"]
OP_IMM = ["addi", "slti", "sltiu", "xori", "ori", "andi"]
SHIFT_IMM = ["slli", "srli", "srai"]
LOADS = {"lb": 1, "lh": 2, "lw": 4, "lbu": 1, "lhu": 2}
STORES = {"sb": 1, "sh": 2, "sw": 4}
BRANCHES = ["beq", "bne", "blt", "bge", "bltu", "bgeu"]
WINDOW = 1024              # s0 = buf + WINDOW; offsets in [-WINDOW, WINDOW)


class Gen:
    def __init__(self, seed: int, length: int | None):
        self.r = random.Random(seed)
        self.seed = seed
        self.length = length if length is not None else self.r.randint(150, 600)
        self.lines: list[str] = []
        self.labels = 0
        self.funcs: list[list[str]] = []

    # -- helpers --------------------------------------------------------------
    def label(self) -> str:
        self.labels += 1
        return f"L{self.labels}"

    def value(self) -> int:
        return self.r.choice(EDGES) if self.r.random() < 0.35 else self.r.getrandbits(32)

    def imm12(self) -> int:
        return self.r.choice(IMM_EDGES) if self.r.random() < 0.25 else self.r.randint(-2048, 2047)

    def rd(self, pool) -> str:
        return f"x{self.r.choice(pool)}"

    def rs(self) -> str:
        return f"x{self.r.choice(SRC)}"

    # -- straight-line instructions -------------------------------------------
    def straight(self, pool) -> str:
        k = self.r.random()
        if k < 0.25:
            return f"{self.r.choice(OP)} {self.rd(pool)}, {self.rs()}, {self.rs()}"
        if k < 0.42:
            return f"{self.r.choice(OP_IMM)} {self.rd(pool)}, {self.rs()}, {self.imm12()}"
        if k < 0.52:
            sh = self.r.choice([0, 1, 31]) if self.r.random() < 0.3 else self.r.randrange(32)
            return f"{self.r.choice(SHIFT_IMM)} {self.rd(pool)}, {self.rs()}, {sh}"
        if k < 0.58:
            return f"{self.r.choice(['lui', 'auipc'])} {self.rd(pool)}, {self.r.getrandbits(20):#x}"
        if k < 0.75:
            name, size = self.r.choice(list(LOADS.items()))
            return f"{name} {self.rd(pool)}, {self.offset(size)}(s0)"
        if k < 0.92:
            name, size = self.r.choice(list(STORES.items()))
            return f"{name} {self.rs()}, {self.offset(size)}(s0)"
        if k < 0.96:
            return self.fence()
        # x0 as the destination (HINT encodings, spec §4.2): the write is discarded.
        if self.r.random() < 0.5:
            return f"{self.r.choice(OP)} x0, {self.rs()}, {self.rs()}"
        return f"{self.r.choice(OP_IMM)} x0, {self.rs()}, {self.imm12()}"

    def offset(self, size: int) -> int:
        return self.r.randrange(-WINDOW, WINDOW, size)

    def fence(self) -> str:
        k = self.r.randrange(5)
        if k == 0:
            return "fence"
        if k == 1:
            return "fence rw, rw"
        if k == 2:
            return ".word 0x8330000f   # fence.tso"
        if k == 3:
            return ".word 0x0100000f   # pause"
        # Random fm/pred/succ and reserved rd/rs1 fields; funct3 = 000 keeps it a FENCE.
        w = self.r.getrandbits(32) & ~0x7FFF | 0x000F
        w |= self.r.getrandbits(5) << 7 | self.r.getrandbits(5) << 15
        return f".word {w:#010x}   # fence, reserved fields set"

    def block(self, n: int, pool) -> list[str]:
        return [self.straight(pool) for _ in range(n)]

    # -- control flow -----------------------------------------------------------
    def forward_branch(self, pool) -> list[str]:
        a, b = self.rs(), self.rs()
        if self.r.random() < 0.2:
            b = a                                    # equal operands: BEQ/BGE/BGEU taken
        lab = self.label()
        return [f"{self.r.choice(BRANCHES)} {a}, {b}, {lab}", *self.block(self.r.randint(0, 6), pool), f"{lab}:"]

    def loop(self) -> list[str]:
        lab = self.label()
        body = []
        for _ in range(self.r.randint(1, 6)):
            body += self.forward_branch(MAIN_RD) if self.r.random() < 0.2 else [self.straight(MAIN_RD)]
        close = self.r.choice(["bne s1, x0", "blt x0, s1", "bltu x0, s1"])
        return [f"li s1, {self.r.randint(1, 6)}", f"{lab}:", *body, "addi s1, s1, -1", f"{close}, {lab}"]

    def jal_forward(self) -> list[str]:
        lab = self.label()
        return [f"jal {self.rd(MAIN_RD)}, {lab}", *self.block(self.r.randint(0, 4), MAIN_RD), f"{lab}:"]

    def jalr_forward(self) -> list[str]:
        lab = self.label()
        bit0 = self.r.random() < 0.3
        return [f"la t6, {lab}", *(["addi t6, t6, 1"] if bit0 else []), f"jalr {self.rd(MAIN_RD)}, 0(t6)",
                *self.block(self.r.randint(0, 4), MAIN_RD), f"{lab}:"]

    def call(self) -> list[str]:
        if not self.funcs or (len(self.funcs) < 4 and self.r.random() < 0.5):
            self.funcs.append(self.block(self.r.randint(1, 8), FUNC_RD))
        name = f"fn{self.r.randrange(len(self.funcs))}"
        if self.r.random() < 0.5:
            return [f"jal ra, {name}"]
        return [f"la t6, {name}", "jalr ra, 0(t6)"]

    # -- endings ----------------------------------------------------------------
    def ending(self) -> list[str]:
        k = self.r.random()
        if k < 0.80:
            return []                                # fall through to TEST_PASS
        if k < 0.86:
            return ["ecall"]
        if k < 0.92:
            return ["ebreak"]
        kind = self.r.randrange(6)
        if kind == 0:
            return [".word 0x00000000   # illegal"]
        if kind == 1:
            return [f"lw a0, {self.r.choice([1, 2, 3])}(s0)   # misaligned load"]
        if kind == 2:
            return [f"sh a0, {self.r.choice([1, 3])}(s0)   # misaligned store"]
        if kind == 3:
            lab = self.label()
            return [f"la t6, {lab}", "addi t6, t6, 2", "jr t6   # misaligned target", f"{lab}:", "nop"]
        if kind == 4:
            return ["lw a0, 0(x0)   # unmapped"]
        return ["li t6, 0x90000000", "jr t6   # fetch outside RAM"]

    # -- program ------------------------------------------------------------------
    def program(self) -> str:
        out = [f"// randgen seed={self.seed} version={GENERATOR_VERSION} length={self.length}",
               "// Generated by scripts/randgen.py; checked by comparison with the model (run_random.py).",
               '#include "test.h"', "TEST_BEGIN", "  la s0, buf + %d" % WINDOW]
        for r in MAIN_RD:
            if r not in (0,):
                out.append(f"  li x{r}, {self.value():#010x}")
        body: list[str] = []
        while len(body) < self.length:
            k = self.r.random()
            if k < 0.70:
                body.append(self.straight(MAIN_RD))
            elif k < 0.82:
                body += self.forward_branch(MAIN_RD)
            elif k < 0.88:
                body += self.loop()
            elif k < 0.92:
                body += self.jal_forward()
            elif k < 0.96:
                body += self.jalr_forward()
            else:
                body += self.call()
        body += self.ending()
        out += [("  " + l if not l.endswith(":") else l) for l in body]
        out.append("TEST_PASS")
        for i, f in enumerate(self.funcs):
            out += [f"fn{i}:", *("  " + l for l in f), "  ret"]
        out += ["TEST_DATA", "buf:"]
        words = [self.value() for _ in range(2 * WINDOW // 4)]
        for i in range(0, len(words), 8):
            out.append("  .word " + ", ".join(f"{w:#010x}" for w in words[i:i + 8]))
        return "\n".join(out) + "\n"


def generate(seed: int, length: int | None = None) -> str:
    return Gen(seed, length).program()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("seed", type=int)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--length", type=int, help="body length in instructions (default: random 150-600)")
    args = ap.parse_args()
    text = generate(args.seed, args.length)
    if args.output:
        args.output.write_text(text, encoding="ascii", newline="\n")
    else:
        sys.stdout.buffer.write(text.encode("ascii"))   # bytes: no CR LF on Windows
    return 0


if __name__ == "__main__":
    sys.exit(main())
