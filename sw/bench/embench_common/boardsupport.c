/* boardsupport.c - Embench board support for rv_soc_sim (docs/exec.md M7.1).
 *
 * Embench's main() (support/main.c) calls start_trigger() and stop_trigger()
 * around benchmark(); these read the CYCLE counter (spec §2.3) and print the
 * cycles in between, the number Embench scores on. main() returns
 * !verify_benchmark(), so a wrong result fails the run (exit 1). */
#include "rvlib.h"

static uint64_t start;

void initialise_board(void) {}

void __attribute__((noinline)) start_trigger(void) { start = rv_cycles(); }

void __attribute__((noinline)) stop_trigger(void) {
  uint64_t cycles = rv_cycles() - start;
  printf("embench: benchmark() took %lu cycles\n", (unsigned long)cycles);
}
