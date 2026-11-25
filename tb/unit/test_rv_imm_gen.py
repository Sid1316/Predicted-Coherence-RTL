"""cocotb unit tests for rv_imm_gen (docs/exec.md M2.2, docs/spec.md §4.1, §6.4)."""

import random

import cocotb
from cocotb.triggers import Timer

from rv_model import IMM_FIELDS, IMM_TYPES, MASK32, imm_decode, imm_encode, imm_range, sext

# Encodings produced by the real assembler (riscv-none-elf-as 2.45,
# -march=rv32i, no compressed instructions). Branch/jump offsets were written
# relative to the instruction itself, so the immediate is exactly the offset.
GOLDEN = [
    # (inst, type, immediate as a signed value, source line)
    (0x80010093, "IMM_I", -2048, "addi x1, x2, -2048"),
    (0x7FF10093, "IMM_I", 2047, "addi x1, x2, 2047"),
    (0xFFF100E7, "IMM_I", -1, "jalr x1, -1(x2)"),
    (0xFE532FA3, "IMM_S", -1, "sw x5, -1(x6)"),
    (0x7E532FA3, "IMM_S", 2047, "sw x5, 2047(x6)"),
    (0x80741023, "IMM_S", -2048, "sh x7, -2048(x8)"),
    (0x80208063, "IMM_B", -4096, "beq x1, x2, . - 4096"),
    (0x7E419FE3, "IMM_B", 4094, "bne x3, x4, . + 4094"),
    (0xFE62DFE3, "IMM_B", -2, "bge x5, x6, . - 2"),
    (0x0083E163, "IMM_B", 2, "bltu x7, x8, . + 2"),
    (0xFFFFF0B7, "IMM_U", -4096, "lui x1, 0xfffff"),
    (0x800000B7, "IMM_U", -(1 << 31), "lui x1, 0x80000"),
    (0x12345197, "IMM_U", 0x12345000, "auipc x3, 0x12345"),
    (0x800000EF, "IMM_J", -1048576, "jal x1, . - 1048576"),
    (0x7FFFF06F, "IMM_J", 1048574, "jal x0, . + 1048574"),
    (0xFFFFF0EF, "IMM_J", -2, "jal x1, . - 2"),
    (0x001000EF, "IMM_J", 2048, "jal x1, . + 2048"),
]


async def drive(dut, type_code: int, inst: int) -> int:
    dut.inst_i.value = inst
    dut.type_i.value = type_code
    await Timer(1, unit="ns")
    got = dut.imm_o.value
    assert got.is_resolvable, f"type {type_code} inst {inst:#010x}: X/Z in output: {got}"
    return got.to_unsigned()


async def check(dut, type_name: str, inst: int, expected: int, what: str = "") -> None:
    got = await drive(dut, IMM_TYPES[type_name], inst)
    assert got == expected & MASK32, (
        f"{type_name} inst={inst:#010x} {what}: got {got:#010x}, expected {expected & MASK32:#010x}"
    )


@cocotb.test()
async def test_golden_assembler(dut):
    """Encodings from the real assembler give exactly the immediate written in the source."""
    for inst, type_name, imm, src in GOLDEN:
        await check(dut, type_name, inst, imm, f"({src})")


@cocotb.test()
async def test_round_trip_extremes(dut):
    """For every format: min, max, -1/0/+1 steps, and every single-bit immediate."""
    for type_name in IMM_FIELDS:
        lo, hi, step = imm_range(type_name)
        values = {lo, hi, 0, step, -step, lo + step, hi - step}
        top = hi.bit_length() + 1
        values |= {1 << b for b in range(top) if (1 << b) <= hi and (1 << b) % step == 0}
        for imm in sorted(values):
            for other in (0x0000_0000, MASK32):  # non-immediate bits all 0, then all 1
                inst = imm_encode(type_name, imm, other)
                await check(dut, type_name, inst, imm, f"(imm={imm}, other bits={other:#x})")


@cocotb.test()
async def test_round_trip_random(dut):
    """Random immediates placed in random instruction words come back unchanged."""
    for _ in range(500):
        for type_name in IMM_FIELDS:
            lo, hi, step = imm_range(type_name)
            imm = random.randrange(lo, hi + 1, step)
            inst = imm_encode(type_name, imm, random.getrandbits(32))
            await check(dut, type_name, inst, imm, f"(imm={imm})")


@cocotb.test()
async def test_random_words(dut):
    """Fully random instruction words, every type, against the field-table model."""
    for _ in range(1000):
        inst = random.getrandbits(32)
        for type_name in IMM_TYPES:
            await check(dut, type_name, inst, imm_decode(type_name, inst))


@cocotb.test()
async def test_none_and_unused_types_give_zero(dut):
    """IMM_NONE and the unused encodings 6 and 7 output 0, never X."""
    for code in (IMM_TYPES["IMM_NONE"], 6, 7):
        for inst in (0x0000_0000, MASK32, 0x8000_0000, 0xDEAD_BEEF):
            got = await drive(dut, code, inst)
            assert got == 0, f"type {code} inst {inst:#010x}: got {got:#010x}"


@cocotb.test()
async def test_model_self_check(dut):
    """The Python model agrees with the assembler table and with itself."""
    del dut  # model-only test
    for inst, type_name, imm, src in GOLDEN:
        assert imm_decode(type_name, inst) == imm & MASK32, src
    assert sext(0x800, 12) == 0xFFFF_F800
    assert sext(0x7FF, 12) == 0x0000_07FF
    for type_name in IMM_FIELDS:
        lo, hi, _ = imm_range(type_name)
        for imm in (lo, hi):
            assert imm_decode(type_name, imm_encode(type_name, imm, MASK32)) == imm & MASK32
