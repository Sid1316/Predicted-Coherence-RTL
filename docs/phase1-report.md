# RISC-V Core: Phase 1 Report

Status: **complete for review** (2026-11-25), apart from the open items in the last section. Phase 1 goal (exec.md): a correct, fully verified single-cycle RV32I core in SystemVerilog, simulated with Verilator, plus the software, verification and measurement setup Phase 2 builds on.

## Summary

- **The core:** single-cycle RV32I, CPI 1, 923 lines of SystemVerilog in `rtl/`. All 40 RV32I instructions are implemented. ECALL/EBREAK halt the core, and every error case (illegal, misaligned, bus error, fetch error) stops it with a cause (spec §10).
- **Verified by:**
  - unit tests on every block;
  - 22 directed assembly tests;
  - 40 of 42 riscv-tests `rv32ui`, with 2 documented waivers;
  - 39 of 39 riscv-arch-test `rv32i_m/I` through RISCOF;
  - 1,000 random programs;
  - Dhrystone, CoreMark and five Embench programs.

  Every program's full trace is compared with the reference model, instruction by instruction.
- **Performance:** 1.03 DMIPS/MHz, 1.39 CoreMark/MHz. On ECP5: about 2,200 slices for the core logic, 41 MHz for the core alone, 30 MHz for the whole single-cycle loop with LUT-RAM memories.
- **Reference model:** the project's own Python RV32I model, not Spike (exec.md §8 decision). An independent Spike check in CI is the main open item.

## What was built

| Part | Where | Notes |
|---|---|---|
| RTL | `rtl/` (9 files) | `rv_pkg`, `rv_pc`, `rv_decoder`, `rv_imm_gen`, `rv_regfile`, `rv_alu`, `rv_branch_unit`, `rv_lsu`, `rv_core`; Verilator `-Wall` clean |
| Simulation SoC | `sim/` | `rv_mem_model` (64 KiB, two combinational ports), `rv_soc_sim` (CONSOLE and CYCLE MMIO, tohost watcher, retire log), `tb_top.cpp` (Verilator harness: exit codes, waves, signature dump) |
| Software | `sw/` | `link.ld`, `crt0.S`, rvlib (printf, mem*/str*, `rv_cycles`), directed tests (`sw/asm/`), C programs (`sw/c/`), benchmark ports (`sw/bench/`) |
| Reference model | `tb/unit/rv_model.py`, `tb/sim/harness_model.py` | RV32I + the SoC's memory map, stepped like the harness |
| Test flows | `scripts/`, `tests/` | `run_progs.py` (asm, C, rv32ui, benchmarks), `run_riscof.py` + plugins, `randgen.py` + `run_random.py`, `trace_compare.py`, `stats.py`, `syn.py` |
| One command | `make regress` | lint, unit, harness tests, programs, rv32ui, RISCOF, 200 random seeds, benchmarks (about 12 minutes) |

## Verification results

| Layer | Tool | Result |
|---|---|---|
| Lint | Verilator `-Wall` | clean: `rtl/`, and with `rv_soc_sim` and the `syn/` harnesses as top |
| Unit | cocotb on Icarus (4-state, X/Z checked) | 92 tests in 10 blocks, each block checked against the Python model; each suite shown to catch injected bugs |
| Harness | `tb/sim/test_tb_top.py` | 290 checks: every SoC scenario vs. the model, exit codes, bad inputs, waves, random reset, signatures |
| Directed | `make asm` | 22/22: 12 pass tests, 10 error tests (one stopping instruction each) |
| C programs | `make c` | 4/4 (hello, libc_test, ret_code, exit_nested) |
| riscv-tests | `make riscv-tests` | 40/42 pass; `fence_i` and `ma_data` waived, and each fails exactly as its waiver says |
| Compliance | `make riscof` | 39/39 `rv32i_m/I`: signatures match, harness exit 0, and every trace matches the model |
| Random | `make random` | seeds 1–1000: zero mismatches, 547k instructions, all 40 instructions and all 7 stop causes covered (`make regress` runs seeds 1–200) |
| Benchmarks | `make bench` | 7/7: Dhrystone, CoreMark, 5 Embench, each passing its own check and matching the model trace (up to 6.4M instructions) |
| Coverage | spec §15.1 | all 40 instructions ticked (directed, riscv-tests and arch-test sources; ECALL/EBREAK through directed and random) |

