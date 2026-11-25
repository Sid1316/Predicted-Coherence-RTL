# RISC-V Core: Phase 1 Specification

| | |
|---|---|
| **Covers** | Phase 1: single-cycle RV32I core + simulation SoC |
| **Companion** | [exec.md](exec.md) (execution plan, milestones, Phase 2 decision inputs) |
| **ISA reference** | *The RISC-V Instruction Set Manual, Volume I: Unprivileged ISA* (ratified), RV32I Base Integer Instruction Set v2.1 |
| **Status** | Rev 1.1: approved, M1 complete (2026-11-25). See §0. |

This document is the single source of truth for Phase 1 RTL, simulation and software. It covers the items listed under milestone M1 in exec.md:

| exec.md item | Where it is covered here |
|---|---|
| M1.1 Datapath block diagram, next-PC mux, writeback mux, control signal table | §5, §6, §7 |
| M1.2 `rv_pkg.sv` contents (enums, `ctrl_t`, memory structs, memory map) | §8 |
| M1.3 Coding and naming conventions | §14 |
| M1.4 Instruction coverage checklist | §15 |

Anything this document does not specify is out of Phase 1 scope (see exec.md §1). Phase 2 choices are listed as **hooks** in §16 but not decided.

---

## 0. M1 review record

The review was done on 2026-11-25 against the pinned submodules (`tests/riscv-tests` at `1b3f8bd`, `tests/riscv-arch-test` at tag `3.10.0`) and the installed tools (Verilator 5.054). "Changed" means this revision of the document was edited.

### 0.1 Result per M1 item

| Item | What was checked | Result |
|---|---|---|
| **M1.1** Datapath, next-PC, writeback, control table | Every row of §7 against §4 and §5; every signal path in §5 for combinational loops; stop handling in §10 against §5.2/§5.3 | One defect found and fixed (R-1). Table unchanged. |
| **M1.2** `rv_pkg.sv` contents | §8 code extracted as-is and linted with `verilator --lint-only -Wall` (alone, and imported by a test module that uses every type and constant) | Compiles; clean when imported. Linted alone, every constant is flagged `UNUSEDPARAM`, so a documented waiver was added (R-2). `ctrl_t` is 28 bits. **`rtl/rv_pkg.sv` is generated from §8 word for word, listed in `rtl/rtl.f`, and passes `make lint`.** |
| **M1.3** Conventions | §14 against the Makefile and lint setup | Unchanged, plus the one waiver allowed by §14.4 (R-2). |
| **M1.4** Coverage checklist | Every test name in §15 against `isa/rv32ui/*.S` and `riscv-test-suite/rv32i_m/I/src/*.S`; what each suite needs from our test environment | All names exist. One arch-test was missing from the table (R-5). Environment requirements were missing or wrong (R-3, R-4). |

### 0.2 Changes in this revision

