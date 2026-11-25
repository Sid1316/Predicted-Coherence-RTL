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
