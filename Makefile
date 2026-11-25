# RISC-V core: top-level Makefile.
# Run from Git Bash on Windows (or a Linux shell). See README.md,
# docs/exec.md and docs/spec.md §3.2.
#
# Targets that a later milestone fills in print "not implemented" and exit 0.

# "bash" without a path, so both native Windows make and Linux make find it on PATH.
SHELL         := bash
.SHELLFLAGS   := -eu -o pipefail -c
.DEFAULT_GOAL := help

ROOT      := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BUILD_DIR := $(ROOT)/build

# ---------------------------------------------------------------------------
# Tools (override on the command line, e.g. make RISCV_PREFIX=riscv64-unknown-elf-)
# ---------------------------------------------------------------------------
# First toolchain prefix with a gcc on PATH (xPack on Windows is riscv-none-elf-).
RISCV_PREFIX ?= $(firstword $(foreach p,riscv-none-elf- riscv64-unknown-elf- riscv32-unknown-elf-,\
                  $(if $(shell command -v $(p)gcc 2>/dev/null),$(p))) riscv-none-elf-)
# The project venv's Python if it exists, else the first interpreter that really
# is Python 3 (Windows has Microsoft Store stubs named python/python3).
PYTHON       ?= $(firstword $(wildcard $(ROOT)/.venv/Scripts/python.exe $(ROOT)/.venv/bin/python3) \
                  $(foreach c,python3 python py,$(if $(shell $(c) --version 2>&1 | grep '^Python 3'),$(c))) python3)
# Windows: MSYS2's Verilator launcher is a Perl script that fails under Git Bash's
# Perl, so call the real binary directly and tell it where its include files are.
MSYS2_UCRT64 ?= C:/msys64/ucrt64
ifneq ($(wildcard $(MSYS2_UCRT64)/bin/verilator_bin.exe),)
VERILATOR      ?= $(MSYS2_UCRT64)/bin/verilator_bin.exe
VERILATOR_ROOT ?= $(MSYS2_UCRT64)/share/verilator
export VERILATOR_ROOT
endif
VERILATOR    ?= verilator
SPIKE        ?= spike
YOSYS        ?= yosys
export RISCV_PREFIX PYTHON VERILATOR

# ---------------------------------------------------------------------------
# RTL sources: read from rtl/rtl.f, dropping // comments and blank lines
# ---------------------------------------------------------------------------
RTL_FILELIST := $(ROOT)/rtl/rtl.f
RTL_SRCS     := $(addprefix $(ROOT)/,$(shell sed -e 's://.*$$::' -e '/^[[:space:]]*$$/d' $(RTL_FILELIST)))

# rv_core instantiates every other block, so linting it as the top checks the
# whole design, including the connections between blocks (spec §14.4).
# LINT_TOP= (empty) lints each module as its own top instead (-Wno-MULTITOP).
LINT_TOP        ?= rv_core
LINT_FLAGS      := --lint-only -Wall --quiet $(if $(LINT_TOP),--top-module $(LINT_TOP),-Wno-MULTITOP)

# ---------------------------------------------------------------------------
# Verilator simulation (rv_soc_sim + sim/tb_top.cpp, spec §2.1)
# ---------------------------------------------------------------------------
SIM_FILELIST := $(ROOT)/sim/sim.f
SIM_SRCS     := $(addprefix $(ROOT)/,$(shell sed -e 's://.*$$::' -e '/^[[:space:]]*$$/d' $(SIM_FILELIST)))
SIM_HARNESS  := $(ROOT)/sim/tb_top.cpp
# RAM size, given to both the RTL (-G) and the harness's +hex= check (-D).
# The default (spec §2.4) builds build/sim/; any other size gets its own
# directory, build/sim-<bytes>/ (RISCOF uses 2 MiB, see tests/riscof/arch_build.py).
MEM_SIZE_BYTES ?= 65536
SIM_DIR      := $(BUILD_DIR)/sim$(if $(filter-out 65536,$(MEM_SIZE_BYTES)),-$(MEM_SIZE_BYTES))
SIM_EXE      := $(SIM_DIR)/Vrv_soc_sim$(if $(filter Windows_NT,$(OS)),.exe)
# --x-initial unique + the harness's default +verilator+rand+reset+2: state
# without a reset (the register file) starts random (spec §2.2).
# VL_USER_STOP/FATAL: tb_top.cpp maps $stop/$fatal/assertions to exit code 6.
# DPI_DLLISPEC empty: svdpi.h would declare the DPI functions dllimport on
# Windows, but Verilator links them statically (rv_mem_peek, signature dump).
# PYTHON3: Verilator's makefile runs a Python helper, and "python3" may be
# the Windows Store stub.
# Waves: FST needs liblz4 (MSYS2 package mingw-w64-ucrt-x86_64-lz4, see
# README). On Windows without it, fall back to VCD; Linux is assumed to have it.
WAVE_FMT     ?= $(if $(filter Windows_NT,$(OS)),$(if $(wildcard $(MSYS2_UCRT64)/include/lz4.h),fst,vcd),fst)
ifeq ($(WAVE_FMT),vcd)
$(warning lz4.h not found in $(MSYS2_UCRT64)/include: building with VCD waves instead of FST. \
  Install with: pacman -S mingw-w64-ucrt-x86_64-lz4)