| ID | Section | Finding | Change |
|---|---|---|---|
| R-1 | §6.8 | `rv_lsu.enable_i` was "0 when halted or stopping". Stopping includes `STOP_BUS_ERROR`, which comes from `dmem_rsp.err`, which depends on `dmem_req.valid`: a **combinational loop**. | `enable_i` now depends only on `halted_q` and the fetch error, never on the data response. |
| R-2 | §8.1, §14.4 | Package constants trip `UNUSEDPARAM` when `rv_pkg.sv` is linted on its own, which is the case until other modules exist. | `lint_off`/`lint_on UNUSEDPARAM` around the constants, with the reason in a comment. |
| R-3 | §11, §12 | §11 said the linker script defines `tohost`/`fromhost`. Both test suites define these symbols in their own macros (`RVTEST_DATA_BEGIN`, `RVMODEL_DATA_BEGIN`), so a linker-script definition would clash. | The symbols come from assembly (test env, `model_test.h`, or `crt0.S`); `link.ld` only places the `.tohost` section. |
| R-4 | §12 | The custom riscv-tests env was underspecified. `RVTEST_CODE_END` is `unimp` (illegal on this core). `TEST_PASSFAIL` places `RVTEST_FAIL` directly before `RVTEST_PASS`, so FAIL must not fall through. | Full macro list and required behaviour added, plus the arch-test entry point, signature dump and trap-handler finding. |
| R-5 | §15.1 | `misalign1-jalr-01` (JALR with target bit 0 set, which must be cleared, so no trap) was not listed. | Added to the JALR row, and the bit-0 case added to directed test `e04`. "(if present)" removed, since `ld_st` and `st_ld` exist and use only aligned RV32 accesses. Suite totals added. |
| R-6 | §2.2 | Verilator's `--x-initial unique` alone gives **zeros** unless the run also asks for random values. | Added the runtime plusargs. |
| R-7 | §3.1 | The build flow assumes Spike, which has no native Windows build. | Note added; the reference model is an open decision (exec.md §8). |
| R-8 | §6.2 | exec.md M3.1 has `rv_pc` choose the next PC and detect misaligned targets, but §6.2 gave it only a `next_pc_i` input, leaving §5.2 in `rv_core` where it could not be unit-tested. | `rv_pc` now holds all of §5.2: new inputs for the control bits, branch result and target, new outputs `next_pc_o` and `misaligned_fetch_o`. Behaviour unchanged. |
| R-9 | §6.1, §6.8, §9.1, §14.3, §14.4 | Writing `rv_core` (M3.2) needed four details the spec left open: what the datapath sees on a fetch error; whether `rv_lsu.enable_i` blocks a store during reset (§2.2 says no memory writes in reset, but §6.8 gated only on `halted_q` and the fetch error); which retire fields an instruction that reads no register, or that stops, reports; and how simulation-only assertions are written. | On a fetch error (and while idle) the instruction word is forced to 0, so the untrusted word never reaches the datapath, and the retire port shows `insn = 0`. `enable_i` also includes `~rst_i`. `rs1_*`/`rs2_*` are 0 for an operand the instruction does not read (as in RVFI); the `mem_*` fields are 0 for a stopping instruction. Assertion blocks use a plain `always @(posedge clk_i)` under `` `ifndef SYNTHESIS ``. `make lint` now lints with `--top-module rv_core`. |
| R-10 | §2.2, §11 | Writing the harness (M3.4) needed: an exit code for an RTL assertion or `$fatal` (Verilator's default handler exits with 1, the "tohost fail" code); what makes `+hex=` bad (Verilator's `$readmemh` reads a word such as `ZZZZZZZZ` as random bits without an error); which stream the console and the result use; and the default random-reset seed. | New exit code 6 (simulation error). `+hex=` is required and checked before loading (format, every word inside RAM); a bad image is exit 5. stdout carries only console bytes, unchanged; the harness's result line goes to stderr. Without `+verilator+` plusargs the harness uses `rand+reset+2` and seed 1, so runs are repeatable (N-5). |
| R-11 | §11, §15.2 | Writing the directed tests (M3.5): `t09`/`t10` were to write `tohost = 1` and then ECALL/EBREAK, expecting exit 0. The harness ends the run when the `tohost` store retires, so the ECALL would never execute and the test would check nothing. The `# expect:` header from §11 is not valid in a preprocessed `.S` file. | `t09`/`t10` execute ECALL/EBREAK without writing `tohost` and expect exit 4 with the stop cause; a fail store follows, so an instruction that does not stop gives exit 1. Headers use `//`. |
| R-12 | §2.4, §11, §12 | Running riscv-arch-test (M5.3): `jal-01` needs about 1.7 MiB and the branch tests up to 310 KiB, more than the 64 KiB RAM. `arch_test.h`'s `LA()` macro switches on `.option rvc` around its `.align` padding, and with linker relaxation ld fills that padding with `c.nop`, illegal on RV32I. riscv-config requires `misa` to be described as accessible. RISCOF names signatures `<DUT|Reference>-<plugin>.signature`. | `MEM_SIZE_BYTES` stays 64 KiB by default; RISCOF builds a second simulator with 2 MiB (`build/sim-2097152/`), links with `--defsym=__ram_size` (`link.ld` takes the size from it) and runs the model with the same size. Arch tests are built with `-mno-relax`. The ISA YAML describes `misa` (MXL = 1, I) although the core has no CSRs. The harness dumps the signature through a DPI-C read port on `rv_mem_model` (Verilator only). |

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
- The register file is **not reset** (no reset on `x1–x31`, as the spec leaves them undefined). Programs must write a register before reading it. The startup code (§12) and the custom test env (`INIT_XREG`) zero all registers. Simulation is built with `--x-initial unique` and run with `+verilator+rand+reset+2 +verilator+seed+<n>` (the harness defaults, seed 1), so uninitialized registers get random values and reading one shows up as a lockstep mismatch. Without the runtime plusargs Verilator initializes them to zero, which would hide the bug.

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

