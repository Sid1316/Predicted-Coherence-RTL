"""Python reference models shared by the cocotb unit tests (docs/exec.md M2).

Encodings must match rtl/rv_pkg.sv (docs/spec.md §8). Enum values without an
explicit value are numbered in declaration order, starting at 0.
"""

MASK32 = 0xFFFF_FFFF

# alu_op_t, in declaration order (spec §8.2)
ALU_OPS = {
    "ALU_ADD": 0,
    "ALU_SUB": 1,
    "ALU_SLL": 2,
    "ALU_SLT": 3,
    "ALU_SLTU": 4,
    "ALU_XOR": 5,
    "ALU_SRL": 6,
    "ALU_SRA": 7,
    "ALU_OR": 8,
    "ALU_AND": 9,
}


def to_signed32(x: int) -> int:
    """Interpret a 32-bit value as two's complement."""
    x &= MASK32
    return x - (1 << 32) if x & 0x8000_0000 else x


def alu_ref(op_name: str, a: int, b: int) -> int:
    """RV32I ALU result (spec §4 operations, §6.6 shift rule)."""
    a &= MASK32
    b &= MASK32
    shamt = b & 0x1F
    if op_name == "ALU_ADD":
        return (a + b) & MASK32
    if op_name == "ALU_SUB":
        return (a - b) & MASK32
    if op_name == "ALU_SLL":
        return (a << shamt) & MASK32
    if op_name == "ALU_SLT":
        return int(to_signed32(a) < to_signed32(b))
    if op_name == "ALU_SLTU":
        return int(a < b)
    if op_name == "ALU_XOR":
        return a ^ b
    if op_name == "ALU_SRL":
        return a >> shamt
    if op_name == "ALU_SRA":
        return (to_signed32(a) >> shamt) & MASK32
    if op_name == "ALU_OR":
        return a | b
    if op_name == "ALU_AND":
        return a & b
    raise ValueError(f"unknown ALU op {op_name}")


# ---------------------------------------------------------------------------
# Immediates (spec §4.1)
# ---------------------------------------------------------------------------

# imm_type_t, in declaration order (spec §8.2)
IMM_TYPES = {
    "IMM_NONE": 0,
    "IMM_I": 1,
    "IMM_S": 2,
    "IMM_B": 3,
    "IMM_U": 4,
    "IMM_J": 5,
}

# Where each immediate bit sits in the instruction word, written the way the
# ISA manual draws the formats: (imm_hi, imm_lo, inst_hi, inst_lo) means
# imm[imm_hi:imm_lo] is stored in inst[inst_hi:inst_lo].
# Immediate bits not listed are zero (B/J bit 0, U bits 11:0) or a copy of
# the sign bit (the top bit of the format).
IMM_FIELDS = {
    "IMM_I": [(11, 0, 31, 20)],
    "IMM_S": [(11, 5, 31, 25), (4, 0, 11, 7)],
    "IMM_B": [(12, 12, 31, 31), (10, 5, 30, 25), (4, 1, 11, 8), (11, 11, 7, 7)],
    "IMM_U": [(31, 12, 31, 12)],
    "IMM_J": [(20, 20, 31, 31), (10, 1, 30, 21), (11, 11, 20, 20), (19, 12, 19, 12)],
}

# Width of the immediate before sign extension, and its lowest stored bit.
IMM_WIDTH = {"IMM_I": 12, "IMM_S": 12, "IMM_B": 13, "IMM_U": 32, "IMM_J": 21}
IMM_ALIGN = {"IMM_I": 0, "IMM_S": 0, "IMM_B": 1, "IMM_U": 12, "IMM_J": 1}


def _bits(value: int, hi: int, lo: int) -> int:
    return (value >> lo) & ((1 << (hi - lo + 1)) - 1)


def sext(value: int, width: int) -> int:
    """Sign-extend a width-bit value to 32 bits (result is unsigned 32-bit)."""
    value &= (1 << width) - 1
    if value & (1 << (width - 1)):
        value -= 1 << width
    return value & MASK32


