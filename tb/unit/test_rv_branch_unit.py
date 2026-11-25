"""cocotb unit tests for rv_branch_unit (docs/exec.md M2.4, docs/spec.md §6.7)."""

import random

import cocotb
from cocotb.triggers import Timer

from rv_model import BRANCH_OPS, branch_ref

# Values on the edges of signed/unsigned 32-bit comparison.
EDGES = [
    0x0000_0000, 0x0000_0001, 0x0000_0002, 0x7FFF_FFFE, 0x7FFF_FFFF,
    0x8000_0000, 0x8000_0001, 0xFFFF_FFFE, 0xFFFF_FFFF, 0x1234_5678,
]


async def check(dut, op_name, a, b):
    """Drive one vector, wait for the combinational result, compare with the model."""
    dut.op_i.value = BRANCH_OPS[op_name]
    dut.a_i.value = a
    dut.b_i.value = b
    await Timer(1, unit="ns")
    got = dut.taken_o.value
    assert got.is_resolvable, f"{op_name} a={a:#010x} b={b:#010x}: taken has X/Z: {got}"
    exp = branch_ref(op_name, a, b)
    assert int(got) == exp, f"{op_name} a={a:#010x} b={b:#010x}: got {int(got)}, expected {exp}"


@cocotb.test()
async def test_edges(dut):
    """Every op on every pair of edge values (includes a == b for each value)."""
    for op_name in BRANCH_OPS:
        for a in EDGES:
            for b in EDGES:
                await check(dut, op_name, a, b)


@cocotb.test()
async def test_signed_vs_unsigned(dut):
    """Pairs where signed and unsigned order disagree, checked by hand, not the model."""
    # (a, b, a <s b, a <u b)
    cases = [
        (0x8000_0000, 0x0000_0000, 1, 0),  # INT_MIN vs 0
        (0xFFFF_FFFF, 0x0000_0001, 1, 0),  # -1 vs 1
        (0xFFFF_FFFF, 0x7FFF_FFFF, 1, 0),  # -1 vs INT_MAX
        (0x7FFF_FFFF, 0x8000_0000, 0, 1),  # INT_MAX vs INT_MIN
        (0x0000_0000, 0xFFFF_FFFF, 0, 1),  # 0 vs -1
        (0x8000_0000, 0xFFFF_FFFF, 1, 1),  # INT_MIN vs -1: both say less
        (0xFFFF_FFFF, 0xFFFF_FFFF, 0, 0),  # equal
    ]
    for a, b, lt, ltu in cases:
        for op_name, exp in (("BR_LT", lt), ("BR_GE", 1 - lt), ("BR_LTU", ltu), ("BR_GEU", 1 - ltu)):
            assert branch_ref(op_name, a, b) == exp, f"model: {op_name} {a:#x} {b:#x}"
            await check(dut, op_name, a, b)


@cocotb.test()
async def test_eq_single_bit(dut):
    """BEQ/BNE see a difference in any single bit position."""
    base = random.getrandbits(32)
    for bit in range(32):
        for op_name in ("BR_EQ", "BR_NE"):
            await check(dut, op_name, base, base ^ (1 << bit))
            await check(dut, op_name, base, base)


@cocotb.test()
async def test_random(dut):
    """Random operands for every op; half the vectors share upper bits to hit near-equal cases."""
    for _ in range(3000):
        op_name = random.choice(list(BRANCH_OPS))
        a = random.getrandbits(32)
        b = random.getrandbits(32)
        if random.random() < 0.5:
            b = (a & 0xFFFF_FF00) | (b & 0xFF)
        await check(dut, op_name, a, b)


@cocotb.test()
async def test_undefined_ops_not_taken(dut):
    """funct3 010/011 are not branches and must give 0, not X."""
    for code in (0b010, 0b011):
        for a, b in ((0, 0), (0, 1), (1, 0), (0xFFFF_FFFF, 0)):
            dut.op_i.value = code
            dut.a_i.value = a
            dut.b_i.value = b
            await Timer(1, unit="ns")
            got = dut.taken_o.value
            assert got.is_resolvable and int(got) == 0, f"op {code:03b} a={a:#x} b={b:#x}: got {got}"
