"""Memory images and runs for the simulation-model tests (docs/exec.md M3.3).

rv_mem_model and rv_soc_sim read +hex= (and +tohost=, +retire_log=) once at
time 0, so each program needs its own simulator run. run_unit.py asks this
module for the runs of a block, writes each run's hex file, and starts one
simulation per run with the run's name in $SIM_RUN. The test module rebuilds
the same image from the same name (every image is generated from a fixed seed),
so the test and the simulated memory agree; the test also re-reads the hex
file to check that.
"""

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rv_model import CONSOLE_ADDR, CYCLE_ADDR, MEM_BASE, MEM_SIZE_BYTES, RESET_PC, asm, write_hex
from rv_progs import DATA, Prog, random_program

MEM_END = MEM_BASE + MEM_SIZE_BYTES
TOHOST = 0x8000_F000          # where a linker script would put .tohost
PATCH = 0x8000_4000           # code slot the "pass" program writes, then runs


@dataclass
class Run:
    name: str
    build: Callable[[], dict[int, int] | None]   # None: run without +hex=
    tohost: int | None = TOHOST                  # None: run without +tohost=
    max_cycles: int = 2000
    expect: dict = field(default_factory=dict)   # directed expectations (cause, done, ...)

    def image(self) -> dict[int, int] | None:
        random.seed(f"sim-run-{self.name}")      # str seeds are stable across processes
        return self.build()

    def plusargs(self, build_dir: Path) -> tuple[list[str], dict[str, str]]:
        """Write the hex file; return (plusargs, extra environment) for this run."""
        args, env = [], {"SIM_RUN": self.name}
        image = self.image()
        if image is not None:
            hex_path = build_dir / f"{self.name}.hex"
            write_hex(image, hex_path)
            args.append(f"+hex={hex_path.as_posix()}")
            env["SIM_HEX"] = hex_path.as_posix()
        if self.tohost is not None:
            args.append(f"+tohost={self.tohost:08x}")
        log = build_dir / f"{self.name}.retire.log"
        log.unlink(missing_ok=True)
        args.append(f"+retire_log={log.as_posix()}")
        env["SIM_LOG"] = log.as_posix()
        return args, env


# ---------------------------------------------------------------------------
# rv_mem_model: one image with gaps, both ends of RAM and partial runs
# ---------------------------------------------------------------------------

def mem_model_image() -> dict[int, int]:
    image = {}
    for idx in list(range(0, 64)) + list(range(0x100, 0x123)) + [0x2001, 0x3FFE, 0x3FFF]:
        image[MEM_BASE + 4 * idx] = random.getrandbits(32)
    image[MEM_BASE + 4 * 0x200] = 0xFFFF_FFFF
    return image


MEM_MODEL_RUNS = [Run("mem_image", mem_model_image, tohost=None)]


# ---------------------------------------------------------------------------
# rv_soc_sim
# ---------------------------------------------------------------------------

def _end(p: Prog) -> Prog:
    p.li(9, TOHOST)("ADDI", rd=10, rs1=0, imm=1)("SW", rs1=9, rs2=10, imm=0)
    return p


