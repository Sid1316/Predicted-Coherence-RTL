// rv_soc_sim.sv - simulation SoC: rv_core + rv_mem_model + MMIO (docs/spec.md §2.1, §6.10). Sim only.
//
//   - Fetch goes straight to memory port A (fetching from anywhere but RAM,
//     CONSOLE included, is an error, spec §2.3).
//   - Data requests are decoded: the CONSOLE word (CONSOLE_ADDR..+3) is
//     handled here, everything else goes to memory port B, which reports err
//     for any address outside RAM.
//   - CONSOLE: a store with be[0] set prints wdata[7:0] (lane 0, offset 0;
//     with lane-replicated store data that is the stored byte for SB/SH/SW
//     to offset 0). Stores to offsets 1..3 print nothing. Reads return 0.
//     No error either way.
//   - CYCLE (0x1000_0008 low word, 0x1000_000C high word): a 64-bit count of
//     clock cycles since reset, for benchmark timing (exec.md M7). Reads
//     return it (sub-word loads take their bytes from the addressed word);
//     stores are bus errors.
//   - tohost (+tohost=<hex address>): when a store to the tohost word
//     retires, done_o is set at that clock edge and tohost_value_o holds the
//     word as it is after the store (partial stores merged with the old
//     word). Both stay put until reset; later writes are ignored. Without
//     +tohost= done_o never rises. The 8-byte tohost's upper word does not
//     count (Phase 1 programs store a 32-bit word, spec §11).
//   - Retire log (+retire_log=<file>): one line per retired instruction in
//     the spec §9.2 format, written at the clock edge it retires on.
//
// The C++ harness (M3.4) drives clk_i/rst_i and, after each rising edge,
// checks done_o / halted_o / status_o.

