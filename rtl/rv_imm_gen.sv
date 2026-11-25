// rv_imm_gen.sv - immediate generator (docs/spec.md §4.1, §6.4).
//
// Purely combinational. Builds the 32-bit immediate for each RV32I format.
// The sign bit is always inst[31]. IMM_NONE and the unused encodings of
// imm_type_t (6, 7) give 0.

`default_nettype none

module rv_imm_gen
  import rv_pkg::*;
(
  input  logic [31:0] inst_i,
  input  imm_type_t   type_i,
  output logic [31:0] imm_o
);

  // The opcode field never contributes to an immediate. Signals whose name
  // contains "unused" are exempt from Verilator's UNUSED warnings (§14.4).
  logic unused_opcode;
  assign unused_opcode = ^inst_i[6:0];

  always_comb begin
    imm_o = 32'd0;
    case (type_i)
      IMM_I:   imm_o = {{21{inst_i[31]}}, inst_i[30:20]};
      IMM_S:   imm_o = {{21{inst_i[31]}}, inst_i[30:25], inst_i[11:7]};
      IMM_B:   imm_o = {{20{inst_i[31]}}, inst_i[7], inst_i[30:25], inst_i[11:8], 1'b0};
      IMM_U:   imm_o = {inst_i[31:12], 12'd0};
      IMM_J:   imm_o = {{12{inst_i[31]}}, inst_i[19:12], inst_i[20], inst_i[30:21], 1'b0};
      default: imm_o = 32'd0;
    endcase
  end

endmodule

`default_nettype wire
