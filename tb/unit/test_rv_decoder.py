"""cocotb unit tests for rv_decoder (docs/exec.md M2.6, docs/spec.md §4, §6.3, §7).

Expected ctrl_t values come from the control signal table (spec §7) and the
legal encodings from the instruction table (spec §4), both parsed from
docs/spec.md by rv_model, so the spec and the test agree. The §4.2 illegal
cases are also written out by hand below, so a parsing slip cannot hide an
RTL bug.
"""

import random

import cocotb
from cocotb.triggers import Timer

from rv_model import CONTROL, CTRL_FIELDS, INSTRS, MASK32, decode_ref, encode, struct_unpack, struct_width

OPC = {  # spec §8.1
    "LUI": 0b0110111, "AUIPC": 0b0010111, "JAL": 0b1101111, "JALR": 0b1100111,
    "BRANCH": 0b1100011, "LOAD": 0b0000011, "STORE": 0b0100011, "OP_IMM": 0b0010011,
    "OP": 0b0110011, "FENCE": 0b0001111, "SYSTEM": 0b1110011,
}

# A-5 (spec §13): at most one of these is set.
ONE_HOT = ("mem_read", "mem_write", "branch", "jump", "is_fence", "is_ecall", "is_ebreak", "illegal")


def word(opcode, funct3=0, funct7=0, rest=None):
    """Instruction word with the given fields; rd/rs1/rs2 random unless rest is given."""
    if rest is None:
        rest = random.getrandbits(32)
    w = rest & ~(0x7F | (0x7 << 12) | (0x7F << 25)) & MASK32
    return w | opcode | (funct3 << 12) | (funct7 << 25)


async def decode(dut, inst):
    """Drive one word; return (ctrl dict, rs1, rs2, rd). Checks for X/Z."""
    dut.inst_i.value = inst & MASK32
    await Timer(1, unit="ns")
    outs = {n: getattr(dut, n).value for n in ("ctrl_o", "rs1_o", "rs2_o", "rd_o")}
    for n, v in outs.items():
        assert v.is_resolvable, f"{inst:#010x}: {n} has X/Z: {v}"
    assert len(outs["ctrl_o"]) == struct_width(CTRL_FIELDS)
    ctrl = struct_unpack(CTRL_FIELDS, outs["ctrl_o"].to_unsigned())
    return ctrl, outs["rs1_o"].to_unsigned(), outs["rs2_o"].to_unsigned(), outs["rd_o"].to_unsigned()


async def check(dut, inst, expect_name=None):
    """Compare every ctrl_t field and the register indices with the spec tables."""
    name, exp = decode_ref(inst)
    if expect_name is not None:
        assert name == expect_name, f"model: {inst:#010x} decodes as {name}, test expects {expect_name}"
    ctrl, rs1, rs2, rd = await decode(dut, inst)
    diffs = {f: (ctrl[f], exp[f]) for f, _ in CTRL_FIELDS if ctrl[f] != exp[f]}
    assert not diffs, f"{inst:#010x} ({name}): field (got, expected): {diffs}"
    assert (rs1, rs2, rd) == ((inst >> 15) & 31, (inst >> 20) & 31, (inst >> 7) & 31), (
        f"{inst:#010x}: register indices rs1={rs1} rs2={rs2} rd={rd}")
    # Assertions A-5 / A-6 (spec §13) on every vector.
    assert sum(ctrl[f] for f in ONE_HOT) <= 1, f"{inst:#010x}: A-5 violated: {ctrl}"
    if ctrl["illegal"]:
        assert not (ctrl["reg_write"] or ctrl["mem_read"] or ctrl["mem_write"]), f"{inst:#010x}: A-6 violated"
    return name


@cocotb.test()
async def test_every_instruction(dut):
    """Each of the 40 instructions, with random rd/rs1/rs2/immediate bits, maps to its §7 row."""
    assert len(INSTRS) == 40 and "illegal" in CONTROL
    for name in INSTRS:
        for _ in range(200):
            await check(dut, encode(name, random.getrandbits(32)), expect_name=name)


