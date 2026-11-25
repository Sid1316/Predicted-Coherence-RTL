// expect: 4 STOP_ECALL
// t09_ecall_halt: ECALL stops the core and nothing after it executes (spec §10, §15.2).
// The harness ends a run at the tohost store (spec §11), so a test that wrote
// tohost = 1 before its ECALL would never execute the ECALL. This one does
// not write tohost before it: the expected result is exit 4 (halt without
// tohost). If ECALL did not stop, the store after it reports fail (exit 1).
#include "test.h"
TEST_BEGIN
  li    a0, 1
  ecall
  addi  a0, a0, 1
  FAIL(2)
  TEST_PASS
TEST_DATA