**Reference model (open):** Spike has no native Windows build, and this project runs natively on Windows (README Setup). The Spike branch of this flow stands for "the reference model". Which model fills it (a project Python RV32I model, Sail, or Spike on a Linux CI runner) is the open decision in exec.md §8, needed before M5.3. The retire-log format (§9.2) stays the comparison interface whichever model is chosen.

### 3.2 Make targets

| Target | Action |
|---|---|
| `make lint` | Verilator lint of all RTL with `-Wall` |
| `make unit` | cocotb unit tests for each block (`tb/unit/`), on Icarus Verilog. `BLOCKS="rv_alu ..."` picks blocks, `WAVES=1` writes FST waveforms |
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

**Request fields:** `valid = enable & (mem_read | mem_write) & ~misaligned_access`, and `misaligned_o` is gated by `enable` the same way. `be` carries the access mask for loads as well as stores (memory ignores it when `we = 0`), so the core takes `mem_rmask`/`mem_wmask` (§9) from it; `be = 0` when `valid = 0`. `addr` is passed through unchanged. The unused `mem_size` encoding 3 gives `be = 0`, `wdata = 0` and `load_data = 0`.

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
PC register plus the whole next-PC logic of §5.2, so that logic can be unit-tested on its own.

| Port | Dir | Description |
|---|---|---|
| `clk_i`, `rst_i` | in | Clock, sync active-high reset (`pc_q ← RESET_PC`) |
| `halted_i` | in | `halted_q` |
| `stop_i` | in | Any §10 stop condition this cycle (may include `misaligned_fetch_o`; no loop, since that output does not depend on `stop_i`) |
| `jump_i`, `jalr_i`, `branch_i` | in | `ctrl.jump`, `ctrl.jalr`, `ctrl.branch` |
| `br_taken_i` | in | `rv_branch_unit.taken_o` |
| `target_i` | in | `alu_res` |
| `pc_o` | out | Current PC (`pc_q`) |
| `pc_plus4_o` | out | `pc_q + 4` |
| `next_pc_o` | out | `next_pc` (§5.2); also the retire port's `pc_wdata` |
| `misaligned_fetch_o` | out | `misaligned_fetch` (§5.2) |

Parameter: `RESET_PC` (passed down from `rv_core`).

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
| `enable_i` | in | `~rst_i & ~halted_q & ~imem_rsp.err`. Must **not** depend on `dmem_rsp` or on any stop cause derived from it (that would be a combinational loop through the memory). Other stop causes need no gating here: illegal instructions already decode to `mem_read = mem_write = 0`, ECALL/EBREAK/jumps never access memory, and the LSU drops `valid` itself on misalignment. |
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
  } ctrl_t;   // 28 bits
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
| `insn`, `pc_rdata` | The instruction and its PC. `insn = 0` for a fetch error (the word is not trusted, §10) |
| `pc_wdata` | Next PC (equals `pc_rdata` for a stopping instruction) |
| `rs1_*`, `rs2_*` | Source registers read, with their values; both 0 for an operand the instruction does not read (as in RVFI: e.g. `rs2` of OP-IMM, both of LUI/JAL/FENCE/ECALL) |
| `rd_addr`, `rd_wdata` | Destination written; **both 0 when nothing is written** (including `rd = x0`) |
| `mem_addr` | Access address (word-aligned, as in RVFI) |
| `mem_rmask` / `mem_wmask` | Byte masks of the access; 0 if none. `mem_addr`, the masks and the data fields are all 0 for an instruction that stops the core (it has no memory effect, §10) |
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

