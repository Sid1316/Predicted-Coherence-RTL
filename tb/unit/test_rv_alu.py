"""cocotb unit tests for rv_alu (docs/exec.md M2.1, docs/spec.md §6.6)."""

import random

import cocotb
from cocotb.triggers import Timer

from rv_model import ALU_OPS, MASK32, alu_ref

# Values that sit on the edges of signed/unsigned 32-bit arithmetic.
EDGES = [
    0x0000_0000, 0x0000_0001, 0x0000_0002, 0x0000_001F, 0x0000_0020,
    0x7FFF_FFFF, 0x8000_0000, 0x8000_0001, 0xFFFF_FFFE, 0xFFFF_FFFF,
    0x1234_5678, 0xDEAD_BEEF,
]

# Shift operands: amounts 0, 1, 31, and values whose upper bits must be ignored.
SHIFT_B = [0, 1, 4, 16, 31, 32, 33, 63, 0xFFFF_FFE0, 0xFFFF_FFFF, 0x8000_001F]


async def check(dut, op_name, a, b):
    """Drive one vector, wait for the combinational result, compare with the model."""
    dut.op_i.value = ALU_OPS[op_name]
    dut.a_i.value = a
    dut.b_i.value = b
    await Timer(1, unit="ns")
    got = dut.res_o.value
    assert got.is_resolvable, f"{op_name} a={a:#010x} b={b:#010x}: result has X/Z: {got}"
    exp = alu_ref(op_name, a, b)
    assert got.to_unsigned() == exp, (
        f"{op_name} a={a:#010x} b={b:#010x}: got {got.to_unsigned():#010x}, expected {exp:#010x}"
    )


@cocotb.test()
async def test_edges(dut):
    """Every op on every pair of edge values."""
    for op_name in ALU_OPS:
        for a in EDGES:
            for b in EDGES:
                await check(dut, op_name, a, b)


@cocotb.test()
async def test_shift_amounts(dut):
    """Shifts use only b[4:0]: amounts 0/1/31 and upper bits of b ignored."""
    for op_name in ("ALU_SLL", "ALU_SRL", "ALU_SRA"):
        for a in EDGES:
            for b in SHIFT_B:
                await check(dut, op_name, a, b)


@cocotb.test()
async def test_random(dut):
    """Random operands for every op (seed is printed by cocotb at start-up)."""
    for _ in range(2000):
        op_name = random.choice(list(ALU_OPS))
        await check(dut, op_name, random.getrandbits(32), random.getrandbits(32))


@cocotb.test()
async def test_undefined_ops_give_zero(dut):
    """Encodings 10..15 of alu_op_t are unused and must give 0, not X."""
    for code in range(len(ALU_OPS), 16):
        dut.op_i.value = code
        dut.a_i.value = 0xFFFF_FFFF
        dut.b_i.value = 0xFFFF_FFFF
        await Timer(1, unit="ns")
        got = dut.res_o.value
        assert got.is_resolvable and got.to_unsigned() == 0, f"op {code}: got {got}"


@cocotb.test()
async def test_model_self_check(dut):
    """Sanity-check the Python model itself on hand-computed values."""
    del dut  # model-only test
    assert alu_ref("ALU_ADD", 0xFFFF_FFFF, 1) == 0
    assert alu_ref("ALU_SUB", 0, 1) == MASK32
    assert alu_ref("ALU_SLT", 0x8000_0000, 0) == 1
    assert alu_ref("ALU_SLTU", 0x8000_0000, 0) == 0
    assert alu_ref("ALU_SRA", 0x8000_0000, 31) == MASK32
    assert alu_ref("ALU_SRL", 0x8000_0000, 31) == 1
    assert alu_ref("ALU_SLL", 1, 33) == 2
