# RISC-V Core: Phase 1 Specification

| | |
|---|---|
| **Covers** | Phase 1: single-cycle RV32I core + simulation SoC |
| **Companion** | [exec.md](exec.md) (execution plan, milestones, Phase 2 decision inputs) |
| **ISA reference** | *The RISC-V Instruction Set Manual, Volume I: Unprivileged ISA* (ratified), RV32I Base Integer Instruction Set v2.1 |
| **Status** | Draft for M1 review |

This document is the single source of truth for Phase 1 RTL, simulation and software. It covers the items listed under milestone M1 in exec.md:

| exec.md item | Where it is covered here |
|---|---|
| M1.1 Datapath block diagram, next-PC mux, writeback mux, control signal table | §5, §6, §7 |
| M1.2 `rv_pkg.sv` contents (enums, `ctrl_t`, memory structs, memory map) | §8 |
| M1.3 Coding and naming conventions | §14 |
| M1.4 Instruction coverage checklist | §15 |

Anything this document does not specify is out of Phase 1 scope (see exec.md §1). Phase 2 choices are listed as **hooks** in §16 but not decided.

---

## 1. Requirements

### 1.1 Functional
| ID | Requirement |
|---|---|
| F-1 | Execute every RV32I instruction (§4) with the architectural results defined by the unprivileged spec. |
| F-2 | Little-endian, byte-addressed, 32-bit address space. |
| F-3 | One instruction retires per clock cycle while running (CPI = 1). |
| F-4 | `x0` always reads as zero; writes to it have no effect. |
| F-5 | `ECALL` and `EBREAK` stop the core (§10). |
| F-6 | Illegal instructions, misaligned data accesses, misaligned jump/branch targets and accesses to unmapped addresses stop the core with an error flag (§10). |
| F-7 | The core reports every retired instruction on a retire trace port (§9). |
| F-8 | Programs built with `-march=rv32i -mabi=ilp32` and linked with the project linker script run without modification. |

### 1.2 Non-functional
| ID | Requirement |
|---|---|
| N-1 | Synthesizable RTL in SystemVerilog-2017 subset supported by Verilator 5.x and Yosys. |
| N-2 | `verilator --lint-only -Wall` clean; every waiver has a comment explaining it. |
| N-3 | Simulation-only constructs (`$readmemh`, `$display`, `$value$plusargs`, `initial`) live only under `sim/`. |
| N-4 | Core and memory are separate modules joined only by the two memory ports (§8.3), so the memory side can be replaced in Phase 2. |
| N-5 | All behaviour is deterministic for a given program image and seed. |

---

## 2. System architecture

### 2.1 Simulation system

```
 ┌──────────────────────────────── tb_top.cpp (Verilator C++ harness) ─────────────────────────────────┐
 │  plusargs: +hex= +tohost= +max_cycles= +waves +retire_log=                                          │
 │  clock/reset generation · cycle counter · end-of-test detection · exit code · FST waves             │
 │                                                                                                     │
 │   ┌───────────────────────────────── rv_soc_sim ───────────────────────────────────────────────┐    │
 │   │                                                                                            │    │
 │   │   ┌──────────────┐  imem_req/rsp   ┌───────────────────────────┐                           │    │
 │   │   │              │────────────────▶│ rv_mem_model              │                           │    │
 │   │   │   rv_core    │                 │ port A: fetch (read only) │                           │    │
 │   │   │              │  dmem_req/rsp   │ port B: data (R/W, BE)    │                           │    │
 │   │   │              │──────┬─────────▶│ 64 KiB @ 0x8000_0000      │                           │    │
 │   │   │              │      │          └───────────────────────────┘                           │    │
 │   │   │              │      │  addr    ┌───────────────────────────┐                           │    │
 │   │   │              │      └─decode──▶│ console MMIO (putchar)    │──▶ $write to stdout       │    │
 │   │   │              │                 └───────────────────────────┘                           │    │
 │   │   │              │                  unmapped ──▶ dmem_rsp.err                              │    │
 │   │   │              │── retire port ──▶ retire logger (file)  · tohost watcher (pass/fail)    │    │
 │   │   │              │── halt / error flags ──▶ harness                                        │    │
 │   │   └──────────────┘                                                                         │    │
 │   └────────────────────────────────────────────────────────────────────────────────────────────┘    │
 └─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Clocking and reset
- **One clock**, `clk`. Every flop in the design is on its rising edge.
- **Reset** `rst`: synchronous, active-high, held for at least 2 cycles by the harness.
- During reset: `pc_q ← RESET_PC`, `halted_q ← 0`, retire counter ← 0, no memory writes, retire port `valid = 0`.
- The register file is **not reset** (no reset on `x1–x31`, as the spec leaves them undefined). Programs must write a register before reading it. The startup code (§12) and the custom test env (`INIT_XREG`) zero all registers. Simulation runs with `--x-initial unique` so that reading an uninitialized register shows up as a lockstep mismatch.

### 2.3 Memory map

| Range | Size | Device | Access | Notes |
|---|---|---|---|---|
| `0x0000_0000 – 0x0FFF_FFFF` | — | unmapped | — | Access → bus error |
| `0x1000_0000` | 4 B | `CONSOLE` | W: byte write prints `wdata[7:0]`; R: returns 0 | Same base address as Spike's default UART, so console output can work under Spike too (confirm on the pinned Spike version). |
| `0x1000_0004 – 0x7FFF_FFFF` | — | unmapped | — | Access → bus error |
| `0x8000_0000 – 0x8000_FFFF` | 64 KiB (`MEM_SIZE_BYTES`) | RAM (code + data) | R/W | Reset vector at base. `tohost`/`fromhost` live here (§11). |
| `0x8001_0000 – 0xFFFF_FFFF` | — | unmapped | — | Access → bus error |

Instruction fetch is only legal from RAM. A fetch outside RAM sets the error flag `imem_err`.

### 2.4 Parameters

| Parameter | Default | Where | Meaning |
|---|---|---|---|
| `RESET_PC` | `32'h8000_0000` | `rv_core` | First instruction address |
| `MEM_BASE` | `32'h8000_0000` | `rv_pkg` | RAM base |
| `MEM_SIZE_BYTES` | `65536` | `rv_soc_sim`, `rv_mem_model` | RAM size, power of two |
| `CONSOLE_ADDR` | `32'h1000_0000` | `rv_pkg` | Console MMIO register |

