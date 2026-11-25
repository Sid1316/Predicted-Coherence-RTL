// rv_core.sv - single-cycle RV32I core (docs/spec.md §5, §6.1, §9, §10).
//
// One instruction per clock: fetch -> decode -> regfile read -> ALU/branch
// -> LSU -> writeback, all combinational between pc_q and the clock edge.
// The only flops here are halted_q, status_q and order_q; pc_q lives in
// rv_pc and x1..x31 in rv_regfile.
//
//   - active = ~rst_i & ~halted_q. Nothing has an effect, and the retire port
//     is idle, unless the core is active (spec §2.2, §9.1, §10).
//   - Fetch error: the instruction word is forced to 0 (which decodes as
//     illegal), so an untrusted word never reaches the datapath; the stop
//     priority still reports STOP_IFETCH_ERROR and the retire port shows
//     insn = 0. The word is also forced to 0 while the core is idle.
//   - Stop conditions (§10) are gathered into `stop`, which holds the PC,
//     blocks the register write and latches halted_q/status_q. Memory needs no
//     extra gating: lsu enable is ~rst & ~halted & ~fetch error only, so it
//     never depends on dmem_rsp (spec R-1); every other stop cause has no
//     memory request by construction (illegal/ECALL/EBREAK/jumps don't access
//     memory, a misaligned access drops valid, a bus error is the memory
//     refusing the access).
//   - Retire port (§9): rs1/rs2 fields are 0 for an operand the instruction
//     does not read, rd fields 0 when nothing is written (incl. x0), and the
//     memory fields 0 unless the access completed (not on a stop).

