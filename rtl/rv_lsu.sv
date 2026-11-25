// rv_lsu.sv - load/store unit (docs/spec.md §5.4, §6.8).
//
// Purely combinational. Builds the data memory request from the decoded
// control bits and extracts/extends the load result from the response.
//   - Stores: data is replicated across lanes and be selects the bytes
//     ({4{b}} / {2{h}} / word, be = 0001/0011/1111 << off).
//   - Loads: rdata >> (off*8), then sign- or zero-extended from 8/16 bits.
//   - be holds the access mask for loads too (memory ignores it when we = 0),
//     so the core can take the retire masks (§9) from it. be = 0 when there
//     is no request.
//   - Misaligned half/word accesses drop valid (no memory side effect) and
//     raise misaligned_o; the core stops (§10).
//   - enable_i gates valid, misaligned_o and bus_err_o. It must not depend on
//     dmem_rsp_i (spec R-1).
//   - mem_size encoding 3 is never produced by the decoder: mask 0, wdata 0,
//     load result 0, not misaligned.

`default_nettype none

module rv_lsu
  import rv_pkg::*;
(
  input  ctrl_t       ctrl_i,
  input  logic [31:0] addr_i,
  input  logic [31:0] store_data_i,
  input  logic        enable_i,
  output dmem_req_t   dmem_req_o,
  input  dmem_rsp_t   dmem_rsp_i,
  output logic [31:0] load_data_o,
  output logic        misaligned_o,
  output logic        bus_err_o
);

  // Only the memory fields of ctrl_t and dmem_rsp_t are used. Signals whose
  // name contains "unused" are exempt from Verilator's UNUSED warnings (§14.4).
  logic unused_ctrl;
  assign unused_ctrl = ^{ctrl_i.imm_type, ctrl_i.op_a_sel, ctrl_i.op_b_sel, ctrl_i.alu_op,
                         ctrl_i.wb_sel, ctrl_i.reg_write, ctrl_i.branch, ctrl_i.br_op,
                         ctrl_i.jump, ctrl_i.jalr, ctrl_i.is_fence, ctrl_i.is_ecall,
                         ctrl_i.is_ebreak, ctrl_i.illegal, dmem_rsp_i.ready};

  logic [1:0]  off;
  logic        is_mem;
  logic        misaligned;
  logic        req_valid;
  logic [3:0]  mask;
  logic [31:0] wdata;
  logic [15:0] shifted;   // low half of rdata >> (off*8); only 8/16 bits are used

  assign off    = addr_i[1:0];
  assign is_mem = ctrl_i.mem_read | ctrl_i.mem_write;

  always_comb begin
    misaligned = 1'b0;
    mask       = 4'b0000;
    wdata      = 32'd0;
    case (ctrl_i.mem_size)
      MEM_B: begin
        mask  = 4'b0001 << off;
        wdata = {4{store_data_i[7:0]}};
      end
      MEM_H: begin
        misaligned = off[0];
        mask       = 4'b0011 << off;
        wdata      = {2{store_data_i[15:0]}};
      end
      MEM_W: begin
        misaligned = (off != 2'b00);
        mask       = 4'b1111;
        wdata      = store_data_i;
      end
      default: begin
        misaligned = 1'b0;
        mask       = 4'b0000;
        wdata      = 32'd0;
      end
    endcase
  end

  assign req_valid    = enable_i & is_mem & ~misaligned;
  assign misaligned_o = enable_i & is_mem & misaligned;
  assign bus_err_o    = req_valid & dmem_rsp_i.err;

  always_comb begin
    dmem_req_o       = '0;
    dmem_req_o.valid = req_valid;
    dmem_req_o.we    = req_valid & ctrl_i.mem_write;
    dmem_req_o.be    = req_valid ? mask : 4'b0000;
    dmem_req_o.addr  = addr_i;
    dmem_req_o.wdata = wdata;
  end

  assign shifted = 16'(dmem_rsp_i.rdata >> {off, 3'b000});

  always_comb begin
    load_data_o = 32'd0;
    case (ctrl_i.mem_size)
      MEM_B:   load_data_o = ctrl_i.mem_unsigned ? {24'd0, shifted[7:0]}
                                                 : {{24{shifted[7]}}, shifted[7:0]};
      MEM_H:   load_data_o = ctrl_i.mem_unsigned ? {16'd0, shifted[15:0]}
                                                 : {{16{shifted[15]}}, shifted[15:0]};
      MEM_W:   load_data_o = dmem_rsp_i.rdata;
      default: load_data_o = 32'd0;
    endcase
  end

endmodule

`default_nettype wire