def prog_pass() -> dict[int, int]:
    """Console (all store widths and offsets, reads), RAM at every width and
    both ends, code written through port B and then fetched, tohost = 1, then
    instructions after tohost (they still retire) and ECALL."""
    p = Prog().init_regs()
    p.li(1, CONSOLE_ADDR)
    for ch in b"Hi!\n":
        p("ADDI", rd=2, rs1=0, imm=ch)("SB", rs1=1, rs2=2, imm=0)
    p.li(2, 0x4142_4344)
    p("SW", rs1=1, rs2=2, imm=0)        # prints 'D' (lane 0)
    p("SH", rs1=1, rs2=2, imm=0)        # prints 'D'
    p("SB", rs1=1, rs2=2, imm=1)        # offsets 1..3: nothing printed
    p("SH", rs1=1, rs2=2, imm=2)
    p("SB", rs1=1, rs2=2, imm=3)
    p("LW", rd=3, rs1=1, imm=0)("LBU", rd=4, rs1=1, imm=3)("LH", rd=5, rs1=1, imm=2)  # all 0

    p.li(5, DATA).li(6, 0x8899_AABB)
    p("SW", rs1=5, rs2=6, imm=0)("SB", rs1=5, rs2=6, imm=5)("SH", rs1=5, rs2=6, imm=10)
    p("SB", rs1=5, rs2=0, imm=1)("SH", rs1=5, rs2=0, imm=-2)
    for off in range(4):
        p("LB", rd=7, rs1=5, imm=off)("LBU", rd=7, rs1=5, imm=off)
    for off in (0, 2, 4, 8, 10):
        p("LH", rd=7, rs1=5, imm=off)("LHU", rd=7, rs1=5, imm=off)
    p("LW", rd=7, rs1=5, imm=0)("LW", rd=7, rs1=5, imm=8)
    # First and last RAM words.
    p.li(8, MEM_END - 4)
    p("SW", rs1=8, rs2=6, imm=0)("LW", rd=7, rs1=8, imm=0)("LB", rd=7, rs1=8, imm=3)
    p.li(8, MEM_BASE)("LW", rd=7, rs1=8, imm=0)

    # Write "ADDI x11, x0, 123" into PATCH (all-zero, i.e. illegal, in the image),
    # then call it; the instruction after it there returns through x13.
    p.li(12, PATCH).li(14, asm("ADDI", rd=11, rs1=0, imm=123))
    p("SW", rs1=12, rs2=14, imm=0)
    p("JALR", rd=13, rs1=12, imm=0)
    _end(p)
    p("ADDI", rd=15, rs1=0, imm=5)("ADDI", rd=15, rs1=15, imm=1)
    p("ECALL")
    image = p.image()
    image[PATCH + 4] = asm("JALR", rd=0, rs1=13, imm=0)
    image[MEM_BASE + 0x7000] = 0x1234_5678   # data that is not code
    return image


def prog_fail() -> dict[int, int]:
    """Upper tohost word (ignored), a partial store to tohost (merged with the
    old word), a later store to tohost (ignored, the first one counts)."""
    p = Prog().init_regs()
    p.li(9, TOHOST).li(10, 0x7777)
    p("SW", rs1=9, rs2=10, imm=4)
    p("SH", rs1=9, rs2=10, imm=0)
    p("ADDI", rd=10, rs1=0, imm=1)("SW", rs1=9, rs2=10, imm=0)
    p("EBREAK")
    image = p.image()
    image[TOHOST] = 0xAAAA_0000
    return image


def prog_store_tohost_ecall() -> dict[int, int]:
    return _end(Prog().init_regs())("ECALL").image()


def prog_stop(*words_fn) -> Callable[[], dict[int, int]]:
    """A program that sets up registers, runs `words_fn(p)` and then ECALLs."""
    def build():
        p = Prog().init_regs()
        for fn in words_fn:
            fn(p)
        return p("ECALL").image()
    return build


def prog_run_off_end() -> dict[int, int]:
    """Jump to the last RAM word, which holds an ADDI; the next fetch is
    MEM_END, outside RAM."""
    p = Prog().init_regs().li(1, MEM_END - 4)("JALR", rd=0, rs1=1, imm=0)
    image = p.image()
    image[MEM_END - 4] = asm("ADDI", rd=2, rs1=0, imm=1)
    return image