- Every program has 8-byte symbols `tohost` and `fromhost` in section `.tohost`. They are defined **in assembly**, not in the linker script: by `RVTEST_DATA_BEGIN` (riscv-tests), `RVMODEL_DATA_BEGIN` (arch-test `model_test.h`), or `crt0.S` (C programs). `link.ld` only places the `.tohost` section; defining the symbols there as well would clash. Spike's HTIF uses the same symbols, so one ELF runs on both.
- A program ends by storing a word to `tohost`:
  - `1` → **pass** (exit code 0)
  - `(code << 1) | 1` → **fail** with `code` (for riscv-tests, `code` = failing test number)
- The harness gets the `tohost` address from `nm` via `+tohost=`. It ends the run in the cycle the store retires.
- For RISCOF, the harness also takes `+signature=<file> +sig_begin=<addr> +sig_end=<addr>` (addresses of `begin_signature`/`end_signature` from `nm`). At the end of the run it writes the words in `[sig_begin, sig_end)` to the file, one 32-bit word per line as 8 lower-case hex digits, which is the format RISCOF compares.

**Harness exit codes**

| Code | Meaning |
|---|---|
| 0 | `tohost == 1` |
| 1 | `tohost` written with a fail value |
| 2 | Timeout (`+max_cycles`, default 1,000,000) |
| 3 | Core stopped with an error cause (§10) |
| 4 | Core halted (ECALL/EBREAK) without writing `tohost` |
| 5 | Harness error (missing or malformed file, bad plusarg) |
| 6 | Simulation error: an RTL assertion, `$error`/`$stop`/`$fatal`, or a Verilator runtime error once the run has started |

Every directed test (§15.2) declares its expected exit code, and for a stop its cause, in a header comment, e.g. `// expect: 3 STOP_ILLEGAL`; `// console: <text>` adds the expected console output. The runner checks both. (`.S` files go through the C preprocessor, which rejects a line starting with `#` that is not a directive, so the tests use `//`; the runner accepts `#` as well.)

---

## 12. Software environment

| Item | Definition |
|---|---|
| ISA / ABI | `-march=rv32i -mabi=ilp32` |
| Compiler flags | `-O2 -nostdlib -nostartfiles -ffreestanding -static -mcmodel=medany` |
| Libraries | `libgcc` (software `mul`/`div`/`rem`), project stubs: `putchar`, minimal `printf`, `memcpy`, `memset` |
| Linker script `link.ld` | `.text.init` first at `0x8000_0000` (both test suites put their entry code there), then `.text`, `.rodata`, `.data`, `.bss`, `.tohost`; `_stack_top` = end of RAM, 16-byte aligned. Places `.tohost` but defines no `tohost`/`fromhost` symbols (§11). |
| `crt0.S` | In `.text.init`: zero `x1–x31`; set `sp = _stack_top`, `gp = __global_pointer$`; zero `.bss`; call `main`; store `(ret << 1) \| 1` to `tohost` (so `ret = 0` → pass); `ecall` as a fallback stop. Defines `tohost`/`fromhost` in `.tohost`. |
| RISCOF `model_test.h` | Start from `riscof-plugins/rv32/spike_simple/env/model_test.h` in the pinned arch-test. `RVMODEL_DATA_BEGIN` defines `tohost`/`fromhost` in `.tohost` and the `begin_signature` label; `RVMODEL_DATA_END` defines `end_signature`; `RVMODEL_HALT` stores `1` to `tohost` (the run ends there); `RVMODEL_BOOT` and the IO macros are empty. The entry label is `rvtest_entry_point`, in `.text.init`. Must **not** define `rvtest_mtrap_routine` (see below). |

