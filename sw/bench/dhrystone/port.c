// port.c - Dhrystone 2.2 (riscv-tests/benchmarks/dhrystone) on rv_soc_sim (docs/exec.md M7.1).
//
// dhry_main_renamed.c compiles dhrystone_main.c with main renamed to dhry_main; this main calls
// it and then checks the final values Dhrystone itself prints as "should
// be" (its own check is only printed, never enforced). The return value is
// the number of the first wrong value, so a wrong result fails the run
// (tohost = (n << 1) | 1). dhrystone.c's debug_printf prints nothing, so only
// Dhrystone's two result lines and this file's summary appear.
#include "rvlib.h"

#ifndef NUMBER_OF_RUNS
#define NUMBER_OF_RUNS 500            // dhrystone.h's default
#endif

int dhry_main(int argc, char **argv);

// Dhrystone's globals (dhrystone_main.c); Boolean is an int there.
extern int  Int_Glob;
extern int  Bool_Glob;
extern char Ch_1_Glob, Ch_2_Glob;
extern int  Arr_1_Glob[50];
extern int  Arr_2_Glob[50][50];

int main(void) {
  uint64_t t0 = rv_cycles();
  dhry_main(0, 0);
  uint64_t total = rv_cycles() - t0;

  int bad = 0;
  if (Int_Glob != 5)                           bad = 1;
  else if (Bool_Glob != 1)                     bad = 2;
  else if (Ch_1_Glob != 'A')                   bad = 3;
  else if (Ch_2_Glob != 'B')                   bad = 4;
  else if (Arr_1_Glob[8] != 7)                 bad = 5;
  else if (Arr_2_Glob[8][7] != NUMBER_OF_RUNS + 10) bad = 6;
  if (bad) {
    printf("dhrystone: final value %d wrong\n", bad);
    return bad;
  }
  printf("dhrystone: final values correct; %d runs, %lu cycles for the whole program\n",
         NUMBER_OF_RUNS, (unsigned long)total);
  return 0;
}
