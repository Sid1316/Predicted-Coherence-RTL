// rv_alu.sv - RV32I arithmetic/logic unit (docs/spec.md §6.6).
//
// Purely combinational. Computes every ALU result in the core, including
// load/store addresses and branch/jump targets (spec §5.1).
//   - Shifts use only b_i[4:0] (RV32I shift amount).
//   - SLT/SLTU return {31'b0, compare result}.
//   - Encodings of alu_op_t that are not defined (10..15) give 0; the decoder
//     never produces them.

`default_nettype none

module rv_alu
  import rv_pkg::*;
(
  input  alu_op_t     op_i,
  input  logic [31:0] a_i,
  input  logic [31:0] b_i,
  output logic [31:0] res_o
);

  logic [4:0] shamt;
  assign shamt = b_i[4:0];

  always_comb begin
    res_o = 32'd0;
    case (op_i)
      ALU_ADD:  res_o = a_i + b_i;
      ALU_SUB:  res_o = a_i - b_i;
      ALU_SLL:  res_o = a_i << shamt;
      ALU_SLT:  res_o = {31'd0, $signed(a_i) < $signed(b_i)};
      ALU_SLTU: res_o = {31'd0, a_i < b_i};
      ALU_XOR:  res_o = a_i ^ b_i;
      ALU_SRL:  res_o = a_i >> shamt;
      ALU_SRA:  res_o = $unsigned($signed(a_i) >>> shamt);
      ALU_OR:   res_o = a_i | b_i;
      ALU_AND:  res_o = a_i & b_i;
      default:  res_o = 32'd0;
    endcase
  end

endmodule

`default_nettype wire
