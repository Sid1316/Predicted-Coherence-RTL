// cycle.c - read the CYCLE counter (docs/spec.md §2.3; exec.md M7).
#include "rvlib.h"

uint64_t rv_cycles(void) {
  volatile const uint32_t *c = (volatile const uint32_t *)RV_CYCLE_ADDR;
  uint32_t hi, lo;
  do {                       // high, low, high again: a carry between the two reads is caught
    hi = c[1];
    lo = c[0];
  } while (hi != c[1]);
  return ((uint64_t)hi << 32) | lo;
}