---

## 3. Software and build system design

### 3.1 Build flow

```
 .S / .c ──riscv*-gcc -march=rv32i -mabi=ilp32 -nostdlib -T link.ld──▶ prog.elf
                                                                          │
               ┌──────────────────────────┬───────────────────────────────┼──────────────────────────┐
               ▼                          ▼                               ▼                          ▼
  objcopy -O verilog → prog.hex   nm → tohost address          spike --isa=rv32i -l          objdump -d → prog.dis
               │                          │                    --log-commits prog.elf        (for debugging)
               ▼                          ▼                               │
        Verilator sim  ◀── +hex= +tohost= ┘                               ▼
               │                                                    spike.log
               ▼                                                          │
        rtl_retire.log ──────────────▶ trace_compare.py ◀─────────────────┘
                                             │
                                             ▼
                                   PASS / first mismatch report
```

### 3.2 Make targets

| Target | Action |
|---|---|
| `make lint` | Verilator lint of all RTL with `-Wall` |
| `make unit` | cocotb unit tests for each block (`tb/unit/`) |
| `make sim PROG=<path>` | Build one program, run it on the RTL, print result and exit code |
| `make spike PROG=<path>` | Run the same ELF on Spike and save the commit log |
| `make compare PROG=<path>` | `sim` + `spike` + `trace_compare.py` |
| `make riscv-tests` | All `rv32ui-p-*` with the custom env, minus waivers |
| `make riscof` | riscv-arch-test `rv32i_m/I` through RISCOF |
| `make random SEEDS=<n>` | Generate, run and compare `n` random programs |
| `make regress` | Everything above, in that order; non-zero exit on any failure |
| `make syn` | Yosys synthesis of `rv_core` and reports |

---

## 4. Supported instructions (RV32I)

40 instructions. `opcode` is `inst[6:0]`, `funct3` is `inst[14:12]`, `funct7` is `inst[31:25]`. `inst[1:0]` must be `11`.

| # | Instr | Fmt | opcode | funct3 | funct7 / imm | Operation |
|---|---|---|---|---|---|---|
| 1 | LUI | U | `0110111` | — | — | `rd = imm_u` |
| 2 | AUIPC | U | `0010111` | — | — | `rd = pc + imm_u` |
| 3 | JAL | J | `1101111` | — | — | `rd = pc + 4; pc = pc + imm_j` |
| 4 | JALR | I | `1100111` | `000` | — | `rd = pc + 4; pc = (rs1 + imm_i) & ~1` |
| 5 | BEQ | B | `1100011` | `000` | — | `if (rs1 == rs2) pc = pc + imm_b` |
| 6 | BNE | B | `1100011` | `001` | — | `if (rs1 != rs2) ...` |
| 7 | BLT | B | `1100011` | `100` | — | `if ($signed(rs1) < $signed(rs2)) ...` |
| 8 | BGE | B | `1100011` | `101` | — | `if ($signed(rs1) >= $signed(rs2)) ...` |
| 9 | BLTU | B | `1100011` | `110` | — | `if (rs1 < rs2) ...` (unsigned) |
| 10 | BGEU | B | `1100011` | `111` | — | `if (rs1 >= rs2) ...` (unsigned) |
| 11 | LB | I | `0000011` | `000` | — | `rd = sext(M8[rs1 + imm_i])` |
| 12 | LH | I | `0000011` | `001` | — | `rd = sext(M16[...])` |
| 13 | LW | I | `0000011` | `010` | — | `rd = M32[...]` |
| 14 | LBU | I | `0000011` | `100` | — | `rd = zext(M8[...])` |
| 15 | LHU | I | `0000011` | `101` | — | `rd = zext(M16[...])` |
| 16 | SB | S | `0100011` | `000` | — | `M8[rs1 + imm_s] = rs2[7:0]` |
| 17 | SH | S | `0100011` | `001` | — | `M16[...] = rs2[15:0]` |
| 18 | SW | S | `0100011` | `010` | — | `M32[...] = rs2` |
| 19 | ADDI | I | `0010011` | `000` | — | `rd = rs1 + imm_i` |
| 20 | SLTI | I | `0010011` | `010` | — | `rd = $signed(rs1) < $signed(imm_i)` |
| 21 | SLTIU | I | `0010011` | `011` | — | `rd = rs1 < imm_i` (unsigned, imm sign-extended first) |
| 22 | XORI | I | `0010011` | `100` | — | `rd = rs1 ^ imm_i` |
| 23 | ORI | I | `0010011` | `110` | — | `rd = rs1 \| imm_i` |
| 24 | ANDI | I | `0010011` | `111` | — | `rd = rs1 & imm_i` |
| 25 | SLLI | I | `0010011` | `001` | `0000000` | `rd = rs1 << shamt` |
| 26 | SRLI | I | `0010011` | `101` | `0000000` | `rd = rs1 >> shamt` (logical) |
| 27 | SRAI | I | `0010011` | `101` | `0100000` | `rd = $signed(rs1) >>> shamt` |
| 28 | ADD | R | `0110011` | `000` | `0000000` | `rd = rs1 + rs2` |
| 29 | SUB | R | `0110011` | `000` | `0100000` | `rd = rs1 - rs2` |
| 30 | SLL | R | `0110011` | `001` | `0000000` | `rd = rs1 << rs2[4:0]` |
| 31 | SLT | R | `0110011` | `010` | `0000000` | `rd = $signed(rs1) < $signed(rs2)` |
| 32 | SLTU | R | `0110011` | `011` | `0000000` | `rd = rs1 < rs2` |
| 33 | XOR | R | `0110011` | `100` | `0000000` | `rd = rs1 ^ rs2` |
| 34 | SRL | R | `0110011` | `101` | `0000000` | `rd = rs1 >> rs2[4:0]` |
| 35 | SRA | R | `0110011` | `101` | `0100000` | `rd = $signed(rs1) >>> rs2[4:0]` |
| 36 | OR | R | `0110011` | `110` | `0000000` | `rd = rs1 \| rs2` |
| 37 | AND | R | `0110011` | `111` | `0000000` | `rd = rs1 & rs2` |
| 38 | FENCE | I | `0001111` | `000` | any `fm/pred/succ` | NOP (includes `FENCE.TSO`, `PAUSE`) |
| 39 | ECALL | I | `1110011` | `000` | `imm=0, rs1=0, rd=0` | Halt (§10) |
| 40 | EBREAK | I | `1110011` | `000` | `imm=1, rs1=0, rd=0` | Halt (§10) |

