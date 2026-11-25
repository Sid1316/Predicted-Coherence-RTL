// expect: 3 STOP_ILLEGAL
// e01a_illegal_zero: the all-zero word is illegal (spec §10, §15.2).
#include "test.h"
TEST_BEGIN
  .word 0x00000000
TEST_UNREACHED
TEST_DATA
buf:
  .word 0x01020304, 0x05060708
