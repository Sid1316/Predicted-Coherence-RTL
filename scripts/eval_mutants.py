"""Injected RTL bugs ("mutants") for the evaluation pipeline's self-check.

scripts/evaluate.py builds one simulator per mutant from a patched copy of
rtl/ and runs the system-level checks on it. A mutant is KILLED when at least
one check fails. The self-check passes only if:
  - every mutant with expect="kill" is killed (the checks can see that bug);
  - the null mutant (no change) survives every check (no false failures);
  - every mutant with expect="survive" survives (it is a known equivalent
    mutant: no program can observe it; if it is ever killed, the reason must
    be understood before the list is changed).

Mutants are written as lint-clean code where the bug allows it (an unused
signal would make Verilator -Wall reject the build), so they exercise the
simulation checks; lint is still run on each one as its own layer.

Each mutant replaces exactly one occurrence of `old` with `new` in one file.
If `old` is not found exactly once, the run stops with an error: a mutant
that no longer applies would silently become the null mutant and look like
a bug that the checks missed, or worse, one they caught.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str | None          # path relative to the repo root; None for the null mutant
    old: str | None
    new: str | None
    what: str                 # the bug, in one line
    expect: str = "kill"      # "kill" or "survive"
    why: str = ""             # for expect="survive": why no check can see it


MUTANTS = [
    Mutant("null", None, None, None,
           "no change: the unmodified design must pass every check", expect="survive",
           why="control: a failure here is a false alarm in the checks themselves"),
    Mutant("alu_sra_logical", "rtl/rv_alu.sv",
           "ALU_SRA:  res_o = $unsigned($signed(a_i) >>> shamt);",
           "ALU_SRA:  res_o = a_i >> shamt;",
           "SRA/SRAI shift in zeros instead of copies of the sign bit"),
    Mutant("alu_sltu_signed", "rtl/rv_alu.sv",
           "ALU_SLTU: res_o = {31'd0, a_i < b_i};",
           "ALU_SLTU: res_o = {31'd0, $signed(a_i) < $signed(b_i)};",
           "SLTU/SLTIU compare as signed numbers"),
    Mutant("branch_bge_unsigned", "rtl/rv_branch_unit.sv",
           "BR_GE:   taken_o = ~lt;",
           "BR_GE:   taken_o = ~ltu;",
           "BGE compares as unsigned numbers (behaves like BGEU)"),
    Mutant("imm_b_bit11", "rtl/rv_imm_gen.sv",
           "IMM_B:   imm_o = {{20{inst_i[31]}}, inst_i[7], inst_i[30:25], inst_i[11:8], 1'b0};",
           "IMM_B:   imm_o = {{20{inst_i[31]}}, inst_i[31], inst_i[30:25], inst_i[11:8], 1'b0};",
           "branch offset bit 11 taken from inst[31] instead of inst[7]"),
    Mutant("lsu_lb_zero_extend", "rtl/rv_lsu.sv",
           ": {{24{shifted[7]}}, shifted[7:0]};",
           ": {24'd0, shifted[7:0]};",
           "LB zero-extends the loaded byte (behaves like LBU)"),
    Mutant("regfile_we_ignored", "rtl/rv_regfile.sv",
           "if (we_i && (wa_i != 5'd0)) begin",
           "if ((we_i || 1'b1) && (wa_i != 5'd0)) begin",
           "the register file writes rd even when the instruction does not write a register"),
    Mutant("pc_jalr_bit0", "rtl/rv_pc.sv",
           "assign target   = jalr_i ? (target_i & 32'hFFFF_FFFE) : target_i;",
           "assign target   = jalr_i ? (target_i & 32'hFFFF_FFFF) : target_i;",
           "JALR does not clear bit 0 of the target address"),
    Mutant("decoder_sub_as_add", "rtl/rv_decoder.sv",
           "3'b000:  c.alu_op = ALU_SUB;",
           "3'b000:  c.alu_op = ALU_ADD;",
           "SUB is decoded as ADD"),
    Mutant("regfile_x0_writable", "rtl/rv_regfile.sv",
           "if (we_i && (wa_i != 5'd0)) begin",
           "if (we_i) begin",
           "writes to x0 are no longer blocked at the write port", expect="survive",
           why="equivalent: x0 has no storage and its reads are forced to 0, so the write cannot be seen"),
]