Every run above also compares the RTL with the reference model at each retired instruction: pc, instruction, destination register and value, and stored bytes.

## Waivers and deviations

| Item | Decision | Where |
|---|---|---|
| `rv32ui-p-fence_i` | Waived: Zifencei is not in Phase 1; FENCE.I stops with STOP_ILLEGAL | `tests/riscv-tests-waivers.txt` |
| `rv32ui-p-ma_data` | Waived: misaligned accesses stop the core in Phase 1 | same |
| Reference model | Python model instead of Spike (no Windows build); Spike in CI later | exec.md §8 |
| `t09`/`t10` | Expect exit 4 (halt without tohost), because a tohost write ends the run before ECALL | spec R-11 |
| Exit code 6 | Added for an assertion or `$fatal` in the RTL | spec R-10 |
| CYCLE MMIO | Sim-only cycle counter at `0x1000_0008` for benchmark timing; programs that read it cannot be compared with Spike | spec R-13 |
| Arch-test build | 2 MiB RAM and `-mno-relax` for RISCOF only | spec R-12 |
| Embench subset | `edn` and `matmult-int` left out (too long to replay on the model), `slre` too (needs libc ctype) | M7 below |

## Bug log

Count of real defects (not injected ones), by the layer that found them (exec.md §6):

| Layer | RTL bugs | Other defects found |
|---|---:|---|
| Spec review (M1) | 1: a combinational loop (`rv_lsu.enable_i` depended on the data response), fixed in the spec before any RTL (R-1) | 6 spec gaps (R-2 to R-7) |
| Unit tests vs. model (M2–M3.2) | 1: the retire port showed `rs1 = 0` for branches (branches read rs1 outside the operand mux) | |
| Integration (M3.3–M3.5) | 0 | Icarus 13 zero-time hang on an `always_comb` struct write in `rv_soc_sim` (worked around); harness defects: `sc_time_stamp` recursion, CR LF in console output, `$readmemh` silently accepting `ZZZZ` (now rejected); 2 spec gaps (R-10, R-11) |
| riscv-tests, RISCOF (M5) | 0 | arch-test `LA()` macro emits compressed `c.nop` padding under relaxation (build fixed with `-mno-relax`); arch tests need 2 MiB RAM (R-12) |
| Random (M6) | 0 | |
| Benchmarks (M7) | 0 | no CSR timer on the core: added the CYCLE MMIO counter (R-13) |

Both RTL bugs were found before integration. After M3.2, no layer found an RTL bug: every integration test, upstream suite, random seed and benchmark matched the model on its first run. The test layers still have teeth: at every level, injected RTL bugs were caught. Unit suites caught every injected bug apart from equivalent ones. At system level, 5 of 6 RTL mutations were caught by the directed tests; the sixth, an x0 write, is invisible because reads of x0 return 0. An SLTU bug, which breaks libgcc's software division, was caught by `libc_test`, an SRA bug by RISCOF (`sra-01`, `srai-01`), and a BGE bug by 4 of the first 6 random seeds.

## M7: Benchmarks, baseline and profile

### Setup

| Item | Value |
|---|---|
| Core | Single-cycle RV32I, CPI = 1 (cycles = instructions retired) |
| Compiler | xPack GCC 15.2.0, `-O2 -march=rv32i -mabi=ilp32`; multiply and divide in software (libgcc) |
| Simulator | Verilator 5.054, `rv_soc_sim` with 64 KiB RAM (spec §2.3) |
| Timing | The sim-only `CYCLE` counter (spec §2.3, R-13), read by each benchmark's own timer hooks. Scores per MHz assume one tick per cycle (a notional 1 MHz clock). |
| Correctness | Each benchmark passes its own result check, and its full trace matches the Python reference model instruction by instruction (`make bench`, exec.md §8). |
| Reproduce | `make bench` (runs the benchmarks, then `scripts/stats.py --bench`) |