**Custom riscv-tests env** (`sw/common/env/p/riscv_test.h`). The `rv32ui` tests include `riscv_test.h` and `isa/macros/scalar/test_macros.h`, and use exactly these macros:

| Macro | Required behaviour on this core |
|---|---|
| `RVTEST_RV32U` | Empty marker (the `rv32ui/*.S` wrappers redefine `RVTEST_RV64U` to it) |
| `RVTEST_CODE_BEGIN` | `.section .text.init`, `.globl _start`, `_start:`, then `INIT_XREG` (zero `x1–x31`). No CSR access, no trap vector. |
| `RVTEST_CODE_END` | `unimp`, as upstream. It is never reached because PASS and FAIL stop the test; if it is reached, the core stops with `STOP_ILLEGAL` and the test fails (exit 3), which is the right result. |
| `TESTNUM` | `gp` (as upstream) |
| `RVTEST_PASS` | `fence; li TESTNUM, 1; sw TESTNUM, tohost, t5; ecall` |
| `RVTEST_FAIL` | `fence; 1: beqz TESTNUM, 1b; sll TESTNUM, TESTNUM, 1; or TESTNUM, TESTNUM, 1; sw TESTNUM, tohost, t5; ecall`. `TEST_PASSFAIL` places FAIL directly before PASS, so FAIL must end the test and never fall through into PASS. |
| `RVTEST_DATA_BEGIN` | As upstream: defines `tohost`/`fromhost` (`.dword`, `.align 6`) in `.tohost`, then `begin_signature` |
| `RVTEST_DATA_END` | As upstream: `end_signature` |

**Arch-test trap handler:** in arch-test 3.10.0, `RVTEST_CODE_BEGIN`/`RVTEST_CODE_END` install and remove a CSR-based trap handler (`mtvec`, `mscratch`, …) only when `rvtest_mtrap_routine` is defined. None of the `rv32i_m/I` tests define it, so these tests run without CSRs, as long as our `model_test.h` doesn't define it either.

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

Verilator is a 2-state simulator, so X-propagation checks need a 4-state simulator. The cocotb unit tests run on Icarus Verilog (4-state) and assert that every checked output is free of X/Z, which covers this for each block. System-level X checks are in the `rv_core` unit test (M3.2): from time 0, through reset and while halted, `imem_req.valid`, `dmem_req.valid/we/be` and the whole retire port must be free of X/Z, and `dmem_req` must be X-free whenever it is valid.

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
- `always_ff @(posedge clk_i)` for flops, `always_comb` for logic. No `always @*`, no `always_latch`. The one exception: simulation-only assertion blocks under `` `ifndef SYNTHESIS `` use `always @(posedge clk_i)`, since they hold no state and simulators reject an assertion's implicit `$error` inside `always_ff`.
- Every `always_comb` assigns defaults at the top, so no latches can be inferred. Every `case` has a `default`.
- Non-blocking (`<=`) in `always_ff`, blocking (`=`) in `always_comb`. Never mixed.
- Explicit widths on all constants (`32'd4`, not `4`).
- Reset logic: `if (rst_i) ... else ...` inside `always_ff` (synchronous).
- No `initial`, `#delay`, `$display` or `$readmemh` in `rtl/`.
- `default_nettype none` at the top of every RTL file, `default_nettype wire` at the end.

