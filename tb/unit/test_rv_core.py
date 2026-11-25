"""cocotb unit tests for rv_core (docs/exec.md M3.2, docs/spec.md §5, §6.1, §9, §10).

The test bench plays the memory: every cycle it answers the fetch request
from a Python SimMemory, then the data request, and applies stores at the
clock edge. Responses are combinational, as the Phase 1 port contract says
(spec §8.3). When a port has no request, the response carries random rdata
and err, which the core must ignore.

Every cycle the retire port is compared, field by field, with CoreModel
(rv_model.py), an instruction-set model written from spec §4/§9/§10. At the
end of each program the register file (read through the hierarchy) and the
whole memory are compared with the model as well, so a side effect that the
retire port does not show is still caught.

Timing: inputs change after a falling edge; combinational outputs are read
before the next rising edge; halted_o/status_o are checked after it.
"""

import random
from collections import Counter

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from rv_model import (
    CONSOLE_ADDR, DMEM_REQ_FIELDS, DMEM_RSP_FIELDS, IMEM_REQ_FIELDS, IMEM_RSP_FIELDS, MASK32,
    RESET_PC, RETIRE_FIELDS, STOP_CAUSES, CoreModel, SimMemory, asm, asm_li, decode_ref,
    struct_pack, struct_unpack, struct_width,
)

PERIOD_NS = 10
DATA = 0x8000_8000          # data window used by the programs
CAUSE_NAMES = {v: k for k, v in STOP_CAUSES.items()}


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


# ---------------------------------------------------------------------------
# Bench
# ---------------------------------------------------------------------------

def resolved(sig, name):
    v = sig.value
    assert v.is_resolvable, f"{name} has X/Z: {v}"
    return int(v)


def field_bits(value, fields, name):
    """The bits of one packed-struct field as a string (MSB first), from a LogicArray."""
    s = str(value)
    assert len(s) == struct_width(fields)
    pos = 0
    for n, w in fields:
        if n == name:
            return s[pos:pos + w]
        pos += w
    raise KeyError(name)


def disasm(word):
    return decode_ref(word)[0]