Benchmarks:

| Benchmark | Source | Result check |
|---|---|---|
| Dhrystone 2.2 | riscv-tests `benchmarks/dhrystone` (`tests/riscv-tests` @ `1b3f8bd`), 500 runs | Final global values against the values Dhrystone prints as "should be" (`sw/bench/dhrystone/port.c`) |
| CoreMark 1.01 | `sw/bench/third_party/coremark` @ `v1.01`, 2K performance run, 1 iteration | CoreMark's own list/matrix/state CRCs (seedcrc `0xe9f5`). It also prints its 10-second reporting-rule error, which a simulation cannot meet. |
| Embench 1.0: crc32, huffbench, nettle-sha256, statemate, ud | `sw/bench/third_party/embench-iot` @ `embench-1.0`, `CPU_MHZ = 1` | Embench's `verify_benchmark()` |

Embench subset: integer-only benchmarks that fit in 64 KiB and need no libc beyond rvlib. Left out: `edn` and `matmult-int`, which run more than 30 million cycles here with software multiply, too long to replay on the reference model. CoreMark covers the multiply-heavy case. `slre` needs `ctype` and `strchr`. The others need floating point or a larger libc.

### M7.3 Performance baseline

| Benchmark | Measured region | Cycles | Score |
|---|---|---:|---|
| Dhrystone | one run through the loop | 554 | 1,805 Dhrystones/s per MHz = **1.03 DMIPS/MHz** |
| CoreMark | one iteration (timed portion) | 721,372 | **1.39 CoreMark/MHz** |
| Embench crc32 | `benchmark()` | 6,094,377 | |
| Embench huffbench | `benchmark()` | 2,383,026 | |
| Embench nettle-sha256 | `benchmark()` | 4,219,467 | |
| Embench statemate | `benchmark()` | 1,720,505 | |
| Embench ud | `benchmark()` | 6,358,411 | |

Whole-program cycle counts (startup and printing included) are the first row of the table below. At CPI 1 a faster core in Phase 2 changes these numbers through CPI and clock rate, and an M extension changes them through the instruction count.

### M7.2 Instruction profile

Whole program, every retired instruction; from `scripts/stats.py --bench --markdown`. Load-use pairs: a load directly followed by a reader of its destination. RAW distance d: instructions whose nearest producer of a source register retired d instructions earlier.

