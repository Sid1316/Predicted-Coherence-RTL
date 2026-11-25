// rv_pc.sv - program counter and next-PC logic (docs/spec.md §5.2, §6.2).
//
// pc_q is the only flop. Everything else is the combinational next-PC logic
// of spec §5.2:
//   taken_branch     = branch & br_taken
//   redirect         = jump | taken_branch
//   target           = jalr ? (target_i & ~1) : target_i
//   next_pc          = halted | stop ? pc_q : redirect ? target : pc_q + 4
//   misaligned_fetch = redirect & target[1]
//   - A not-taken branch never raises misaligned_fetch.
//   - misaligned_fetch does not depend on stop_i, so the core may feed it
//     back into stop_i without a combinational loop.
//   - Synchronous active-high reset loads RESET_PC (spec §2.2).

`default_nettype none

module rv_pc #(
  parameter logic [31:0] RESET_PC = 32'h8000_0000
) (
  input  logic        clk_i,
  input  logic        rst_i,
  input  logic        halted_i,
  input  logic        stop_i,
  input  logic        jump_i,
  input  logic        jalr_i,
  input  logic        branch_i,
  input  logic        br_taken_i,
  input  logic [31:0] target_i,
  output logic [31:0] pc_o,
  output logic [31:0] pc_plus4_o,
  output logic [31:0] next_pc_o,
  output logic        misaligned_fetch_o
);

  logic [31:0] pc_q;
  logic        redirect;
  logic [31:0] target;

  assign pc_o       = pc_q;
  assign pc_plus4_o = pc_q + 32'd4;

  assign redirect = jump_i | (branch_i & br_taken_i);
  assign target   = jalr_i ? (target_i & 32'hFFFF_FFFE) : target_i;

  assign misaligned_fetch_o = redirect & target[1];

  always_comb begin
    next_pc_o = pc_plus4_o;
    if (halted_i | stop_i) next_pc_o = pc_q;
    else if (redirect)     next_pc_o = target;
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) pc_q <= RESET_PC;
    else       pc_q <= next_pc_o;
  end

endmodule

`default_nettype wire