class Bench:
    def __init__(self, dut, image=None):
        self.dut = dut
        self.mem = SimMemory(image)
        self.model = CoreModel(SimMemory(image))
        self.cycles = 0

    async def start(self):
        Clock(self.dut.clk_i, PERIOD_NS, unit="ns").start()
        await self.reset(cycles=2)

    async def new_program(self, image, faults=(), reset_cycles=2):
        """Replace both memories with a fresh image and reset. Registers are kept,
        in the RTL and in the model, as a real reset keeps them (spec §2.2)."""
        self.mem = SimMemory(image)
        self.model.mem = SimMemory(image)
        self.mem.fetch_faults = set(faults)
        self.model.mem.fetch_faults = set(faults)
        await self.reset(cycles=reset_cycles)

    def _garbage(self, port):
        port.value = struct_pack(IMEM_RSP_FIELDS, ready=1, rdata=random.getrandbits(32),
                                 err=random.getrandbits(1))

    def _check_idle(self, ctx):
        """No fetch, no data request, retire port all zero (reset or halted)."""
        d = self.dut
        assert field_bits(d.imem_req_o.value, IMEM_REQ_FIELDS, "valid") == "0", f"imem_req.valid ({ctx})"
        assert field_bits(d.dmem_req_o.value, DMEM_REQ_FIELDS, "valid") == "0", f"dmem_req.valid ({ctx})"
        assert resolved(d.retire_o, "retire_o") == 0, f"retire_o not idle ({ctx})"

    async def reset(self, cycles=2):
        """Hold rst_i for `cycles` rising edges (spec §2.2), checking the core is idle throughout.
        Called between clock edges (at the start, or after cycle()), so no cycle is skipped."""
        d = self.dut
        d.rst_i.value = 1
        for i in range(cycles):
            self._garbage(d.imem_rsp_i)
            self._garbage(d.dmem_rsp_i)
            await Timer(2, unit="ns")
            self._check_idle(f"reset cycle {i}")
            await RisingEdge(d.clk_i)
            await FallingEdge(d.clk_i)
        d.rst_i.value = 0
        self.model.reset()
        assert resolved(d.halted_o, "halted_o") == 0
        assert resolved(d.status_o, "status_o") == STOP_CAUSES["STOP_NONE"]

    async def cycle(self):
        """One clock: answer both ports, compare retire with the model, clock, check halt state."""
        d = self.dut
        await Timer(1, unit="ns")   # let inputs written at the falling edge (e.g. rst_i) settle
        ireq = struct_unpack(IMEM_REQ_FIELDS, resolved(d.imem_req_o, "imem_req_o"))
        if ireq["valid"]:
            word, err = self.mem.fetch(ireq["addr"])
            d.imem_rsp_i.value = struct_pack(IMEM_RSP_FIELDS, ready=1, rdata=word, err=err)
        else:
            self._garbage(d.imem_rsp_i)
        await Timer(1, unit="ns")

        dreq_raw = d.dmem_req_o.value
        for f in ("valid", "we", "be"):
            assert "x" not in field_bits(dreq_raw, DMEM_REQ_FIELDS, f).lower() and \
                   "z" not in field_bits(dreq_raw, DMEM_REQ_FIELDS, f).lower(), f"dmem_req.{f}: {dreq_raw}"
        dvalid = field_bits(dreq_raw, DMEM_REQ_FIELDS, "valid") == "1"
        dreq = None
        if dvalid:
            dreq = struct_unpack(DMEM_REQ_FIELDS, resolved(d.dmem_req_o, "dmem_req_o"))
            rdata, err = self.mem.read(dreq["addr"])
            d.dmem_rsp_i.value = struct_pack(DMEM_RSP_FIELDS, ready=1, rdata=rdata, err=err)
        else:
            self._garbage(d.dmem_rsp_i)
        await Timer(1, unit="ns")
        assert str(d.dmem_req_o.value) == str(dreq_raw), "dmem_req changed after the response: depends on dmem_rsp"

        got = struct_unpack(RETIRE_FIELDS, resolved(d.retire_o, "retire_o"))
        exp = self.model.step()
        if got != exp:
            diff = {k: (f"{got[k]:#x}", f"{exp[k]:#x}") for k in exp if got[k] != exp[k]}
            name = disasm(exp["insn"]) if exp["valid"] else "-"
            raise AssertionError(f"retire mismatch at pc={exp['pc_rdata']:#010x} insn={exp['insn']:#010x} "
                                 f"({name}), (got, expected): {diff}")
        if not exp["valid"]:
            self._check_idle("halted")

        await RisingEdge(d.clk_i)
        if dreq and dreq["we"]:
            self.mem.write(dreq["addr"], dreq["be"], dreq["wdata"])
        await FallingEdge(d.clk_i)
        self.cycles += 1
        assert resolved(d.halted_o, "halted_o") == int(self.model.halted)
        assert resolved(d.status_o, "status_o") == self.model.status, \
            f"status_o={CAUSE_NAMES.get(int(d.status_o.value))}, expected {CAUSE_NAMES[self.model.status]}"
        return got

    async def run(self, max_cycles=2000, idle_after=3):
        """Run until the core stops (or max_cycles), then a few idle cycles. Returns the stop cause name."""
        for _ in range(max_cycles):
            await self.cycle()
            if self.model.halted:
                break
        for _ in range(idle_after if self.model.halted else 0):
            await self.cycle()
        self.check_state()
        return CAUSE_NAMES[self.model.status]

    def check_state(self):
        """Register file and memory equal the model's (catches side effects the retire port hides)."""
        regs = self.dut.u_regfile.regs_q
        for i in range(1, 32):
            exp = self.model.regs[i]
            if exp is None:
                continue
            v = regs[i].value
            assert v.is_resolvable and int(v) == exp, f"x{i} = {v}, expected {exp:#010x}"
        if self.mem.ram != self.model.mem.ram:
            first = next(i for i in range(len(self.mem.ram)) if self.mem.ram[i] != self.model.mem.ram[i])
            raise AssertionError(f"memory differs from the model at {0x8000_0000 + first:#010x}")
        assert self.mem.console == self.model.mem.console, (self.mem.console, self.model.mem.console)


async def run_prog(dut, prog, **kw):
    b = Bench(dut, prog.image())
    await b.start()
    cause = await b.run(**kw)
    return b, cause


# ---------------------------------------------------------------------------
# Directed tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_reset(dut):
    """Idle during reset; first fetch at RESET_PC with order 0; a mid-run reset drops an in-flight store."""
    p = Prog().init_regs().li(30, DATA).li(5, 0xA5A5_A5A5)
    p.label("loop")("SW", rs1=30, rs2=5, imm=0)("ADDI", rd=6, rs1=6, imm=1).to("JAL", "loop", rd=0)
    b = Bench(dut, p.image())
    await b.start()
    first = await b.cycle()
    assert (first["pc_rdata"], first["order"]) == (RESET_PC, 0)
    while True:   # run until the store is the next instruction
        await b.cycle()
        if b.model.pc == p.labels["loop"] and b.model.regs[6] == 3:
            break
    # Reset while the SW is at pc: no write may happen (spec §2.2).
    b.mem.write(DATA, 0xF, 0)
    b.model.mem.write(DATA, 0xF, 0)
    await b.reset(cycles=3)
    assert b.mem.word(DATA) == 0, "store executed during reset"
    first = await b.cycle()
    assert (first["pc_rdata"], first["order"]) == (RESET_PC, 0), "reset must restart pc and order"