### 4.1 Immediate formats

| Type | Value (32-bit, sign bit = `inst[31]`) |
|---|---|
| I | `{{21{i[31]}}, i[30:20]}` |
| S | `{{21{i[31]}}, i[30:25], i[11:7]}` |
| B | `{{20{i[31]}}, i[7], i[30:25], i[11:8], 1'b0}` |
| U | `{i[31:12], 12'b0}` |
| J | `{{12{i[31]}}, i[19:12], i[20], i[30:21], 1'b0}` |

### 4.2 Illegal instruction rules
The decoder sets `illegal = 1` for any of the following:
1. `inst[1:0] != 2'b11` (this includes the all-zero word, which is defined as illegal).
2. `opcode` is not one of the 11 listed above (this covers CSR/M/A/F/C encodings, which are out of scope).
3. A listed opcode with a `funct3` not in the table (e.g. `LOAD` with `011`, `110`, `111`; `STORE` with `≥ 011`; `BRANCH` with `010`/`011`; `JALR` with `≠ 000`; `MISC-MEM` with `≠ 000`, which includes `FENCE.I`).
4. `OP` with a `funct7` not in the table, or `funct7 = 0100000` with a `funct3` other than `000`/`101`.
5. `SLLI` with `inst[31:25] != 0000000`; `SRLI`/`SRAI` with `inst[31:25]` not `0000000`/`0100000` (RV32 requires `shamt[5] = 0`).
6. `SYSTEM` with `funct3 != 000` (CSR instructions), or `funct3 = 000` with an encoding other than exactly ECALL/EBREAK (e.g. `MRET`, `WFI`, `SRET`).

**HINT encodings** (e.g. `ADDI x0, x0, imm`, `ADD x0, ...`) are **legal** and execute normally; the write to `x0` is discarded.

---

## 5. Microarchitecture

### 5.1 Datapath

```
                 ┌──────────────── next_pc = stop ? pc : redirect ? target : pc+4  (§5.2) ◀───────────┐
                 ▼                                                                                   │
            ┌─────────┐  pc                                                                          │
            │  pc_q   │───┬──▶ imem (port A) ── inst ──┬──▶ rv_decoder ── ctrl_t ──▶ every mux below │
            └─────────┘   │                            ├──▶ rv_imm_gen ── imm ───────────┐           │
                          │                            └──▶ rv_regfile (2R/1W)           │           │
                          │                                   rs1 │        │ rs2         │           │
                          │                                       │        │             │           │
                          ├── pc ─────▶ op_a mux ◀── rs1 / 0 ─────┤        │             │           │
                          │            (rs1/pc/0)                 │        │             │           │
                          │                │        op_b mux ◀────┼── rs2 ─┤◀── imm ─────┘           │
                          │                │       (rs2/imm)      │        │                         │
                          │                ▼           ▼          │        │                         │
                          │             ┌─────────────────┐       │        │                         │
                          │             │     rv_alu      │── alu_res ─────┼── target ──────────────▶│
                          │             └─────────────────┘       │        │                         │
                          │                       │ addr          ▼        ▼                         │
                          │                       │         rv_branch_unit ─── taken ──────────────▶│
                          │                       ▼                        │                         │
                          │                  ┌──────────┐ ◀── rs2 (store) ─┘                         │
                          │                  │  rv_lsu  │ ◀────▶ dmem (port B)                       │
                          │                  └──────────┘                                            │
                          │                       │ load_data                                        │
                          ├── pc+4 ───────────────┼──────────────────────────────────────────────────┘
                          │                       │
                          ▼                       ▼
              writeback mux: alu_res / load_data / pc+4 ── wb_data ──▶ rv_regfile write port (rd)
```

Design notes:
- **One ALU** computes every address and target: `rs1+imm` for loads/stores/JALR, `pc+imm` for branches/JAL/AUIPC, `0+imm` for LUI.
- **A separate `pc + 4` adder** feeds the next-PC mux and the `WB_PC4` writeback path.
- **The branch unit only compares** `rs1` and `rs2`; it never computes a target.
- The critical path is expected to be: `pc_q → imem → decoder/regfile read → op mux → ALU → dmem → LSU load align → wb mux → regfile` setup. M8 measures this.

### 5.2 Next-PC logic