`default_nettype none

module rv_core
  import rv_pkg::*;
#(
  parameter logic [31:0] RESET_PC = 32'h8000_0000
) (
  input  logic        clk_i,
  input  logic        rst_i,

  output imem_req_t   imem_req_o,
  input  imem_rsp_t   imem_rsp_i,
  output dmem_req_t   dmem_req_o,
  input  dmem_rsp_t   dmem_rsp_i,

  output retire_t     retire_o,
  output logic        halted_o,
  output stop_cause_t status_o
);

  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------
  logic        halted_q;
  stop_cause_t status_q;
  logic [63:0] order_q;
  logic        active;

  assign active = ~rst_i & ~halted_q;

  // -------------------------------------------------------------------------
  // Fetch
  // -------------------------------------------------------------------------
  logic [31:0] pc;
  logic [31:0] pc_plus4;
  logic [31:0] next_pc;
  logic        misaligned_fetch;
  logic        ifetch_err;
  logic [31:0] inst;

  assign imem_req_o.valid = active;
  assign imem_req_o.addr  = pc;

  assign ifetch_err = active & imem_rsp_i.err;
  assign inst       = (active & ~imem_rsp_i.err) ? imem_rsp_i.rdata : 32'd0;

  // -------------------------------------------------------------------------
  // Decode, immediates, register read
  // -------------------------------------------------------------------------
  ctrl_t       ctrl;
  logic [4:0]  rs1, rs2, rd;
  logic [31:0] imm;
  logic [31:0] rs1_val, rs2_val;
  logic        rf_we;
  logic [31:0] wb_data;

  rv_decoder u_decoder (
    .inst_i (inst),
    .ctrl_o (ctrl),
    .rs1_o  (rs1),
    .rs2_o  (rs2),
    .rd_o   (rd)
  );

  rv_imm_gen u_imm_gen (
    .inst_i (inst),
    .type_i (ctrl.imm_type),
    .imm_o  (imm)
  );

  rv_regfile u_regfile (
    .clk_i (clk_i),
    .ra1_i (rs1),
    .ra2_i (rs2),
    .rd1_o (rs1_val),
    .rd2_o (rs2_val),
    .we_i  (rf_we),
    .wa_i  (rd),
    .wd_i  (wb_data)
  );

  // -------------------------------------------------------------------------
  // Execute: operand muxes, ALU, branch compare
  // -------------------------------------------------------------------------
  logic [31:0] op_a, op_b;
  logic [31:0] alu_res;
  logic        br_taken;

  always_comb begin
    op_a = rs1_val;
    case (ctrl.op_a_sel)
      OPA_RS1:  op_a = rs1_val;
      OPA_PC:   op_a = pc;
      OPA_ZERO: op_a = 32'd0;
      default:  op_a = 32'd0;
    endcase
  end

  assign op_b = (ctrl.op_b_sel == OPB_IMM) ? imm : rs2_val;

  rv_alu u_alu (
    .op_i  (ctrl.alu_op),
    .a_i   (op_a),
    .b_i   (op_b),
    .res_o (alu_res)
  );

  rv_branch_unit u_branch (
    .op_i    (ctrl.br_op),
    .a_i     (rs1_val),
    .b_i     (rs2_val),
    .taken_o (br_taken)
  );

  // -------------------------------------------------------------------------
  // Memory
  // -------------------------------------------------------------------------
  logic [31:0] load_data;
  logic        misaligned_data;
  logic        bus_err;

  rv_lsu u_lsu (
    .ctrl_i       (ctrl),
    .addr_i       (alu_res),
    .store_data_i (rs2_val),
    .enable_i     (active & ~imem_rsp_i.err),
    .dmem_req_o   (dmem_req_o),
    .dmem_rsp_i   (dmem_rsp_i),
    .load_data_o  (load_data),
    .misaligned_o (misaligned_data),
    .bus_err_o    (bus_err)
  );

  // -------------------------------------------------------------------------
  // Stop conditions (§10), highest priority first
  // -------------------------------------------------------------------------
  stop_cause_t cause;
  logic        stop;

  always_comb begin
    cause = STOP_NONE;
    if (active) begin
      if      (ifetch_err)                   cause = STOP_IFETCH_ERROR;
      else if (ctrl.illegal)                 cause = STOP_ILLEGAL;
      else if (ctrl.is_ecall)                cause = STOP_ECALL;
      else if (ctrl.is_ebreak)               cause = STOP_EBREAK;
      else if (misaligned_fetch)             cause = STOP_MISALIGNED_FETCH;
      else if (misaligned_data)              cause = STOP_MISALIGNED_DATA;
      else if (bus_err)                      cause = STOP_BUS_ERROR;
      else                                   cause = STOP_NONE;
    end
  end

  assign stop = (cause != STOP_NONE);

  // -------------------------------------------------------------------------
  // PC and next-PC (§5.2)
  // -------------------------------------------------------------------------
  rv_pc #(
    .RESET_PC (RESET_PC)
  ) u_pc (
    .clk_i              (clk_i),
    .rst_i              (rst_i),
    .halted_i           (halted_q),
    .stop_i             (stop),
    .jump_i             (ctrl.jump),
    .jalr_i             (ctrl.jalr),
    .branch_i           (ctrl.branch),
    .br_taken_i         (br_taken),
    .target_i           (alu_res),
    .pc_o               (pc),
    .pc_plus4_o         (pc_plus4),
    .next_pc_o          (next_pc),
    .misaligned_fetch_o (misaligned_fetch)
  );

  // -------------------------------------------------------------------------
  // Writeback (§5.3)
  // -------------------------------------------------------------------------
  always_comb begin
    wb_data = alu_res;
    case (ctrl.wb_sel)
      WB_ALU:  wb_data = alu_res;
      WB_MEM:  wb_data = load_data;
      WB_PC4:  wb_data = pc_plus4;
      default: wb_data = alu_res;
    endcase
  end

  assign rf_we = active & ctrl.reg_write & ~stop;

  // -------------------------------------------------------------------------
  // Halt / status / retire counter
  // -------------------------------------------------------------------------
  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      halted_q <= 1'b0;
      status_q <= STOP_NONE;
      order_q  <= 64'd0;
    end else if (active) begin
      order_q <= order_q + 64'd1;
      if (stop) begin
        halted_q <= 1'b1;
        status_q <= cause;
      end
    end
  end

  assign halted_o = halted_q;
  assign status_o = status_q;

  // -------------------------------------------------------------------------
  // Retire port (§9)
  // -------------------------------------------------------------------------
  logic no_operands;
  logic rs1_used, rs2_used;
  logic rd_written;
  logic mem_done;
  logic is_halt;

  // FENCE/ECALL/EBREAK/illegal leave op_a_sel/op_b_sel at their RS1/RS2
  // defaults but read no register. Branches and stores read registers that
  // bypass the operand muxes (branch unit, store data).
  assign no_operands = ctrl.is_fence | ctrl.is_ecall | ctrl.is_ebreak | ctrl.illegal;
  assign rs1_used    = ((ctrl.op_a_sel == OPA_RS1) & ~no_operands) | ctrl.branch;
  assign rs2_used    = ((ctrl.op_b_sel == OPB_RS2) & ~no_operands) | ctrl.mem_write | ctrl.branch;
  assign rd_written  = rf_we & (rd != 5'd0);
  assign mem_done    = dmem_req_o.valid & ~stop;
  assign is_halt     = (cause == STOP_ECALL) | (cause == STOP_EBREAK);

  always_comb begin
    retire_o           = '0;
    retire_o.valid     = active;
    retire_o.order     = order_q;
    retire_o.insn      = inst;
    retire_o.pc_rdata  = pc;
    retire_o.pc_wdata  = next_pc;
    retire_o.rs1_addr  = rs1_used ? rs1     : 5'd0;
    retire_o.rs1_rdata = rs1_used ? rs1_val : 32'd0;
    retire_o.rs2_addr  = rs2_used ? rs2     : 5'd0;
    retire_o.rs2_rdata = rs2_used ? rs2_val : 32'd0;
    retire_o.rd_addr   = rd_written ? rd      : 5'd0;
    retire_o.rd_wdata  = rd_written ? wb_data : 32'd0;
    if (mem_done) begin
      retire_o.mem_addr  = {dmem_req_o.addr[31:2], 2'b00};
      retire_o.mem_rmask = dmem_req_o.we ? 4'b0000 : dmem_req_o.be;
      retire_o.mem_wmask = dmem_req_o.we ? dmem_req_o.be : 4'b0000;
      retire_o.mem_rdata = dmem_req_o.we ? 32'd0 : dmem_rsp_i.rdata;
      retire_o.mem_wdata = dmem_req_o.we ? dmem_req_o.wdata : 32'd0;
    end
    retire_o.trap      = stop & ~is_halt;
    retire_o.halt      = is_halt;
    if (!active) retire_o = '0;
  end

  // -------------------------------------------------------------------------
  // Assertions (spec §13). A-2: Phase 1 memories are always ready.
  // A-3: fetch addresses are word-aligned. A-4: a halted core has no effect.
  // -------------------------------------------------------------------------
  // ready is only checked by the assertions, which synthesis drops.
  logic unused_ready;
  assign unused_ready = ^{imem_rsp_i.ready, dmem_rsp_i.ready};

`ifndef SYNTHESIS
  // A plain always (not always_ff): this block holds no state, and simulators
  // reject the assertions' implicit $error inside always_ff.
  always @(posedge clk_i) begin
    if (!rst_i) begin
      a2_imem_ready: assert (!imem_req_o.valid || imem_rsp_i.ready);
      a2_dmem_ready: assert (!dmem_req_o.valid || dmem_rsp_i.ready);
      a3_imem_align: assert (!imem_req_o.valid || imem_req_o.addr[1:0] == 2'b00);
      a4_halted:     assert (!halted_q || (!dmem_req_o.valid && !rf_we));
    end
  end
`endif

endmodule

`default_nettype wire
