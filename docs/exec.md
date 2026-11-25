# RISC-V Core: Execution Plan

## Phases at a glance

| Phase | Goal | Status |
|---|---|---|
| **Phase 1** | A correct, fully verified **single-cycle RV32I core** in SystemVerilog, simulated with Verilator, plus the software, verification and measurement setup the rest of the project will build on. | **Planned (this document)** |
| **Phase 2** | Microarchitecture work: pipelining, memory system, ISA extensions, target platform. | **Deferred.** We make the architectural choices when Phase 1 is done, using the data Phase 1 collects (see §9). |

The architecture and system design for Phase 1 (memory map, datapath, module interfaces, control signals, test protocol, coverage checklist) are specified in [spec.md](spec.md).

Phase 1 aims for **correctness and infrastructure, not performance**. Every Phase 1 design choice is kept simple and easy to replace, so it doesn't commit us to anything in Phase 2.

---

## 1. Phase 1 scope

### In scope
- RV32I base integer ISA (unprivileged spec): all computational, control-transfer and load/store instructions, plus `FENCE`, `ECALL` and `EBREAK`.
- Single-cycle microarchitecture: one instruction retires every clock (CPI = 1).
- A simulation-only memory model and a small simulation SoC (memory + MMIO for test pass/fail and console output).
- Verilator-based simulation harness, unit tests, ISA compliance tests, lockstep comparison against Spike, and random instruction tests.
- A bare-metal software flow (toolchain, linker script, startup code) able to run assembly tests and C programs.
- Synthesis characterization (area and critical path) and instruction-mix profiling, as inputs for Phase 2.

### Out of scope (deferred to Phase 2 or later)
- Pipelining, hazards, forwarding, branch prediction
- Caches, TCMs, bus protocols (AXI/Wishbone/OBI), real FPGA memories
- Extensions: M, C, A, F/D, Zicsr, Zifencei, B
- Privileged architecture: CSRs, traps, interrupts, privilege modes
- FPGA bring-up on real hardware, ASIC flow

### Phase 1 simplifications (documented on purpose, removed in Phase 2)
| Situation | Phase 1 behaviour | Why |
|---|---|---|
| `ECALL` / `EBREAK` | Raise a `halt` signal; the testbench stops the simulation | No trap machinery without Zicsr/privileged spec |
| `FENCE` (incl. `FENCE.TSO`, `PAUSE`) | Executed as a NOP | Single hart, in-order, no caches: nothing to order |
| Illegal/unsupported instruction | Core stops with `STOP_ILLEGAL`; the testbench fails the test | No trap handler yet |
| Misaligned load/store address | Core stops with `STOP_MISALIGNED_DATA`; the testbench fails the test | The spec lets the execution environment trap; we treat it as an error for now |
| Misaligned jump/branch target (bit 1 set) | Core stops with `STOP_MISALIGNED_FETCH`; the testbench fails the test | Would be an instruction-address-misaligned exception |

The full stop-condition rules are in [spec.md §10](spec.md).

---

## 2. Toolchain and environment

