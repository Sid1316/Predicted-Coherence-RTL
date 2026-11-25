// rv_mem_model.sv - dual-port simulation memory (docs/spec.md §2.3, §6.9). Sim only.
//
//   - Port A: instruction fetch, read-only. Port B: data, read/write.
//   - Reads are combinational (zero latency, ready = 1, spec §8.3). Port B
//     writes the lanes selected by be on the rising clock edge, so a read in
//     the same cycle as a write to the same word returns the old word, and
//     port A sees the new word from the next cycle on.
//   - RAM is MEM_SIZE_BYTES at MEM_BASE. Any other address sets err on that
//     port (for a valid request), returns rdata = 0 and writes nothing. The
//     address is checked in full before indexing, so an out-of-range address
//     never aliases into RAM.
//   - Port B returns the addressed word for stores as well (rv_soc_sim uses it
//     to merge a partial store to tohost). The core ignores rdata on stores.
//   - Contents: every word starts at 0 (so running off the end of the program
//     fetches an illegal all-zero word, and runs are deterministic, spec N-5),
//     then +hex=<file> is loaded with $readmemh.
//
// Image format (+hex=): what `objcopy -O verilog --verilog-data-width=4
// --change-addresses=-MEM_BASE` writes. One 32-bit word per entry, in hex;
// `@<n>` sets the WORD index n relative to MEM_BASE (byte address
// MEM_BASE + 4*n). Words not in the file stay 0.

`default_nettype none

module rv_mem_model
  import rv_pkg::*;
#(
  parameter int unsigned MEM_SIZE_BYTES = 32'd65536   // power of two (spec §2.4)
) (
  input  logic      clk_i,

  input  imem_req_t imem_req_i,
  output imem_rsp_t imem_rsp_o,
  input  dmem_req_t dmem_req_i,
  output dmem_rsp_t dmem_rsp_o
);

  localparam int unsigned WORDS = MEM_SIZE_BYTES / 32'd4;
  localparam int unsigned IDX_W = $clog2(WORDS);

  logic [31:0] mem [WORDS];

  // -------------------------------------------------------------------------
  // Address decode. off = addr - MEM_BASE wraps for addresses below the base,
  // so one unsigned compare covers both sides of the RAM range.
  // -------------------------------------------------------------------------
  logic [31:0]      i_off, d_off;
  logic             i_in_ram, d_in_ram;
  logic [IDX_W-1:0] i_idx, d_idx;

  assign i_off    = imem_req_i.addr - MEM_BASE;
  assign d_off    = dmem_req_i.addr - MEM_BASE;
  assign i_in_ram = (i_off < MEM_SIZE_BYTES);
  assign d_in_ram = (d_off < MEM_SIZE_BYTES);
  assign i_idx    = i_off[IDX_W+1:2];
  assign d_idx    = d_off[IDX_W+1:2];

  // -------------------------------------------------------------------------
  // Port A: fetch
  // -------------------------------------------------------------------------
  always_comb begin
    imem_rsp_o       = '0;
    imem_rsp_o.ready = 1'b1;
    if (imem_req_i.valid) begin
      if (i_in_ram) imem_rsp_o.rdata = mem[i_idx];
      else          imem_rsp_o.err   = 1'b1;
    end
  end

  // -------------------------------------------------------------------------
  // Port B: data
  // -------------------------------------------------------------------------
  always_comb begin
    dmem_rsp_o       = '0;
    dmem_rsp_o.ready = 1'b1;
    if (dmem_req_i.valid) begin
      if (d_in_ram) dmem_rsp_o.rdata = mem[d_idx];
      else          dmem_rsp_o.err   = 1'b1;
    end
  end

  // Store: the old word with the lanes selected by be replaced. The byte
  // mask is built from plain vectors (Icarus cannot index a struct member
  // with a loop variable).
  logic [3:0]  d_be;
  logic [31:0] d_lane_mask;
  logic [31:0] d_merged;

  assign d_be        = dmem_req_i.be;
  assign d_lane_mask = {{8{d_be[3]}}, {8{d_be[2]}}, {8{d_be[1]}}, {8{d_be[0]}}};
  assign d_merged    = (dmem_req_i.wdata & d_lane_mask) | (mem[d_idx] & ~d_lane_mask);

  // A plain always (not always_ff): mem is also written by the initial block
  // below, and a variable written by always_ff may have no other writer.
  always @(posedge clk_i) begin
    if (dmem_req_i.valid && dmem_req_i.we && d_in_ram) mem[d_idx] <= d_merged;
  end

  // -------------------------------------------------------------------------
  // Initial contents
  // -------------------------------------------------------------------------
  initial begin
    string hex;
    integer fd;
    for (int i = 0; i < int'(WORDS); i++) mem[i] = 32'd0;
    if ($value$plusargs("hex=%s", hex)) begin
      // $readmemh on a missing file is fatal in some simulators and silent in
      // others; check first so the message is the same everywhere. The C++
      // harness checks the file too and exits with code 5 (spec §11).
      fd = $fopen(hex, "r");
      if (fd == 0) begin
        $display("rv_mem_model: cannot open +hex=%s; memory left all zero", hex);
      end else begin
        $fclose(fd);
        $readmemh(hex, mem);
      end
    end
  end

endmodule

`default_nettype wire
