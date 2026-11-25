// rv_branch_unit.sv - branch condition unit (docs/spec.md §6.7).
//
// Purely combinational. Compares rs1 (a_i) and rs2 (b_i) for the six RV32I
// branches; it never computes a target (the ALU does, spec §5.1).
//   - op_i is funct3, so BLT/BGE compare signed and BLTU/BGEU unsigned.
//   - The unused funct3 values 010/011 give 0 (not taken). The decoder marks
//     those encodings illegal, so ctrl.branch is 0 and taken_o is ignored.

`default_nettype none

module rv_branch_unit
  import rv_pkg::*;
(
  input  branch_op_t  op_i,
  input  logic [31:0] a_i,
  input  logic [31:0] b_i,
  output logic        taken_o
);

  logic eq, lt, ltu;
  assign eq  = (a_i == b_i);
  assign lt  = ($signed(a_i) < $signed(b_i));
  assign ltu = (a_i < b_i);

  always_comb begin
    taken_o = 1'b0;
    case (op_i)
      BR_EQ:   taken_o = eq;
      BR_NE:   taken_o = ~eq;
      BR_LT:   taken_o = lt;
      BR_GE:   taken_o = ~lt;
      BR_LTU:  taken_o = ltu;
      BR_GEU:  taken_o = ~ltu;
      default: taken_o = 1'b0;
    endcase
  end

endmodule

`default_nettype wire
