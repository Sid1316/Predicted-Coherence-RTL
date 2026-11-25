// rv_pkg.sv - shared types and constants for the Phase 1 RV32I core.
//
// Source of truth: docs/spec.md section 8. This file must match the spec
// exactly; change the spec first, then copy the change here.

`default_nettype none

package rv_pkg;
  // Constants are used by the modules that import this package. Verilator
  // flags them as unused when the package is linted on its own (M1), so the
  // warning is waived for this block only (§14.4).
  /* verilator lint_off UNUSEDPARAM */
  // Opcodes (inst[6:0])
  localparam logic [6:0] OPC_LUI    = 7'b0110111;
  localparam logic [6:0] OPC_AUIPC  = 7'b0010111;
  localparam logic [6:0] OPC_JAL    = 7'b1101111;
  localparam logic [6:0] OPC_JALR   = 7'b1100111;
  localparam logic [6:0] OPC_BRANCH = 7'b1100011;
  localparam logic [6:0] OPC_LOAD   = 7'b0000011;
  localparam logic [6:0] OPC_STORE  = 7'b0100011;
  localparam logic [6:0] OPC_OP_IMM = 7'b0010011;
  localparam logic [6:0] OPC_OP     = 7'b0110011;
  localparam logic [6:0] OPC_FENCE  = 7'b0001111;
  localparam logic [6:0] OPC_SYSTEM = 7'b1110011;

  // Memory map
  localparam logic [31:0] MEM_BASE     = 32'h8000_0000;
  localparam logic [31:0] CONSOLE_ADDR = 32'h1000_0000;
  /* verilator lint_on UNUSEDPARAM */

  typedef enum logic [3:0] {
    ALU_ADD, ALU_SUB, ALU_SLL, ALU_SLT, ALU_SLTU,
    ALU_XOR, ALU_SRL, ALU_SRA, ALU_OR,  ALU_AND
  } alu_op_t;

  typedef enum logic [2:0] { IMM_NONE, IMM_I, IMM_S, IMM_B, IMM_U, IMM_J } imm_type_t;
  typedef enum logic [1:0] { OPA_RS1, OPA_PC, OPA_ZERO }                  op_a_sel_t;
  typedef enum logic       { OPB_RS2, OPB_IMM }                           op_b_sel_t;
  typedef enum logic [1:0] { WB_ALU, WB_MEM, WB_PC4 }                     wb_sel_t;
  typedef enum logic [1:0] { MEM_B, MEM_H, MEM_W }                        mem_size_t;

  // Values equal funct3 so the decoder can pass funct3 straight through
  typedef enum logic [2:0] {
    BR_EQ = 3'b000, BR_NE = 3'b001, BR_LT  = 3'b100,
    BR_GE = 3'b101, BR_LTU = 3'b110, BR_GEU = 3'b111
  } branch_op_t;

  typedef struct packed {
    imm_type_t  imm_type;
    op_a_sel_t  op_a_sel;
    op_b_sel_t  op_b_sel;
    alu_op_t    alu_op;
    wb_sel_t    wb_sel;
    logic       reg_write;
    logic       mem_read;
    logic       mem_write;
    mem_size_t  mem_size;
    logic       mem_unsigned;
    logic       branch;
    branch_op_t br_op;
    logic       jump;
    logic       jalr;
    logic       is_fence;
    logic       is_ecall;
    logic       is_ebreak;
    logic       illegal;
  } ctrl_t;   // 28 bits

  typedef struct packed {
    logic        valid;
    logic [31:0] addr;      // byte address, [1:0] == 0
  } imem_req_t;

  typedef struct packed {
    logic        ready;     // Phase 1: always 1
    logic [31:0] rdata;     // valid in the same cycle as the request
    logic        err;       // address outside instruction memory
  } imem_rsp_t;

  typedef struct packed {
    logic        valid;
    logic        we;        // 1 = store, 0 = load
    logic [3:0]  be;        // byte enables (stores); loads read the full word
    logic [31:0] addr;      // byte address
    logic [31:0] wdata;     // lane-placed store data (§5.4)
  } dmem_req_t;

  typedef struct packed {
    logic        ready;     // Phase 1: always 1
    logic [31:0] rdata;     // full aligned word, same cycle
    logic        err;       // unmapped address
  } dmem_rsp_t;

  typedef enum logic [2:0] {
    STOP_NONE, STOP_ECALL, STOP_EBREAK, STOP_ILLEGAL,
    STOP_MISALIGNED_FETCH, STOP_MISALIGNED_DATA, STOP_BUS_ERROR, STOP_IFETCH_ERROR
  } stop_cause_t;

  typedef struct packed {           // see §9
    logic        valid;
    logic [63:0] order;
    logic [31:0] insn;
    logic [31:0] pc_rdata;
    logic [31:0] pc_wdata;
    logic [4:0]  rs1_addr;
    logic [4:0]  rs2_addr;
    logic [31:0] rs1_rdata;
    logic [31:0] rs2_rdata;
    logic [4:0]  rd_addr;
    logic [31:0] rd_wdata;
    logic [31:0] mem_addr;
    logic [3:0]  mem_rmask;
    logic [3:0]  mem_wmask;
    logic [31:0] mem_rdata;
    logic [31:0] mem_wdata;
    logic        trap;
    logic        halt;
  } retire_t;
endpackage

`default_nettype wire
