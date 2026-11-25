// rv_timing_soc.sv - timing harness for the whole single-cycle loop (docs/exec.md M8.2, M8.3). Synthesis only.
//
// rv_core with small instruction and data memories that read
// combinationally, as the Phase 1 port contract requires (spec §8.3):
// 1 KiB each (WORDS = 256), which yosys maps to ECP5 distributed RAM
// (TRELLIS_DPR16X4, asynchronous read). The core's critical path then runs
// through both memories in one cycle:
//   pc_q -> instruction memory -> decode -> register file -> ALU
//        -> data memory -> load alignment -> write-back -> register file.
// Block RAM (DP16KD) cannot be used here: its read is synchronous (the data
// comes one clock after the address), see M8.3.
//
// Pins: sin_i feeds a shift register that loads the instruction memory
// (an address, a word and a write enable), so the memory is not constant
// and is not optimized away. sout_o is the XOR of all core outputs, through
// flops, as in rv_timing_core.sv. Addresses use only the word index bits;
// there is no MMIO and no bus error.

`default_nettype none

module rv_timing_soc
  import rv_pkg::*;
#(
  parameter int unsigned WORDS       = 256,
  parameter bit          IMEM_LUTRAM = 1'b0
) (
  input  logic clk_i,
  input  logic rst_i,
  input  logic sin_i,
  output logic sout_o
);

  localparam int unsigned AW    = $clog2(WORDS);
  localparam int unsigned LD_W  = 1 + AW + 32;                       // we, address, data
  localparam int unsigned OUT_W = $bits(imem_req_t) + $bits(dmem_req_t) + $bits(retire_t) + 1
                                  + $bits(stop_cause_t);

  // Loader for the instruction memory.
  logic [LD_W-1:0] ld_q;

  always_ff @(posedge clk_i) begin
    ld_q <= {ld_q[LD_W-2:0], sin_i};
  end

  logic          ld_we;
  logic [AW-1:0] ld_addr;
  logic [31:0]   ld_data;

  assign {ld_we, ld_addr, ld_data} = ld_q;

  imem_req_t   imem_req;
  imem_rsp_t   imem_rsp;
  dmem_req_t   dmem_req;
  dmem_rsp_t   dmem_rsp;
  retire_t     retire;
  logic        halted;
  stop_cause_t status;

  // rst_i through a flop, as a reset synchronizer would be: no path from a pin
  // into the core is left unregistered.
  logic rst_q;

  always_ff @(posedge clk_i) begin
    rst_q <= rst_i;
  end

  rv_core u_core (
    .clk_i      (clk_i),
    .rst_i      (rst_q),
    .imem_req_o (imem_req),
    .imem_rsp_i (imem_rsp),
    .dmem_req_o (dmem_req),
    .dmem_rsp_i (dmem_rsp),
    .retire_o   (retire),
    .halted_o   (halted),
    .status_o   (status)
  );

  // Instruction memory: write from the loader, asynchronous read.
  // IMEM_LUTRAM = 0: yosys may choose. It puts the memory in block RAM: the
  // read address is pc_q, a register, which yosys folds into the block
  // RAM's own address register (the RAM then latches next_pc at the clock
  // edge), so the synchronous read still delivers the word in the same
  // cycle. IMEM_LUTRAM = 1 forces distributed RAM, to time both choices.
  logic [31:0] imem_rdata;

  if (IMEM_LUTRAM) begin : g_imem_lutram
    (* ram_style = "distributed" *) logic [31:0] imem [WORDS];

    always_ff @(posedge clk_i) begin
      if (ld_we) imem[ld_addr] <= ld_data;
    end

    assign imem_rdata = imem[imem_req.addr[AW+1:2]];
  end else begin : g_imem_auto
    logic [31:0] imem [WORDS];

    always_ff @(posedge clk_i) begin
      if (ld_we) imem[ld_addr] <= ld_data;
    end

    assign imem_rdata = imem[imem_req.addr[AW+1:2]];
  end

  assign imem_rsp = {1'b1, imem_rdata, 1'b0};                        // ready, rdata, err

  // Data memory: four byte lanes, written under the byte enables, read asynchronously.
  logic [7:0]    dmem0 [WORDS];
  logic [7:0]    dmem1 [WORDS];
  logic [7:0]    dmem2 [WORDS];
  logic [7:0]    dmem3 [WORDS];
  logic [AW-1:0] didx;
  logic          dwe;

  assign didx = dmem_req.addr[AW+1:2];
  assign dwe  = dmem_req.valid & dmem_req.we;

  always_ff @(posedge clk_i) begin
    if (dwe && dmem_req.be[0]) dmem0[didx] <= dmem_req.wdata[7:0];
    if (dwe && dmem_req.be[1]) dmem1[didx] <= dmem_req.wdata[15:8];
    if (dwe && dmem_req.be[2]) dmem2[didx] <= dmem_req.wdata[23:16];
    if (dwe && dmem_req.be[3]) dmem3[didx] <= dmem_req.wdata[31:24];
  end

  assign dmem_rsp = {1'b1, dmem3[didx], dmem2[didx], dmem1[didx], dmem0[didx], 1'b0};

  logic [OUT_W-1:0] out_q;
  logic             sout_q;

  always_ff @(posedge clk_i) begin
    out_q  <= {imem_req, dmem_req, retire, halted, status};
    sout_q <= ^out_q;
  end

  assign sout_o = sout_q;

endmodule

`default_nettype wire
