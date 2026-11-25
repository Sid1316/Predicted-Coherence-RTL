// expect: 4 STOP_EBREAK
// t10_ebreak_halt: EBREAK stops the core and nothing after it executes (spec §10, §15.2).
// See t09_ecall_halt.S for why the expected exit code is 4.
#include "test.h"
TEST_BEGIN
  li    a0, 1
  ebreak
  addi  a0, a0, 1
  FAIL(2)
  TEST_PASS
TEST_DATA