def imm_decode(type_name: str, inst: int) -> int:
    """Immediate the decoder should produce for this instruction word."""
    if type_name not in IMM_FIELDS:  # IMM_NONE and unused encodings
        return 0
    imm = 0
    for imm_hi, imm_lo, inst_hi, inst_lo in IMM_FIELDS[type_name]:
        imm |= _bits(inst, inst_hi, inst_lo) << imm_lo
    return sext(imm, IMM_WIDTH[type_name])


def imm_encode(type_name: str, imm: int, other_bits: int = 0) -> int:
    """Instruction word holding imm in its immediate fields.

    other_bits fills every bit that is not part of the immediate (opcode,
    registers, funct3), so tests can check those bits are ignored.
    """
    inst = 0
    used = 0
    for imm_hi, imm_lo, inst_hi, inst_lo in IMM_FIELDS[type_name]:
        width = imm_hi - imm_lo + 1
        inst |= _bits(imm, imm_hi, imm_lo) << inst_lo
        used |= ((1 << width) - 1) << inst_lo
    return (inst | (other_bits & ~used)) & MASK32


def imm_range(type_name: str) -> tuple[int, int, int]:
    """(min, max, step) of the signed immediate values a format can hold."""
    width = IMM_WIDTH[type_name]
    step = 1 << IMM_ALIGN[type_name]
    if type_name == "IMM_U":
        return (-(1 << 31), (1 << 31) - step, step)
    return (-(1 << (width - 1)), (1 << (width - 1)) - step, step)


# ---------------------------------------------------------------------------
# Register file (spec §6.5)
# ---------------------------------------------------------------------------

class RegFileModel:
    """x0..x31; x0 reads 0 and ignores writes. None means "never written".

    Matches the RTL timing: read() gives the value before the next clock edge,
    write() is applied at the edge.
    """

    def __init__(self) -> None:
        self.regs: list[int | None] = [0] + [None] * 31

    def read(self, addr: int) -> int | None:
        return 0 if addr == 0 else self.regs[addr]

    def write(self, we: int, addr: int, data: int) -> None:
        if we and addr != 0:
            self.regs[addr] = data & MASK32


# ---------------------------------------------------------------------------
# Branch unit (spec §6.7)
# ---------------------------------------------------------------------------

# branch_op_t: values equal funct3 (spec §8.2)
BRANCH_OPS = {
    "BR_EQ": 0b000,
    "BR_NE": 0b001,
    "BR_LT": 0b100,
    "BR_GE": 0b101,
    "BR_LTU": 0b110,
    "BR_GEU": 0b111,
}


def branch_ref(op_name: str, a: int, b: int) -> int:
    """1 if the branch is taken (RV32I BEQ/BNE/BLT/BGE/BLTU/BGEU)."""
    a &= MASK32
    b &= MASK32
    if op_name == "BR_EQ":
        return int(a == b)
    if op_name == "BR_NE":
        return int(a != b)
    if op_name == "BR_LT":
        return int(to_signed32(a) < to_signed32(b))
    if op_name == "BR_GE":
        return int(to_signed32(a) >= to_signed32(b))
    if op_name == "BR_LTU":
        return int(a < b)
    if op_name == "BR_GEU":
        return int(a >= b)
    raise ValueError(f"unknown branch op {op_name}")


# ---------------------------------------------------------------------------
# Packed structs (spec §8.2, §8.3)
# ---------------------------------------------------------------------------
# Fields in declaration order with their widths. In a SystemVerilog packed
# struct the first field is the most significant.

CTRL_FIELDS = [
    ("imm_type", 3), ("op_a_sel", 2), ("op_b_sel", 1), ("alu_op", 4),
    ("wb_sel", 2), ("reg_write", 1), ("mem_read", 1), ("mem_write", 1),
    ("mem_size", 2), ("mem_unsigned", 1), ("branch", 1), ("br_op", 3),
    ("jump", 1), ("jalr", 1), ("is_fence", 1), ("is_ecall", 1),
    ("is_ebreak", 1), ("illegal", 1),
]  # 28 bits
DMEM_REQ_FIELDS = [("valid", 1), ("we", 1), ("be", 4), ("addr", 32), ("wdata", 32)]  # 70 bits
DMEM_RSP_FIELDS = [("ready", 1), ("rdata", 32), ("err", 1)]  # 34 bits