@cocotb.test()
async def test_program(dut):
    """Every instruction class, with results checked against hand-computed values (not only the model)."""
    p = Prog().init_regs()
    p.li(30, DATA).li(1, 0x1234_5678).li(2, -3)("ADDI", rd=6, rs1=0, imm=4)
    # OP
    p("ADD", rd=3, rs1=1, rs2=2)("SUB", rd=4, rs1=2, rs2=1)("SLL", rd=5, rs1=1, rs2=6)
    p("SLT", rd=7, rs1=2, rs2=1)("SLTU", rd=8, rs1=2, rs2=1)("SRA", rd=9, rs1=2, rs2=6)
    p("SRL", rd=10, rs1=2, rs2=6)("XOR", rd=11, rs1=1, rs2=2)("OR", rd=12, rs1=1, rs2=6)
    p("AND", rd=13, rs1=1, rs2=2)
    # OP-IMM
    p("ADDI", rd=14, rs1=1, imm=-0x678)("SLTI", rd=15, rs1=2, imm=-2)("SLTIU", rd=16, rs1=2, imm=-1)
    p("XORI", rd=17, rs1=1, imm=-1)("ORI", rd=18, rs1=0, imm=0x7FF)("ANDI", rd=19, rs1=1, imm=0xFF)
    p("SLLI", rd=20, rs1=1, imm=8)("SRLI", rd=21, rs1=2, imm=28)("SRAI", rd=22, rs1=2, imm=1)
    # U-type
    p("LUI", rd=23, imm=0xABCD_E000)
    auipc_pc = p.pc()
    p("AUIPC", rd=24, imm=0x1000)
    # Stores and loads
    p("SW", rs1=30, rs2=1, imm=0)("SH", rs1=30, rs2=2, imm=4)("SB", rs1=30, rs2=6, imm=7)
    p("LW", rd=25, rs1=30, imm=4)("LB", rd=26, rs1=30, imm=4)("LBU", rd=27, rs1=30, imm=4)
    p("LH", rd=28, rs1=30, imm=4)("LHU", rd=29, rs1=30, imm=6)
    # x0 is never written
    p("ADDI", rd=0, rs1=0, imm=5)("LW", rd=0, rs1=30, imm=0)("LUI", rd=0, imm=0x1000)
    # Branches: x31 counts wrong decisions. Taken branches jump over the increment.
    p("ADDI", rd=31, rs1=0, imm=0)
    for i, (br, a, b_, taken) in enumerate([
            ("BEQ", 1, 1, 1), ("BEQ", 1, 2, 0), ("BNE", 1, 2, 1), ("BNE", 2, 2, 0),
            ("BLT", 2, 1, 1), ("BLT", 1, 2, 0), ("BGE", 1, 2, 1), ("BGE", 2, 1, 0), ("BGE", 1, 1, 1),
            ("BLTU", 1, 2, 1), ("BLTU", 2, 1, 0), ("BGEU", 2, 1, 1), ("BGEU", 1, 2, 0)]):
        if taken:
            p.to(br, f"t{i}", rs1=a, rs2=b_)("ADDI", rd=31, rs1=31, imm=1).label(f"t{i}")
        else:
            p.to(br, f"t{i}", rs1=a, rs2=b_).to("JAL", f"n{i}", rd=0).label(f"t{i}")
            p("ADDI", rd=31, rs1=31, imm=1).label(f"n{i}")
    # Backward loop: count x6 from 4 up to 9
    p("ADDI", rd=7, rs1=0, imm=9).label("loop")("ADDI", rd=6, rs1=6, imm=1).to("BNE", "loop", rs1=6, rs2=7)
    # Call and return; JALR clears bit 0 of the target
    p.to("JAL", "func", rd=1)
    ret_pc = p.pc()
    p.to("JAL", "end", rd=0)
    p.label("func")("ADDI", rd=8, rs1=0, imm=42)("JALR", rd=0, rs1=1, imm=1)
    p.label("end")("FENCE")
    # Store every register for the hand check, then stop
    for r in range(1, 32):
        p("SW", rs1=30, rs2=r, imm=0x100 + 4 * r)
    p("ECALL")

    b, cause = await run_prog(dut, p)
    assert cause == "STOP_ECALL"
    stored = {r: b.mem.word(DATA + 0x100 + 4 * r) for r in range(1, 32)}
    expected = {
        1: ret_pc, 2: 0xFFFF_FFFD, 3: 0x1234_5675, 4: 0xEDCB_A985, 5: 0x2345_6780, 6: 9, 7: 9, 8: 42,
        9: 0xFFFF_FFFF, 10: 0x0FFF_FFFF, 11: 0xEDCB_A985, 12: 0x1234_567C, 13: 0x1234_5678,
        14: 0x1234_5000, 15: 1, 16: 1, 17: 0xEDCB_A987, 18: 0x7FF, 19: 0x78, 20: 0x3456_7800,
        21: 0xF, 22: 0xFFFF_FFFE, 23: 0xABCD_E000, 24: (auipc_pc + 0x1000) & MASK32,
        25: 0x0400_FFFD, 26: 0xFFFF_FFFD, 27: 0xFD, 28: 0xFFFF_FFFD, 29: 0x0400, 30: DATA, 31: 0,
    }
    bad = {f"x{r}": (f"{stored[r]:#010x}", f"{v:#010x}") for r, v in expected.items() if stored[r] != v}
    assert not bad, f"(stored, expected): {bad}"
    assert b.mem.word(DATA) == 0x1234_5678


