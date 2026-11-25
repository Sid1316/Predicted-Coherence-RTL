// expect: 3 STOP_ILLEGAL
// e01d_illegal_mul: an M-extension op (mul) is illegal (spec §10, §15.2).
#include "test.h"
TEST_BEGIN
  .word 0x02c58533                // mul a0, a1, a2
TEST_UNREACHED
TEST_DATA
buf:
  .word 0x01020304, 0x05060708
