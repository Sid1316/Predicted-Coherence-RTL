// rv_regfile.sv - 32 x 32-bit register file, 2 read / 1 write (docs/spec.md §6.5).
//
//   - Reads are combinational; address 0 always reads 0 (x0).
//   - The write happens on the rising clock edge when we_i = 1; writes to
//     address 0 are ignored, so x0 has no storage at all.
//   - A read of the register being written in the same cycle returns the OLD
//     value (the write only lands at the edge).
//   - No reset (spec §2.2): x1..x31 start undefined, which keeps the array
//     mappable to FPGA distributed RAM. Software initialises every register.

`default_nettype none

module rv_regfile (
  input  logic        clk_i,

  input  logic [4:0]  ra1_i,
  input  logic [4:0]  ra2_i,
  output logic [31:0] rd1_o,
  output logic [31:0] rd2_o,

  input  logic        we_i,
  input  logic [4:0]  wa_i,
  input  logic [31:0] wd_i
);

  logic [31:0] regs_q [1:31];

  always_ff @(posedge clk_i) begin
    if (we_i && (wa_i != 5'd0)) begin
      regs_q[wa_i] <= wd_i;
    end
  end

  assign rd1_o = (ra1_i == 5'd0) ? 32'd0 : regs_q[ra1_i];
  assign rd2_o = (ra2_i == 5'd0) ? 32'd0 : regs_q[ra2_i];

endmodule

`default_nettype wire