def struct_width(fields: list[tuple[str, int]]) -> int:
    return sum(w for _, w in fields)


def struct_pack(fields: list[tuple[str, int]], **values: int) -> int:
    """Packed-struct integer; fields not given are 0."""
    unknown = set(values) - {name for name, _ in fields}
    if unknown:
        raise ValueError(f"unknown field(s) {sorted(unknown)}")
    word = 0
    for name, width in fields:
        v = values.get(name, 0)
        if v >> width:
            raise ValueError(f"{name}={v:#x} does not fit in {width} bits")
        word = (word << width) | v
    return word


def struct_unpack(fields: list[tuple[str, int]], word: int) -> dict[str, int]:
    out = {}
    for name, width in reversed(fields):
        out[name] = word & ((1 << width) - 1)
        word >>= width
    return out


# ---------------------------------------------------------------------------
# Load/store unit (spec §5.4, §6.8)
# ---------------------------------------------------------------------------

# mem_size_t, in declaration order (spec §8.2)
MEM_SIZES = {"MEM_B": 0, "MEM_H": 1, "MEM_W": 2}
SIZE_BYTES = {"MEM_B": 1, "MEM_H": 2, "MEM_W": 4}


def lsu_misaligned(size_name: str, addr: int) -> bool:
    """Spec §5.4: halfwords need addr[0] = 0, words addr[1:0] = 0."""
    return addr % SIZE_BYTES[size_name] != 0


def lsu_ref(*, size_name: str, unsigned: int, mem_read: int, mem_write: int, enable: int,
            addr: int, store_data: int, rdata: int, err: int) -> dict[str, int | None]:
    """Expected LSU outputs. load_data is None where it is don't-care
    (no load, or a misaligned one); the tests then check it is only X-free."""
    addr &= MASK32
    off = addr & 3
    nbytes = SIZE_BYTES[size_name]
    is_mem = bool(mem_read or mem_write)
    mis = lsu_misaligned(size_name, addr)
    valid = bool(enable and is_mem and not mis)

    # Bytes off .. off+nbytes-1 of the word are accessed.
    mask = ((1 << nbytes) - 1) << off if not mis else None
    # Each lane holds store_data's byte (lane mod nbytes), so the accessed
    # lanes carry store_data[nbytes*8-1:0] in order.
    sd = store_data.to_bytes(4, "little")
    wdata = int.from_bytes(bytes(sd[lane % nbytes] for lane in range(4)), "little")

    load_data = None
    if mem_read and not mis:
        raw = (rdata >> (8 * off)) & ((1 << (8 * nbytes)) - 1)
        load_data = raw if (unsigned or nbytes == 4) else sext(raw, 8 * nbytes)

    return {
        "valid": int(valid),
        "we": int(valid and bool(mem_write)),
        "be": mask if valid else 0,
        "addr": addr,
        "wdata": wdata,
        "load_data": load_data,
        "misaligned": int(bool(enable and is_mem and mis)),
        "bus_err": int(valid and bool(err)),
    }


# ---------------------------------------------------------------------------
# Decoder (spec §4, §4.2, §6.3, §7)
# ---------------------------------------------------------------------------
# The expected values come from the tables in docs/spec.md, parsed at import
# time, so the spec and the test cannot drift apart (exec.md M2.6).

import re
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "spec.md"

# Remaining enums, in declaration order (spec §8.2)
OPA_SELS = {"OPA_RS1": 0, "OPA_PC": 1, "OPA_ZERO": 2}
OPB_SELS = {"OPB_RS2": 0, "OPB_IMM": 1}
WB_SELS = {"WB_ALU": 0, "WB_MEM": 1, "WB_PC4": 2}

DASH = "—"


