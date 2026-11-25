// rv_timing_core.sv - timing and area harness for rv_core alone (docs/exec.md M8.1, M8.2). Synthesis only.
//
// rv_core has about 550 port bits (the retire port alone is 378), more than
// an FPGA package has pins. This harness gives it three pins:
//   - sin_i: a shift register, clocked in one bit per cycle, drives both
//     memory responses (imem_rsp, dmem_rsp). The responses come from flops.
//   - sout_o: every core output goes into a flop, and the XOR of those
//     flops into one more flop drives the pin.
// So every path through the core runs from a flop to a flop: the core's
// combinational segments are timed with the memories taken out (the
// memories would add their read time to the imem_rsp -> dmem_req and
// dmem_rsp -> register-write segments; rv_timing_soc.sv includes them).
// The output XOR adds a little depth after the core, so Fmax is slightly
// under-reported.

`default_nettype none

module rv_timing_core
  import rv_pkg::*;
(
  input  logic clk_i,
  input  logic rst_i,
  input  logic sin_i,
  output logic sout_o
);

  localparam int unsigned IN_W  = $bits(imem_rsp_t) + $bits(dmem_rsp_t);
  localparam int unsigned OUT_W = $bits(imem_req_t) + $bits(dmem_req_t) + $bits(retire_t) + 1
                                  + $bits(stop_cause_t);

  logic [IN_W-1:0] in_q;

  always_ff @(posedge clk_i) begin
    in_q <= {in_q[IN_W-2:0], sin_i};
  end

  imem_req_t   imem_req;
  imem_rsp_t   imem_rsp;
  dmem_req_t   dmem_req;
  dmem_rsp_t   dmem_rsp;
  retire_t     retire;
  logic        halted;
  stop_cause_t status;

  assign imem_rsp = in_q[$bits(imem_rsp_t)-1:0];
  assign dmem_rsp = in_q[IN_W-1:$bits(imem_rsp_t)];

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

  logic [OUT_W-1:0] out_q;
  logic             sout_q;

  always_ff @(posedge clk_i) begin
    out_q  <= {imem_req, dmem_req, retire, halted, status};
    sout_q <= ^out_q;
  end

  assign sout_o = sout_q;

endmodule

`default_nettype wire