@cocotb.test()
async def test_console(dut):
    """Byte stores to CONSOLE reach the console; a console load returns 0 without an error."""
    p = Prog().init_regs().li(30, CONSOLE_ADDR)
    for ch in b"Hi\n":
        p("ADDI", rd=5, rs1=0, imm=ch)("SB", rs1=30, rs2=5, imm=0)
    p("ADDI", rd=6, rs1=0, imm=-1)("LW", rd=6, rs1=30, imm=0)("ECALL")
    b, cause = await run_prog(dut, p)
    assert cause == "STOP_ECALL"
    assert bytes(b.mem.console) == b"Hi\n"
    assert b.model.regs[6] == 0


# Each case: (name, program body after the prologue of stop_case, expected cause).
# The last instruction of the body is the one that stops; everything else is legal.
STOP_CASES = [
    ("ecall", lambda p: p("ECALL"), "STOP_ECALL"),
    ("ebreak", lambda p: p("EBREAK"), "STOP_EBREAK"),
    ("illegal_zero", lambda p: p.word(0), "STOP_ILLEGAL"),
    ("illegal_csr", lambda p: p.word(0x3400_9073), "STOP_ILLEGAL"),          # csrw mscratch, x1
    ("illegal_mul", lambda p: p.word(0x0220_82B3), "STOP_ILLEGAL"),          # mul x5, x1, x2
    ("illegal_funct7", lambda p: p.word(asm("ADD", rd=5, rs1=1, rs2=2) | (1 << 26)), "STOP_ILLEGAL"),
    ("jal_misaligned", lambda p: p.word(asm("JAL", rd=5, imm=6)), "STOP_MISALIGNED_FETCH"),
    ("jalr_misaligned", lambda p: p.li(6, RESET_PC + 0x202)("JALR", rd=5, rs1=6, imm=0),
     "STOP_MISALIGNED_FETCH"),
    ("branch_misaligned", lambda p: p.word(asm("BEQ", rs1=0, rs2=0, imm=6)), "STOP_MISALIGNED_FETCH"),
    # A not-taken branch to a misaligned target and a JALR with only bit 0 set must not stop.
    ("not_stopping_then_ecall", lambda p: (p.word(asm("BNE", rs1=0, rs2=0, imm=6)).li(6, p.pc() + 8 + 9)
                                           ("JALR", rd=5, rs1=6, imm=0)("ECALL")("ECALL")), "STOP_ECALL"),
    ("lw_misaligned", lambda p: p("LW", rd=5, rs1=30, imm=2), "STOP_MISALIGNED_DATA"),
    ("lh_misaligned", lambda p: p("LH", rd=5, rs1=30, imm=1), "STOP_MISALIGNED_DATA"),
    ("sw_misaligned", lambda p: p("SW", rs1=30, rs2=1, imm=1), "STOP_MISALIGNED_DATA"),
    ("sh_misaligned", lambda p: p("SH", rs1=30, rs2=1, imm=3), "STOP_MISALIGNED_DATA"),
    ("lw_bus_error", lambda p: p("LW", rd=5, rs1=0, imm=0), "STOP_BUS_ERROR"),
    ("sw_bus_error", lambda p: p("SW", rs1=0, rs2=1, imm=0x10), "STOP_BUS_ERROR"),
    ("sb_bus_error", lambda p: p.li(6, 0x7FFF_FFFF)("SB", rs1=6, rs2=1, imm=0), "STOP_BUS_ERROR"),
    # The JALR retires normally (rd = x0 so x5 stays); the fetch at its target faults.
    ("ifetch_unmapped", lambda p: p.li(6, 0x0000_1000)("JALR", rd=0, rs1=6, imm=0), "STOP_IFETCH_ERROR"),
]
# A faulting fetch whose word would otherwise store, write a register, halt or be illegal:
# IFETCH_ERROR wins and nothing happens (spec §10 priority).
FAULT_WORDS = {
    "fault_store": asm("SW", rs1=30, rs2=1, imm=0),
    "fault_addi": asm("ADDI", rd=5, rs1=0, imm=7),
    "fault_ecall": asm("ECALL"),
    "fault_illegal": 0,
    "fault_jal_misaligned": asm("JAL", rd=5, imm=6),
}