```
taken_branch = ctrl.branch & br_taken
redirect     = ctrl.jump | taken_branch
target       = ctrl.jalr ? (alu_res & 32'hFFFF_FFFE) : alu_res
next_pc      = halted_q | stop ? pc_q
             : redirect        ? target
             :                   pc_q + 4
misaligned_fetch = redirect & target[1]
```
- `stop` is any condition from §10 that halts the core in the current cycle.
- `target[0]` is always 0: JAL/branch immediates are even and JALR clears bit 0. So only `target[1]` has to be checked.
- A branch that is **not taken** never raises `misaligned_fetch`, even if its target is misaligned (as the spec requires).

### 5.3 Writeback mux

| `wb_sel` | `wb_data` | Used by |
|---|---|---|
| `WB_ALU` | `alu_res` | LUI, AUIPC, OP, OP-IMM |
| `WB_MEM` | `load_data` from LSU | Loads |
| `WB_PC4` | `pc_q + 4` | JAL, JALR |

`rf_we = ctrl.reg_write & ~stop & ~halted_q` (writes to `x0` are discarded inside the register file).

### 5.4 Load/store unit

**Store lane placement** (`off = addr[1:0]`):

| Size | Legal `off` | `be` | `wdata` |
|---|---|---|---|
| Byte | 0–3 | `4'b0001 << off` | `{4{rs2[7:0]}}` |
| Half | 0, 2 | `4'b0011 << off` | `{2{rs2[15:0]}}` |
| Word | 0 | `4'b1111` | `rs2` |

Replicating the data across lanes means the memory only needs to look at `be`.

**Load extraction:** shift `rdata` right by `off*8`, then sign- or zero-extend from 8 or 16 bits as `mem_unsigned` and `mem_size` say.

**Misalignment:** `misaligned_access = (size == HALF & addr[0]) | (size == WORD & addr[1:0] != 0)`. When it is set, the request's `valid` is held low (no memory side effect) and the core stops (§10).

---

## 6. Module specifications

All ports use `_i` / `_o` suffixes. Widths are 32 bits unless shown.

### 6.1 `rv_core`
| Port | Dir | Width / type | Description |
|---|---|---|---|
| `clk_i`, `rst_i` | in | 1 | Clock, sync active-high reset |
| `imem_req_o` | out | `imem_req_t` | Fetch request (§8.3) |
| `imem_rsp_i` | in | `imem_rsp_t` | Fetch response |
| `dmem_req_o` | out | `dmem_req_t` | Data request |
| `dmem_rsp_i` | in | `dmem_rsp_t` | Data response |
| `retire_o` | out | `retire_t` | Retire trace (§9) |
| `halted_o` | out | 1 | Core has stopped (sticky until reset) |
| `status_o` | out | `stop_cause_t` | Why it stopped (§10) |

Parameter: `RESET_PC`.

### 6.2 `rv_pc`
| Port | Dir | Description |
|---|---|---|
| `clk_i`, `rst_i` | in | |
| `next_pc_i` | in | From next-PC mux |
| `pc_o` | out | Current PC (`pc_q`) |
| `pc_plus4_o` | out | `pc_q + 4` |

### 6.3 `rv_decoder` (purely combinational)
| Port | Dir | Description |
|---|---|---|
| `inst_i` | in | Instruction word |
| `ctrl_o` | out | `ctrl_t` (§8.2); `ctrl_o.illegal` per §4.2 |
| `rs1_o`, `rs2_o`, `rd_o` | out | 5-bit register indices (`inst[19:15]`, `[24:20]`, `[11:7]`) |

The decoder drives `reg_write = 0` and `mem_read = mem_write = 0` for illegal instructions.

### 6.4 `rv_imm_gen` (combinational)
| Port | Dir | Description |
|---|---|---|
| `inst_i` | in | Instruction word |
| `type_i` | in | `imm_type_t` |
| `imm_o` | out | Immediate per §4.1 (`0` for `IMM_NONE`) |

### 6.5 `rv_regfile`
| Port | Dir | Description |
|---|---|---|
| `clk_i` | in | No reset (§2.2) |
| `ra1_i`, `ra2_i` | in | 5-bit read addresses |
| `rd1_o`, `rd2_o` | out | Combinational read; returns 0 for address 0 |
| `we_i`, `wa_i`, `wd_i` | in | Write enable, address, data; written on clock edge, ignored when `wa_i == 0` |

A read and a write to the same register in the same cycle returns the **old** value. In a single-cycle core this never matters, because the reading instruction is the one doing the write. It is written down for Phase 2.

### 6.6 `rv_alu` (combinational)
| Port | Dir | Description |
|---|---|---|
| `op_i` | in | `alu_op_t` |
| `a_i`, `b_i` | in | Operands |
| `res_o` | out | Result. Shifts use `b_i[4:0]`; SLT/SLTU return `{31'b0, cmp}` |

### 6.7 `rv_branch_unit` (combinational)
| Port | Dir | Description |
|---|---|---|
| `op_i` | in | `branch_op_t` (= `funct3`) |
| `a_i`, `b_i` | in | `rs1`, `rs2` values |
| `taken_o` | out | Condition result |

### 6.8 `rv_lsu` (combinational)
| Port | Dir | Description |
|---|---|---|
| `ctrl_i` | in | `mem_read`, `mem_write`, `mem_size`, `mem_unsigned` from `ctrl_t` |
| `addr_i` | in | `alu_res` |
| `store_data_i` | in | `rs2` value |
| `enable_i` | in | 0 when halted or stopping, so nothing happens on the memory side |
| `dmem_req_o` | out | `dmem_req_t` (lane-placed data, byte enables) |
| `dmem_rsp_i` | in | `dmem_rsp_t` |
| `load_data_o` | out | Extended load result |
| `misaligned_o` | out | §5.4 |
| `bus_err_o` | out | `dmem_rsp_i.err` for an active request |