| Metric | coremark | dhrystone | embench-crc32 | embench-huffbench | embench-nettle-sha256 | embench-statemate | embench-ud |
|---|---:|---:|---:|---:|---:|---:|---:|
| Instructions (= cycles) | 764,679 | 299,858 | 6,136,113 | 2,616,963 | 4,234,188 | 1,727,508 | 6,370,968 |
| ALU % | 58.6 | 38.7 | 74.3 | 46.8 | 83.5 | 10.5 | 59.2 |
| load % | 7.8 | 20.9 | 5.7 | 16.7 | 8.6 | 18.3 | 7.9 |
| store % | 2.4 | 15.0 | 2.9 | 10.8 | 4.4 | 34.9 | 3.5 |
| branch % | 27.2 | 18.0 | 2.9 | 24.6 | 3.2 | 12.7 | 22.3 |
| jump % | 3.8 | 7.0 | 5.7 | 1.1 | 0.3 | 1.8 | 6.5 |
| upper-imm % | 0.3 | 0.4 | 8.6 | 0.0 | 0.1 | 21.6 | 0.6 |
| other % | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| branches taken % | 61.8 | 58.5 | 99.5 | 63.9 | 91.7 | 84.4 | 48.7 |
| backward branches % | 49.2 | 55.9 | 99.4 | 57.7 | 94.7 | 63.8 | 48.3 |
| backward taken % | 87.6 | 90.7 | 99.8 | 92.4 | 95.0 | 97.1 | 62.2 |
| forward taken % | 36.8 | 17.7 | 34.1 | 25.1 | 31.6 | 62.1 | 36.1 |
| load-use pairs % | 2.9 | 4.5 | 0.0 | 4.7 | 0.4 | 2.4 | 0.3 |
| load-use % of loads | 36.7 | 21.3 | 0.0 | 28.2 | 4.7 | 13.0 | 3.3 |
| RAW dist 1 % | 18.7 | 20.1 | 65.6 | 20.1 | 24.2 | 31.4 | 11.4 |
| RAW dist 2 % | 16.5 | 12.4 | 8.6 | 8.4 | 13.7 | 7.7 | 11.9 |
| RAW dist 3 % | 13.8 | 4.9 | 5.7 | 24.3 | 11.6 | 8.3 | 11.4 |
| in libgcc mul/div % | 59.3 | 6.8 | 0.1 | 0.2 | 0.1 | 0.3 | 47.2 |
| code (.text) bytes | 19,072 | 10,660 | 8,740 | 10,288 | 15,280 | 14,224 | 13,236 |
| data bytes | 2,688 | 12,588 | 1,868 | 10,036 | 1,288 | 1,092 | 2,692 |
| stack bytes | 2,496 | 624 | 352 | 7,824 | 384 | 352 | 576 |

### Observations (inputs for exec.md §9, not decisions)

