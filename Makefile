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

# Set to rv_core once it exists (M3.2). Until then the blocks are independent,
# so every module is linted as its own top: -Wno-MULTITOP only silences the
# "several top-level modules" notice, every module is still fully checked.
LINT_TOP        ?=
LINT_FLAGS      := --lint-only -Wall --quiet $(if $(LINT_TOP),--top-module $(LINT_TOP),-Wno-MULTITOP)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# $(call not_yet,<milestone>)
define not_yet
@echo "$@: not implemented yet (docs/exec.md $(1))"
endef

# $(call need_prog)
define need_prog
@if [ -z "$(PROG)" ]; then echo "$@: set PROG=<path to program>, e.g. PROG=sw/asm/t00_lui_addi"; exit 2; fi
endef

.PHONY: help check-env lint unit sim spike compare riscv-tests riscof random regress syn clean

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

sim: ## Run one program on the RTL: make sim PROG=<path>
	$(call need_prog)
	$(call not_yet,M3/M4)

spike: ## Run one program on Spike: make spike PROG=<path>
	$(call need_prog)
	$(call not_yet,M6.1)

compare: ## RTL vs. Spike lockstep comparison: make compare PROG=<path>
	$(call need_prog)
	$(call not_yet,M6.1)

riscv-tests: ## Run the rv32ui-p-* suite (minus waivers)
	$(call not_yet,M5.1-M5.2)

riscof: ## Run riscv-arch-test rv32i_m/I through RISCOF
	$(call not_yet,M5.3-M5.4)

random: ## Random program tests: make random SEEDS=<n>
	$(call not_yet,M6.3-M6.4)

regress: lint unit riscv-tests riscof random ## Full regression (filled in at M9.1)
	@echo "regress: lint and unit are implemented; the other stages are placeholders"

syn: ## Yosys synthesis of rv_core
	$(call not_yet,M8)

clean: ## Remove build output
	rm -rf $(BUILD_DIR) $(ROOT)/obj_dir
