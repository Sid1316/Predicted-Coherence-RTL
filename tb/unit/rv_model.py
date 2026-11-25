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