- **Multiply/divide in software dominates two of the seven.** CoreMark spends 59% of its instructions in libgcc's `__mulsi3` and friends, and Embench `ud` 47% in division. Dhrystone spends 7%, and the other Embench programs under 1%. This is the main data point for adding the M extension.
- **Load-use pairs** (a load followed right away by a reader of its result) are 0–4.7% of instructions, and up to 37% of loads (CoreMark). A 5-stage pipeline with forwarding would still stall once on each of them.
- **RAW at distance 1** covers 11–66% of instructions (66% in crc32's tight loop), distance 2 a further 8–17%, distance 3 5–24%. Without forwarding, most instructions would wait.
- **Branches:** backward branches are taken 62–100% of the time, forward ones 18–62%. Static backward-taken / forward-not-taken prediction (BTFN) fits most of these programs, though CoreMark and `ud` have many forward branches that are taken.
- **Footprint:** code 8.7–19 KB, data up to 12.6 KB, stack up to 7.8 KB. Every program fits easily in the 64 KiB RAM, which is relevant for TCM vs. cache sizing.

## M8: Synthesis characterization

### Setup

| Item | Value |
|---|---|
| Device | Lattice ECP5 LFE5U-25F, CABGA256, speed grade 6 |
| Flow | sv2v 0.0.13 (SystemVerilog to Verilog, `SYNTHESIS` defined) → Yosys 0.66 `synth_ecp5` → nextpnr-ecp5 0.7, 3 placement seeds |
| Reproduce | `make syn` (`scripts/syn.py`); full report and tool logs in `syn/reports/` |
| Harnesses | `syn/rv_timing_core.sv`: rv_core alone; memory responses come from flops and outputs go into flops, so every path is register to register. `syn/rv_timing_soc.sv`: rv_core plus 1 KiB instruction and 1 KiB data memory with the zero-latency combinational read of spec §8.3, so the whole single-cycle loop is timed. Both reach the pins through a shift register and an XOR tree, which adds a little area and depth. |

### M8.1–M8.2 Area and Fmax

rv_core alone, Yosys pre-pack: 2,163 LUT4, 517 PFUMX, 223 L6MUX21, 95 CCU2C, 100 flip-flops and 32 TRELLIS_DPR16X4. The flip-flops are `pc_q` (32), `order_q` (64), `halted_q` and `status_q` (4). The register file maps to distributed RAM: 32 entries × 32 bits × 2 read ports = 32 DPR16X4, not 992 flops. The largest blocks by their own cells are the ALU (745 LUT4, mostly its shifters), rv_core's own glue and retire port (838), and the register file's read muxes (266).

| Variant | TRELLIS_COMB (post-pack) | Flip-flops | LUT RAM | Block RAM | Fmax (best of 3 seeds) |
|---|---:|---:|---:|---:|---:|
| core (rv_core alone, harness included) | 2,203 (9 %) | 651 | 32 | 0 | **41.3 MHz** |
| soc_bram (instruction memory in block RAM) | 3,556 (14 %) | 626 | 160 | 1 | **28.7 MHz** |
| soc_lutram (both memories in LUT RAM) | 5,362 (22 %) | 625 | 288 | 0 | **30.3 MHz** |

Most of the flip-flops in this table belong to the harnesses' input and output registers.

### Critical path by stage

Taken from hierarchical netlists, so that every cell keeps its module name. Those netlists are not optimized across module boundaries and run slower (29.0 and 25.8 MHz), so the table shows where the delay is, not the achievable clock. About 70 % of the delay is routing.

| Stage | core: rv_core alone (34.4 ns) | soc_lutram: whole loop (38.8 ns) |
|---|---:|---:|
| Fetch: instruction memory and read mux | n/a | 6.6 ns (17 %) |
| Fetch: fetch-error gating, `active` | 5.8 ns (17 %) | 2.2 ns (6 %) |
| Decode + immediate | 7.3 ns (21 %) | 6.5 ns (17 %) |
| Operand select | 1.4 ns (4 %) | 2.0 ns (5 %) |
| ALU (adder carry chain) | 7.4 ns (22 %) | 6.9 ns (18 %) |
| Memory: data memory and read mux | n/a | 7.0 ns (18 %) |
| Memory: load/store unit | 4.0 ns (12 %) | 3.4 ns (9 %) |
| Stop logic → next-PC (core) / write-back mux → register file and retire port (soc) | 8.5 ns (25 %) | 4.2 ns (11 %) |

- **The whole loop (soc_lutram)** runs from an instruction-memory read through decode, the ALU address add, the data-memory read and load alignment to the register-file write. The two memory reads together take 35 % of the cycle.
- **rv_core alone (core)** has a different slowest path, the stop condition. A misaligned data address computed by the ALU must stop the core in the same cycle (spec §10), which holds the PC. So LSU misalignment detection, the stop-cause priority logic and the next-PC mux are in series behind the ALU.

### M8.3 The memory finding

ECP5 block RAM (DP16KD) reads synchronously: the data appears one clock after the address. The Phase 1 core expects zero-latency reads (spec §8.3). What this means:

- **Instruction memory can use block RAM even in a single-cycle core.** The fetch address is `pc_q`, a register, so the block RAM's address register can be the PC itself: the RAM latches `next_pc` at the clock edge and delivers the instruction in the next cycle. Yosys did this transform without being asked (soc_bram: 1 DP16KD). It saves 1,806 slices against LUT RAM, but does not raise Fmax: the block RAM's 5.8 ns clock-to-out costs about what the LUT-RAM read and its mux do.
- **Data memory cannot.** Its address comes from the ALU in the same cycle, so the read needs a second clock. With block RAM, a load must either take two cycles (a stall, CPI > 1) or move into a pipeline stage. The only same-cycle option is LUT RAM: 128 DPR16X4 per KiB here, so only small memories are practical.
- **Phase 2 input:** a 2-stage design (fetch / execute) can keep instruction fetch in block RAM with no extra latency, and gets the data side through a memory stage or a load stall. That moves the data-memory read (18 % of today's loop) out of the critical path. The `rv_core` memory ports (spec §8.3, §16) already have the `ready` and latency hooks for this.

## Phase 2 decision inputs (exec.md §9, filled in)

Phase 1 measures; it decides none of these. The review at M9.4 does.

| Phase 2 decision | What Phase 1 measured |
|---|---|
| Pipeline depth and style | The whole single-cycle loop is 38.8 ns (hierarchical netlist, 25.8 MHz; 30.3 MHz flattened). Its parts: instruction-memory read 17 %, decode 17 %, ALU 18 %, data-memory read 18 %, LSU 9 %, write-back and control 11 %; about 70 % of it is routing. With the memories out, the core's slowest path is the stop condition (ALU address → misalignment detection → stop priority → next-PC, 41.3 MHz flattened). |
| Hazard handling | RAW at distance 1: 11–66 % of instructions, at distance 2: 8–17 %, at distance 3: 5–24 %. Load-use pairs: 0–4.7 % of instructions, up to 37 % of loads (CoreMark). |
| Branch handling | Branches are 3–27 % of instructions. Backward branches are taken 62–100 % of the time, forward ones 18–62 %. |
| Memory interface / bus | ECP5 block RAM reads synchronously. Instruction fetch can still use it with the PC as the RAM's address register (no Fmax change, 1,806 fewer slices); the data memory needs a stage or a stall (M8.3). The ports already carry `ready` for latency (spec §8.3, §16). |
| Memory hierarchy | Code 8.7–19 KB, data up to 12.6 KB, stack up to 7.8 KB for every benchmark: each fits in the 64 KiB RAM. |
| ISA extensions and order | Software multiply/divide takes 59 % of CoreMark's instructions and 47 % of Embench `ud`'s (7 % for Dhrystone, under 1 % for the others): M is the extension with the most measured effect. C would shrink the 8.7–19 KB of code; no workload needed interrupts or an OS. |
| Target platform | rv_core alone uses about 9 % of an LFE5U-25F (2,203 TRELLIS_COMB with the harness). The whole loop with 2 KiB of LUT-RAM memory uses 22 %. |
| Verification scaling | 2 RTL bugs, both found before integration (spec review, unit tests vs. model); after that, zero mismatches across every suite, 1,000 random seeds and 22M benchmark instructions. Every comparison so far uses the project's own model, so an independent reference (Spike in CI, or riscv-formal, M6.6) is the most valuable next step. |

## Phase 1 definition of done (exec.md §7)

| Criterion | Status |
|---|---|
| Every RV32I instruction implemented and ticked (spec §15.1) | Done: 40/40 |
| `rv32ui-p-*` pass except the documented waivers | Done: 40/42, `fence_i` and `ma_data` waived |
| RISCOF `rv32i_m/I` passes 100 % | Done: 39/39, against the Python reference |
| Zero lockstep mismatches against Spike on directed tests, benchmarks, ≥ 1,000 random seeds | **Met against the Python reference model, not Spike** (exec.md §8 decision). Spike in CI is open. |
| `hello.c`, Dhrystone and CoreMark run correctly | Done |
| Verilator lint clean with `-Wall` | Done |
| `make regress` passes from a clean checkout | Done: a fresh clone with submodules passed every stage (11 minutes) |
| Synthesis numbers and benchmark statistics recorded | Done: M7, M8 above |
| `docs/spec.md` matches the final RTL, this report complete | Done: `rv_pkg.sv` matches spec §8 line for line; all module ports match spec §6 |

## Open items

1. **An independent reference:** run the lockstep comparison against Spike on a Linux CI runner (`scripts/trace_compare.py` already reads Spike `--log-commits`; its Spike parser is checked only on hand-written samples so far). Programs that read the CYCLE counter cannot be compared with Spike.
2. **M6.5** (riscv-dv as a second random source, optional) and **M6.6** (riscv-formal, stretch): not done.
3. **M9.4:** the Phase 2 architecture review meeting, using the table above.
4. `edn` and `matmult-int` (Embench) were left out because the Python model replays about 50k instructions/s; a faster reference (Spike) would let them in.