### 6.9 `rv_mem_model` (sim only)
Two ports: port A (fetch, read-only, combinational) and port B (data, combinational read, write on clock edge under `be`). Contents loaded with `$readmemh` from `+hex=`. Address bits `[31:2]` minus `MEM_BASE` index the word array. Out-of-range addresses set `err`.

### 6.10 `rv_soc_sim` (sim only)
Instantiates `rv_core` and `rv_mem_model`, decodes data addresses (RAM / `CONSOLE` / unmapped), prints console bytes with `$write("%c")`, watches the retire port for a store to the `tohost` address (from `+tohost=`), and writes the retire log (§9.2). Exposes `done_o`, `tohost_value_o`, `halted_o`, `status_o` to the C++ harness.

---

## 7. Control signal table

One row per instruction. `—` means "don't care" (the decoder drives a fixed default, which is 0 or the first enum value).

| Instr | `imm` | `op_a` | `op_b` | `alu_op` | `wb_sel` | `reg_write` | `mem_read` | `mem_write` | `mem_size` | `mem_uns` | `branch` | `jump` | `jalr` | Other |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LUI | U | ZERO | IMM | ADD | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| AUIPC | U | PC | IMM | ADD | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| JAL | J | PC | IMM | ADD | PC4 | 1 | 0 | 0 | — | — | 0 | 1 | 0 | |
| JALR | I | RS1 | IMM | ADD | PC4 | 1 | 0 | 0 | — | — | 0 | 1 | 1 | |
| BEQ | B | PC | IMM | ADD | — | 0 | 0 | 0 | — | — | 1 | 0 | 0 | `br_op=EQ` |
| BNE | B | PC | IMM | ADD | — | 0 | 0 | 0 | — | — | 1 | 0 | 0 | `br_op=NE` |
| BLT | B | PC | IMM | ADD | — | 0 | 0 | 0 | — | — | 1 | 0 | 0 | `br_op=LT` |
| BGE | B | PC | IMM | ADD | — | 0 | 0 | 0 | — | — | 1 | 0 | 0 | `br_op=GE` |
| BLTU | B | PC | IMM | ADD | — | 0 | 0 | 0 | — | — | 1 | 0 | 0 | `br_op=LTU` |
| BGEU | B | PC | IMM | ADD | — | 0 | 0 | 0 | — | — | 1 | 0 | 0 | `br_op=GEU` |
| LB | I | RS1 | IMM | ADD | MEM | 1 | 1 | 0 | B | 0 | 0 | 0 | 0 | |
| LH | I | RS1 | IMM | ADD | MEM | 1 | 1 | 0 | H | 0 | 0 | 0 | 0 | |
| LW | I | RS1 | IMM | ADD | MEM | 1 | 1 | 0 | W | 0 | 0 | 0 | 0 | |
| LBU | I | RS1 | IMM | ADD | MEM | 1 | 1 | 0 | B | 1 | 0 | 0 | 0 | |
| LHU | I | RS1 | IMM | ADD | MEM | 1 | 1 | 0 | H | 1 | 0 | 0 | 0 | |
| SB | S | RS1 | IMM | ADD | — | 0 | 0 | 1 | B | — | 0 | 0 | 0 | |
| SH | S | RS1 | IMM | ADD | — | 0 | 0 | 1 | H | — | 0 | 0 | 0 | |
| SW | S | RS1 | IMM | ADD | — | 0 | 0 | 1 | W | — | 0 | 0 | 0 | |
| ADDI | I | RS1 | IMM | ADD | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| SLTI | I | RS1 | IMM | SLT | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| SLTIU | I | RS1 | IMM | SLTU | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| XORI | I | RS1 | IMM | XOR | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| ORI | I | RS1 | IMM | OR | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| ANDI | I | RS1 | IMM | AND | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| SLLI | I | RS1 | IMM | SLL | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | shamt = `imm[4:0]` |
| SRLI | I | RS1 | IMM | SRL | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| SRAI | I | RS1 | IMM | SRA | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| ADD | — | RS1 | RS2 | ADD | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| SUB | — | RS1 | RS2 | SUB | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| SLL | — | RS1 | RS2 | SLL | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| SLT | — | RS1 | RS2 | SLT | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| SLTU | — | RS1 | RS2 | SLTU | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| XOR | — | RS1 | RS2 | XOR | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| SRL | — | RS1 | RS2 | SRL | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| SRA | — | RS1 | RS2 | SRA | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| OR | — | RS1 | RS2 | OR | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| AND | — | RS1 | RS2 | AND | ALU | 1 | 0 | 0 | — | — | 0 | 0 | 0 | |
| FENCE | — | — | — | — | — | 0 | 0 | 0 | — | — | 0 | 0 | 0 | `is_fence=1` (NOP) |
| ECALL | — | — | — | — | — | 0 | 0 | 0 | — | — | 0 | 0 | 0 | `is_ecall=1` |
| EBREAK | — | — | — | — | — | 0 | 0 | 0 | — | — | 0 | 0 | 0 | `is_ebreak=1` |
| *illegal* | — | — | — | — | — | 0 | 0 | 0 | — | — | 0 | 0 | 0 | `illegal=1` |

The decoder unit test (exec.md M2.6) generates its expected values from this table. Keep the table and `rv_decoder.sv` in sync. If they disagree, the table is right until the review says otherwise.

---

## 8. Package `rv_pkg.sv`

### 8.1 Constants
```systemverilog
package rv_pkg;
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
```

### 8.2 Enums and control struct
```systemverilog
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
  } ctrl_t;
```

### 8.3 Memory port structs
```systemverilog
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
```

**Phase 1 port contract:** responses are combinational (zero latency) and `ready` is always 1. The core includes a simulation assertion that `ready == 1` whenever `valid == 1`. Phase 2 may add latency and real handshaking behind the same structs (§16).