@cocotb.test()
async def test_opcode_space(dut):
    """Every 7-bit opcode x every funct3 x a set of funct7 values (covers §4.2 rules 1-3)."""
    for opcode in range(128):
        for funct3 in range(8):
            for funct7 in (0b0000000, 0b0100000, 0b0000001, 0b1111111, random.getrandbits(7)):
                await check(dut, word(opcode, funct3, funct7))


@cocotb.test()
async def test_op_and_op_imm_exhaustive(dut):
    """OP and OP-IMM: every funct3 x every funct7 (§4.2 rules 4 and 5)."""
    for opcode in (OPC["OP"], OPC["OP_IMM"]):
        for funct3 in range(8):
            for funct7 in range(128):
                await check(dut, word(opcode, funct3, funct7))


@cocotb.test()
async def test_illegal_hand_written(dut):
    """One or more examples of every §4.2 rule, marked illegal by hand."""
    cases = {
        "rule 1: all-zero word": 0x0000_0000,
        "rule 1: all-ones word": 0xFFFF_FFFF,
        "rule 1: ADDI with inst[1:0]=10 (compressed)": 0x0000_0012,
        "rule 1: ADDI with inst[1:0]=00": 0x0000_0010,
        "rule 2: AMO opcode": word(0b0101111),
        "rule 2: LOAD-FP opcode": word(0b0000111),
        "rule 2: OP-32 (RV64) opcode": word(0b0111011),
        "rule 3: LOAD funct3 011 (LD)": word(OPC["LOAD"], 0b011),
        "rule 3: LOAD funct3 110 (LWU)": word(OPC["LOAD"], 0b110),
        "rule 3: LOAD funct3 111": word(OPC["LOAD"], 0b111),
        "rule 3: STORE funct3 011 (SD)": word(OPC["STORE"], 0b011),
        "rule 3: STORE funct3 100": word(OPC["STORE"], 0b100),
        "rule 3: STORE funct3 111": word(OPC["STORE"], 0b111),
        "rule 3: BRANCH funct3 010": word(OPC["BRANCH"], 0b010),
        "rule 3: BRANCH funct3 011": word(OPC["BRANCH"], 0b011),
        "rule 3: JALR funct3 001": word(OPC["JALR"], 0b001),
        "rule 3: JALR funct3 111": word(OPC["JALR"], 0b111),
        "rule 3: FENCE.I": 0x0000_100F,
        "rule 3: MISC-MEM funct3 111": word(OPC["FENCE"], 0b111),
        "rule 4: MUL (funct7 0000001)": 0x0220_81B3,
        "rule 4: OP funct7 1000000": word(OPC["OP"], 0b000, 0b1000000),
        "rule 4: funct7 0100000 with funct3 001": word(OPC["OP"], 0b001, 0b0100000),
        "rule 4: funct7 0100000 with funct3 111": word(OPC["OP"], 0b111, 0b0100000),
        "rule 5: SLLI with shamt[5]=1": word(OPC["OP_IMM"], 0b001, 0b0000001),
        "rule 5: SLLI with funct7 0100000": word(OPC["OP_IMM"], 0b001, 0b0100000),
        "rule 5: SRLI with shamt[5]=1": word(OPC["OP_IMM"], 0b101, 0b0000001),
        "rule 5: SRAI with shamt[5]=1": word(OPC["OP_IMM"], 0b101, 0b0100001),
        "rule 6: CSRRW": 0x3400_1073,
        "rule 6: CSRRS funct3 010": word(OPC["SYSTEM"], 0b010),
        "rule 6: SYSTEM funct3 100": word(OPC["SYSTEM"], 0b100),
        "rule 6: MRET": 0x3020_0073,
        "rule 6: SRET": 0x1020_0073,
        "rule 6: WFI": 0x1050_0073,
        "rule 6: ECALL with rd=1": 0x0000_00F3,
        "rule 6: ECALL with rs1=1": 0x0000_8073,
        "rule 6: imm=2 (URET-like)": 0x0020_0073,
    }
    for reason, inst in cases.items():
        name = await check(dut, inst, expect_name="illegal")
        assert name == "illegal", reason