async def stop_case(b, body, expected, fault_word=None):
    p = Prog().init_regs().li(30, DATA).li(1, 0x1122_3344).li(5, 0x55)
    faults = ()
    if fault_word is None:
        body(p)
    else:
        faults = (p.pc(),)
        p.word(fault_word)
    await b.new_program(p.image(), faults)
    cause = await b.run(idle_after=5)
    assert cause == expected, f"stopped with {cause}, expected {expected}"
    assert b.model.regs[5] == 0x55 or expected == "STOP_ECALL", "test bug: stopping instruction wrote x5"
    # The halt is sticky; reset clears it and the same program runs again.
    await b.reset()
    assert await b.run(idle_after=1) == expected


@cocotb.test()
async def test_stop_causes(dut):
    """Every stop cause (spec §10): no side effect, PC held, idle until reset, status latched."""
    b = Bench(dut)
    await b.start()
    seen = Counter()
    for name, body, expected in STOP_CASES:
        dut._log.info(f"stop case {name}")
        await stop_case(b, body, expected)
        seen[expected] += 1
    for name, word in FAULT_WORDS.items():
        dut._log.info(f"stop case {name}")
        await stop_case(b, None, "STOP_IFETCH_ERROR", fault_word=word)
    missing = set(STOP_CAUSES) - {"STOP_NONE", "STOP_IFETCH_ERROR"} - set(seen)
    assert not missing, f"no case for {missing}"


# ---------------------------------------------------------------------------
# Random programs
# ---------------------------------------------------------------------------

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


@cocotb.test()
async def test_random(dut):
    """Random programs, lockstep with the model; every stop cause must show up."""
    b = None
    causes = Counter()
    retired = 0
    for _ in range(150):
        prog = random_program()
        image = prog.image()
        # Random data around DATA so loads see varied bytes.
        for off in range(-0x800, 0x800, 4):
            image[DATA + off] = random.getrandbits(32)
        if b is None:
            b = Bench(dut, image)
            await b.start()
        else:
            await b.new_program(image, reset_cycles=random.randint(1, 3))
        start = b.cycles
        causes[await b.run(max_cycles=400, idle_after=1)] += 1
        retired += b.cycles - start
    dut._log.info(f"{retired} cycles, stop causes: {dict(causes)}")
    missing = set(STOP_CAUSES) - set(causes) - {"STOP_NONE"}
    assert not missing, f"random programs never hit {missing}: generator needs tuning"


@cocotb.test()
async def test_model_self_check(dut):
    """Sanity-check CoreModel on hand-computed values."""
    del dut  # model-only test
    p = Prog().li(1, 0x8000_8000).li(2, -2)
    p("SW", rs1=1, rs2=2, imm=0)("LBU", rd=3, rs1=1, imm=1)("JAL", rd=4, imm=8)("EBREAK")("EBREAK")
    m = CoreModel(SimMemory(p.image()))
    trace = [m.step() for _ in range(7)]
    assert trace[4]["mem_wmask"] == 0xF and trace[4]["mem_wdata"] == 0xFFFF_FFFE
    assert trace[5]["rd_wdata"] == 0xFF and trace[5]["mem_rmask"] == 0b0010
    assert trace[6]["rd_wdata"] == RESET_PC + 28 and trace[6]["pc_wdata"] == RESET_PC + 32
    r = m.step()
    assert (r["halt"], r["trap"], r["pc_wdata"], m.status) == (1, 0, RESET_PC + 32, STOP_CAUSES["STOP_EBREAK"])
    assert m.step()["valid"] == 0