`default_nettype none

module rv_soc_sim
  import rv_pkg::*;
#(
  parameter logic [31:0] RESET_PC       = 32'h8000_0000,
  parameter int unsigned MEM_SIZE_BYTES = 32'd65536
) (
  input  logic        clk_i,
  input  logic        rst_i,

  output logic        done_o,           // tohost written (sticky until reset)
  output logic [31:0] tohost_value_o,   // tohost word after that store
  output logic        halted_o,
  output stop_cause_t status_o,
  output logic        console_valid_o,  // CONSOLE byte written this cycle
  output logic [7:0]  console_data_o,
  output retire_t     retire_o
);

  // -------------------------------------------------------------------------
  // Core and memory
  // -------------------------------------------------------------------------
  imem_req_t imem_req;
  imem_rsp_t imem_rsp;
  dmem_req_t core_dreq, mem_dreq;
  dmem_rsp_t core_drsp, mem_drsp;

  rv_core #(
    .RESET_PC (RESET_PC)
  ) u_core (
    .clk_i      (clk_i),
    .rst_i      (rst_i),
    .imem_req_o (imem_req),
    .imem_rsp_i (imem_rsp),
    .dmem_req_o (core_dreq),
    .dmem_rsp_i (core_drsp),
    .retire_o   (retire_o),
    .halted_o   (halted_o),
    .status_o   (status_o)
  );

  rv_mem_model #(
    .MEM_SIZE_BYTES (MEM_SIZE_BYTES)
  ) u_mem (
    .clk_i      (clk_i),
    .imem_req_i (imem_req),
    .imem_rsp_o (imem_rsp),
    .dmem_req_i (mem_dreq),
    .dmem_rsp_o (mem_drsp)
  );

  // -------------------------------------------------------------------------
  // CYCLE counter (spec §2.3): clock cycles since reset was released, so a
  // load in the k-th cycle after reset reads k (at CPI 1: the load's retire
  // number). Read-only; a store to it is a bus error.
  // -------------------------------------------------------------------------
  localparam logic [31:0] CYCLE_ADDR = 32'h1000_0008;   // LO at +0, HI at +4

  logic [63:0] cycle_q;

  always_ff @(posedge clk_i) begin
    if (rst_i) cycle_q <= 64'd0;
    else       cycle_q <= cycle_q + 64'd1;
  end

  // -------------------------------------------------------------------------
  // Data address decode
  // -------------------------------------------------------------------------
  logic        is_console, is_cycle;
  logic [31:0] cycle_word;

  assign is_console = (core_dreq.addr[31:2] == CONSOLE_ADDR[31:2]);
  assign is_cycle   = (core_dreq.addr[31:3] == CYCLE_ADDR[31:3]);
  assign cycle_word = core_dreq.addr[2] ? cycle_q[63:32] : cycle_q[31:0];

  // Continuous assigns, not an always_comb: Icarus 13 spins forever in zero
  // time on an always_comb that writes core_drsp as '0 and then sets .ready
  // (it hung on the first CONSOLE access). Fields in struct order (spec §8.3);
  // Icarus has no named assignment patterns.
  assign mem_dreq  = {core_dreq.valid & ~is_console & ~is_cycle, core_dreq.we, core_dreq.be,
                      core_dreq.addr, core_dreq.wdata};
  assign core_drsp = is_console ? {1'b1, 32'd0, 1'b0} :                  // ready, rdata, err
                     is_cycle   ? {1'b1, cycle_word, core_dreq.we} :     // stores: bus error
                                  mem_drsp;

  assign console_valid_o = core_dreq.valid & core_dreq.we & is_console & core_dreq.be[0];
  assign console_data_o  = core_dreq.wdata[7:0];

  always @(posedge clk_i) begin
    if (console_valid_o) begin
      $write("%c", console_data_o);
      $fflush();
    end
  end

  // -------------------------------------------------------------------------
  // tohost watcher (spec §11)
  // -------------------------------------------------------------------------
  logic        tohost_en;
  logic [31:0] tohost_addr;
  logic        tohost_hit;
  logic [31:0] tohost_merged;
  logic        done_q;
  logic [31:0] tohost_q;

  initial begin
    tohost_addr = 32'd0;
    tohost_en   = 1'b0;
    if ($value$plusargs("tohost=%h", tohost_addr)) tohost_en = 1'b1;
  end

  // The retire port's memory fields are only set for an access that
  // completed, so a store that stopped the core never counts.
  assign tohost_hit = tohost_en & retire_o.valid & (retire_o.mem_wmask != 4'b0000)
                    & (retire_o.mem_addr[31:2] == tohost_addr[31:2]);

  // Old word from memory port B (it returns rdata for stores too), new lanes
  // from the store.
  logic [3:0]  wmask;
  logic [31:0] lane_mask;

  assign wmask         = retire_o.mem_wmask;
  assign lane_mask     = {{8{wmask[3]}}, {8{wmask[2]}}, {8{wmask[1]}}, {8{wmask[0]}}};
  assign tohost_merged = (retire_o.mem_wdata & lane_mask) | (core_drsp.rdata & ~lane_mask);

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      done_q   <= 1'b0;
      tohost_q <= 32'd0;
    end else if (tohost_hit && !done_q) begin
      done_q   <= 1'b1;
      tohost_q <= tohost_merged;
    end
  end

  // tohost is compared as a word address; the byte offset bits are ignored.
  logic unused_tohost_offset;
  assign unused_tohost_offset = ^tohost_addr[1:0];

  assign done_o         = done_q;
  assign tohost_value_o = tohost_q;

  // -------------------------------------------------------------------------
  // Retire log (spec §9.2)
  // -------------------------------------------------------------------------
  // Stop-cause names for HALT/TRAP lines: the stop_cause_t name without STOP_.
  function automatic string cause_name(stop_cause_t c);
    case (c)
      STOP_ECALL:            return "ECALL";
      STOP_EBREAK:           return "EBREAK";
      STOP_ILLEGAL:          return "ILLEGAL";
      STOP_MISALIGNED_FETCH: return "MISALIGNED_FETCH";
      STOP_MISALIGNED_DATA:  return "MISALIGNED_DATA";
      STOP_BUS_ERROR:        return "BUS_ERROR";
      STOP_IFETCH_ERROR:     return "IFETCH_ERROR";
      default:               return "NONE";
    endcase
  endfunction

  integer log_fd;

  initial begin
    string path;
    log_fd = 0;
    if ($value$plusargs("retire_log=%s", path)) begin
      log_fd = $fopen(path, "w");
      if (log_fd == 0) $display("rv_soc_sim: cannot open +retire_log=%s; no retire log", path);
    end
  end

  // Sampled at the edge the instruction retires on, so every value is the
  // pre-edge one. The stop cause is not on the retire port; it is read from
  // the core (u_core.cause), as status_o only shows it after the edge.
  // order is printed as its low 32 bits (8 digits, as in the spec example).
  always @(posedge clk_i) begin
    if (log_fd != 0 && retire_o.valid) begin
      $fwrite(log_fd, "%h %h %h", retire_o.order[31:0], retire_o.pc_rdata, retire_o.insn);
      if (retire_o.rd_addr != 5'd0)
        $fwrite(log_fd, " x%0d %h", retire_o.rd_addr, retire_o.rd_wdata);
      if (retire_o.mem_wmask != 4'b0000)
        $fwrite(log_fd, " mem W %h %h %h", retire_o.mem_addr, retire_o.mem_wmask, retire_o.mem_wdata);
      if (retire_o.mem_rmask != 4'b0000)
        $fwrite(log_fd, " mem R %h %h %h", retire_o.mem_addr, retire_o.mem_rmask, retire_o.mem_rdata);
      if (retire_o.halt || retire_o.trap)
        $fwrite(log_fd, " %s %s", retire_o.halt ? "HALT" : "TRAP", cause_name(u_core.cause));
      $fwrite(log_fd, "\n");
      // Flush where a run normally ends, so the file is complete when read.
      if (retire_o.halt || retire_o.trap || tohost_hit) $fflush(log_fd);
    end
  end

  final begin
    if (log_fd != 0) $fclose(log_fd);
  end

endmodule

`default_nettype wire