endif
SIM_FLAGS    := --cc --exe --build -j 0 -Wall --quiet --top-module rv_soc_sim \
                -GMEM_SIZE_BYTES=$(MEM_SIZE_BYTES) \
                --timescale 1ns/1ns --assert --x-assign unique --x-initial unique --trace-$(WAVE_FMT) \
                -CFLAGS "-O2 -DVL_USER_STOP -DVL_USER_FATAL -DMEM_SIZE_BYTES=$(MEM_SIZE_BYTES) -DDPI_DLLISPEC=" \
                --MAKEFLAGS "PYTHON3=$(PYTHON)" \
                --Mdir $(SIM_DIR) -o $(notdir $(SIM_EXE))
# make sim HEX=... options
MAX_CYCLES ?=
SEED       ?=
RETIRE_LOG ?= $(SIM_DIR)/retire.log

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# $(call not_yet,<milestone>)
define not_yet
@echo "$@: not implemented yet (docs/exec.md $(1))"
endef

# $(call need_prog)
define need_prog
@if [ -z "$(PROG)" ]; then echo "$@: set PROG=<path to program>, e.g. PROG=sw/c/hello or PROG=sw/asm/t00_lui_addi"; exit 2; fi
endef

.PHONY: help check-env lint unit sim-build sim-test asm c progs bench sim spike compare riscv-tests riscof random regress syn clean

help: ## List the targets
	@echo "Usage: make <target> [VAR=value ...]"
	@echo
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*## "} {printf "  %-12s %s\n", $$1, $$2}'

check-env: ## Check that the required tools are installed (M0.2)
	@bash $(ROOT)/scripts/check_env.sh

lint: ## Verilator -Wall lint of the sources in rtl/rtl.f
ifeq ($(strip $(RTL_SRCS)),)
	@echo "lint: rtl/rtl.f lists no sources yet, nothing to lint"
else
	$(VERILATOR) $(LINT_FLAGS) $(RTL_SRCS)
	@echo "lint: clean ($(words $(RTL_SRCS)) files)"
endif

unit: ## cocotb unit tests on Icarus: make unit [BLOCKS="rv_alu ..."] [WAVES=1]
	$(PYTHON) $(ROOT)/tb/unit/run_unit.py $(BLOCKS) $(if $(WAVES),--waves)

$(SIM_EXE): $(RTL_SRCS) $(SIM_SRCS) $(SIM_HARNESS) $(RTL_FILELIST) $(SIM_FILELIST) $(ROOT)/Makefile
	$(VERILATOR) $(SIM_FLAGS) $(RTL_SRCS) $(SIM_SRCS) $(SIM_HARNESS)

sim-build: $(SIM_EXE) ## Build the Verilator simulator (build/sim/Vrv_soc_sim)

sim-test: $(SIM_EXE) ## Check the Verilator harness against the Python model (M3.4)
	$(PYTHON) $(ROOT)/tb/sim/test_tb_top.py $(SIM_EXE)
	$(PYTHON) $(ROOT)/tb/sim/test_trace_compare.py
	$(PYTHON) $(ROOT)/tb/sim/test_stats.py

# Programs are built by scripts/run_progs.py (one place for the compiler
# flags, spec §12), which also checks each against its header and the model.
RUN_PROGS := $(PYTHON) $(ROOT)/scripts/run_progs.py --exe $(SIM_EXE)

asm: $(SIM_EXE) ## Build and run the directed tests in sw/asm/ (M3.5): make asm [TESTS="t00 e01"]
	$(RUN_PROGS) $(if $(TESTS),$(TESTS),sw/asm)

