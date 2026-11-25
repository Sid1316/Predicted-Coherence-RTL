// util.h - stands in for riscv-tests/benchmarks/common/util.h in the Dhrystone port (exec.md M7.1).
//
// dhrystone.h times the benchmark with read_csr(mcycle); this core has no
// CSRs, so the timer reads the CYCLE counter MMIO instead (spec §2.3).
// dhrystone.h's RISC-V branch sets HZ = 1000000: with one cycle per "tick",
// Dhrystone's "Microseconds for one run" is then cycles per run at a notional
// 1 MHz clock, and "Dhrystones per Second" is Dhrystones per second per MHz.
#ifndef SW_BENCH_DHRYSTONE_UTIL_H
#define SW_BENCH_DHRYSTONE_UTIL_H

#include "rvlib.h"

#define read_csr(reg) ((long)rv_cycles())

static inline void setStats(int enable) { (void)enable; }

#endif