@cocotb.test()
async def test_system_neighbours(dut):
    """Every single-bit change of ECALL and EBREAK outside the opcode: only the exact words are legal."""
    for base, name in ((0x0000_0073, "ECALL"), (0x0010_0073, "EBREAK")):
        await check(dut, base, expect_name=name)
        for bit in range(7, 32):
            flipped = base ^ (1 << bit)
            other = {0x0000_0073 ^ (1 << 20): "EBREAK", 0x0010_0073 ^ (1 << 20): "ECALL"}.get(flipped, "illegal")
            await check(dut, flipped, expect_name=other)


@cocotb.test()
async def test_legal_hand_written(dut):
    """Assembled words checked by hand, including HINTs and FENCE variants that must stay legal."""
    cases = [
        (0x0000_0013, "ADDI"),   # nop
        (0x0050_0013, "ADDI"),   # addi x0, x0, 5 (HINT)
        (0x0000_0033, "ADD"),    # add x0, x0, x0 (HINT)
        (0x0000_0037, "LUI"),    # lui x0, 0 (HINT)
        (0x4030_D093, "SRAI"),   # srai x1, x1, 3
        (0x01F0_9093, "SLLI"),   # slli x1, x1, 31
        (0x4020_81B3, "SUB"),    # sub x3, x1, x2
        (0xFE20_CEE3, "BLT"),    # blt x1, x2, -4
        (0x0000_8067, "JALR"),   # ret
        (0x0080_006F, "JAL"),    # j +8
        (0x0FF0_000F, "FENCE"),  # fence iorw, iorw
        (0x8330_000F, "FENCE"),  # fence.tso
        (0x0100_000F, "FENCE"),  # pause
        (0x0041_2303, "LW"),     # lw x6, 4(x2)
        (0x0061_2223, "SW"),     # sw x6, 4(x2)
        (0x0000_0073, "ECALL"),
        (0x0010_0073, "EBREAK"),
    ]
    for inst, name in cases:
        ctrl, *_ = await decode(dut, inst)
        assert ctrl["illegal"] == 0, f"{inst:#010x} ({name}) decoded as illegal"
        await check(dut, inst, expect_name=name)


@cocotb.test()
async def test_random_words(dut):
    """Uniformly random 32-bit words (mostly illegal) vs. the spec tables."""
    for _ in range(5000):
        await check(dut, random.getrandbits(32))


@cocotb.test()
async def test_model_self_check(dut):
    """Spot-check the parsed §7 table against values read off the spec by hand."""
    del dut  # model-only test
    assert CONTROL["LUI"]["op_a_sel"] == 2 and CONTROL["LUI"]["imm_type"] == 4      # OPA_ZERO, IMM_U
    assert CONTROL["JALR"]["jump"] == 1 and CONTROL["JALR"]["jalr"] == 1 and CONTROL["JALR"]["wb_sel"] == 2
    assert CONTROL["BGEU"]["br_op"] == 0b111 and CONTROL["BGEU"]["reg_write"] == 0
    assert CONTROL["LHU"]["mem_size"] == 1 and CONTROL["LHU"]["mem_unsigned"] == 1
    assert CONTROL["SW"]["mem_write"] == 1 and CONTROL["SW"]["mem_size"] == 2 and CONTROL["SW"]["imm_type"] == 2
    assert CONTROL["SRA"]["alu_op"] == 7 and CONTROL["SRA"]["op_b_sel"] == 0 and CONTROL["SRA"]["imm_type"] == 0
    assert CONTROL["FENCE"]["is_fence"] == 1 and CONTROL["EBREAK"]["is_ebreak"] == 1
    assert CONTROL["illegal"] == {f: int(f == "illegal") for f, _ in CTRL_FIELDS}
    assert decode_ref(0x4000_5013)[0] == "SRAI" and decode_ref(0x4000_1013)[0] == "illegal"