### 14.4 Lint and formatting
- `verilator --lint-only -Wall` must report zero warnings. Waivers use `/* verilator lint_off <RULE> */` around the smallest possible region, with a comment saying why.
- Current waivers: `UNUSEDPARAM` around the constants in `rv_pkg.sv` (§8.1).
- Bits a module deliberately ignores (e.g. the opcode field in `rv_imm_gen`) are XOR-reduced into a signal whose name contains `unused` (`logic unused_opcode; assign unused_opcode = ^inst_i[6:0];`). Verilator exempts such names from `UNUSED` warnings, so no `lint_off` is needed and any *other* unused bit is still reported.
- `make lint` lints with `--top-module rv_core`, which instantiates every other block, so the connections between blocks are checked too. `make lint LINT_TOP=` lints each module as its own top instead, with `-Wno-MULTITOP` (which only silences the "several top-level modules" notice).
- Format with `verible-verilog-format` (if installed) using the repo's `.verible-format` settings; 2-space indent, 100-column lines.

### 14.5 Commits
- Subject line in the imperative, ≤ 72 characters, prefixed with the area: `rtl: add rv_alu`, `sw: add crt0`, `tb: lsu unit test`, `docs: ...`.
- `make lint unit` passes before every commit; `make regress` passes before a milestone is marked done.

---

## 15. Instruction coverage checklist

Each instruction must be covered by **all three** sources before Phase 1 is done (exec.md §7). Every upstream name below was checked in M1 against the pinned submodules (§0): riscv-tests sources are `tests/riscv-tests/isa/rv32ui/<name>.S`, arch-tests are `tests/riscv-arch-test/riscv-test-suite/rv32i_m/I/src/<name>.S`. If a submodule pin moves, re-check this table.

### 15.1 Per instruction

| Instr | Directed (`sw/asm/`) | riscv-tests (`rv32ui-p-`) | riscv-arch-test (`rv32i_m/I/`) | Covered |
|---|---|---|---|---|
| LUI | `t00_lui_addi` | `lui` | `lui-01` | [x] |
| AUIPC | `t07_auipc` | `auipc` | `auipc-01` | [x] |
| JAL | `t05_jal_jalr` | `jal` | `jal-01` | [x] |
| JALR | `t05_jal_jalr` | `jalr` | `jalr-01`, `misalign1-jalr-01` | [x] |
| BEQ | `t04_branch` | `beq` | `beq-01` | [x] |
| BNE | `t04_branch` | `bne` | `bne-01` | [x] |
| BLT | `t04_branch` | `blt` | `blt-01` | [x] |
| BGE | `t04_branch` | `bge` | `bge-01` | [x] |
| BLTU | `t04_branch` | `bltu` | `bltu-01` | [x] |
| BGEU | `t04_branch` | `bgeu` | `bgeu-01` | [x] |
| LB | `t03_load_store` | `lb` | `lb-align-01` | [x] |
| LH | `t03_load_store` | `lh` | `lh-align-01` | [x] |
| LW | `t03_load_store` | `lw` | `lw-align-01` | [x] |
| LBU | `t03_load_store` | `lbu` | `lbu-align-01` | [x] |
| LHU | `t03_load_store` | `lhu` | `lhu-align-01` | [x] |
| SB | `t03_load_store` | `sb` | `sb-align-01` | [x] |
| SH | `t03_load_store` | `sh` | `sh-align-01` | [x] |
| SW | `t03_load_store` | `sw` | `sw-align-01` | [x] |
| ADDI | `t00_lui_addi`, `t01_alu_imm` | `addi` | `addi-01` | [x] |
| SLTI | `t01_alu_imm` | `slti` | `slti-01` | [x] |
| SLTIU | `t01_alu_imm` | `sltiu` | `sltiu-01` | [x] |
| XORI | `t01_alu_imm` | `xori` | `xori-01` | [x] |
| ORI | `t01_alu_imm` | `ori` | `ori-01` | [x] |
| ANDI | `t01_alu_imm` | `andi` | `andi-01` | [x] |
| SLLI | `t01_alu_imm` | `slli` | `slli-01` | [x] |
| SRLI | `t01_alu_imm` | `srli` | `srli-01` | [x] |
| SRAI | `t01_alu_imm` | `srai` | `srai-01` | [x] |
| ADD | `t02_alu_reg` | `add` | `add-01` | [x] |
| SUB | `t02_alu_reg` | `sub` | `sub-01` | [x] |
| SLL | `t02_alu_reg` | `sll` | `sll-01` | [x] |
| SLT | `t02_alu_reg` | `slt` | `slt-01` | [x] |
| SLTU | `t02_alu_reg` | `sltu` | `sltu-01` | [x] |
| XOR | `t02_alu_reg` | `xor` | `xor-01` | [x] |
| SRL | `t02_alu_reg` | `srl` | `srl-01` | [x] |
| SRA | `t02_alu_reg` | `sra` | `sra-01` | [x] |
| OR | `t02_alu_reg` | `or` | `or-01` | [x] |
| AND | `t02_alu_reg` | `and` | `and-01` | [x] |
| FENCE | `t08_fence_nop` | — (`fence_i` is Zifencei, waived) | `fence-01` | [x] |
| ECALL | `t09_ecall_halt` | — (`rv32mi-scall` needs CSRs) | — (privilege suite needs CSRs) | [ ] |
| EBREAK | `t10_ebreak_halt` | — (`rv32mi-sbreak` needs CSRs) | — (privilege suite needs CSRs) | [ ] |