c: $(SIM_EXE) ## Build and run the C programs in sw/c/ (M4): make c [TESTS="hello"]
	$(RUN_PROGS) $(if $(TESTS),$(TESTS),sw/c)

progs: $(SIM_EXE) ## Build and run every program in sw/asm/ and sw/c/
	$(RUN_PROGS) asm c

# Benchmarks (M7): Dhrystone, CoreMark and an Embench subset, each checked by
# its own result check and against the model trace; then the statistics.
# The model replays every instruction (about 60k per second), hence -j.
JOBS ?= 8
bench: $(SIM_EXE) ## Benchmarks (sw/bench/) vs. the model, then scripts/stats.py: make bench [JOBS=8]
	$(RUN_PROGS) -j $(JOBS) bench
	$(PYTHON) $(ROOT)/scripts/stats.py --bench

# make sim HEX=<file> [TOHOST=<hex>] [MAX_CYCLES=<n>] [SEED=<n>] [WAVES=1] [RETIRE_LOG=<file>]
# runs a ready-made image. make sim PROG=sw/asm/<test> or PROG=sw/c/<prog>
# builds, converts and runs one program (build/{asm,c}/<name>.*) and checks
# it like make progs; WAVES=1 and SEED= apply to both forms.
sim: ## Run one program: make sim PROG=sw/c/hello (or sw/asm/<test>), or HEX=<file> [TOHOST=<hex addr>]
ifneq ($(HEX),)
	@$(MAKE) --no-print-directory sim-build
	$(SIM_EXE) +hex=$(HEX) $(if $(TOHOST),+tohost=$(TOHOST)) $(if $(MAX_CYCLES),+max_cycles=$(MAX_CYCLES)) \
	  +retire_log=$(RETIRE_LOG) $(if $(WAVES),+waves=$(SIM_DIR)/waves.$(WAVE_FMT)) $(if $(SEED),+verilator+seed+$(SEED))
else
	$(call need_prog)
	@$(MAKE) --no-print-directory sim-build
	$(RUN_PROGS) -v $(if $(WAVES),--waves $(SIM_DIR)/waves.$(WAVE_FMT)) $(if $(SEED),--seed $(SEED)) $(PROG)
endif

spike: ## Run one program on Spike: make spike PROG=<path>
	$(call need_prog)
	$(call not_yet,M6.1)

compare: ## RTL vs. Spike lockstep comparison: make compare PROG=<path>
	$(call need_prog)
	$(call not_yet,M6.1)

riscv-tests: $(SIM_EXE) ## Run the rv32ui-p-* suite; waived tests must fail as tests/riscv-tests-waivers.txt says
	$(RUN_PROGS) rv32ui

# The arch tests need more RAM than the default (tests/riscof/arch_build.py):
# build a second simulator with 2 MiB, then run RISCOF (DUT: that simulator,
# reference: the Python model, exec.md §8).
riscof: ## Run riscv-arch-test rv32i_m/I through RISCOF (DUT vs. the Python reference model)
	@$(MAKE) --no-print-directory sim-build MEM_SIZE_BYTES=2097152
	$(PYTHON) $(ROOT)/scripts/run_riscof.py

# Random programs (scripts/randgen.py) on the RTL and the reference model;
# failing seeds are saved to tests/random/ and rerun every time.
SEEDS ?= 200
START ?= 1
random: $(SIM_EXE) ## Random programs vs. the reference model: make random [SEEDS=200] [START=1]
	$(PYTHON) $(ROOT)/scripts/run_random.py --exe $(SIM_EXE) --seeds $(SEEDS) --start $(START)

regress: lint unit sim-test progs riscv-tests riscof random bench ## Full regression (filled in at M9.1)
	@echo "regress: all stages passed (random: $(SEEDS) seeds from $(START))"

# Synthesis characterization (M8): sv2v -> yosys synth_ecp5 -> nextpnr-ecp5,
# report in syn/reports/. Needs sv2v (SV2V=...) and MSYS2's yosys and nextpnr.
SYN_SEEDS ?= 3
syn: ## Yosys + nextpnr (ECP5) area, Fmax and critical path of rv_core: make syn [SYN_SEEDS=3]
	$(PYTHON) $(ROOT)/scripts/syn.py --seeds $(SYN_SEEDS)

clean: ## Remove build output
	rm -rf $(BUILD_DIR) $(ROOT)/obj_dir