### 8.4 Retire and status types
```systemverilog
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
```

---

## 9. Retire trace

### 9.1 Port semantics
The field names follow the RISC-V Formal Interface (RVFI), so riscv-formal can be connected later (exec.md M6.6).

| Field | Meaning |
|---|---|
| `valid` | 1 for every cycle in which an instruction retires or stops the core. 0 during reset and while halted. |
| `order` | Retire counter, starts at 0 |
| `insn`, `pc_rdata` | The instruction and its PC |
| `pc_wdata` | Next PC (equals `pc_rdata` for a stopping instruction) |
| `rs1_*`, `rs2_*` | Source registers read, with their values |
| `rd_addr`, `rd_wdata` | Destination written; **both 0 when nothing is written** (including `rd = x0`) |
| `mem_addr` | Access address (word-aligned, as in RVFI) |
| `mem_rmask` / `mem_wmask` | Byte masks of the access; 0 if none |
| `mem_rdata` / `mem_wdata` | Raw word read / lane-placed word written |
| `trap` | 1 if the instruction stopped the core with an error (§10) |
| `halt` | 1 for ECALL/EBREAK |

### 9.2 Retire log format (text, one line per retired instruction)
```
<order> <pc> <insn> [x<rd> <rd_wdata>] [mem W <addr> <wmask> <wdata>] [mem R <addr> <rmask> <rdata>] [HALT|TRAP <cause>]
```
All numbers are lower-case hex without `0x`, PC/addr/data padded to 8 digits. Example:
```
0000000c 8000000c 00a12023 mem W 80001000 f 0000002a
0000000d 80000010 00012583 x11 0000002a mem R 80001000 f 0000002a
```
`trace_compare.py` converts Spike's `--log-commits` output into this format (§3.1). The comparison checks `pc`, `insn`, `rd`/`rd_wdata`, and for stores `addr`/data of the written bytes.

---

## 10. Stop conditions and error handling

When a stop condition is detected for the instruction at `pc_q`:
1. The instruction has **no architectural side effect**: no register write and no memory write.
2. It is reported once on the retire port with `halt = 1` (ECALL/EBREAK) or `trap = 1` (errors).
3. `halted_q ← 1` and `status_o` latches the cause. The PC stays put and every later cycle is idle until reset.

| Cause (`stop_cause_t`) | Detected when | Harness result |
|---|---|---|
| `STOP_ECALL` | `ctrl.is_ecall` | End of test; pass/fail decided by `tohost` (if `tohost` was never written: **fail**) |
| `STOP_EBREAK` | `ctrl.is_ebreak` | Same as ECALL |
| `STOP_ILLEGAL` | `ctrl.illegal` | **Error** |
| `STOP_MISALIGNED_FETCH` | `misaligned_fetch` (§5.2) | **Error** |
| `STOP_MISALIGNED_DATA` | `lsu.misaligned_o` | **Error** |
| `STOP_BUS_ERROR` | `dmem_rsp.err` on an active request | **Error** |
| `STOP_IFETCH_ERROR` | `imem_rsp.err` | **Error** |

If several conditions apply in one cycle, `status_o` records the highest-priority one: `IFETCH_ERROR` > `ILLEGAL` > `ECALL`/`EBREAK` > `MISALIGNED_FETCH` > `MISALIGNED_DATA` > `BUS_ERROR`. A fetch error comes first because the instruction word itself can't be trusted.

---

## 11. Test-end protocol (HTIF-compatible)

- The linker script defines 8-byte-aligned symbols `tohost` and `fromhost` in section `.tohost`. Spike uses these to end a simulation, so the same ELF runs on both.
- A program ends by storing a word to `tohost`:
  - `1` → **pass** (exit code 0)
  - `(code << 1) | 1` → **fail** with `code` (for riscv-tests, `code` = failing test number)
- The harness gets the `tohost` address from `nm` via `+tohost=`. It ends the run in the cycle the store retires.

**Harness exit codes**

| Code | Meaning |
|---|---|
| 0 | `tohost == 1` |
| 1 | `tohost` written with a fail value |
| 2 | Timeout (`+max_cycles`, default 1,000,000) |
| 3 | Core stopped with an error cause (§10) |
| 4 | Core halted (ECALL/EBREAK) without writing `tohost` |
| 5 | Harness error (missing file, bad plusarg) |

Negative tests (exec.md M3, the `e*` tests in §15.2) declare their expected exit code and cause in a header comment, e.g. `# expect: 3 STOP_ILLEGAL`. The runner checks it.

---

## 12. Software environment

| Item | Definition |
|---|---|
| ISA / ABI | `-march=rv32i -mabi=ilp32` |
| Compiler flags | `-O2 -nostdlib -nostartfiles -ffreestanding -static -mcmodel=medany` |
| Libraries | `libgcc` (software `mul`/`div`/`rem`), project stubs: `putchar`, minimal `printf`, `memcpy`, `memset` |
| Linker script `link.ld` | `.text` at `0x8000_0000` (entry `_start`), then `.rodata`, `.data`, `.bss`, `.tohost`; `_stack_top` = end of RAM, 16-byte aligned |
| `crt0.S` | Zero `x1–x31`; set `sp = _stack_top`, `gp = __global_pointer$`; zero `.bss`; call `main`; store `(ret << 1) \| 1` to `tohost` (so `ret = 0` → pass); `ecall` as a fallback stop |
| Custom riscv-tests env (`sw/common/env/p/riscv_test.h`) | `RVTEST_RV32U`; `RVTEST_CODE_BEGIN` = `_start:` + `INIT_XREG`; `RVTEST_PASS` = store `1` to `tohost`; `RVTEST_FAIL` = store `(TESTNUM << 1) \| 1`; no CSR access |
| RISCOF `model_test.h` | `RVMODEL_HALT` = pass write to `tohost` + `ecall`; `RVMODEL_DATA_BEGIN/END` mark the signature region; `RVMODEL_BOOT` empty; IO macros empty |

