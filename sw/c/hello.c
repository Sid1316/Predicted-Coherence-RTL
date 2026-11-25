// expect: 0
// console: Hello, RISC-V\n
// hello.c - the M4 exit check: print through the console MMIO and exit 0 (docs/exec.md M4).
#include "rvlib.h"

int main(void) {
  printf("Hello, RISC-V\n");
  return 0;
}
