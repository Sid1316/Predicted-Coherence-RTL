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