The host is Windows 10, and the project runs **natively on Windows, without WSL**: commands run in Git Bash, using Windows builds of each tool. Install steps are in the [README](../README.md#setup).

| Tool | Purpose | Notes |
|---|---|---|
| Git for Windows / Git Bash | Version control, shell for scripts and make | Installed |
| GNU make (ezwinports) | Build driver | |
| Verilator ≥ 5.x (MSYS2 UCRT64) | RTL simulation + lint | `verilator --lint-only -Wall` must be clean |
| xPack RISC-V GCC (`riscv-none-elf-*`) | Assemble/compile tests | Build with `-march=rv32i -mabi=ilp32`; the Makefile also accepts other prefixes |
| Spike (riscv-isa-sim) | Golden reference model | **No native Windows build.** Replacement is an open decision (§8) |
| Python 3.10+ | Scripts, trace compare, random test generator | Use a venv |
| cocotb + Icarus Verilog | Unit tests of individual RTL blocks | cocotb 2.1 on Icarus 13; cocotb has no Verilator plugin on Windows. Icarus is 4-state, so unit tests also catch X/Z |
| RISCOF + Sail or Spike plugin | Architectural compliance (riscv-arch-test) | |
| Yosys (+ nextpnr / OpenSTA) | Synthesis characterization | Area + critical path estimate |
| GTKWave or Surfer | Waveform viewing | |
| Verible (optional) | SystemVerilog format/lint | |

---

## 3. Repository layout

```
Risc-V/
├── Makefile                 # top-level: lint, unit, sim, regress, syn
├── docs/
│   ├── exec.md              # this plan
│   ├── spec.md              # Phase 1 architecture + system design, conventions, coverage checklist
│   └── phase1-report.md     # closeout report + Phase 2 decision inputs (written in M9)
├── rtl/
│   ├── rv_pkg.sv            # opcodes, funct codes, enums, control struct
│   ├── rv_core.sv           # single-cycle core top
│   ├── rv_pc.sv             # PC register + next-PC selection
│   ├── rv_decoder.sv        # instruction -> control struct
│   ├── rv_imm_gen.sv        # I/S/B/U/J immediates
│   ├── rv_regfile.sv        # 32x32, 2R1W, x0 hardwired to 0
│   ├── rv_alu.sv            # arithmetic/logic/shift/compare
│   ├── rv_branch_unit.sv    # branch condition evaluation
│   └── rv_lsu.sv            # byte enables, store data alignment, load sign/zero-extend
├── sim/
│   ├── rv_mem_model.sv      # dual-port sim memory, $readmemh loadable
│   ├── rv_soc_sim.sv        # core + memory + MMIO (tohost, console)
│   └── tb_top.cpp           # Verilator C++ harness
├── tb/unit/                 # cocotb tests per block
├── sw/
│   ├── common/              # link.ld, crt0.S, env/ (custom riscv-tests env)
│   ├── asm/                 # hand-written directed tests
│   └── c/                   # hello, dhrystone, coremark, embench subset
├── tests/
│   ├── riscv-tests/         # git submodule
│   ├── riscv-arch-test/     # git submodule
│   └── riscof/              # RISCOF config + DUT plugin
├── scripts/                 # elf2hex, trace_compare.py, randgen.py, stats.py
└── syn/                     # Yosys scripts + reports
```

---

## 4. Phase 1 design decisions (locked)

These choices hold only for Phase 1. Each one leaves the related Phase 2 choice open.

| Area | Decision | How it keeps Phase 2 open |
|---|---|---|
| Reset | Synchronous, active-high `rst` | Simple and FPGA-friendly; easy to change in one place |
| Reset vector | Parameter `RESET_PC`, default `0x8000_0000` | Same as the Spike / riscv-tests default, so traces line up |
| Memory | One unified **dual-port** sim memory: port A = instruction fetch (read-only), port B = data (read/write with byte enables). Reads are combinational, writes happen on the clock edge. Size is a parameter (default 64 KiB). | The core only sees two **request/response ports** defined in `rv_pkg`. Phase 2 can put caches, a bus or BRAMs behind them without touching the core datapath. |
| Control signals | The decoder outputs one `ctrl_t` packed struct | A struct is easy to pass through pipeline registers later |
| Register file | Write on clock edge, combinational read, x0 forced to 0 | Documented so Phase 2 can choose write-first vs. bypass |
| Retire trace port | Every retired instruction drives an RVFI-style bundle: `valid, pc, insn, rd, rd_wdata, mem_addr, mem_wmask, mem_wdata, mem_rdata, next_pc` | Drives Spike lockstep now. Lets us adopt riscv-formal later. Stays valid unchanged once the core is pipelined. |
| MMIO | `tohost` (ELF symbol, also understood by Spike) for pass/fail; `CONSOLE` at a fixed address for byte output | Memory map stays in one package file |
| Coding style | `always_ff` / `always_comb` only, no latches, no `initial` in RTL (only in sim/), lint-clean with `-Wall`, every waiver commented | Code is synthesizable and portable from day one |

---

## 5. Milestones and tasks

Effort: **S** = hours, **M** = 1–3 days, **L** = 3+ days. Order follows the dependencies; M2 and M4 can overlap.

### M0: Environment and repository setup (S–M)
- [ ] **M0.1** Install the native Windows tools (README Setup): make, MSYS2 packages (Verilator, C++ compiler, Yosys, Icarus, GTKWave), xPack RISC-V GCC, Python venv with cocotb and RISCOF.
- [ ] **M0.2** Write `scripts/check_env.sh` to print each tool's version and fail if a tool is missing.
- [ ] **M0.3** `git init`, add `.gitignore` (build/, obj_dir/, *.vcd, *.fst, venv/), and create the directory skeleton from §3.
- [ ] **M0.4** Add `riscv-tests` and `riscv-arch-test` as git submodules.
- [ ] **M0.5** Top-level `Makefile` with empty targets: `lint`, `unit`, `sim`, `regress`, `syn`, `clean`.

**Exit criteria:** `check_env.sh` passes; `make lint` runs on an empty RTL file list without errors.

### M1: Specification (S–M)
All four items are drafted in [spec.md](spec.md); this milestone is reviewing them and turning §8 into code. Review results and the changes they caused are recorded in spec.md §0.
- [x] **M1.1** Review the single-cycle datapath block diagram, next-PC mux, writeback mux and control signal table (spec.md §5–§7).
- [x] **M1.2** Write `rtl/rv_pkg.sv` from spec.md §8: opcodes, `alu_op_t`, `imm_type_t`, `wb_sel_t`, `ctrl_t`, memory request/response structs, retire/status types, memory map constants.
- [x] **M1.3** Review the coding and naming conventions (spec.md §14).
- [x] **M1.4** Review the instruction coverage checklist (spec.md §15) and confirm the upstream test names against the submodule checkouts from M0.4.

**Exit criteria:** spec.md reviewed and marked approved; `rv_pkg.sv` compiles and passes lint.

**Status: done (2026-11-25).** spec.md rev 1.1 approved; `rtl/rv_pkg.sv` is in `rtl/rtl.f` and `make lint` is clean.

### M2: Datapath blocks and unit tests (M–L)
Each block gets a cocotb test in `tb/unit/test_<block>.py`, with randomized checks against a Python reference (`tb/unit/rv_model.py`) where that makes sense. Tests run on Icarus Verilog through `tb/unit/run_unit.py` (`make unit`); Verilator stays the lint tool. Each test suite is checked by injecting a bug and confirming it fails.

- [x] **M2.1** `rv_alu`: ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND. Test shift amounts 0/31, signed edge cases (`0x8000_0000`, `-1`), random vectors vs. Python.
- [x] **M2.2** `rv_imm_gen`: I/S/B/U/J formats. Check sign extension and bit scrambling for B/J with random instruction words.
- [x] **M2.3** `rv_regfile`: x0 stays 0 after writes, read-after-write timing, all 31 registers written and read back.
- [x] **M2.4** `rv_branch_unit`: BEQ/BNE/BLT/BGE/BLTU/BGEU, signed vs. unsigned edge cases.
- [x] **M2.5** `rv_lsu`: LB/LH/LW/LBU/LHU sign/zero extension at every byte offset; SB/SH/SW byte enables and data lane placement; misalignment detection.
- [x] **M2.6** `rv_decoder`: every legal RV32I encoding maps to the expected `ctrl_t`; every case in spec.md §4.2 sets `ctrl.illegal`. Generate the expected values from the control signal table (spec.md §7) so the spec and the test agree.

**Exit criteria:** `make unit` passes; every block is lint-clean.

### M3: Core integration (M)
- [x] **M3.1** `rv_pc`: PC register, next-PC = PC+4 / branch target / JAL target / JALR target (`& ~1`), misaligned-target detection.
- [x] **M3.2** `rv_core`: connect fetch → decode → regfile read → ALU/branch → LSU → writeback. Drive the retire trace port and the `halt` / error flags.
- [x] **M3.3** `rv_mem_model` + `rv_soc_sim`: dual-port memory with `$readmemh`, `tohost` and console MMIO decode.
- [ ] **M3.4** `tb_top.cpp`: load hex, apply reset, run until `halt`, `tohost` write, error flag or cycle timeout. Optional FST waves (`+waves`). Print the console stream. Write the retire log (spec.md §9.2) and return the exit codes from spec.md §11.
- [ ] **M3.5** Bring-up with the directed tests in `sw/asm/` (list in spec.md §15.2): `lui`/`addi` sequence → arithmetic → loads/stores → branches/loops → `jal`/`jalr` function call, then the `e*` error tests. Each test checks register values and reports pass/fail through `tohost`.

**Exit criteria:** every `sw/asm/` test passes; the retire log is produced; lint is clean.

### M4: Software infrastructure (M)
- [ ] **M4.1** `sw/common/link.ld`: `.text` at `0x8000_0000`, `.data`/`.bss`, stack at the top of memory, a `tohost` symbol in its own section.
- [ ] **M4.2** `sw/common/crt0.S`: zero the registers, set `sp` and `gp`, zero `.bss`, call `main`, write `(ret << 1) | 1` to `tohost` (spec.md §12).
- [ ] **M4.3** Minimal libc stubs: `putchar` → CONSOLE MMIO, a small `printf`, and `memcpy`/`memset`. Link `libgcc` for software multiply/divide.
- [ ] **M4.4** `scripts/elf2hex`: ELF → `$readmemh` image (via `objcopy -O verilog` or a small Python script). The Makefile also extracts the `tohost` address with `nm` and passes it to the harness as a plusarg.
- [ ] **M4.5** Generic build rules: `make sim PROG=sw/c/hello` builds, converts and runs.

**Exit criteria:** `hello.c` prints "Hello, RISC-V" through the console MMIO and exits with code 0.

### M5: ISA compliance (M–L)
- [ ] **M5.1** **riscv-tests (`rv32ui-p-*`)**: the stock `p` environment uses CSRs (`mtvec`, `mhartid`, …), which we don't have. Write a **custom env** in `sw/common/env/` with a minimal `riscv_test.h`: `RVTEST_CODE_BEGIN` just sets up registers, `RVTEST_PASS`/`RVTEST_FAIL` write `1` / `(TESTNUM<<1)|1` to `tohost`.
- [ ] **M5.2** Run all `rv32ui` tests. **Expected exclusions:** `fence_i` (Zifencei, not in Phase 1) and `ma_data` (misaligned data, which we treat as an error). Record the exclusions in a waiver file with the reason.
- [ ] **M5.3** **riscv-arch-test via RISCOF**: write the DUT plugin (compile with our env, run Verilator, dump the memory region between `begin_signature` and `end_signature`). Write `model_test.h` (`RVMODEL_HALT` → `tohost`, `RVMODEL_DATA_BEGIN/END`). Use Sail or Spike as the reference.
- [ ] **M5.4** Run the `rv32i_m/I` suite and get it to 100 % pass.

**Exit criteria:** every non-waived `rv32ui-p-*` test passes; RISCOF `rv32i_m/I` reports all tests passing.

### M6: Lockstep comparison and random testing (M–L)
- [ ] **M6.1** `scripts/trace_compare.py`: parse Spike's `--log-commits` output, drop bootrom instructions (PC below `0x8000_0000`), normalize to the retire-log format, and compare instruction by instruction (pc, insn, rd, rd_wdata, memory writes). Report the first mismatch with context.
- [ ] **M6.2** Run lockstep comparison on every M3/M5 test and every C program.
- [ ] **M6.3** `scripts/randgen.py`: constrained-random RV32I program generator. Random register values; all ALU ops; loads/stores within a safe aligned data window; forward-only or bounded-loop branches; `jal`/`jalr` to known labels. Seeds are reproducible.
- [ ] **M6.4** Nightly/batch run: N random programs (start with 1,000 seeds) through RTL + Spike + compare. Any failing seed becomes a regression test.
- [ ] **M6.5** *(Optional)* evaluate riscv-dv's Python generator (`pygen`) as a second, independent random source.
- [ ] **M6.6** *(Stretch)* bind the retire port to riscv-formal and run its RV32I instruction checks.

**Exit criteria:** zero trace mismatches across all directed tests and ≥ 1,000 random seeds.

### M7: Programs, benchmarks and profiling (M)
- [ ] **M7.1** Port and run: Dhrystone, CoreMark (rv32i build, multiply/divide in libgcc), and a small Embench subset. All must pass lockstep comparison.
- [ ] **M7.2** `scripts/stats.py` on retire logs, per benchmark:
  - instruction mix by class (ALU, load, store, branch, jump, upper-immediate)
  - percentage of branches taken / not taken, forward vs. backward
  - **load-use pairs** (a load followed directly by an instruction that reads its `rd`)
  - **back-to-back RAW dependencies** at distance 1, 2 and 3
  - share of time in `libgcc` multiply/divide routines
  - code size (`.text`) and data footprint
- [ ] **M7.3** Record the cycle counts (= instruction counts at CPI 1) as the performance baseline.

**Exit criteria:** all benchmarks run correctly; the stats table is in `phase1-report.md`.

### M8: Synthesis characterization (S–M)
- [ ] **M8.1** Yosys synthesis of `rv_core` alone, with memories outside the core as top-level ports, for one FPGA family (e.g. Lattice ECP5 via nextpnr, or Xilinx 7-series via Vivado if available).
- [ ] **M8.2** Report LUTs, FFs, Fmax and the **critical path broken down by stage** (fetch → decode → regfile → ALU → memory → writeback).
- [ ] **M8.3** Note the **memory finding**: FPGA block RAMs have synchronous reads, which a single-cycle core with combinational reads can't use directly. Record what this means for Phase 2.

**Exit criteria:** synthesis runs from `make syn`; the report is in `syn/reports/` and summarized in `phase1-report.md`.

### M9: Phase 1 closeout (S)
- [ ] **M9.1** `make regress` runs, in one command: lint, unit tests, directed asm, `rv32ui`, RISCOF, lockstep on all programs, and a fixed set of random seeds.
- [ ] **M9.2** Write `docs/phase1-report.md`: what was built, test results, waivers, bugs found (count and kind), synthesis numbers, benchmark stats, and the Phase 2 decision inputs table (§9) filled in with real data.
- [ ] **M9.3** Tag the repo `phase1-done`.
- [ ] **M9.4** Phase 2 architecture review meeting: go through §9 and decide.

---

## 6. Verification strategy summary

| Layer | Tool | What it catches |
|---|---|---|
| Lint | Verilator `-Wall` | Width mismatches, latches, unused/undriven signals |
| Unit | cocotb on Icarus | Block-level functional bugs, edge cases, X/Z on outputs |
| Directed | Hand-written asm | Bring-up, basic integration |
| Compliance | riscv-tests, riscv-arch-test (RISCOF) | Spec conformance per instruction |
| Lockstep | Spike commit-log comparison | Any architectural-state divergence, found at the first wrong instruction |
| Random | `randgen.py` (+ riscv-dv optional) | Corner cases and instruction combinations nobody wrote a test for |
| Real programs | C benchmarks | Toolchain/ABI integration, long-running behaviour |
| Formal (stretch) | riscv-formal | Proof-level checks per instruction |

**Bug tracking:** log every RTL bug found, with the layer that found it. That record helps decide how much verification investment Phase 2 needs.

---

## 7. Phase 1 definition of done

- [ ] Every RV32I instruction is implemented and ticked in the coverage checklist (spec.md §15.1).
- [ ] `rv32ui-p-*` pass, except documented waivers (`fence_i`, `ma_data`).
- [ ] RISCOF `rv32i_m/I` passes 100 %.
- [ ] Zero lockstep mismatches against Spike on all directed tests, benchmarks and ≥ 1,000 random seeds.
- [ ] `hello.c`, Dhrystone and CoreMark run correctly.
- [ ] Verilator lint is clean with `-Wall`.
- [ ] `make regress` passes from a clean checkout.
- [ ] Synthesis numbers and benchmark statistics are recorded.
- [ ] `docs/spec.md` matches the final RTL, and `docs/phase1-report.md` is complete.

---

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Toolchain friction on native Windows (Verilator needs a C++ compiler and make; mixing Git Bash with MSYS2) | Lost days on setup | `check_env.sh` reports every tool; only `C:\msys64\ucrt64\bin` goes on `PATH`; pin tool versions in the README |
| **Spike has no native Windows build** | No reference model for lockstep (M6) or for RISCOF signatures (M5.3) | **Open decision, needed before M5.3.** Options: (a) write a small Python RV32I reference model and use it for both; (b) use Sail's prebuilt model if a Windows build is available; (c) run Spike only in CI on a Linux runner |
| riscv-tests' stock env needs CSRs | Tests won't run | Custom minimal env (M5.1) |
| Spike trace format quirks (bootrom, x0 writes, version differences) | False mismatches | Normalize in `trace_compare.py`; pin the Spike version |
| cocotb / simulator incompatibility | Unit tests break | Resolved for M2: unit tests run on Icarus, which cocotb supports on Windows; versions pinned in setup_require.txt |
| Single-cycle combinational memory can't map to FPGA BRAM | Misleading synthesis numbers | Synthesize the core alone, memory as ports (M8.1); record as a Phase 2 input |
| Scope creep (adding M/Zicsr/pipelining early) | Phase 1 never finishes | Anything outside §1 goes into a "Phase 2 backlog" list, not into the RTL |

---

## 9. Phase 2 decision inputs

Phase 1 doesn't decide any of these. It produces the data for each decision, which we review at M9.4.

| Phase 2 decision | Options to consider | Phase 1 data that informs it |
|---|---|---|
| Pipeline depth and style | 2-, 3-, 5-stage, or deeper | Critical path breakdown by stage (M8.2) |
| Hazard handling | Forwarding paths, stall-only, scoreboard | RAW dependency distances, load-use frequency (M7.2) |
| Branch handling | Static not-taken, BTFN, BHT/BTB | Branch frequency, taken %, forward/backward split (M7.2) |
| Memory interface / bus | Custom, OBI, AXI4-Lite, Wishbone | Target platform; BRAM synchronous-read finding (M8.3) |
| Memory hierarchy | TCM vs. I/D caches, sizes | Code and data footprint of benchmarks (M7.2) |
| ISA extensions and order | M, Zicsr + traps, C, Zifencei, privileged spec, interrupts | Time share in `libgcc` mul/div; code size (C ext.); need for interrupts/OS |
| Target platform | Specific FPGA board, ASIC flow | Area/Fmax results (M8.2) |
| Verification scaling | riscv-formal, riscv-dv, coverage | Bug log: which layers caught which bugs (§6) |

---

## 10. Phase 2 backlog (parking lot)

Ideas that come up during Phase 1 go here instead of into the RTL.

- *(empty)*
