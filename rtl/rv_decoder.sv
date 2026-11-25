// rv_decoder.sv - RV32I instruction decoder (docs/spec.md §4, §6.3, §7).
//
// Purely combinational. Maps an instruction word to ctrl_t following the
// control signal table (spec §7) and flags every encoding listed in §4.2 as
// illegal.
//   - "Don't care" table entries are driven to 0 / the first enum value, so
//     every field has one exact expected value.
//   - An illegal instruction gives ctrl_o = '0 except illegal = 1 (so
//     reg_write = mem_read = mem_write = 0, spec §6.3, A-6).
//   - br_op is funct3 for branches and BR_EQ (0) otherwise.

`default_nettype none

module rv_decoder
  import rv_pkg::*;
(
  input  logic [31:0] inst_i,
  output ctrl_t       ctrl_o,
  output logic [4:0]  rs1_o,
  output logic [4:0]  rs2_o,
  output logic [4:0]  rd_o
);

  logic [6:0] opcode;
  logic [2:0] funct3;
  logic [6:0] funct7;

  assign opcode = inst_i[6:0];
  assign funct3 = inst_i[14:12];
  assign funct7 = inst_i[31:25];

  assign rs1_o = inst_i[19:15];
  assign rs2_o = inst_i[24:20];
  assign rd_o  = inst_i[11:7];

  ctrl_t c;
  logic  bad;

  always_comb begin
    c   = '0;
    bad = 1'b0;

    case (opcode)
      OPC_LUI: begin
        c.imm_type = IMM_U;  c.op_a_sel = OPA_ZERO; c.op_b_sel = OPB_IMM;
        c.alu_op   = ALU_ADD; c.wb_sel  = WB_ALU;   c.reg_write = 1'b1;
      end

      OPC_AUIPC: begin
        c.imm_type = IMM_U;  c.op_a_sel = OPA_PC;   c.op_b_sel = OPB_IMM;
        c.alu_op   = ALU_ADD; c.wb_sel  = WB_ALU;   c.reg_write = 1'b1;
      end

      OPC_JAL: begin
        c.imm_type = IMM_J;  c.op_a_sel = OPA_PC;   c.op_b_sel = OPB_IMM;
        c.alu_op   = ALU_ADD; c.wb_sel  = WB_PC4;   c.reg_write = 1'b1;
        c.jump     = 1'b1;
      end

      OPC_JALR: begin
        c.imm_type = IMM_I;  c.op_a_sel = OPA_RS1;  c.op_b_sel = OPB_IMM;
        c.alu_op   = ALU_ADD; c.wb_sel  = WB_PC4;   c.reg_write = 1'b1;
        c.jump     = 1'b1;   c.jalr     = 1'b1;
        bad        = (funct3 != 3'b000);
      end

      OPC_BRANCH: begin
        c.imm_type = IMM_B;  c.op_a_sel = OPA_PC;   c.op_b_sel = OPB_IMM;
        c.alu_op   = ALU_ADD; c.branch  = 1'b1;
        c.br_op    = branch_op_t'(funct3);
        bad        = (funct3 == 3'b010) | (funct3 == 3'b011);
      end

      OPC_LOAD: begin
        c.imm_type = IMM_I;  c.op_a_sel = OPA_RS1;  c.op_b_sel = OPB_IMM;
        c.alu_op   = ALU_ADD; c.wb_sel  = WB_MEM;   c.reg_write = 1'b1;
        c.mem_read = 1'b1;
        case (funct3)
          3'b000:  c.mem_size = MEM_B;
          3'b001:  c.mem_size = MEM_H;
          3'b010:  c.mem_size = MEM_W;
          3'b100:  begin c.mem_size = MEM_B; c.mem_unsigned = 1'b1; end
          3'b101:  begin c.mem_size = MEM_H; c.mem_unsigned = 1'b1; end
          default: bad = 1'b1;
        endcase
      end

      OPC_STORE: begin
        c.imm_type  = IMM_S;  c.op_a_sel = OPA_RS1; c.op_b_sel = OPB_IMM;
        c.alu_op    = ALU_ADD; c.mem_write = 1'b1;
        case (funct3)
          3'b000:  c.mem_size = MEM_B;
          3'b001:  c.mem_size = MEM_H;
          3'b010:  c.mem_size = MEM_W;
          default: bad = 1'b1;
        endcase
      end

      OPC_OP_IMM: begin
        c.imm_type = IMM_I;  c.op_a_sel = OPA_RS1;  c.op_b_sel = OPB_IMM;
        c.wb_sel   = WB_ALU; c.reg_write = 1'b1;
        case (funct3)
          3'b000: c.alu_op = ALU_ADD;
          3'b010: c.alu_op = ALU_SLT;
          3'b011: c.alu_op = ALU_SLTU;
          3'b100: c.alu_op = ALU_XOR;
          3'b110: c.alu_op = ALU_OR;
          3'b111: c.alu_op = ALU_AND;
          3'b001: begin
            c.alu_op = ALU_SLL;
            bad      = (funct7 != 7'b0000000);
          end
          default: begin  // 3'b101
            if (funct7 == 7'b0100000) c.alu_op = ALU_SRA;
            else                      c.alu_op = ALU_SRL;
            bad = (funct7 != 7'b0000000) & (funct7 != 7'b0100000);
          end
        endcase
      end

      OPC_OP: begin
        c.op_a_sel = OPA_RS1; c.op_b_sel = OPB_RS2;
        c.wb_sel   = WB_ALU;  c.reg_write = 1'b1;
        if (funct7 == 7'b0000000) begin
          case (funct3)
            3'b000:  c.alu_op = ALU_ADD;
            3'b001:  c.alu_op = ALU_SLL;
            3'b010:  c.alu_op = ALU_SLT;
            3'b011:  c.alu_op = ALU_SLTU;
            3'b100:  c.alu_op = ALU_XOR;
            3'b101:  c.alu_op = ALU_SRL;
            3'b110:  c.alu_op = ALU_OR;
            default: c.alu_op = ALU_AND;  // 3'b111
          endcase
        end else if (funct7 == 7'b0100000) begin
          case (funct3)
            3'b000:  c.alu_op = ALU_SUB;
            3'b101:  c.alu_op = ALU_SRA;
            default: bad = 1'b1;
          endcase
        end else begin
          bad = 1'b1;
        end
      end

      OPC_FENCE: begin
        c.is_fence = 1'b1;
        bad        = (funct3 != 3'b000);
      end

      OPC_SYSTEM: begin
        // Only the exact ECALL / EBREAK words are legal (§4.2 rule 6).
        if (inst_i == 32'h0000_0073)      c.is_ecall  = 1'b1;
        else if (inst_i == 32'h0010_0073) c.is_ebreak = 1'b1;
        else                              bad         = 1'b1;
      end

      default: bad = 1'b1;  // includes inst[1:0] != 2'b11
    endcase
  end

  always_comb begin
    ctrl_o = c;
    if (bad) begin
      ctrl_o         = '0;
      ctrl_o.illegal = 1'b1;
    end
  end

endmodule

`default_nettype wire