def prog_cycle() -> dict[int, int]:
    """The CYCLE counter: LO read at different cycles, every load width and
    offset of LO and HI, kept in registers (the retire log shows each value)."""
    p = Prog().init_regs().li(1, CYCLE_ADDR)
    p("LW", rd=2, rs1=1, imm=0)("LW", rd=3, rs1=1, imm=0)            # consecutive cycles
    for _ in range(5):
        p("ADDI", rd=4, rs1=4, imm=1)
    p("LW", rd=3, rs1=1, imm=0)("LW", rd=5, rs1=1, imm=4)            # HI is 0
    for off in range(4):
        p("LB", rd=6, rs1=1, imm=off)("LBU", rd=6, rs1=1, imm=off)
    for off in (0, 2, 4, 6):
        p("LH", rd=7, rs1=1, imm=off)("LHU", rd=7, rs1=1, imm=off)
    return _end(p)("ECALL").image()


def prog_random() -> dict[int, int]:
    image = random_program().image()
    for off in range(-0x800, 0x800, 4):
        image[DATA + off] = random.getrandbits(32)
    return image


SOC_RUNS = [
    Run("pass", prog_pass, expect={"cause": "STOP_ECALL", "done": True, "tohost": 1,
                                   "console": b"Hi!\nDD"}),
    Run("fail", prog_fail, expect={"cause": "STOP_EBREAK", "done": True, "tohost": 0xAAAA_7777}),
    Run("no_tohost_arg", prog_store_tohost_ecall, tohost=None,
        expect={"cause": "STOP_ECALL", "done": False}),
    Run("no_hex", lambda: None, expect={"cause": "STOP_ILLEGAL", "done": False, "retired": 1}),
    Run("bus_load_zero", prog_stop(lambda p: p("LW", rd=1, rs1=0, imm=0)),
        expect={"cause": "STOP_BUS_ERROR"}),
    Run("bus_load_console_gap", prog_stop(lambda p: p.li(1, CONSOLE_ADDR + 4)("LB", rd=2, rs1=1, imm=0)),
        expect={"cause": "STOP_BUS_ERROR"}),
    Run("bus_store_above_ram", prog_stop(lambda p: p.li(1, MEM_END).li(2, -1)("SW", rs1=1, rs2=2, imm=0)),
        expect={"cause": "STOP_BUS_ERROR"}),
    Run("bus_store_below_ram", prog_stop(lambda p: p.li(1, MEM_BASE - 4).li(2, -1)("SW", rs1=1, rs2=2, imm=0)),
        expect={"cause": "STOP_BUS_ERROR"}),
    Run("cycle_counter", prog_cycle, expect={"cause": "STOP_ECALL", "done": True, "tohost": 1}),
    Run("bus_store_cycle", prog_stop(lambda p: p.li(1, CYCLE_ADDR)("SW", rs1=1, rs2=1, imm=0)),
        expect={"cause": "STOP_BUS_ERROR"}),
    Run("bus_store_cycle_hi", prog_stop(lambda p: p.li(1, CYCLE_ADDR + 4)("SB", rs1=1, rs2=1, imm=3)),
        expect={"cause": "STOP_BUS_ERROR"}),
    Run("bus_load_after_cycle", prog_stop(lambda p: p.li(1, CYCLE_ADDR + 8)("LW", rd=2, rs1=1, imm=0)),
        expect={"cause": "STOP_BUS_ERROR"}),
    Run("ifetch_console", prog_stop(lambda p: p.li(1, CONSOLE_ADDR)("JALR", rd=0, rs1=1, imm=0)),
        expect={"cause": "STOP_IFETCH_ERROR"}),
    Run("ifetch_end_of_ram", prog_run_off_end, expect={"cause": "STOP_IFETCH_ERROR"}),
] + [
    # tohost inside the random data window, so random stores sometimes hit it.
    Run(f"random_{k:02d}", prog_random, tohost=DATA + 0x40, max_cycles=1000) for k in range(16)
]

assert RESET_PC == MEM_BASE

RUNS = {"rv_mem_model": MEM_MODEL_RUNS, "rv_soc_sim": SOC_RUNS}


def find(name: str) -> Run:
    return next(r for runs in RUNS.values() for r in runs if r.name == name)