def _md_table(text: str, header_prefix: str) -> list[list[str]]:
    """Rows (cells stripped of backticks) of the markdown table whose header starts with header_prefix."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(header_prefix))
    header = [c.strip().strip("`") for c in lines[start].strip().strip("|").split("|")]
    rows = []
    for ln in lines[start + 2:]:
        if not ln.startswith("|"):
            break
        # "\|" inside a cell is an escaped pipe, not a column separator
        cells = [c.strip().replace("`", "") for c in re.split(r"(?<!\\)\|", ln.strip().strip("|"))]
        assert len(cells) == len(header), f"bad row in spec table: {ln}"
        rows.append(dict(zip(header, cells)))
    return rows


def _encoding_rules(spec: str) -> dict[str, dict]:
    """§4 table -> {instr: {"mask": m, "match": v}}: inst & mask == match means this instruction."""
    rules = {}
    for row in _md_table(spec, "| # | Instr | Fmt"):
        mask, match = 0x7F, int(row["opcode"], 2)
        if row["funct3"] != DASH:
            mask |= 0x7 << 12
            match |= int(row["funct3"], 2) << 12
        f7 = row["funct7 / imm"]
        if re.fullmatch(r"[01]{7}", f7):
            mask |= 0x7F << 25
            match |= int(f7, 2) << 25
        else:
            # e.g. "imm=1, rs1=0, rd=0" (ECALL/EBREAK) or "any fm/pred/succ" (FENCE)
            fields = {"imm": (31, 20), "rs1": (19, 15), "rd": (11, 7)}
            for name, value in re.findall(r"(\w+)=(\d+)", f7):
                hi, lo = fields[name]
                mask |= ((1 << (hi - lo + 1)) - 1) << lo
                match |= int(value) << lo
            assert f7 == DASH or f7.startswith("any") or "=" in f7, f"unparsed §4 cell: {f7}"
        rules[row["Instr"]] = {"mask": mask, "match": match}
    return rules


_CTRL_ENUMS = {
    "imm": ("imm_type", "IMM_", IMM_TYPES),
    "op_a": ("op_a_sel", "OPA_", OPA_SELS),
    "op_b": ("op_b_sel", "OPB_", OPB_SELS),
    "alu_op": ("alu_op", "ALU_", ALU_OPS),
    "wb_sel": ("wb_sel", "WB_", WB_SELS),
    "mem_size": ("mem_size", "MEM_", MEM_SIZES),
}
_CTRL_BITS = {"reg_write": "reg_write", "mem_read": "mem_read", "mem_write": "mem_write",
              "mem_uns": "mem_unsigned", "branch": "branch", "jump": "jump", "jalr": "jalr"}


def _control_table(spec: str) -> dict[str, dict[str, int]]:
    """§7 table -> {instr: ctrl_t field values}; "—" is 0 (first enum value)."""
    table = {}
    for row in _md_table(spec, "| Instr | `imm`"):
        ctrl = {name: 0 for name, _ in CTRL_FIELDS}
        for col, (field, prefix, enum) in _CTRL_ENUMS.items():
            if row[col] != DASH:
                ctrl[field] = enum[prefix + row[col]]
        for col, field in _CTRL_BITS.items():
            if row[col] != DASH:
                ctrl[field] = int(row[col])
        for name, value in re.findall(r"(\w+)=(\w+)", row["Other"]):
            ctrl[name] = BRANCH_OPS["BR_" + value] if name == "br_op" else int(value)
        table[row["Instr"].strip("*")] = ctrl
    return table


_SPEC = SPEC_PATH.read_text(encoding="utf-8")
ENCODINGS = _encoding_rules(_SPEC)
CONTROL = _control_table(_SPEC)   # includes the "illegal" row
INSTRS = list(ENCODINGS)


def decode_ref(inst: int) -> tuple[str, dict[str, int]]:
    """(instruction name or "illegal", expected ctrl_t fields) for a 32-bit word."""
    hits = [name for name, r in ENCODINGS.items() if inst & r["mask"] == r["match"]]
    assert len(hits) <= 1, f"{inst:#010x} matches several §4 rows: {hits}"
    name = hits[0] if hits else "illegal"
    return name, CONTROL[name]


def encode(name: str, rand_bits: int) -> int:
    """A legal word for instruction `name`, with every free bit taken from rand_bits."""
    r = ENCODINGS[name]
    return (rand_bits & ~r["mask"] & MASK32) | r["match"]


# ---------------------------------------------------------------------------
# PC and next-PC logic (spec §5.2, §6.2)
# ---------------------------------------------------------------------------

RESET_PC = 0x8000_0000  # spec §2.4


def next_pc_ref(*, pc: int, halted: int, stop: int, jump: int, jalr: int, branch: int,
                br_taken: int, target: int) -> tuple[int, int]:
    """(next_pc, misaligned_fetch) for one cycle, written from the §5.2 prose:
    a jump always redirects, a branch only when taken; JALR clears bit 0;
    a redirect to an address with bit 1 set is a misaligned fetch; a halted or
    stopping core keeps its PC."""
    redirects = bool(jump) or (bool(branch) and bool(br_taken))
    dest = target & ~1 & MASK32 if jalr else target & MASK32
    misaligned = int(redirects and bool(dest & 0b10))
    if halted or stop:
        return pc, misaligned
    return (dest if redirects else (pc + 4) & MASK32), misaligned


# ---------------------------------------------------------------------------
# Core: assembler, memory and instruction-set model (spec §2.3, §4, §9, §10)
# ---------------------------------------------------------------------------
# Used by the rv_core test, which runs programs on the RTL and on this model
# and compares the retire port every cycle. The model is written from the
# operation column of spec §4 and the rules of §9/§10, not from the RTL
# structure (it has no ctrl_t, no operand muxes, no stop-priority chain).

IMEM_REQ_FIELDS = [("valid", 1), ("addr", 32)]
IMEM_RSP_FIELDS = [("ready", 1), ("rdata", 32), ("err", 1)]
RETIRE_FIELDS = [
    ("valid", 1), ("order", 64), ("insn", 32), ("pc_rdata", 32), ("pc_wdata", 32),
    ("rs1_addr", 5), ("rs2_addr", 5), ("rs1_rdata", 32), ("rs2_rdata", 32),
    ("rd_addr", 5), ("rd_wdata", 32), ("mem_addr", 32), ("mem_rmask", 4), ("mem_wmask", 4),
    ("mem_rdata", 32), ("mem_wdata", 32), ("trap", 1), ("halt", 1),
]  # 378 bits

# stop_cause_t, in declaration order (spec §8.4)
STOP_CAUSES = {
    "STOP_NONE": 0, "STOP_ECALL": 1, "STOP_EBREAK": 2, "STOP_ILLEGAL": 3,
    "STOP_MISALIGNED_FETCH": 4, "STOP_MISALIGNED_DATA": 5, "STOP_BUS_ERROR": 6,
    "STOP_IFETCH_ERROR": 7,
}

MEM_BASE = 0x8000_0000       # spec §2.3
MEM_SIZE_BYTES = 0x1_0000
CONSOLE_ADDR = 0x1000_0000
CYCLE_ADDR = 0x1000_0008     # 64-bit cycle counter, LO then HI (sim/rv_soc_sim.sv)

FORMATS = {row["Instr"]: row["Fmt"] for row in _md_table(_SPEC, "| # | Instr | Fmt")}


def asm(name: str, rd: int = 0, rs1: int = 0, rs2: int = 0, imm: int = 0) -> int:
    """Encode one instruction. Shifts take the shift amount as imm."""
    match = ENCODINGS[name]["match"]
    fmt = FORMATS[name]
    regs = (rd << 7) | (rs1 << 15) | (rs2 << 20)
    if name in ("ECALL", "EBREAK"):    # every field is fixed
        return match
    if name in ("SLLI", "SRLI", "SRAI"):
        return match | (rd << 7) | (rs1 << 15) | ((imm & 0x1F) << 20)
    if fmt == "R":
        return match | regs
    if fmt == "I":
        return imm_encode("IMM_I", imm, match | (rd << 7) | (rs1 << 15))
    if fmt == "S":
        return imm_encode("IMM_S", imm, match | (rs1 << 15) | (rs2 << 20))
    if fmt == "B":
        return imm_encode("IMM_B", imm, match | (rs1 << 15) | (rs2 << 20))
    if fmt == "U":
        return imm_encode("IMM_U", imm, match | (rd << 7))
    if fmt == "J":
        return imm_encode("IMM_J", imm, match | (rd << 7))
    raise ValueError(f"unknown format {fmt} for {name}")


def asm_li(rd: int, value: int) -> list[int]:
    """LUI + ADDI pair that loads any 32-bit constant."""
    value &= MASK32
    lo = sext(value & 0xFFF, 12)
    hi = (value - lo) & MASK32
    return [asm("LUI", rd=rd, imm=hi), asm("ADDI", rd=rd, rs1=rd, imm=to_signed32(lo))]


class SimMemory:
    """The memory map of spec §2.3: RAM at MEM_BASE, CONSOLE, everything else unmapped.

    `size` is the RAM size in bytes (spec §2.4 MEM_SIZE_BYTES); RISCOF runs use
    a larger RAM than the 64 KiB default (exec.md M5.3)."""

    def __init__(self, image: dict[int, int] | None = None, size: int = MEM_SIZE_BYTES):
        self.size = size
        self.ram = bytearray(size)
        self.cycle = 0          # the CYCLE counter's value; CoreModel.step sets it
        self.console = bytearray()
        # RAM addresses whose fetch reports err (the response still carries
        # the stored word), to check that a faulting fetch has no effect.
        self.fetch_faults: set[int] = set()
        for addr, word in (image or {}).items():
            self.ram[addr - MEM_BASE:addr - MEM_BASE + 4] = word.to_bytes(4, "little")

    def in_ram(self, addr: int) -> bool:
        return MEM_BASE <= addr < MEM_BASE + self.size

    @staticmethod
    def is_console(addr: int) -> bool:
        return addr & ~3 & MASK32 == CONSOLE_ADDR

    @staticmethod
    def is_cycle(addr: int) -> bool:
        return addr & ~7 & MASK32 == CYCLE_ADDR

    def fetch(self, addr: int) -> tuple[int, int]:
        """(word, err) for an instruction fetch; only RAM is executable."""
        if not self.in_ram(addr):
            return 0, 1
        return self.word(addr), int(addr in self.fetch_faults)

    def word(self, addr: int) -> int:
        a = (addr & ~3) - MEM_BASE
        return int.from_bytes(self.ram[a:a + 4], "little")

    def read(self, addr: int) -> tuple[int, int]:
        """(aligned word, err) for a data read."""
        if self.in_ram(addr):
            return self.word(addr), 0
        if self.is_console(addr):
            return 0, 0
        if self.is_cycle(addr):
            return (self.cycle >> 32 if addr & 4 else self.cycle) & MASK32, 0
        return 0, 1

    def write(self, addr: int, be: int, wdata: int) -> int:
        """Apply a lane-placed store; returns err."""
        if self.is_console(addr):
            if be & 1:
                self.console.append(wdata & 0xFF)
            return 0
        if self.is_cycle(addr):
            return 1                # read-only
        if not self.in_ram(addr):
            return 1
        a = (addr & ~3) - MEM_BASE
        for lane in range(4):
            if be >> lane & 1:
                self.ram[a + lane] = (wdata >> (8 * lane)) & 0xFF
        return 0


_LOADS = {"LB": (1, False), "LH": (2, False), "LW": (4, False), "LBU": (1, True), "LHU": (2, True)}
_STORES = {"SB": 1, "SH": 2, "SW": 4}
_BRANCH_REF_OPS = {"BEQ": "BR_EQ", "BNE": "BR_NE", "BLT": "BR_LT", "BGE": "BR_GE",
                   "BLTU": "BR_LTU", "BGEU": "BR_GEU"}
_ALU_INSTRS = {  # name -> (ALU op, second operand is the immediate)
    "ADDI": ("ALU_ADD", True), "SLTI": ("ALU_SLT", True), "SLTIU": ("ALU_SLTU", True),
    "XORI": ("ALU_XOR", True), "ORI": ("ALU_OR", True), "ANDI": ("ALU_AND", True),
    "SLLI": ("ALU_SLL", True), "SRLI": ("ALU_SRL", True), "SRAI": ("ALU_SRA", True),
    "ADD": ("ALU_ADD", False), "SUB": ("ALU_SUB", False), "SLL": ("ALU_SLL", False),
    "SLT": ("ALU_SLT", False), "SLTU": ("ALU_SLTU", False), "XOR": ("ALU_XOR", False),
    "SRL": ("ALU_SRL", False), "SRA": ("ALU_SRA", False), "OR": ("ALU_OR", False),
    "AND": ("ALU_AND", False),
}


class CoreModel:
    """RV32I instruction-set model of rv_core. step() returns the expected
    retire_t fields for the instruction at pc and updates the state.

    regs[i] is None until written (the RTL register file is not reset); a
    program that reads such a register is a test bug and raises."""

    def __init__(self, mem: SimMemory, reset_pc: int = RESET_PC):
        self.mem = mem
        self.reset_pc = reset_pc
        self.regs: list[int | None] = [None] * 32   # not cleared by reset (spec §2.2)
        self.reset()

    def reset(self):
        self.pc = self.reset_pc
        self.order = 0
        self.halted = False
        self.status = STOP_CAUSES["STOP_NONE"]

    def _reg(self, i: int) -> int:
        if i == 0:
            return 0
        if self.regs[i] is None:
            raise AssertionError(f"program reads x{i} before writing it")
        return self.regs[i]

    def step(self) -> dict[str, int]:
        if self.halted:
            return struct_unpack(RETIRE_FIELDS, 0)
        pc = self.pc
        r = {name: 0 for name, _ in RETIRE_FIELDS}
        r.update(valid=1, order=self.order, pc_rdata=pc)
        self.mem.cycle = self.order     # one instruction per cycle since reset
        self.order += 1

        word, ferr = self.mem.fetch(pc)
        if ferr:
            return self._stop(r, "STOP_IFETCH_ERROR")   # insn reported as 0
        r["insn"] = word
        name, _ = decode_ref(word)
        if name == "illegal":
            return self._stop(r, "STOP_ILLEGAL")
        if name in ("ECALL", "EBREAK"):
            return self._stop(r, "STOP_" + name)

        fmt = FORMATS[name]
        rd, rs1, rs2 = (word >> 7) & 31, (word >> 15) & 31, (word >> 20) & 31
        if fmt in ("R", "I", "S", "B") and name != "FENCE":
            r["rs1_addr"], r["rs1_rdata"] = rs1, self._reg(rs1)
        if fmt in ("R", "S", "B"):
            r["rs2_addr"], r["rs2_rdata"] = rs2, self._reg(rs2)
        a, b = r["rs1_rdata"], r["rs2_rdata"]
        imm = imm_decode("IMM_" + fmt, word) if fmt != "R" else 0

        next_pc = (pc + 4) & MASK32
        result = None   # value written to rd, if any
        if name in _ALU_INSTRS:
            op, uses_imm = _ALU_INSTRS[name]
            result = alu_ref(op, a, imm if uses_imm else b)
        elif name == "LUI":
            result = imm
        elif name == "AUIPC":
            result = (pc + imm) & MASK32
        elif name in ("JAL", "JALR"):
            target = (pc + imm) & MASK32 if name == "JAL" else (a + imm) & MASK32 & ~1
            if target & 2:
                return self._stop(r, "STOP_MISALIGNED_FETCH")
            result, next_pc = (pc + 4) & MASK32, target
        elif name in _BRANCH_REF_OPS:
            if branch_ref(_BRANCH_REF_OPS[name], a, b):
                target = (pc + imm) & MASK32
                if target & 2:
                    return self._stop(r, "STOP_MISALIGNED_FETCH")
                next_pc = target
        elif name in _LOADS or name in _STORES:
            addr = (a + imm) & MASK32
            size = _LOADS[name][0] if name in _LOADS else _STORES[name]
            if addr % size:
                return self._stop(r, "STOP_MISALIGNED_DATA")
            mask = ((1 << size) - 1) << (addr & 3)
            if name in _LOADS:
                rdata, err = self.mem.read(addr)
                if err:
                    return self._stop(r, "STOP_BUS_ERROR")
                raw = (rdata >> (8 * (addr & 3))) & ((1 << (8 * size)) - 1)
                result = raw if _LOADS[name][1] or size == 4 else sext(raw, 8 * size)
                r.update(mem_addr=addr & ~3, mem_rmask=mask, mem_rdata=rdata)
            else:
                data = b & ((1 << (8 * size)) - 1)
                # Lanes outside the mask carry copies of the data (spec §5.4)
                wdata = int.from_bytes(bytes(data.to_bytes(4, "little")[lane % size]
                                             for lane in range(4)), "little")
                if self.mem.write(addr, mask, wdata):
                    return self._stop(r, "STOP_BUS_ERROR")
                r.update(mem_addr=addr & ~3, mem_wmask=mask, mem_wdata=wdata)
        elif name == "FENCE":
            pass
        else:
            raise AssertionError(f"model has no semantics for {name}")

        if result is not None and rd != 0:
            self.regs[rd] = result
            r["rd_addr"], r["rd_wdata"] = rd, result
        self.pc = next_pc
        r["pc_wdata"] = next_pc
        return r

    def _stop(self, r: dict[str, int], cause: str) -> dict[str, int]:
        """A stopping instruction: no side effects, PC stays, core halts (spec §10)."""
        r.update(rd_addr=0, rd_wdata=0, mem_addr=0, mem_rmask=0, mem_wmask=0,
                 mem_rdata=0, mem_wdata=0, pc_wdata=r["pc_rdata"])
        r["halt"] = int(cause in ("STOP_ECALL", "STOP_EBREAK"))
        r["trap"] = 1 - r["halt"]
        self.halted = True
        self.status = STOP_CAUSES[cause]
        return r


# ---------------------------------------------------------------------------
# Retire log and memory image formats (spec §9.2, §6.9)
# ---------------------------------------------------------------------------

def retire_log_line(r: dict[str, int], status: int) -> str:
    """One spec §9.2 retire-log line for retire fields `r`; `status` is the
    stop_cause_t value latched by this instruction (used for HALT/TRAP)."""
    s = f"{r['order'] & MASK32:08x} {r['pc_rdata']:08x} {r['insn']:08x}"
    if r["rd_addr"]:
        s += f" x{r['rd_addr']} {r['rd_wdata']:08x}"
    if r["mem_wmask"]:
        s += f" mem W {r['mem_addr']:08x} {r['mem_wmask']:x} {r['mem_wdata']:08x}"
    if r["mem_rmask"]:
        s += f" mem R {r['mem_addr']:08x} {r['mem_rmask']:x} {r['mem_rdata']:08x}"
    if r["halt"] or r["trap"]:
        cause = next(k for k, v in STOP_CAUSES.items() if v == status)
        s += f" {'HALT' if r['halt'] else 'TRAP'} {cause[len('STOP_'):]}"
    return s


def write_hex(image: dict[int, int], path, per_line: int = 4) -> None:
    """Write a word image {byte address: word} in the rv_mem_model $readmemh
    format: `@<word index from MEM_BASE>` before each run of consecutive
    words, upper-case hex, as objcopy -O verilog --verilog-data-width=4 does."""
    lines = []
    prev = None
    run: list[str] = []

    def flush():
        for i in range(0, len(run), per_line):
            lines.append(" ".join(run[i:i + per_line]))

    for addr in sorted(image):
        assert addr % 4 == 0 and MEM_BASE <= addr < MEM_BASE + MEM_SIZE_BYTES, f"bad image address {addr:#x}"
        idx = (addr - MEM_BASE) // 4
        if idx != (None if prev is None else prev + 1):
            flush()
            run = []
            lines.append(f"@{idx:08X}")
        run.append(f"{image[addr] & MASK32:08X}")
        prev = idx
    flush()
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")


def read_hex(path) -> dict[int, int]:
    """Parse a word-wide $readmemh file (the subset write_hex and objcopy
    produce: @ addresses, hex words, // comments) into {byte address: word}."""
    image = {}
    idx = 0
    for line in Path(path).read_text(encoding="ascii").splitlines():
        for tok in line.split("//")[0].split():
            if tok.startswith("@"):
                idx = int(tok[1:], 16)
            else:
                image[MEM_BASE + 4 * idx] = int(tok, 16)
                idx += 1
    return image
