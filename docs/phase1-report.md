# RISC-V Core: Phase 1 Report

Status: **in progress.** This report collects the Phase 1 measurements as the milestones produce them; M9.2 completes it (what was built, test results, waivers, bug log, synthesis numbers, and the Phase 2 decision inputs of exec.md §9).

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