For ECALL and EBREAK, the directed tests plus random-test coverage of the halt path are the full coverage in Phase 1. Upstream coverage arrives with Zicsr in Phase 2. Ticked (2026-11-25, M5): every row whose listed sources all pass; FENCE has no riscv-tests source. ECALL/EBREAK wait for the random tests (M6).

Suite totals at the pinned versions:
- **riscv-tests `rv32ui`:** 42 tests, of which 40 run. The rows above, plus `simple`, `ld_st` and `st_ld`, which aren't tied to one instruction. `ld_st`/`st_ld` use only aligned accesses on RV32; their 64-bit parts are compiled out. Waived: `fence_i` (Zifencei) and `ma_data` (misaligned loads such as `lw` at offset 1, which this core treats as an error).
- **riscv-arch-test `rv32i_m/I`:** 39 tests, all run, all listed above.

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
| `t09_ecall_halt` | ECALL with no `tohost` write before it; a fail store after it must not execute | exit 4, `STOP_ECALL` |
| `t10_ebreak_halt` | Same with EBREAK | exit 4, `STOP_EBREAK` |
| `e01a`–`e01d` | All-zero word, a CSR instruction, a bad funct7, an `M`-extension op (one file each) | exit 3, `STOP_ILLEGAL` |
| `e02a`, `e02b` | `LW` at offset 2, `LH` at offset 1 | exit 3, `STOP_MISALIGNED_DATA` |
| `e03_misaligned_store` | `SW` at offset 1 | exit 3, `STOP_MISALIGNED_DATA` |
| `e04_misaligned_jump` | `JALR` to an address with bit 1 set; a not-taken branch to a misaligned target, and a `JALR` whose target has only bit 0 set, must **not** stop | exit 3, `STOP_MISALIGNED_FETCH` |
| `e05_bus_error` | Load from `0x0000_0000` | exit 3, `STOP_BUS_ERROR` |
| `e06_ifetch_error` | JALR to an address outside RAM | exit 3, `STOP_IFETCH_ERROR` |
| `t11_console` | Write a string to `CONSOLE` | pass; harness output matches the expected string |

Each error test (`e*`) contains exactly one stopping instruction, followed by a fail store to `tohost`, so a core that does not stop there fails the test (exit 1) instead of passing it. Variants of a case (e.g. `LW` vs. `LH`) are separate files named `e02a_`, `e02b_`, …. The macros are in `sw/asm/test.h`; `make asm` (`scripts/run_progs.py`) builds and runs them and also compares each retire log with the Python model.

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