---

## 13. Verification hooks in RTL and sim

Assertions compiled with Verilator `--assert` (under `` `ifndef SYNTHESIS ``):

| ID | Assertion |
|---|---|
| A-1 | `rv_regfile`: register 0 always reads 0 |
| A-2 | `imem_req.valid -> imem_rsp.ready` and `dmem_req.valid -> dmem_rsp.ready` (Phase 1 contract) |
| A-3 | `imem_req.addr[1:0] == 0` |
| A-4 | `halted_q -> !dmem_req.valid && !rf_we` |
| A-5 | Decoder: at most one of {`mem_read`, `mem_write`, `branch`, `jump`, `is_fence`, `is_ecall`, `is_ebreak`, `illegal`} is set |
| A-6 | Decoder: `illegal` implies `!reg_write && !mem_read && !mem_write` |

Verilator is a 2-state simulator, so X-propagation checks (no X on `ctrl_o`, `next_pc`, `dmem_req` after reset) need a 4-state simulator. They are optional in Phase 1: run the unit tests once on Icarus Verilog if it is installed.

---

## 14. Coding and naming conventions

### 14.1 Files and modules
- One module per file; file name = module name (`rv_alu.sv` holds `module rv_alu`).
- Prefix `rv_` for all RTL modules; `tb_` for testbenches.
- `rv_pkg.sv` is compiled first; modules `import rv_pkg::*;` inside the module header.

### 14.2 Naming
| Kind | Convention | Example |
|---|---|---|
| Input / output ports | `_i` / `_o` suffix | `dmem_req_o` |
| Flop output / next value | `_q` / `_d` | `pc_q`, `pc_d` |
| Active-low signal | `_n` suffix | (none in Phase 1) |
| Parameters, localparams | `UPPER_SNAKE` | `RESET_PC` |
| Types | `_t` suffix | `ctrl_t` |
| Enum values | `UPPER_SNAKE` with a type prefix | `ALU_ADD`, `WB_PC4` |
| Signals | `lower_snake` | `alu_res` |

### 14.3 RTL rules
- `always_ff @(posedge clk_i)` for flops, `always_comb` for logic. No `always @*`, no `always_latch`.
- Every `always_comb` assigns defaults at the top, so no latches can be inferred. Every `case` has a `default`.
- Non-blocking (`<=`) in `always_ff`, blocking (`=`) in `always_comb`. Never mixed.
- Explicit widths on all constants (`32'd4`, not `4`).
- Reset logic: `if (rst_i) ... else ...` inside `always_ff` (synchronous).
- No `initial`, `#delay`, `$display` or `$readmemh` in `rtl/`.
- `default_nettype none` at the top of every RTL file, `default_nettype wire` at the end.

### 14.4 Lint and formatting
- `verilator --lint-only -Wall` must report zero warnings. Waivers use `/* verilator lint_off <RULE> */` around the smallest possible region, with a comment saying why.
- Format with `verible-verilog-format` (if installed) using the repo's `.verible-format` settings; 2-space indent, 100-column lines.

### 14.5 Commits
- Subject line in the imperative, ≤ 72 characters, prefixed with the area: `rtl: add rv_alu`, `sw: add crt0`, `tb: lsu unit test`, `docs: ...`.
- `make lint unit` passes before every commit; `make regress` passes before a milestone is marked done.

---

## 15. Instruction coverage checklist

Each instruction must be covered by **all three** sources before Phase 1 is done (exec.md §7). Test names follow the upstream repositories; check them against the pinned submodule versions in M0.4.

### 15.1 Per instruction

| Instr | Directed (`sw/asm/`) | riscv-tests (`rv32ui-p-`) | riscv-arch-test (`rv32i_m/I/`) | Covered |
|---|---|---|---|---|
| LUI | `t00_lui_addi` | `lui` | `lui-01` | [ ] |
| AUIPC | `t07_auipc` | `auipc` | `auipc-01` | [ ] |
| JAL | `t05_jal_jalr` | `jal` | `jal-01` | [ ] |
| JALR | `t05_jal_jalr` | `jalr` | `jalr-01` | [ ] |
| BEQ | `t04_branch` | `beq` | `beq-01` | [ ] |
| BNE | `t04_branch` | `bne` | `bne-01` | [ ] |
| BLT | `t04_branch` | `blt` | `blt-01` | [ ] |
| BGE | `t04_branch` | `bge` | `bge-01` | [ ] |
| BLTU | `t04_branch` | `bltu` | `bltu-01` | [ ] |
| BGEU | `t04_branch` | `bgeu` | `bgeu-01` | [ ] |
| LB | `t03_load_store` | `lb` | `lb-align-01` | [ ] |
| LH | `t03_load_store` | `lh` | `lh-align-01` | [ ] |
| LW | `t03_load_store` | `lw` | `lw-align-01` | [ ] |
| LBU | `t03_load_store` | `lbu` | `lbu-align-01` | [ ] |
| LHU | `t03_load_store` | `lhu` | `lhu-align-01` | [ ] |
| SB | `t03_load_store` | `sb` | `sb-align-01` | [ ] |
| SH | `t03_load_store` | `sh` | `sh-align-01` | [ ] |
| SW | `t03_load_store` | `sw` | `sw-align-01` | [ ] |
| ADDI | `t00_lui_addi`, `t01_alu_imm` | `addi` | `addi-01` | [ ] |
| SLTI | `t01_alu_imm` | `slti` | `slti-01` | [ ] |
| SLTIU | `t01_alu_imm` | `sltiu` | `sltiu-01` | [ ] |
| XORI | `t01_alu_imm` | `xori` | `xori-01` | [ ] |
| ORI | `t01_alu_imm` | `ori` | `ori-01` | [ ] |
| ANDI | `t01_alu_imm` | `andi` | `andi-01` | [ ] |
| SLLI | `t01_alu_imm` | `slli` | `slli-01` | [ ] |
| SRLI | `t01_alu_imm` | `srli` | `srli-01` | [ ] |
| SRAI | `t01_alu_imm` | `srai` | `srai-01` | [ ] |
| ADD | `t02_alu_reg` | `add` | `add-01` | [ ] |
| SUB | `t02_alu_reg` | `sub` | `sub-01` | [ ] |
| SLL | `t02_alu_reg` | `sll` | `sll-01` | [ ] |
| SLT | `t02_alu_reg` | `slt` | `slt-01` | [ ] |
| SLTU | `t02_alu_reg` | `sltu` | `sltu-01` | [ ] |
| XOR | `t02_alu_reg` | `xor` | `xor-01` | [ ] |
| SRL | `t02_alu_reg` | `srl` | `srl-01` | [ ] |
| SRA | `t02_alu_reg` | `sra` | `sra-01` | [ ] |
| OR | `t02_alu_reg` | `or` | `or-01` | [ ] |
| AND | `t02_alu_reg` | `and` | `and-01` | [ ] |
| FENCE | `t08_fence_nop` | — (`fence_i` is Zifencei, waived) | `fence-01` | [ ] |
| ECALL | `t09_ecall_halt` | — (`rv32mi-scall` needs CSRs) | — (privilege suite needs CSRs) | [ ] |
| EBREAK | `t10_ebreak_halt` | — (`rv32mi-sbreak` needs CSRs) | — (privilege suite needs CSRs) | [ ] |

For ECALL and EBREAK, the directed tests plus random-test coverage of the halt path are the full coverage in Phase 1. Upstream coverage arrives with Zicsr in Phase 2.

Additional upstream tests that run but aren't tied to one instruction: `rv32ui-p-simple`, `rv32ui-p-ld_st`, `rv32ui-p-st_ld` (if present in the pinned version). Waived: `rv32ui-p-fence_i`, `rv32ui-p-ma_data`.

### 15.2 Directed tests list (`sw/asm/`)

| Test | Checks | Expected result |
|---|---|---|
| `t00_lui_addi` | LUI/ADDI constant building, `li` of full 32-bit values, sign edge cases | pass |
| `t01_alu_imm` | Every OP-IMM instruction; shamt 0/31; negative immediates; SLTIU with `-1` | pass |
| `t02_alu_reg` | Every OP instruction; shift by `rs2[4:0]` ignores upper bits; overflow wrap | pass |
| `t03_load_store` | All widths at every legal offset; sign vs. zero extension; store-then-load | pass |
| `t04_branch` | All 6 branches, taken and not taken, forward and backward, signed vs. unsigned edges | pass |
| `t05_jal_jalr` | Call/return, `rd = x0` jumps, JALR bit-0 clearing, link value | pass |
| `t06_x0` | Writes to `x0` from every write-capable class are discarded | pass |
| `t07_auipc` | AUIPC at different PCs, used for PC-relative addressing | pass |
| `t08_fence_nop` | FENCE, FENCE.TSO, PAUSE encodings change nothing | pass |
| `t09_ecall_halt` | Write `tohost = 1`, then ECALL; nothing after it executes | pass (exit 0) |
| `t10_ebreak_halt` | Same with EBREAK | pass (exit 0) |
| `e01_illegal` | All-zero word, a CSR instruction, a bad funct7, an `M`-extension op | exit 3, `STOP_ILLEGAL` |
| `e02_misaligned_load` | `LW` at offset 2, `LH` at offset 1 | exit 3, `STOP_MISALIGNED_DATA` |
| `e03_misaligned_store` | `SW` at offset 1 | exit 3, `STOP_MISALIGNED_DATA` |
| `e04_misaligned_jump` | `JALR` to an address with bit 1 set; a not-taken branch to a misaligned target must **not** stop | exit 3, `STOP_MISALIGNED_FETCH` |
| `e05_bus_error` | Load from `0x0000_0000` | exit 3, `STOP_BUS_ERROR` |
| `e06_ifetch_error` | JALR to an address outside RAM | exit 3, `STOP_IFETCH_ERROR` |
| `t11_console` | Write a string to `CONSOLE` | pass; harness output matches the expected string |

Each error test (`e*`) contains exactly one stopping instruction. Variants of a case (e.g. `LW` vs. `LH`) are separate files named `e02a_`, `e02b_`, ….

---

## 16. Phase 2 hooks (not decided)

These are the places where Phase 1 was shaped so Phase 2 changes stay local. The choices themselves are made at the Phase 2 review (exec.md §9).

| Hook | Phase 1 state | What Phase 2 may change |
|---|---|---|
| Memory ports (§8.3) | Zero-latency, `ready = 1` | Real handshakes, latency, caches, a bus adapter (OBI/AXI-Lite/Wishbone), FPGA BRAM |
| `ctrl_t` struct | Used in one stage | Carried through pipeline registers |
| Retire port (§9) | Driven by the single stage | Driven from the writeback stage; connected to riscv-formal |
| Register file read/write timing (§6.5) | Old value on same-cycle read | Write-first or forwarding network |
| Stop conditions (§10) | Halt the core | Become precise exceptions with `mcause`/`mepc`/`mtvec` once Zicsr and the privileged spec are added |
| Decoder illegal rules (§4.2) | M/A/C/CSR encodings are illegal | Relaxed per extension added |
| Memory map (§2.3) | RAM + console | Real peripherals, boot ROM, timer (`mtime`) for interrupts |
| Reset (§2.2) | Synchronous active-high | Kept or changed per target platform |
